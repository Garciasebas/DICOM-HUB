from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from dicom_app.models import (
    Experiment, Participant, ParticipantGroup, ExperimentParticipant,
    ConsentFile, DicomFile
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
        """TEST 3: Un participante que pertenece a un Experiment mediante ExperimentParticipant NO puede eliminarse."""
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

    def test_4_participant_with_dicom_file_cannot_be_deleted(self):
        """TEST 4: Un participante que tiene DicomFile NO puede eliminarse."""
        p_dicom = Participant.objects.create(subject_id='SUBJ-DICOM-001', first_name='David', last_name='ConDicom')
        DicomFile.objects.create(
            participant=p_dicom,
            patient_name='David ConDicom',
            file=SimpleUploadedFile('test.dcm', b'dummy content')
        )

        url = reverse('delete_participant', kwargs={'participant_id': p_dicom.pk})
        response = self.client.post(url, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Participant.objects.filter(pk=p_dicom.pk).exists())
        self.assertContains(response, 'No se puede eliminar este participante')
        self.assertContains(response, 'tiene archivos DICOM asociados')

    def test_5_participant_with_consent_file_cannot_be_deleted(self):
        """TEST 5: Un participante que tiene ConsentFile NO puede eliminarse."""
        experiment = Experiment.objects.create(name='Exp Test 5', created_by=self.user)
        p_consent = Participant.objects.create(subject_id='SUBJ-CONSENT-001', first_name='Elena', last_name='ConConsent')
        ConsentFile.objects.create(
            participant=p_consent,
            experiment=experiment,
            file=SimpleUploadedFile('consent.pdf', b'%PDF-1.4 dummy'),
            original_filename='consent.pdf',
            file_size=15
        )

        url = reverse('delete_participant', kwargs={'participant_id': p_consent.pk})
        response = self.client.post(url, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Participant.objects.filter(pk=p_consent.pk).exists())
        self.assertContains(response, 'No se puede eliminar este participante')
        self.assertContains(response, 'tiene notas de consentimiento asociadas')

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
            # Configurar el context manager mock
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

    def test_11_participant_created_without_experiments_persists_in_db(self):
        """NUEVO 1: Un participante creado sin experimentos permanece en la base de datos."""
        p_new = Participant.objects.create(subject_id='SUBJ-NEW-001', first_name='Ana', last_name='SinExp')
        self.assertEqual(p_new.experiment_participants.count(), 0)
        self.assertTrue(Participant.objects.filter(pk=p_new.pk).exists())

    def test_12_removing_participant_from_last_experiment_does_not_delete_participant(self):
        """NUEVO 2: Quitar un participante de su último experimento NO elimina el Participant."""
        experiment = Experiment.objects.create(name='Exp Unico', created_by=self.user)
        p = Participant.objects.create(subject_id='SUBJ-LAST-001', first_name='Beto', last_name='Ultimo')
        ExperimentParticipant.objects.create(experiment=experiment, participant=p)

        url_remove = reverse('remove_participant_from_experiment', args=[experiment.pk, p.pk])
        response = self.client.post(url_remove)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExperimentParticipant.objects.filter(experiment=experiment, participant=p).exists())
        self.assertTrue(Participant.objects.filter(pk=p.pk).exists())

    def test_13_deleting_experiment_does_not_delete_participants(self):
        """NUEVO 3: Eliminar un experimento NO elimina sus participantes."""
        experiment = Experiment.objects.create(name='Exp a Borrar', created_by=self.user)
        p = Participant.objects.create(subject_id='SUBJ-EXP-DEL-001', first_name='Clara', last_name='Persistente')
        ExperimentParticipant.objects.create(experiment=experiment, participant=p)

        url_del_exp = reverse('experiment_delete', kwargs={'pk': experiment.pk})
        response = self.client.post(url_del_exp)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Experiment.objects.filter(pk=experiment.pk).exists())
        self.assertTrue(Participant.objects.filter(pk=p.pk).exists())

    def test_14_participant_with_zero_experiments_appears_in_dashboard(self):
        """NUEVO 4: Un participante con 0 experimentos aparece en participant_dashboard."""
        p_zero = Participant.objects.create(subject_id='SUBJ-ZERO-001', first_name='Diego', last_name='CeroExp')
        url = reverse('participant_dashboard')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Diego CeroExp')

    def test_15_explicit_x_deletion_works_for_participant_without_experiments(self):
        """NUEVO 5: La eliminación explícita mediante la X sigue funcionando correctamente para un participante sin experimentos."""
        p_zero = Participant.objects.create(subject_id='SUBJ-ZERO-DEL-001', first_name='Eduardo', last_name='ParaBorrar')
        url_delete = reverse('delete_participant', kwargs={'participant_id': p_zero.pk})
        response = self.client.post(url_delete, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Participant.objects.filter(pk=p_zero.pk).exists())
        self.assertContains(response, 'Participante eliminado correctamente')

