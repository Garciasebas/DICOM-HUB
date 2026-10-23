import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from dicom_app.models import Experiment, Participant, ParticipantGroup, ExperimentParticipant, DicomFile

class Phase3GroupDetailTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # User 1: Authorized Researcher
        self.user1 = User.objects.create_user(username='group_inv1', password='password123')
        # User 2: Unauthorized Researcher
        self.user2 = User.objects.create_user(username='group_inv2', password='password123')

        self.client.force_login(self.user1)

        # Experiments
        self.exp1 = Experiment.objects.create(
            name="Estudio Grupo Alfa",
            description="Descripcion Alfa",
            created_by=self.user1
        )
        self.exp2 = Experiment.objects.create(
            name="Estudio Grupo Beta",
            description="Descripcion Beta",
            created_by=self.user1
        )
        self.exp_unauth = Experiment.objects.create(
            name="Estudio Ajeno",
            description="Ajeno",
            created_by=self.user2
        )

        # Groups
        self.group1_exp1 = ParticipantGroup.objects.create(
            experiment=self.exp1,
            name="Control Alfa",
            description="Grupo de control para Alfa"
        )
        self.group2_exp1 = ParticipantGroup.objects.create(
            experiment=self.exp1,
            name="Tratamiento Alfa",
            description=""
        )
        self.group1_exp2 = ParticipantGroup.objects.create(
            experiment=self.exp2,
            name="Control Beta"
        )

        # Participants
        self.part1 = Participant.objects.create(
            subject_id="SUBJ-G-1",
            first_name="Carlos",
            last_name="Mendoza"
        )
        self.part2 = Participant.objects.create(
            subject_id="SUBJ-G-2",
            first_name="Lucia",
            last_name="Fernandez"
        )
        self.part3 = Participant.objects.create(
            subject_id="SUBJ-G-3",
            first_name="Mateo",
            last_name="Gomez"
        )

        # Associate participants
        self.ep1 = ExperimentParticipant.objects.create(
            experiment=self.exp1,
            participant=self.part1,
            group=self.group1_exp1
        )
        self.ep2 = ExperimentParticipant.objects.create(
            experiment=self.exp1,
            participant=self.part2,
            group=self.group2_exp1
        )

        self.dicom1 = DicomFile.objects.create(
            participant=self.part1,
            experiment=self.exp1,
            patient_name="PACIENTE_01",
            file="dicoms/test1.dcm"
        )

    # --- Acceso y Visualización ---

    def test_01_authorized_user_can_access_group_detail(self):
        """1. Un usuario autorizado puede abrir el detalle de un grupo."""
        url = reverse('group_detail', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'dicom_app/group_detail.html')
        self.assertEqual(res.context['experiment'], self.exp1)
        self.assertEqual(res.context['group'], self.group1_exp1)

    def test_02_unauthorized_user_cannot_access_group_detail(self):
        """2. Un usuario sin permisos no puede acceder (404 para otro investigador)."""
        self.client.force_login(self.user2)
        url = reverse('group_detail', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 404)

    def test_03_group_from_another_experiment_returns_404(self):
        """3. Un grupo de otro experimento no puede abrirse manipulando la URL."""
        # Intenta abrir group1_exp2 (de exp2) usando la URL de exp1
        url = reverse('group_detail', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp2.pk})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 404)

    def test_04_displays_non_editable_experiment_name(self):
        """4. Se muestra el nombre correcto del experimento de forma no editable."""
        url = reverse('group_detail', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.get(url)
        html = res.content.decode('utf-8')
        self.assertIn("Estudio Grupo Alfa", html)
        self.assertIn("Experimento:", html)

    def test_05_breadcrumbs_link_to_experiment_detail_and_dashboard(self):
        """5. Las migas de pan apuntan a las páginas correspondientes."""
        url = reverse('group_detail', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.get(url)
        html = res.content.decode('utf-8')
        self.assertIn(reverse('dashboard'), html)
        self.assertIn(reverse('experiment_detail', kwargs={'pk': self.exp1.pk}), html)

    def test_06_displays_only_participants_of_current_group_and_experiment(self):
        """6. Solo se muestran los participantes asociados al grupo actual y al experimento actual."""
        url = reverse('group_detail', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.get(url)
        participants = list(res.context['experiment_participants'])
        self.assertIn(self.ep1, participants)
        self.assertNotIn(self.ep2, participants)  # Perteneciente a group2_exp1

    def test_07_empty_group_shows_empty_message_and_plus_button(self):
        """7. Un grupo sin participantes muestra el mensaje de estado vacío y mantiene visible el botón +."""
        empty_group = ParticipantGroup.objects.create(experiment=self.exp1, name="Grupo Vacio")
        url = reverse('group_detail', kwargs={'pk': self.exp1.pk, 'group_id': empty_group.pk})
        res = self.client.get(url)
        html = res.content.decode('utf-8')
        self.assertIn("Este grupo todavía no tiene participantes.", html)
        self.assertIn('id="btn-add-participant-group"', html)

    def test_08_no_id_sujeto_or_creation_date_in_participant_table(self):
        """8. La tabla no muestra columna ID SUJETO ni fecha de creación del participante."""
        url = reverse('group_detail', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.get(url)
        html = res.content.decode('utf-8')
        self.assertNotIn("ID Sujeto", html)
        self.assertNotIn("ID SUJETO", html)
        self.assertIn("Nombre del participante", html)
        self.assertIn("btn-remove-x", html)

    # --- Edición del Grupo ---

    def test_09_update_group_name_success(self):
        """9. Se puede modificar correctamente el nombre del grupo."""
        url = reverse('update_group_name_ajax', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.post(url, data=json.dumps({'name': 'Nuevo Nombre Control'}), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['name'], 'Nuevo Nombre Control')

        self.group1_exp1.refresh_from_db()
        self.assertEqual(self.group1_exp1.name, 'Nuevo Nombre Control')

    def test_10_update_group_name_reject_empty_or_whitespace(self):
        """10. Se rechazan nombres vacíos o compuestos únicamente por espacios."""
        url = reverse('update_group_name_ajax', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.post(url, data=json.dumps({'name': '   '}), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn("El nombre del grupo no puede estar vacío.", data['message'])

    def test_11_update_group_name_reject_duplicate_in_same_experiment(self):
        """11. Se rechaza un nombre duplicado dentro del mismo experimento."""
        url = reverse('update_group_name_ajax', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.post(url, data=json.dumps({'name': 'Tratamiento Alfa'}), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn("Ya existe un grupo llamado 'Tratamiento Alfa' en este experimento.", data['message'])

    def test_12_update_group_name_allow_keeping_own_name(self):
        """12. Se permite conservar el nombre actual sin generar un falso error de duplicidad."""
        url = reverse('update_group_name_ajax', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.post(url, data=json.dumps({'name': 'Control Alfa'}), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')

    def test_13_update_group_description_success(self):
        """13. Se puede modificar la descripción."""
        url = reverse('update_group_description_ajax', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.post(url, data=json.dumps({'description': 'Nueva descripción detallada.'}), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['description'], 'Nueva descripción detallada.')

        self.group1_exp1.refresh_from_db()
        self.assertEqual(self.group1_exp1.description, 'Nueva descripción detallada.')

    def test_14_update_group_description_allow_blank(self):
        """14. Se puede guardar una descripción vacía."""
        url = reverse('update_group_description_ajax', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.post(url, data=json.dumps({'description': '   '}), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['description'], '')

        self.group1_exp1.refresh_from_db()
        self.assertEqual(self.group1_exp1.description, '')

    def test_15_unauthorized_user_cannot_update_group(self):
        """15. Un usuario sin permisos no puede modificar el nombre ni la descripción mediante los endpoints AJAX."""
        self.client.force_login(self.user2)
        url_name = reverse('update_group_name_ajax', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res1 = self.client.post(url_name, data=json.dumps({'name': 'Hack Name'}), content_type='application/json')
        self.assertEqual(res1.status_code, 404)

        url_desc = reverse('update_group_description_ajax', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res2 = self.client.post(url_desc, data=json.dumps({'description': 'Hack Desc'}), content_type='application/json')
        self.assertEqual(res2.status_code, 404)

    def test_16_reject_non_post_methods(self):
        """16. Se rechazan solicitudes con métodos HTTP no permitidos."""
        url_name = reverse('update_group_name_ajax', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res1 = self.client.get(url_name)
        self.assertEqual(res1.status_code, 405)

        url_desc = reverse('update_group_description_ajax', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res2 = self.client.get(url_desc)
        self.assertEqual(res2.status_code, 405)

    def test_17_verify_group_belongs_to_experiment_on_update(self):
        """17. Se verifica que el grupo pertenezca al experimento antes de actualizarlo."""
        # Intenta actualizar group1_exp2 (de exp2) usando la URL de exp1
        url_name = reverse('update_group_name_ajax', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp2.pk})
        res = self.client.post(url_name, data=json.dumps({'name': 'Hack Name'}), content_type='application/json')
        self.assertEqual(res.status_code, 404)

    def test_18_remove_participant_from_group_success(self):
        """18. Eliminar la asociación del participante con el grupo no elimina el participante global ni sus datos."""
        url = reverse('remove_group_participant_ajax', kwargs={
            'pk': self.exp1.pk,
            'group_id': self.group1_exp1.pk,
            'participant_id': self.part1.pk
        })
        res = self.client.post(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')

        # La asociación ExperimentParticipant del grupo/exp fue eliminada
        self.assertFalse(ExperimentParticipant.objects.filter(
            experiment=self.exp1, group=self.group1_exp1, participant=self.part1
        ).exists())

        # El objeto global Participant se conserva en la BD
        self.assertTrue(Participant.objects.filter(pk=self.part1.pk).exists())

    def test_19_remove_participant_does_not_affect_other_experiments(self):
        """19. Eliminar asociación no afecta las asociaciones del participante con otros experimentos."""
        # Asociar part1 a exp2
        ep_other = ExperimentParticipant.objects.create(
            experiment=self.exp2, participant=self.part1, group=self.group1_exp2
        )

        url = reverse('remove_group_participant_ajax', kwargs={
            'pk': self.exp1.pk,
            'group_id': self.group1_exp1.pk,
            'participant_id': self.part1.pk
        })
        res = self.client.post(url)
        self.assertEqual(res.status_code, 200)

        # La asociación con exp2 se conserva intacta
        self.assertTrue(ExperimentParticipant.objects.filter(pk=ep_other.pk).exists())

    def test_20_unauthorized_user_cannot_remove_participant_from_group(self):
        """20. Un usuario sin permisos no puede eliminar una asociación de participante."""
        self.client.force_login(self.user2)
        url = reverse('remove_group_participant_ajax', kwargs={
            'pk': self.exp1.pk,
            'group_id': self.group1_exp1.pk,
            'participant_id': self.part1.pk
        })
        res = self.client.post(url)
        self.assertEqual(res.status_code, 404)

        # La asociación sigue existiendo
        self.assertTrue(ExperimentParticipant.objects.filter(
            experiment=self.exp1, group=self.group1_exp1, participant=self.part1
        ).exists())

    # --- Preservación del Contexto de Navegación ---

    def test_21_participant_link_in_group_detail_includes_from_group(self):
        """21. El enlace del participante en group_detail.html incluye el parámetro from_group."""
        url_group = reverse('group_detail', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.get(url_group)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        expected_url = f"{reverse('participant_experiment_dicoms', kwargs={'participant_id': self.part1.pk, 'experiment_id': self.exp1.pk})}?from_group={self.group1_exp1.pk}"
        self.assertIn(expected_url, html)

    def test_22_navigation_from_group_detail_displays_experiment_flow_and_back_button(self):
        """22. Al abrir la participación desde group_detail, muestra el flujo de Experimentos y botón Atrás al grupo."""
        url_part_dicoms = f"{reverse('participant_experiment_dicoms', kwargs={'participant_id': self.part1.pk, 'experiment_id': self.exp1.pk})}?from_group={self.group1_exp1.pk}"
        res = self.client.get(url_part_dicoms)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        url_dash = reverse('dashboard')
        url_exp_detail = reverse('experiment_detail', kwargs={'pk': self.exp1.pk})
        url_group_detail = reverse('group_detail', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})

        # Migas de pan del Flujo A
        self.assertIn(url_dash, html)
        self.assertIn('Listado de Experimentos', html)
        self.assertIn(url_exp_detail, html)
        self.assertIn('Detalle del Experimento', html)
        self.assertIn(url_group_detail, html)
        self.assertIn(f'Detalle del Grupo: {self.group1_exp1.name}', html)
        self.assertIn('Participación en el Experimento', html)

        # Botón Atrás vuelve al detalle del grupo de origen
        self.assertIn(f'href="{url_group_detail}"', html)

    def test_23_navigation_from_participants_maintains_participant_flow_and_back_button(self):
        """23. Al abrir la participación desde Participantes, se conservan las migas de pan y el botón Atrás actuales."""
        url_part_dicoms = reverse('participant_experiment_dicoms', kwargs={'participant_id': self.part1.pk, 'experiment_id': self.exp1.pk})
        res = self.client.get(url_part_dicoms)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        url_part_list = reverse('participant_list')
        url_part_exp = reverse('participant_experiments', kwargs={'participant_id': self.part1.pk})

        # Migas de pan del Flujo B
        self.assertIn(url_part_list, html)
        self.assertIn('Participantes', html)
        self.assertIn(url_part_exp, html)
        self.assertIn('Experimentos del Participante', html)
        self.assertIn('Participación en el Experimento', html)

        # Botón Atrás vuelve a experimentos del participante
        self.assertIn(f'href="{url_part_exp}"', html)

        # No debe figurar Detalle del Grupo
        self.assertNotIn('Detalle del Grupo:', html)

    def test_24_group_from_another_experiment_cannot_be_injected_via_url(self):
        """24. Un grupo de otro experimento no puede introducirse manipulando la URL (fallback a default)."""
        # Intentar pasar group1_exp2 (que pertenece a exp2) en la URL de participación de exp1
        url_manipulated = f"{reverse('participant_experiment_dicoms', kwargs={'participant_id': self.part1.pk, 'experiment_id': self.exp1.pk})}?from_group={self.group1_exp2.pk}"
        res = self.client.get(url_manipulated)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        # No debe contener el nombre ni el enlace del grupo ajeno
        self.assertNotIn(self.group1_exp2.name, html)
        url_foreign_group = reverse('group_detail', kwargs={'pk': self.exp2.pk, 'group_id': self.group1_exp2.pk})
        self.assertNotIn(url_foreign_group, html)

        # Debe utilizar el comportamiento predeterminado (Flujo Participantes)
        url_part_exp = reverse('participant_experiments', kwargs={'participant_id': self.part1.pk})
        self.assertIn(f'href="{url_part_exp}"', html)
        self.assertIn('Experimentos del Participante', html)

    def test_25_unauthorized_user_cannot_access_participation_nor_group(self):
        """25. Un usuario sin permisos no puede acceder a la participación ni al grupo."""
        self.client.force_login(self.user2)

        # Acceso no autorizado a la participación
        url_part = f"{reverse('participant_experiment_dicoms', kwargs={'participant_id': self.part1.pk, 'experiment_id': self.exp1.pk})}?from_group={self.group1_exp1.pk}"
        res_part = self.client.get(url_part)
        self.assertEqual(res_part.status_code, 404)

        # Acceso no autorizado al detalle del grupo
        url_group = reverse('group_detail', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res_group = self.client.get(url_group)
        self.assertEqual(res_group.status_code, 404)

    def test_26_direct_access_without_origin_maintains_default_behavior(self):
        """26. Abrir la participación directamente sin origen mantiene el comportamiento predeterminado válido."""
        url_direct = reverse('participant_experiment_dicoms', kwargs={'participant_id': self.part1.pk, 'experiment_id': self.exp1.pk})
        res = self.client.get(url_direct)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        url_part_exp = reverse('participant_experiments', kwargs={'participant_id': self.part1.pk})
        self.assertIn(f'href="{url_part_exp}"', html)
        self.assertIn('Experimentos del Participante', html)
        self.assertIn('Participación en el Experimento', html)
        self.assertNotIn('Detalle del Grupo:', html)

    def test_27_invalid_or_malformed_from_group_falls_back_to_default(self):
        """27. Un valor no numérico o inexistente de from_group realiza fallback a default sin error."""
        for invalid_val in ['invalid_str', '-99', '999999', '']:
            url = f"{reverse('participant_experiment_dicoms', kwargs={'participant_id': self.part1.pk, 'experiment_id': self.exp1.pk})}?from_group={invalid_val}"
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200)
            html = res.content.decode('utf-8')

            url_part_exp = reverse('participant_experiments', kwargs={'participant_id': self.part1.pk})
            self.assertIn(f'href="{url_part_exp}"', html)
            self.assertNotIn('Detalle del Grupo:', html)

    def test_28_dicom_detail_breadcrumbs_and_back_from_group_flow(self):
        """28. Abrir un DICOM desde la participación alcanzada por el flujo de Experimentos/Grupo muestra las migas de pan correctas y botón Atrás."""
        # 1. En participant_experiment_dicoms con ?from_group=... la tabla DICOM contiene el link a detalles con ?from_group=...
        url_part_dicoms = f"{reverse('participant_experiment_dicoms', kwargs={'participant_id': self.part1.pk, 'experiment_id': self.exp1.pk})}?from_group={self.group1_exp1.pk}"
        res_part = self.client.get(url_part_dicoms)
        self.assertEqual(res_part.status_code, 200)
        html_part = res_part.content.decode('utf-8')
        dicom_detail_url = f"{reverse('dicomfile_detail', kwargs={'pk': self.dicom1.pk})}?from_group={self.group1_exp1.pk}"
        self.assertIn(dicom_detail_url, html_part)

        # 2. Abrir el detalle del DICOM con ?from_group=...
        res = self.client.get(dicom_detail_url)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        url_dash = reverse('dashboard')
        url_exp_detail = reverse('experiment_detail', kwargs={'pk': self.exp1.pk})
        url_group_detail = reverse('group_detail', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})

        # Migas de pan del Flujo A
        self.assertIn(url_dash, html)
        self.assertIn('Listado de Experimentos', html)
        self.assertIn(url_exp_detail, html)
        self.assertIn('Detalle del Experimento', html)
        self.assertIn(url_group_detail, html)
        self.assertIn(f'Detalle del Grupo: {self.group1_exp1.name}', html)
        self.assertIn(url_part_dicoms, html)
        self.assertIn('Participación en el Experimento', html)
        self.assertIn('Detalle de Archivo DICOM', html)

        # Botón Atrás vuelve a la pantalla de Participación con el parámetro from_group
        self.assertIn(f'href="{url_part_dicoms}"', html)

    def test_29_dicom_detail_breadcrumbs_and_back_from_participants_flow(self):
        """29. Abrir un DICOM desde el flujo de Participantes conserva las migas de pan y el comportamiento actual."""
        url_part_dicoms = reverse('participant_experiment_dicoms', kwargs={'participant_id': self.part1.pk, 'experiment_id': self.exp1.pk})
        res_part = self.client.get(url_part_dicoms)
        self.assertEqual(res_part.status_code, 200)
        html_part = res_part.content.decode('utf-8')

        dicom_detail_url = reverse('dicomfile_detail', kwargs={'pk': self.dicom1.pk})
        self.assertIn(dicom_detail_url, html_part)
        self.assertNotIn(f"{dicom_detail_url}?from_group", html_part)

        # Abrir el detalle DICOM sin from_group
        res = self.client.get(dicom_detail_url)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        url_part_list = reverse('participant_list')
        url_part_exp = reverse('participant_experiments', kwargs={'participant_id': self.part1.pk})

        # Migas de pan del Flujo B
        self.assertIn(url_part_list, html)
        self.assertIn('Participantes', html)
        self.assertIn(url_part_exp, html)
        self.assertIn('Experimentos del Participante', html)
        self.assertIn(url_part_dicoms, html)
        self.assertIn('Participación en el Experimento', html)
        self.assertIn('Detalle de Archivo DICOM', html)
        self.assertNotIn('Detalle del Grupo:', html)

        # Botón Atrás vuelve a la pantalla de Participación sin from_group
        self.assertIn(f'href="{url_part_dicoms}"', html)

    def test_30_tampered_or_cross_experiment_group_falls_back_to_default(self):
        """30. Un contexto manipulado o un grupo de otro experimento no permite acceder a datos no autorizados (fallback a Flujo B)."""
        # Intentar pasar group1_exp2 (que pertenece a exp2) en el detalle de un DICOM de exp1
        url_manipulated = f"{reverse('dicomfile_detail', kwargs={'pk': self.dicom1.pk})}?from_group={self.group1_exp2.pk}"
        res = self.client.get(url_manipulated)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        # No debe contener el grupo ajeno
        self.assertNotIn(self.group1_exp2.name, html)
        self.assertNotIn('Detalle del Grupo:', html)

        # Debe mostrar Flujo B (Participantes)
        self.assertIn('Experimentos del Participante', html)

        # Probar valores inválidos de from_group
        for invalid_val in ['invalid_str', '-99', '999999']:
            res_inv = self.client.get(f"{reverse('dicomfile_detail', kwargs={'pk': self.dicom1.pk})}?from_group={invalid_val}")
            self.assertEqual(res_inv.status_code, 200)
            html_inv = res_inv.content.decode('utf-8')
            self.assertNotIn('Detalle del Grupo:', html_inv)
            self.assertIn('Experimentos del Participante', html_inv)

    def test_31_unauthorized_user_cannot_access_dicom_detail(self):
        """31. Un usuario sin permisos no puede acceder al detalle del DICOM."""
        self.client.force_login(self.user2)
        url = f"{reverse('dicomfile_detail', kwargs={'pk': self.dicom1.pk})}?from_group={self.group1_exp1.pk}"
        res = self.client.get(url)
        self.assertEqual(res.status_code, 404)

    def test_32_dicom_patient_name_edit_preserves_context(self):
        """32. Editar el nombre del paciente conserva el contexto en la redirección."""
        url = f"{reverse('dicomfile_detail', kwargs={'pk': self.dicom1.pk})}?from_group={self.group1_exp1.pk}"
        # Petición no-AJAX (POST form clásico)
        res = self.client.post(url, data={'patient_name': 'NUEVO_PACIENTE_01'})
        self.assertEqual(res.status_code, 302)
        self.assertIn(f"from_group={self.group1_exp1.pk}", res.url)

        # Petición AJAX
        res_ajax = self.client.post(url, data={'patient_name': 'AJAX_PACIENTE_01'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_ajax.status_code, 200)
        data = res_ajax.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['patient_name'], 'AJAX_PACIENTE_01')

    def test_33_dicom_delete_modal_and_redirect_preserves_from_group_context(self):
        """33. La eliminación de un DICOM envía el contexto del grupo y redirige a la participación con from_group."""
        # 1. Verificar input oculto en el modal de detalle DICOM
        url_detail = f"{reverse('dicomfile_detail', kwargs={'pk': self.dicom1.pk})}?from_group={self.group1_exp1.pk}"
        res_detail = self.client.get(url_detail)
        self.assertEqual(res_detail.status_code, 200)
        html_detail = res_detail.content.decode('utf-8')
        self.assertIn(f'<input type="hidden" name="from_group" value="{self.group1_exp1.pk}">', html_detail)

        # 2. POST a dicomfile_delete con from_group
        url_delete = reverse('dicomfile_delete', kwargs={'pk': self.dicom1.pk})
        res_del = self.client.post(url_delete, data={'from_group': self.group1_exp1.pk})
        self.assertEqual(res_del.status_code, 302)
        expected_redirect = f"{reverse('participant_experiment_dicoms', kwargs={'participant_id': self.part1.pk, 'experiment_id': self.exp1.pk})}?from_group={self.group1_exp1.pk}"
        self.assertEqual(res_del.url, expected_redirect)

    def test_34_dicom_confirm_delete_get_preserves_context(self):
        """34. La vista de confirmación de eliminación (GET) conserva las migas de pan y el botón Cancelar con from_group."""
        url_confirm = f"{reverse('dicomfile_delete', kwargs={'pk': self.dicom1.pk})}?from_group={self.group1_exp1.pk}"
        res = self.client.get(url_confirm)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        url_group_detail = reverse('group_detail', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        self.assertIn(url_group_detail, html)
        self.assertIn(f'Detalle del Grupo: {self.group1_exp1.name}', html)
        self.assertIn(f'<input type="hidden" name="from_group" value="{self.group1_exp1.pk}">', html)

        # Cancelar debe regresar al detalle DICOM con from_group
        expected_cancel = f"{reverse('dicomfile_detail', kwargs={'pk': self.dicom1.pk})}?from_group={self.group1_exp1.pk}"
        self.assertIn(f'href="{expected_cancel}"', html)
