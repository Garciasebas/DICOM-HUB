import os
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from dicom_app.models import (
    Experiment, Participant, ParticipantGroup, ExperimentParticipant,
    ConsentFile, DicomFile, DicomTag
)

class ParticipantDeleteTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='test_investigador', password='password123')
        self.client.login(username='test_investigador', password='password123')

        self.free_participant = Participant.objects.create(
            subject_id='SUBJ-FREE-001',
            first_name='Libre',
            last_name='SinDatos'
        )

    def test_1_free_participant_can_be_deleted_successfully(self):
        """TEST 1: Un participante sin experimentos ni información asociada puede eliminarse correctamente."""
        url = reverse('delete_participant', kwargs={'participant_id': self.free_participant.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('participant_dashboard'))
        self.assertFalse(Participant.objects.filter(pk=self.free_participant.pk).exists())

    def test_2_deleted_participant_no_longer_appears_in_list(self):
        """TEST 2: Después de eliminarlo, el participante ya no aparece en el listado."""
        url_delete = reverse('delete_participant', kwargs={'participant_id': self.free_participant.pk})
        self.client.post(url_delete)

        url_list = reverse('participant_dashboard')
        response = self.client.get(url_list)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Libre SinDatos')
        self.assertNotContains(response, 'SUBJ-FREE-001')

    def test_3_participant_with_experiment_participant_cannot_be_deleted(self):
        """TEST 3: Un participante que pertenece a un Experiment mediante ExperimentParticipant NO puede eliminarse globalmente."""
        experiment = Experiment.objects.create(name='Exp Test 3', created_by=self.user)
        group = ParticipantGroup.objects.create(experiment=experiment, name='Grupo A')
        p_exp = Participant.objects.create(subject_id='SUBJ-EXP-001', first_name='Carlos', last_name='ConExp')
        ExperimentParticipant.objects.create(experiment=experiment, participant=p_exp, group=group)

        url = reverse('delete_participant', kwargs={'participant_id': p_exp.pk})
        response = self.client.post(url, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Participant.objects.filter(pk=p_exp.pk).exists())
        self.assertContains(response, 'No se puede eliminar este participante')
        self.assertContains(response, 'pertenece a uno o más experimentos')

    def test_4_participant_with_unlinked_dicom_file_is_deleted_and_files_cleaned(self):
        """TEST 4: Un participante sin experimentos pero con DicomFile no asociado a un experimento se elimina junto con sus archivos y tags."""
        p_dicom = Participant.objects.create(subject_id='SUBJ-DICOM-001', first_name='David', last_name='ConDicom')
        df = DicomFile.objects.create(
            participant=p_dicom,
            experiment=None,
            patient_name='David ConDicom',
            file=SimpleUploadedFile('test.dcm', b'dummy dicom content')
        )
        tag = DicomTag.objects.create(dicom_file=df, tag='(0010,0010)', description='PatientName', vr='PN', value='David')

        df_id = df.id
        file_path = df.file.path

        url = reverse('delete_participant', kwargs={'participant_id': p_dicom.pk})
        response = self.client.post(url, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Participant.objects.filter(pk=p_dicom.pk).exists())
        self.assertFalse(DicomFile.objects.filter(id=df_id).exists())
        self.assertFalse(DicomTag.objects.filter(id=tag.id).exists())
        self.assertFalse(os.path.exists(file_path))
        self.assertContains(response, 'Participante eliminado correctamente')

    def test_5_participant_with_residual_experiment_files_can_be_deleted_globally(self):
        """TEST 5: Un participante sin asociaciones ExperimentParticipant puede eliminarse globalmente aunque tenga registros residuales de consentimiento o DICOM."""
        experiment = Experiment.objects.create(name='Exp Residual', created_by=self.user)
        p_residual = Participant.objects.create(subject_id='SUBJ-RES-001', first_name='Sebastian', last_name='Garcia')

        cf = ConsentFile.objects.create(
            participant=p_residual,
            experiment=experiment,
            file=SimpleUploadedFile('consent_res.pdf', b'consent content'),
            original_filename='consent_res.pdf',
            file_size=15
        )
        df = DicomFile.objects.create(
            participant=p_residual,
            experiment=experiment,
            patient_name='Sebastian Garcia',
            file=SimpleUploadedFile('dicom_res.dcm', b'dicom content'),
            original_filename='dicom_res.dcm'
        )
        tag = DicomTag.objects.create(dicom_file=df, tag='(0010,0010)', description='PatientName', vr='PN', value='Sebastian Garcia')

        cf_path = cf.file.path
        df_path = df.file.path
        cf_id = cf.id
        df_id = df.id
        tag_id = tag.id

        url = reverse('delete_participant', kwargs={'participant_id': p_residual.pk})
        response = self.client.post(url, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Participant.objects.filter(pk=p_residual.pk).exists())
        self.assertFalse(ConsentFile.objects.filter(id=cf_id).exists())
        self.assertFalse(DicomFile.objects.filter(id=df_id).exists())
        self.assertFalse(DicomTag.objects.filter(id=tag_id).exists())
        self.assertFalse(os.path.exists(cf_path))
        self.assertFalse(os.path.exists(df_path))
        self.assertContains(response, 'Participante eliminado correctamente')

    def test_6_unauthorized_user_cannot_delete_other_user_participant(self):
        """TEST 6: Un usuario sin permisos NO puede eliminar un participante que no le corresponde."""
        other_user = User.objects.create_user(username='other_user', password='password123')
        other_exp = Experiment.objects.create(name='Exp Otro User', created_by=other_user)
        p_other = Participant.objects.create(subject_id='SUBJ-OTHER-001', first_name='Pedro', last_name='Ajeno')
        ExperimentParticipant.objects.create(experiment=other_exp, participant=p_other)

        url = reverse('delete_participant', kwargs={'participant_id': p_other.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Participant.objects.filter(pk=p_other.pk).exists())

    def test_7_participant_deletion_does_not_affect_django_users(self):
        """TEST 7: La eliminación no afecta a ningún usuario de Django."""
        user_count_before = User.objects.count()
        user_ids_before = set(User.objects.values_list('id', flat=True))

        url = reverse('delete_participant', kwargs={'participant_id': self.free_participant.pk})
        self.client.post(url)

        user_count_after = User.objects.count()
        user_ids_after = set(User.objects.values_list('id', flat=True))

        self.assertEqual(user_count_before, user_count_after)
        self.assertEqual(user_ids_before, user_ids_after)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_8_deletion_executes_within_atomic_transaction(self):
        """TEST 8: La eliminación se ejecuta dentro de una transacción atómica."""
        url = reverse('delete_participant', kwargs={'participant_id': self.free_participant.pk})

        with patch('dicom_app.views.transaction.atomic') as mock_atomic:
            mock_atomic.return_value.__enter__.return_value = None
            response = self.client.post(url)
            self.assertTrue(mock_atomic.called)

    def test_9_x_icon_appears_and_no_acciones_column_header_exists(self):
        """TEST 9: La X aparece en el listado de participantes y NO existe una columna 'Acciones'."""
        url = reverse('participant_dashboard')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'btn-remove-x')
        self.assertNotContains(response, '<th>Acciones</th>')
        self.assertNotContains(response, '<th>Acción</th>')
        self.assertNotContains(response, 'Acciones')

    def test_10_delete_confirmation_modal_is_rendered(self):
        """TEST 10: La confirmación de eliminación se muestra antes de ejecutar la operación."""
        url = reverse('participant_dashboard')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'modal-delete-participant')
        self.assertContains(response, '¿Está seguro de que desea eliminar este participante?')
        self.assertContains(response, 'confirmDeleteParticipant')

    def test_11_remove_group_participant_deletes_files_and_preserves_participant(self):
        """TEST 11: Desvincular desde el grupo elimina archivos y consentimiento de ese experimento, pero conserva el Participant global."""
        experiment = Experiment.objects.create(name='Exp Grupo Clean', created_by=self.user)
        group = ParticipantGroup.objects.create(experiment=experiment, name='Grupo Clean')
        p = Participant.objects.create(subject_id='SUBJ-GRP-CLEAN', first_name='Juan', last_name='Limpio')
        ep = ExperimentParticipant.objects.create(experiment=experiment, participant=p, group=group)

        cf = ConsentFile.objects.create(
            participant=p,
            experiment=experiment,
            file=SimpleUploadedFile('consent_juan.pdf', b'consent juan'),
            original_filename='consent_juan.pdf',
            file_size=12
        )
        df = DicomFile.objects.create(
            participant=p,
            experiment=experiment,
            patient_name='Juan Limpio',
            file=SimpleUploadedFile('dicom_juan.dcm', b'dicom juan')
        )
        tag = DicomTag.objects.create(dicom_file=df, tag='(0010,0010)', description='PatientName', vr='PN', value='Juan')

        cf_path = cf.file.path
        df_path = df.file.path
        cf_id = cf.id
        df_id = df.id
        tag_id = tag.id

        url = reverse('remove_group_participant_ajax', kwargs={'pk': experiment.pk, 'group_id': group.pk, 'participant_id': p.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('status'), 'success')
        self.assertFalse(ExperimentParticipant.objects.filter(pk=ep.pk).exists())
        self.assertFalse(ConsentFile.objects.filter(id=cf_id).exists())
        self.assertFalse(DicomFile.objects.filter(id=df_id).exists())
        self.assertFalse(DicomTag.objects.filter(id=tag_id).exists())
        self.assertFalse(os.path.exists(cf_path))
        self.assertFalse(os.path.exists(df_path))
        self.assertTrue(Participant.objects.filter(pk=p.pk).exists())

    def test_12_remove_group_participant_preserves_other_experiments_data(self):
        """TEST 12: Desvincular de un grupo conserva las asociaciones y archivos del participante en otros experimentos."""
        exp1 = Experiment.objects.create(name='Exp Uno', created_by=self.user)
        grp1 = ParticipantGroup.objects.create(experiment=exp1, name='G1')

        exp2 = Experiment.objects.create(name='Exp Dos', created_by=self.user)
        grp2 = ParticipantGroup.objects.create(experiment=exp2, name='G2')

        p = Participant.objects.create(subject_id='SUBJ-MULTI', first_name='Laura', last_name='Multi')
        ep1 = ExperimentParticipant.objects.create(experiment=exp1, participant=p, group=grp1)
        ep2 = ExperimentParticipant.objects.create(experiment=exp2, participant=p, group=grp2)

        cf1 = ConsentFile.objects.create(participant=p, experiment=exp1, file=SimpleUploadedFile('c1.pdf', b'c1'), original_filename='c1.pdf', file_size=10)
        cf2 = ConsentFile.objects.create(participant=p, experiment=exp2, file=SimpleUploadedFile('c2.pdf', b'c2'), original_filename='c2.pdf', file_size=10)

        cf2_path = cf2.file.path

        url = reverse('remove_group_participant_ajax', kwargs={'pk': exp1.pk, 'group_id': grp1.pk, 'participant_id': p.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExperimentParticipant.objects.filter(pk=ep1.pk).exists())
        self.assertFalse(ConsentFile.objects.filter(pk=cf1.pk).exists())

        # exp2 data remains completely intact
        self.assertTrue(ExperimentParticipant.objects.filter(pk=ep2.pk).exists())
        self.assertTrue(ConsentFile.objects.filter(pk=cf2.pk).exists())
        self.assertTrue(os.path.exists(cf2_path))
        self.assertTrue(Participant.objects.filter(pk=p.pk).exists())

        if os.path.exists(cf2_path):
            os.remove(cf2_path)

    def test_13_shared_physical_files_are_not_deleted_from_disk(self):
        """TEST 13: Si un archivo físico es referenciado por otro registro válido, no se elimina de disco al desvincular o eliminar."""
        exp = Experiment.objects.create(name='Exp Compartido', created_by=self.user)
        grp = ParticipantGroup.objects.create(experiment=exp, name='G Compartido')

        p1 = Participant.objects.create(subject_id='SUBJ-SHARED-1', first_name='Ana', last_name='Uno')
        ep1 = ExperimentParticipant.objects.create(experiment=exp, participant=p1, group=grp)

        p2 = Participant.objects.create(subject_id='SUBJ-SHARED-2', first_name='Beatriz', last_name='Dos')
        ep2 = ExperimentParticipant.objects.create(experiment=exp, participant=p2, group=grp)

        uploaded = SimpleUploadedFile('shared_image.dcm', b'shared dicom data')
        df1 = DicomFile.objects.create(participant=p1, experiment=exp, patient_name='Ana Uno', file=uploaded)
        # p2 shares the exact same file
        df2 = DicomFile.objects.create(participant=p2, experiment=exp, patient_name='Beatriz Dos', file=df1.file)

        shared_path = df1.file.path

        url = reverse('remove_group_participant_ajax', kwargs={'pk': exp.pk, 'group_id': grp.pk, 'participant_id': p1.pk})
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(DicomFile.objects.filter(pk=df1.pk).exists())
        self.assertTrue(DicomFile.objects.filter(pk=df2.pk).exists())
        self.assertTrue(os.path.exists(shared_path))

        if os.path.exists(shared_path):
            os.remove(shared_path)

    def test_14_io_error_during_cleanup_does_not_report_false_success(self):
        """TEST 14: Un error en el sistema de archivos durante la limpieza revierte la transacción y no reporta éxito."""
        p = Participant.objects.create(subject_id='SUBJ-ERR-IO', first_name='Tomas', last_name='Fallo')
        df = DicomFile.objects.create(participant=p, patient_name='Tomas Fallo', file=SimpleUploadedFile('err.dcm', b'content'))
        file_path = df.file.path

        url = reverse('delete_participant', kwargs={'participant_id': p.pk})

        with patch('os.remove', side_effect=OSError('Error simulado de disco protegido')):
            response = self.client.post(url, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ocurrió un error al intentar eliminar el participante')
        # Participant and records still exist due to rollback
        self.assertTrue(Participant.objects.filter(pk=p.pk).exists())
        self.assertTrue(DicomFile.objects.filter(pk=df.pk).exists())

        if os.path.exists(file_path):
            os.remove(file_path)

    def test_15_deleting_participant_does_not_affect_other_participants_files(self):
        """TEST 15: Eliminar un participante no borra archivos ni datos de otros participantes."""
        p1 = Participant.objects.create(subject_id='SUBJ-P1-001', first_name='Mario', last_name='Uno')
        df1 = DicomFile.objects.create(participant=p1, patient_name='Mario Uno', file=SimpleUploadedFile('p1.dcm', b'p1 content'))

        p2 = Participant.objects.create(subject_id='SUBJ-P2-002', first_name='Luigi', last_name='Dos')
        df2 = DicomFile.objects.create(participant=p2, patient_name='Luigi Dos', file=SimpleUploadedFile('p2.dcm', b'p2 content'))
        file2_path = df2.file.path

        url = reverse('delete_participant', kwargs={'participant_id': p1.pk})
        response = self.client.post(url, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Participant.objects.filter(pk=p1.pk).exists())
        self.assertTrue(Participant.objects.filter(pk=p2.pk).exists())
        self.assertTrue(DicomFile.objects.filter(pk=df2.pk).exists())
        self.assertTrue(os.path.exists(file2_path))
        if os.path.exists(file2_path):
            os.remove(file2_path)
