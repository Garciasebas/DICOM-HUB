import uuid
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from dicom_app.models import Experiment, Participant, Member, DicomFile

class NavigationAndValidationTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username='test_nav_admin',
            email='admin@test.com',
            password='password123'
        )
        self.client.force_login(self.admin_user)

        self.uid = str(uuid.uuid4())[:8]
        self.participant = Participant.objects.create(
            first_name=f'NavUser_{self.uid}',
            last_name=f'NavTest_{self.uid}',
            subject_id=f'SUBJ_NAV_{self.uid}'
        )

        self.member = Member.objects.create(
            first_name=f'NavMember_{self.uid}',
            last_name='Test',
            role='Neurólogo/a'
        )

        self.experiment_origin = Experiment.objects.create(
            name=f'Alfa_Origen_{self.uid}',
            description='Experimento de origen',
            created_by=self.admin_user
        )
        self.experiment_origin.participants.add(self.participant)
        self.experiment_origin.members.add(self.member)

        self.experiment_second = Experiment.objects.create(
            name=f'Beta_Secundario_{self.uid}',
            description='Experimento secundario',
            created_by=self.admin_user
        )
        self.experiment_second.participants.add(self.participant)
        self.experiment_second.members.add(self.member)

        self.dicom_file = DicomFile.objects.create(
            participant=self.participant,
            experiment=self.experiment_origin,
            patient_name=f'ORIGINAL_PATIENT_{self.uid}',
            file='dicoms/test.dcm'
        )

    def test_01_experiment_detail_and_from_experiment_link(self):
        url_exp_detail = reverse('experiment_detail', kwargs={'pk': self.experiment_origin.pk})
        res_exp_detail = self.client.get(url_exp_detail)
        self.assertEqual(res_exp_detail.status_code, 200)

        url_part_dicoms = reverse('participant_experiment_dicoms', kwargs={'participant_id': self.participant.pk, 'experiment_id': self.experiment_origin.pk})
        self.assertIn(url_part_dicoms, res_exp_detail.content.decode('utf-8'))

    def test_02_participant_experiments_search_with_from_experiment(self):
        url_part_experiments = reverse('participant_experiments', kwargs={'participant_id': self.participant.pk})
        url_search_with_context = f'{url_part_experiments}?from_experiment={self.experiment_origin.pk}&q=Alfa'
        res_search = self.client.get(url_search_with_context)
        self.assertEqual(res_search.status_code, 200)
        content_search = res_search.content.decode('utf-8')

        tbody_search = content_search.split('<tbody>')[1].split('</tbody>')[0]
        self.assertIn(self.experiment_origin.name, tbody_search)
        self.assertNotIn(self.experiment_second.name, tbody_search)
        self.assertIn(f'name="from_experiment" value="{self.experiment_origin.pk}"', content_search)

    def test_03_participant_experiments_search_no_match(self):
        url_part_experiments = reverse('participant_experiments', kwargs={'participant_id': self.participant.pk})
        url_no_match = f'{url_part_experiments}?from_experiment={self.experiment_origin.pk}&q=InexistenteXYZ'
        res_no_match = self.client.get(url_no_match)
        self.assertEqual(res_no_match.status_code, 200)
        content_no_match = res_no_match.content.decode('utf-8')
        tbody_no_match = content_no_match.split('<tbody>')[1].split('</tbody>')[0]
        self.assertNotIn(self.experiment_origin.name, tbody_no_match)
        self.assertNotIn(self.experiment_second.name, tbody_no_match)
        self.assertIn("No se encontraron experimentos", tbody_no_match)

    def test_04_participant_experiments_search_without_from_experiment(self):
        url_part_experiments = reverse('participant_experiments', kwargs={'participant_id': self.participant.pk})
        url_direct_search = f'{url_part_experiments}?q=Beta'
        res_direct_search = self.client.get(url_direct_search)
        self.assertEqual(res_direct_search.status_code, 200)
        content_direct = res_direct_search.content.decode('utf-8')
        tbody_direct = content_direct.split('<tbody>')[1].split('</tbody>')[0]
        self.assertIn(self.experiment_second.name, tbody_direct)
        self.assertNotIn(self.experiment_origin.name, tbody_direct)
        self.assertNotIn('from_experiment', content_direct)

    def test_05_participant_dashboard_search_bar(self):
        res_part_dash = self.client.get(reverse('participant_dashboard'))
        self.assertEqual(res_part_dash.status_code, 200)
        content = res_part_dash.content.decode('utf-8')
        self.assertIn('class="search-bar"', content)
        self.assertIn('class="search-input"', content)

    def test_06_inline_patient_name_edit_ajax(self):
        url_dicom_detail = reverse('dicomfile_detail', kwargs={'pk': self.dicom_file.pk})
        res_dicom_detail = self.client.get(url_dicom_detail)
        self.assertEqual(res_dicom_detail.status_code, 200)
        self.assertIn(f'ORIGINAL_PATIENT_{self.uid}', res_dicom_detail.content.decode('utf-8'))

        new_patient_name = f'UPDATED_PATIENT_{self.uid}'
        res_post_update = self.client.post(
            url_dicom_detail,
            data={'patient_name': new_patient_name},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_post_update.status_code, 200)
        self.assertEqual(res_post_update.json().get('status'), 'success')
        self.assertEqual(res_post_update.json().get('patient_name'), new_patient_name)

        self.dicom_file.refresh_from_db()
        self.assertEqual(self.dicom_file.patient_name, new_patient_name)

    def test_07_experiment_create_validation_name_only(self):
        url_create_exp = reverse('experiment_create')
        res_only_name = self.client.post(url_create_exp, data={'name': 'Solo Nombre'})
        self.assertEqual(res_only_name.status_code, 200)
        self.assertIn('La descripción del experimento es obligatoria.', res_only_name.content.decode('utf-8'))
        self.assertFalse(Experiment.objects.filter(name='Solo Nombre').exists())

    def test_08_experiment_create_without_participants_or_members_is_valid(self):
        url_create_exp = reverse('experiment_create')
        res_name_desc = self.client.post(url_create_exp, data={
            'name': 'Nombre y Desc Solo',
            'description': 'Una descripcion valida'
        })
        self.assertIn(res_name_desc.status_code, [200, 302])
        created_exp = Experiment.objects.filter(name='Nombre y Desc Solo').first()
        self.assertIsNotNone(created_exp)
        self.assertEqual(created_exp.participants.count(), 0)
        self.assertEqual(created_exp.members.count(), 0)

    def test_10_experiment_create_validation_empty_name(self):
        url_create_exp = reverse('experiment_create')
        res_empty_name = self.client.post(url_create_exp, data={
            'name': '   ',
            'description': 'Descripcion valida'
        })
        self.assertEqual(res_empty_name.status_code, 200)
        self.assertIn('El nombre del experimento es obligatorio.', res_empty_name.content.decode('utf-8'))

    def test_11_experiment_create_validation_empty_description(self):
        url_create_exp = reverse('experiment_create')
        res_empty_desc = self.client.post(url_create_exp, data={
            'name': 'Nombre Valido',
            'description': '    '
        })
        self.assertEqual(res_empty_desc.status_code, 200)
        self.assertIn('La descripción del experimento es obligatoria.', res_empty_desc.content.decode('utf-8'))

    def test_12_experiment_create_validation_description_exceeds_300(self):
        url_create_exp = reverse('experiment_create')
        long_desc = 'A' * 301
        res_long_desc = self.client.post(url_create_exp, data={
            'name': 'Nombre Valido',
            'description': long_desc
        })
        self.assertEqual(res_long_desc.status_code, 200)
        self.assertIn('La descripción del experimento no puede superar los 300 caracteres.', res_long_desc.content.decode('utf-8'))

    def test_13_experiment_create_valid_submission(self):
        url_create_exp = reverse('experiment_create')
        exp_valid_name = f'Experimento_Valido_{self.uid}'
        res_valid = self.client.post(url_create_exp, data={
            'name': exp_valid_name,
            'description': 'Descripcion completa y valida.'
        })
        self.assertIn(res_valid.status_code, [200, 302])
        created_exp = Experiment.objects.filter(name=exp_valid_name).first()
        self.assertIsNotNone(created_exp)
        self.assertEqual(created_exp.name, exp_valid_name)
