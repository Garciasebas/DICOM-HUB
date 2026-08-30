import os
import tempfile
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from dicom_app.models import (
    Experiment, Participant, ParticipantGroup, ExperimentParticipant,
    ConsentFile, DicomFile
)

class Phase3ParticipantDetailTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user1 = User.objects.create_user(username='phase3_inv1', password='password123')
        self.user2 = User.objects.create_user(username='phase3_inv2', password='password123')
        self.client.force_login(self.user1)

        self.exp1 = Experiment.objects.create(name="Estudio Alfa P3", description="Alfa P3", created_by=self.user1)
        self.exp2 = Experiment.objects.create(name="Estudio Beta P3", description="Beta P3", created_by=self.user1)
        self.exp_unauth = Experiment.objects.create(name="Estudio Ajeno", description="Ajeno", created_by=self.user2)

        self.group1_exp1 = ParticipantGroup.objects.create(experiment=self.exp1, name="Control Alfa")
        self.group1_exp2 = ParticipantGroup.objects.create(experiment=self.exp2, name="Placebo Beta")

        self.part1 = Participant.objects.create(
            subject_id="SUBJ-P3-1",
            first_name="Sebastian",
            last_name="Garcia",
            email="seba@test.com",
            phone="123456789",
            details="Participante de prueba"
        )
        self.part2 = Participant.objects.create(
            subject_id="SUBJ-P3-2",
            first_name="Jorge",
            last_name="Garcia"
        )

        self.ep1_exp1 = ExperimentParticipant.objects.create(
            experiment=self.exp1,
            participant=self.part1,
            group=self.group1_exp1
        )
        self.ep1_exp2 = ExperimentParticipant.objects.create(
            experiment=self.exp2,
            participant=self.part1,
            group=self.group1_exp2
        )
        self.ep2_exp1 = ExperimentParticipant.objects.create(
            experiment=self.exp1,
            participant=self.part2,
            group=None
        )

    def test_01_and_02_and_03_access_participant_data_in_experiment(self):
        """1, 2, 3. Acceso correcto a datos del participante mostrando el participante y experimento seleccionados."""
        url = reverse('participant_experiment_dicoms', args=[self.part1.pk, self.exp1.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['participant'], self.part1)
        self.assertEqual(res.context['experiment'], self.exp1)
        self.assertIn("Datos del Participante", res.content.decode('utf-8'))
        self.assertIn("Sebastian", res.content.decode('utf-8'))
        self.assertIn("Garcia", res.content.decode('utf-8'))
        self.assertIn("Estudio Alfa P3", res.content.decode('utf-8'))

    def test_04_display_correct_group_for_experiment(self):
        """4. El grupo mostrado corresponde al grupo del participante dentro de ese experimento."""
        url = reverse('participant_experiment_dicoms', args=[self.part1.pk, self.exp1.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['group'], self.group1_exp1)
        self.assertIn("Control Alfa", res.content.decode('utf-8'))

    def test_05_different_groups_in_different_experiments(self):
        """5. Un participante puede pertenecer a diferentes grupos en diferentes experimentos y se muestra el correcto."""
        url1 = reverse('participant_experiment_dicoms', args=[self.part1.pk, self.exp1.pk])
        res1 = self.client.get(url1)
        self.assertEqual(res1.context['group'], self.group1_exp1)

        url2 = reverse('participant_experiment_dicoms', args=[self.part1.pk, self.exp2.pk])
        res2 = self.client.get(url2)
        self.assertEqual(res2.context['group'], self.group1_exp2)

    def test_06_link_from_experiment_detail_leads_to_participant_data(self):
        """6. El enlace desde "Detalle del Experimento" lleva al participante y experimento correctos."""
        url_detail = reverse('experiment_detail', args=[self.exp1.pk])
        res = self.client.get(url_detail)
        self.assertEqual(res.status_code, 200)
        target_url = reverse('participant_experiment_dicoms', args=[self.part1.pk, self.exp1.pk])
        self.assertIn(target_url, res.content.decode('utf-8'))

    def test_07_and_08_experiment_detail_table_headers_and_columns_simplified(self):
        """7 & 8. Las columnas Consentimiento/DICOM y el texto ACCIONES no aparecen en la tabla de participantes."""
        url_detail = reverse('experiment_detail', args=[self.exp1.pk])
        res = self.client.get(url_detail)
        html = res.content.decode('utf-8')
        
        # Check simplified headers in participant table
        self.assertNotIn("<div>Consentimiento</div>", html)
        self.assertNotIn("<div>DICOM</div>", html)
        self.assertNotIn("<div class=\"text-end\">Acciones</div>", html)
        self.assertNotIn("ARCHIVOS", html)

    def test_09_remove_participant_button_remains_functional(self):
        """9. La X de eliminación del participante en el experimento continúa funcionando."""
        url_remove = reverse('remove_participant_from_experiment', args=[self.exp1.pk, self.part2.pk])
        res = self.client.post(url_remove)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(ExperimentParticipant.objects.filter(experiment=self.exp1, participant=self.part2).exists())

    def test_10_render_without_consent_note(self):
        """10. Visualización cuando no existe nota de consentimiento."""
        url = reverse('participant_experiment_dicoms', args=[self.part1.pk, self.exp1.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(res.context['consent_file'])
        self.assertIn("No se ha cargado una nota de consentimiento", res.content.decode('utf-8'))

    def test_11_render_with_consent_note(self):
        """11. Visualización cuando existe nota de consentimiento."""
        consent = ConsentFile.objects.create(
            participant=self.part1,
            experiment=self.exp1,
            original_filename="consentimiento_seba.pdf",
            file_size=1024
        )
        url = reverse('participant_experiment_dicoms', args=[self.part1.pk, self.exp1.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['consent_file'], consent)
        self.assertIn("Nota de consentimiento cargada", res.content.decode('utf-8'))

    def test_12_render_without_dicom_files(self):
        """12. Visualización cuando no existen DICOM."""
        url = reverse('participant_experiment_dicoms', args=[self.part1.pk, self.exp1.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['dicom_files'].count(), 0)
        self.assertIn("No hay archivos DICOM para este participante en este experimento", res.content.decode('utf-8'))

    def test_13_render_with_dicom_files(self):
        """13. Visualización cuando existen DICOM."""
        dicom = DicomFile.objects.create(
            participant=self.part1,
            experiment=self.exp1,
            original_filename="escaneo_brain.dcm"
        )
        url = reverse('participant_experiment_dicoms', args=[self.part1.pk, self.exp1.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['dicom_files'].count(), 1)
        self.assertIn("escaneo_brain.dcm", res.content.decode('utf-8'))

    @patch('dicom_app.views.process_dicom_file')
    def test_14_and_15_upload_dicom_redirects_to_participant_data(self, mock_process):
        """14 & 15. La carga de DICOM funciona y después de cargar se muestra el enlace a Datos del Participante."""
        dicom_instance = DicomFile.objects.create(participant=self.part1, experiment=self.exp1, original_filename="test.dcm")
        mock_process.return_value = (dicom_instance, {})

        url_upload = reverse('upload_participant_dicom', args=[self.exp1.pk, self.part1.pk])
        file = SimpleUploadedFile("test.dcm", b"dummy_content", content_type="application/dicom")
        
        res = self.client.post(url_upload, {'dicom_file': file})
        self.assertEqual(res.status_code, 200)
        self.assertIn("Volver a Datos del Participante", res.content.decode('utf-8'))
        target_url = reverse('participant_experiment_dicoms', args=[self.part1.pk, self.exp1.pk])
        self.assertIn(target_url, res.content.decode('utf-8'))

    def test_16_and_17_upload_consent_redirects_to_participant_data(self):
        """16 & 17. La carga de consentimiento funciona y regresa a Datos del Participante."""
        url_upload = reverse('upload_consent_note', args=[self.exp1.pk, self.part1.pk])
        pdf_content = b'%PDF-1.4 test content'
        file = SimpleUploadedFile("consent.pdf", pdf_content, content_type="application/pdf")
        
        res = self.client.post(url_upload, {'consent_file': file})
        self.assertEqual(res.status_code, 200)
        self.assertIn("Volver a Datos del Participante", res.content.decode('utf-8'))
        target_url = reverse('participant_experiment_dicoms', args=[self.part1.pk, self.exp1.pk])
        self.assertIn(target_url, res.content.decode('utf-8'))

    def test_18_access_participant_from_unrelated_experiment_rejected(self):
        """18. Acceso a un participante de otro experimento (no asociado a él) es rechazado (404)."""
        part_unassociated = Participant.objects.create(subject_id="SUBJ-OTHER", first_name="Carlos", last_name="Sosa")
        url = reverse('participant_experiment_dicoms', args=[part_unassociated.pk, self.exp1.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 404)

    def test_19_unauthorized_access_rejected(self):
        """19. Acceso no autorizado a experimentos de otros usuarios es rechazado."""
        url = reverse('participant_experiment_dicoms', args=[self.part1.pk, self.exp_unauth.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 404)

    def test_20_no_regressions_in_groups_and_participants(self):
        """20. No existen regresiones en grupos ni participantes."""
        self.assertEqual(self.exp1.participants.count(), 2)
        self.assertEqual(self.exp1.groups.count(), 1)
        self.assertEqual(self.group1_exp1.experiment_participants.count(), 1)
