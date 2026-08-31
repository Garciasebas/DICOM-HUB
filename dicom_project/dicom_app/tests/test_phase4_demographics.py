import json
import datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from dicom_app.models import (
    Experiment, Participant, ParticipantGroup, ExperimentParticipant,
    ConsentFile, DicomFile
)

class Phase4DemographicsTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='phase4_user', password='password123')
        self.client.force_login(self.user)

        self.exp = Experiment.objects.create(name="Estudio Demografia", description="Demografia", created_by=self.user)
        self.group = ParticipantGroup.objects.create(experiment=self.exp, name="Grupo Alfa")

        self.part1 = Participant.objects.create(
            subject_id="SUBJ-P4-001",
            first_name="Sebastian",
            last_name="Garcia",
            email="seba@test.com",
            phone="123456",
            details="Info confidencial"
        )
        self.ep1 = ExperimentParticipant.objects.create(
            experiment=self.exp,
            participant=self.part1,
            group=self.group
        )

    def test_01_and_02_create_participant_without_birth_date_or_sex(self):
        """1 & 2. Un participante puede crearse sin fecha de nacimiento ni sexo."""
        part = Participant.objects.create(
            subject_id="SUBJ-P4-002",
            first_name="Carlos",
            last_name="Perez"
        )
        self.assertIsNone(part.birth_date)
        self.assertIsNone(part.sex)

    def test_03_04_05_create_participant_with_birth_date_and_sex(self):
        """3, 4, 5. Un participante puede tener fecha de nacimiento y sexo almacenados correctamente."""
        bdate = datetime.date(1990, 5, 15)
        part = Participant.objects.create(
            subject_id="SUBJ-P4-003",
            first_name="Laura",
            last_name="Gomez",
            birth_date=bdate,
            sex='F'
        )
        self.assertEqual(part.birth_date, bdate)
        self.assertEqual(part.sex, 'F')

    def test_06_sex_rejects_invalid_choices(self):
        """6. El sexo solamente acepta las opciones definidas por choices."""
        url = reverse('update_participant_demographics_ajax', args=[self.part1.pk])
        res = self.client.post(
            url,
            data=json.dumps({'sex': 'X'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 400)

    def test_07_update_demographics(self):
        """7. Los datos demográficos pueden modificarse (establecer, actualizar, limpiar)."""
        url = reverse('update_participant_demographics_ajax', args=[self.part1.pk])

        # Set birth_date & sex
        res1 = self.client.post(
            url,
            data=json.dumps({'birth_date': '1985-10-20', 'sex': 'M'}),
            content_type='application/json'
        )
        self.assertEqual(res1.status_code, 200)
        self.part1.refresh_from_db()
        self.assertEqual(self.part1.birth_date, datetime.date(1985, 10, 20))
        self.assertEqual(self.part1.sex, 'M')

        # Clear birth_date & sex
        res2 = self.client.post(
            url,
            data=json.dumps({'birth_date': '', 'sex': ''}),
            content_type='application/json'
        )
        self.assertEqual(res2.status_code, 200)
        self.part1.refresh_from_db()
        self.assertIsNone(self.part1.birth_date)
        self.assertIsNone(self.part1.sex)

    def test_08_existing_participants_not_broken(self):
        """8. Los participantes existentes continúan funcionando tras la migración."""
        self.assertIsNotNone(self.part1.pk)
        self.assertEqual(self.part1.first_name, "Sebastian")

    def test_09_subject_id_retained_in_model_and_db(self):
        """9. subject_id continúa existiendo en el modelo y la base de datos."""
        self.assertEqual(self.part1.subject_id, "SUBJ-P4-001")
        part_db = Participant.objects.get(subject_id="SUBJ-P4-001")
        self.assertEqual(part_db, self.part1)

    def test_10_and_11_and_12_and_13_participant_data_screen_rendering(self):
        """10, 11, 12, 13. La pantalla "Datos del Participante" muestra Nombre, Apellido, Fecha de nacimiento, Sexo; NO muestra subject_id, email, phone, details ni "Participante: ..."; sí muestra Experimento y Grupo."""
        self.part1.birth_date = datetime.date(1995, 3, 25)
        self.part1.sex = 'M'
        self.part1.save()

        url = reverse('participant_experiment_dicoms', args=[self.part1.pk, self.exp.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        # Allowed fields shown
        self.assertIn("Sebastian", html)
        self.assertIn("Garcia", html)
        self.assertIn("25-03-1995", html)
        self.assertIn("Masculino", html)

        # Excluded fields hidden
        self.assertNotIn("SUBJ-P4-001", html)
        self.assertNotIn("seba@test.com", html)
        self.assertNotIn("123456", html)
        self.assertNotIn("Info confidencial", html)

        # Redundant header text removed
        self.assertNotIn("<strong>Participante:</strong>", html)

        # Experiment and Group preserved
        self.assertIn("Estudio Demografia", html)
        self.assertIn("Grupo Alfa", html)

    def test_14_existing_group_dicom_and_consent_functionalities_unaffected(self):
        """14. Las funciones de grupos, DICOM y consentimiento continúan funcionando."""
        ConsentFile.objects.create(participant=self.part1, experiment=self.exp, file_size=500)
        DicomFile.objects.create(participant=self.part1, experiment=self.exp)

        url = reverse('participant_experiment_dicoms', args=[self.part1.pk, self.exp.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(res.context['consent_file'])
        self.assertEqual(res.context['dicom_files'].count(), 1)

    def test_15_update_first_name_only(self):
        """15. Se puede modificar solamente el nombre manteniendo el apellido."""
        url = reverse('update_participant_demographics_ajax', args=[self.part1.pk])
        res = self.client.post(
            url,
            data=json.dumps({'first_name': 'Juan', 'last_name': 'Garcia'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        self.part1.refresh_from_db()
        self.assertEqual(self.part1.first_name, 'Juan')
        self.assertEqual(self.part1.last_name, 'Garcia')

    def test_16_update_last_name_only(self):
        """16. Se puede modificar solamente el apellido manteniendo el nombre."""
        url = reverse('update_participant_demographics_ajax', args=[self.part1.pk])
        res = self.client.post(
            url,
            data=json.dumps({'first_name': 'Sebastian', 'last_name': 'Gomez'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        self.part1.refresh_from_db()
        self.assertEqual(self.part1.first_name, 'Sebastian')
        self.assertEqual(self.part1.last_name, 'Gomez')

    def test_17_update_first_and_last_name_together(self):
        """17. Se pueden modificar nombre y apellido juntos."""
        url = reverse('update_participant_demographics_ajax', args=[self.part1.pk])
        res = self.client.post(
            url,
            data=json.dumps({'first_name': 'Mateo', 'last_name': 'Fernandez'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        self.part1.refresh_from_db()
        self.assertEqual(self.part1.first_name, 'Mateo')
        self.assertEqual(self.part1.last_name, 'Fernandez')

    def test_18_update_name_with_demographics(self):
        """18. Se pueden modificar nombre/apellido junto con fecha de nacimiento y sexo."""
        url = reverse('update_participant_demographics_ajax', args=[self.part1.pk])
        res = self.client.post(
            url,
            data=json.dumps({
                'first_name': 'Lucas',
                'last_name': 'Rios',
                'birth_date': '1992-04-12',
                'sex': 'M'
            }),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 200)
        self.part1.refresh_from_db()
        self.assertEqual(self.part1.first_name, 'Lucas')
        self.assertEqual(self.part1.last_name, 'Rios')
        self.assertEqual(self.part1.birth_date, datetime.date(1992, 4, 12))
        self.assertEqual(self.part1.sex, 'M')

    def test_19_edit_persists_in_db_and_shows_on_detail_screen(self):
        """19. Los cambios quedan persistidos y aparecen en la pantalla del participante."""
        url_edit = reverse('update_participant_demographics_ajax', args=[self.part1.pk])
        self.client.post(
            url_edit,
            data=json.dumps({'first_name': 'Sofia', 'last_name': 'Lopez'}),
            content_type='application/json'
        )

        url_screen = reverse('participant_experiment_dicoms', args=[self.part1.pk, self.exp.pk])
        res = self.client.get(url_screen)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')
        self.assertIn('Sofia', html)
        self.assertIn('Lopez', html)

    def test_20_edit_preserves_experiment_and_group_relationships(self):
        """20. La edición de nombre/apellido no altera relaciones de experimento ni grupo."""
        url_edit = reverse('update_participant_demographics_ajax', args=[self.part1.pk])
        self.client.post(
            url_edit,
            data=json.dumps({'first_name': 'Martina', 'last_name': 'Sosa'}),
            content_type='application/json'
        )

        self.ep1.refresh_from_db()
        self.assertEqual(self.ep1.experiment, self.exp)
        self.assertEqual(self.ep1.group, self.group)
        self.assertEqual(self.ep1.participant.first_name, 'Martina')

    def test_21_edit_rejects_duplicate_first_last_name(self):
        """21. La edición rechaza una combinación nombre + apellido que ya pertenece a otro participante."""
        Participant.objects.create(
            subject_id="SUBJ-P4-099",
            first_name="Esteban",
            last_name="Quito"
        )
        url_edit = reverse('update_participant_demographics_ajax', args=[self.part1.pk])
        res = self.client.post(
            url_edit,
            data=json.dumps({'first_name': 'Esteban', 'last_name': 'Quito'}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn("Ya existe un participante", data['message'])

    def test_22_birth_date_formatted_dd_mm_yyyy(self):
        """22. Comprueba que una fecha de nacimiento como 2006-02-21 se renderiza como 21-02-2006 en Datos del Participante."""
        self.part1.birth_date = datetime.date(2006, 2, 21)
        self.part1.save()

        url = reverse('participant_experiment_dicoms', args=[self.part1.pk, self.exp.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        self.assertIn('<span id="display-birth-date">21-02-2006</span>', html)
