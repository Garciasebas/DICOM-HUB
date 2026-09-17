import os
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from dicom_app.models import (
    Experiment, Participant, ParticipantGroup, ExperimentParticipant,
    Member, ConsentFile, DicomFile, DicomTag
)
from django.core.files.uploadedfile import SimpleUploadedFile


class ExperimentDeleteViewTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='test_exp_user', password='password123')
        self.client.login(username='test_exp_user', password='password123')

        self.experiment = Experiment.objects.create(
            name='Experimento Test Eliminación',
            description='Test eliminación de experimento',
            created_by=self.user
        )

        self.participant = Participant.objects.create(
            subject_id='SUBJ-DEL-001',
            first_name='Juan',
            last_name='Perez'
        )

        self.group = ParticipantGroup.objects.create(
            experiment=self.experiment,
            name='Grupo Control'
        )

        self.exp_participant = ExperimentParticipant.objects.create(
            experiment=self.experiment,
            participant=self.participant,
            group=self.group
        )

        self.member = Member.objects.create(
            first_name='Carlos',
            last_name='Gomez',
            role='Investigador/a Posdoctoral'
        )
        self.member.experiments.add(self.experiment)

        self.consent_file = ConsentFile.objects.create(
            participant=self.participant,
            experiment=self.experiment,
            file=SimpleUploadedFile('consent_dummy.pdf', b'PDF content dummy'),
            original_filename='consent_dummy.pdf',
            file_size=17
        )

        self.dicom_file = DicomFile.objects.create(
            participant=self.participant,
            experiment=self.experiment,
            patient_name='Juan Perez',
            file=SimpleUploadedFile('test_image.dcm', b'DICOM dummy content'),
            original_filename='test_image.dcm',
            file_size=18
        )

        self.dicom_tag = DicomTag.objects.create(
            dicom_file=self.dicom_file,
            tag='(0010,0010)',
            description='PatientName',
            vr='PN',
            value='Juan Perez'
        )

    def test_experiment_deletion_cleans_resources_and_preserves_participants_and_users(self):
        exp_id = self.experiment.pk
        part_id = self.participant.pk
        user_id = self.user.pk
        consent_id = self.consent_file.pk
        dicom_id = self.dicom_file.pk
        tag_id = self.dicom_tag.pk
        group_id = self.group.pk
        ep_id = self.exp_participant.pk

        url = reverse('experiment_delete', kwargs={'pk': exp_id})
        response = self.client.post(url)

        # 1. Successful redirect to dashboard
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('dashboard'))

        # 2. Experiment deleted
        self.assertFalse(Experiment.objects.filter(pk=exp_id).exists())

        # 3. ExperimentParticipant & ParticipantGroup deleted
        self.assertFalse(ExperimentParticipant.objects.filter(pk=ep_id).exists())
        self.assertFalse(ParticipantGroup.objects.filter(pk=group_id).exists())

        # 4. ConsentFile deleted
        self.assertFalse(ConsentFile.objects.filter(pk=consent_id).exists())

        # 5. DicomFile & DicomTag deleted
        self.assertFalse(DicomFile.objects.filter(pk=dicom_id).exists())
        self.assertFalse(DicomTag.objects.filter(pk=tag_id).exists())

        # 6. M2M relations removed
        self.assertEqual(self.member.experiments.filter(pk=exp_id).count(), 0)

        # 7. Participant NOT deleted (preserved)
        self.assertTrue(Participant.objects.filter(pk=part_id).exists())

        # 8. User intact
        self.assertTrue(User.objects.filter(pk=user_id).exists())

    def test_delete_experiment_belonging_to_another_user_returns_404(self):
        other_user = User.objects.create_user(username='other_user', password='password123')
        other_exp = Experiment.objects.create(name='Otro Exp', created_by=other_user)

        url = reverse('experiment_delete', kwargs={'pk': other_exp.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Experiment.objects.filter(pk=other_exp.pk).exists())
