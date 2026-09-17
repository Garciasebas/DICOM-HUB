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

    def test_14_dashboard_experiment_name_link_and_no_visualizar_column(self):
        res_dash = self.client.get(reverse('dashboard'))
        self.assertEqual(res_dash.status_code, 200)
        content = res_dash.content.decode('utf-8')

        # Verify Visualizar column is removed from table header
        self.assertNotIn('>Visualizar<', content)

        # Verify experiment name is clickable and points to experiment_detail
        url_detail = reverse('experiment_detail', kwargs={'pk': self.experiment_origin.pk})
        self.assertIn(url_detail, content)
        self.assertIn(self.experiment_origin.name, content)

        # Verify Exportación a BIDS link remains present
        url_bids = reverse('export_experiment_to_bids', args=[self.experiment_origin.pk])
        self.assertIn(url_bids, content)

    def test_15_dicom_file_delete_redirects_to_participant_experiment_dicoms(self):
        """15. Al eliminar un archivo DICOM se redirige a Datos del Participante y NO a Experimentos del Participante."""
        # 1. Access DICOM detail view from participant data context
        url_detail = reverse('dicomfile_detail', kwargs={'pk': self.dicom_file.pk})
        res_detail = self.client.get(url_detail)
        self.assertEqual(res_detail.status_code, 200)

        # 2. Execute deletion
        url_delete = reverse('dicomfile_delete', kwargs={'pk': self.dicom_file.pk})
        res_delete = self.client.post(url_delete)

        # 3. Confirm file was deleted from DB
        self.assertFalse(DicomFile.objects.filter(pk=self.dicom_file.pk).exists())

        # 4. Confirm redirect URL is participant_experiment_dicoms (Datos del Participante)
        expected_url = reverse('participant_experiment_dicoms', kwargs={
            'participant_id': self.participant.pk,
            'experiment_id': self.experiment_origin.pk
        })
        wrong_url = reverse('participant_experiments', kwargs={'participant_id': self.participant.pk})

        self.assertEqual(res_delete.status_code, 302)
        self.assertRedirects(res_delete, expected_url)

        # 5. Confirm it does NOT redirect to participant_experiments
        self.assertNotEqual(res_delete.url, wrong_url)

    def test_16_participant_experiments_simplified_table_and_name_link(self):
        """16. En Experimentos del Participante la tabla no tiene Visualizar y el nombre del experimento lleva a Datos del Participante."""
        url_part_exp = reverse('participant_experiments', kwargs={'participant_id': self.participant.pk})
        res = self.client.get(url_part_exp)
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')

        # 1. Verify "Visualizar" column is removed from table header
        self.assertNotIn('>Visualizar<', content)

        # 2. Verify "Archivos DICOM" and "Nota de Consentimiento" links are removed from this table
        self.assertNotIn('Archivos DICOM', content)
        self.assertNotIn('Nota de Consentimiento', content)

        # 3. Verify experiment name appears as a link pointing to participant_experiment_dicoms
        target_url = reverse('participant_experiment_dicoms', kwargs={
            'participant_id': self.participant.pk,
            'experiment_id': self.experiment_origin.pk
        })
        self.assertIn(target_url, content)
        self.assertIn(self.experiment_origin.name, content)

        # 4. Verify accessing participant_experiment_dicoms view works cleanly
        res_target = self.client.get(target_url)
        self.assertEqual(res_target.status_code, 200)
        content_target = res_target.content.decode('utf-8')
        self.assertIn('Participación en el Experimento', content_target)
        self.assertIn('Información del Participante', content_target)

    def test_17_flow_1_navigation_from_participants(self):
        """TEST A: Flujo 1 desde Participantes -> Experimentos del Participante -> Participación en el Experimento"""
        # 1. Access view without from_experiment (from Participants flow)
        url_part_exp = reverse('participant_experiments', kwargs={'participant_id': self.participant.pk})
        url_part_dicoms = reverse('participant_experiment_dicoms', kwargs={
            'participant_id': self.participant.pk,
            'experiment_id': self.experiment_origin.pk
        })
        res = self.client.get(url_part_dicoms)
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')

        # 2. Verify Breadcrumb for Flow 1
        url_part_list = reverse('participant_list')
        self.assertIn(url_part_list, content)
        self.assertIn('Participantes', content)
        self.assertIn(url_part_exp, content)
        self.assertIn('Experimentos del Participante', content)
        self.assertIn('Participación en el Experimento', content)

        # 3. Verify Atrás button returns to Experimentos del Participante
        self.assertIn(f'href="{url_part_exp}"', content)

    def test_18_flow_2_navigation_from_experiments(self):
        """TEST B: Flujo 2 desde Listado de Experimentos -> Detalle del Experimento -> Participación en el Experimento"""
        # 1. Access view with from_experiment (from Experiments flow)
        url_exp_detail = reverse('experiment_detail', kwargs={'pk': self.experiment_origin.pk})
        url_part_dicoms = f"{reverse('participant_experiment_dicoms', kwargs={'participant_id': self.participant.pk, 'experiment_id': self.experiment_origin.pk})}?from_experiment={self.experiment_origin.pk}"
        res = self.client.get(url_part_dicoms)
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')

        # 2. Verify Breadcrumb for Flow 2
        url_dash = reverse('dashboard')
        self.assertIn(url_dash, content)
        self.assertIn('Listado de Experimentos', content)
        self.assertIn(url_exp_detail, content)
        self.assertIn('Detalle del Experimento', content)
        self.assertIn('Participación en el Experimento', content)

        # 3. Verify Atrás button returns to Detalle del Experimento
        self.assertIn(f'href="{url_exp_detail}"', content)

    def test_20_participacion_en_el_experimento_renaming(self):
        """20. Comprueba que la vista muestra 'Participación en el Experimento' y YA NO muestra 'Datos del Participante' como título/cabecera."""
        url_flow1 = reverse('participant_experiment_dicoms', kwargs={
            'participant_id': self.participant.pk,
            'experiment_id': self.experiment_origin.pk
        })
        res1 = self.client.get(url_flow1)
        self.assertEqual(res1.status_code, 200)
        html1 = res1.content.decode('utf-8')
        self.assertIn("Participación en el Experimento", html1)
        self.assertNotIn("Datos del Participante", html1)

        url_flow2 = f"{url_flow1}?from_experiment={self.experiment_origin.pk}"
        res2 = self.client.get(url_flow2)
        self.assertEqual(res2.status_code, 200)
        html2 = res2.content.decode('utf-8')
        self.assertIn("Participación en el Experimento", html2)
        self.assertNotIn("Datos del Participante", html2)

    def test_19_participant_dashboard_header_and_ver_experimentos_link(self):
        """19. En Listado de Participantes se muestra 'Experimentos' y 'Ver experimentos' apuntando a participant_experiments."""
        url_part_dash = reverse('participant_dashboard')
        res = self.client.get(url_part_dash)
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')

        # 1. Verify "Visualizar" header is removed and "Experimentos" is present
        self.assertNotIn('>Visualizar<', content)
        self.assertIn('>Experimentos<', content)

        # 2. Verify "Detalles" text link is removed and "Ver experimentos" is present
        self.assertNotIn('Detalles</a>', content)
        self.assertIn('Ver experimentos</a>', content)

        # 3. Verify "Ver experimentos" points to participant_experiments
        target_url = reverse('participant_experiments', kwargs={'participant_id': self.participant.pk})
        self.assertIn(target_url, content)

        # 4. Verify accessing participant_experiments works correctly
        res_part_exp = self.client.get(target_url)
        self.assertEqual(res_part_exp.status_code, 200)

    def test_21_dicom_file_detail_navigation_from_experiments(self):
        """21. Acceder al detalle DICOM desde Experimentos conserva el breadcrumb de Experimentos y el botón Atrás."""
        # 1. Access participant_experiment_dicoms with from_experiment
        url_part_dicoms = f"{reverse('participant_experiment_dicoms', kwargs={'participant_id': self.participant.pk, 'experiment_id': self.experiment_origin.pk})}?from_experiment={self.experiment_origin.pk}"
        res_part_dicoms = self.client.get(url_part_dicoms)
        self.assertEqual(res_part_dicoms.status_code, 200)
        content_part_dicoms = res_part_dicoms.content.decode('utf-8')

        # Verify details link includes ?from_experiment=...
        dicom_detail_url_with_context = f"{reverse('dicomfile_detail', kwargs={'pk': self.dicom_file.pk})}?from_experiment={self.experiment_origin.pk}"
        self.assertIn(dicom_detail_url_with_context, content_part_dicoms)

        # 2. Access DICOM file detail view with from_experiment
        res_dicom_detail = self.client.get(dicom_detail_url_with_context)
        self.assertEqual(res_dicom_detail.status_code, 200)
        content_detail = res_dicom_detail.content.decode('utf-8')

        # 3. Verify Breadcrumb for Flow Experimentos
        url_dash = reverse('dashboard')
        url_exp_detail = reverse('experiment_detail', kwargs={'pk': self.experiment_origin.pk})
        self.assertIn(url_dash, content_detail)
        self.assertIn('Listado de Experimentos', content_detail)
        self.assertIn(url_exp_detail, content_detail)
        self.assertIn('Detalle del Experimento', content_detail)
        self.assertIn(url_part_dicoms, content_detail)
        self.assertIn('Participación en el Experimento', content_detail)
        self.assertIn('Detalle de Archivo DICOM', content_detail)

        # 4. Verify Atrás button points back to participant_experiment_dicoms with from_experiment
        self.assertIn(f'href="{url_part_dicoms}"', content_detail)

    def test_22_dicom_file_detail_navigation_from_participants(self):
        """22. Acceder al detalle DICOM desde Participantes conserva el breadcrumb de Participantes y el botón Atrás."""
        # 1. Access participant_experiment_dicoms without from_experiment
        url_part_dicoms = reverse('participant_experiment_dicoms', kwargs={'participant_id': self.participant.pk, 'experiment_id': self.experiment_origin.pk})
        res_part_dicoms = self.client.get(url_part_dicoms)
        self.assertEqual(res_part_dicoms.status_code, 200)
        content_part_dicoms = res_part_dicoms.content.decode('utf-8')

        # Verify details link points to dicomfile_detail without from_experiment
        dicom_detail_url = reverse('dicomfile_detail', kwargs={'pk': self.dicom_file.pk})
        self.assertIn(dicom_detail_url, content_part_dicoms)
        self.assertNotIn(f"{dicom_detail_url}?from_experiment", content_part_dicoms)

        # 2. Access DICOM file detail view without from_experiment
        res_dicom_detail = self.client.get(dicom_detail_url)
        self.assertEqual(res_dicom_detail.status_code, 200)
        content_detail = res_dicom_detail.content.decode('utf-8')

        # 3. Verify Breadcrumb for Flow Participantes
        url_part_list = reverse('participant_list')
        url_part_exp = reverse('participant_experiments', kwargs={'participant_id': self.participant.pk})
        self.assertIn(url_part_list, content_detail)
        self.assertIn('Participantes', content_detail)
        self.assertIn(url_part_exp, content_detail)
        self.assertIn('Experimentos del Participante', content_detail)
        self.assertIn(url_part_dicoms, content_detail)
        self.assertIn('Participación en el Experimento', content_detail)
        self.assertIn('Detalle de Archivo DICOM', content_detail)

        # 4. Verify Atrás button points back to participant_experiment_dicoms without from_experiment
        self.assertIn(f'href="{url_part_dicoms}"', content_detail)

