import os
import tempfile
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from dicom_app.models import (
    Experiment, Participant, ParticipantGroup, ExperimentParticipant,
    ConsentFile, DicomFile, Member
)
import json

class Phase4AddParticipantGroupTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # Users
        self.user1 = User.objects.create_user(username='phase4_inv1', password='password123')
        self.user2 = User.objects.create_user(username='phase4_inv2', password='password123')
        self.client.force_login(self.user1)

        # Experiments
        self.exp1 = Experiment.objects.create(name="Estudio P4 Alfa", description="Alfa P4", created_by=self.user1)
        self.exp2 = Experiment.objects.create(name="Estudio P4 Beta", description="Beta P4", created_by=self.user1)

        # Groups
        self.group1_exp1 = ParticipantGroup.objects.create(experiment=self.exp1, name="Grupo Alfa 1")
        self.group2_exp1 = ParticipantGroup.objects.create(experiment=self.exp1, name="Grupo Alfa 2")
        self.group1_exp2 = ParticipantGroup.objects.create(experiment=self.exp2, name="Grupo Beta 1")

    def test_01_plus_button_opens_search_modal(self):
        """1. El botón + en el detalle del grupo abre el modal de búsqueda y contiene la opción 'Crear participante nuevo'."""
        url = reverse('group_detail', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        self.assertIn('openAddParticipantSearchModal()', html)
        self.assertIn('id="modal-add-participant-search"', html)
        self.assertIn('Buscar por nombre o apellido...', html)
        create_url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        self.assertIn(create_url, html)
        self.assertIn('Crear participante nuevo', html)

    def test_02_add_participant_page_layout_matches_participant_experiment_dicoms(self):
        """2, 7, 8, 9. La página de creación tiene el mismo diseño visual, sin lápiz de edición, sin botón guardar redundante."""
        url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        # Título y contexto
        self.assertIn("Crear Participante", html)
        self.assertIn(self.exp1.name, html)
        self.assertIn(self.group1_exp1.name, html)

        # Secciones completas
        self.assertIn("Información del Participante", html)
        self.assertIn("Nota de Consentimiento", html)
        self.assertIn("Archivos DICOM", html)

        # Campos editables directamente
        self.assertIn('id="id_first_name"', html)
        self.assertIn('id="id_last_name"', html)
        self.assertIn('id="id_birth_date"', html)
        self.assertIn('id="id_sex"', html)

        # Sin botón de lápiz ni botones redundantes al final
        self.assertNotIn("fa-pen", html)
        self.assertNotIn("Guardar participante", html)

        # Botón Guardar único arriba a la derecha
        self.assertIn('form="form-create-participant"', html)
        self.assertIn("Guardar", html)

    def test_03_create_new_participant_with_full_demographics(self):
        """3, 10. Alta exitosa de participante nuevo con todos los campos personales y regreso al detalle del grupo."""
        url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.post(url, data={
            'mode': 'create',
            'first_name': 'Mario',
            'last_name': 'Rossi',
            'birth_date': '1990-05-15',
            'sex': 'M',
            'email': 'mario@example.com',
            'phone': '11223344',
            'details': 'Paciente sin observaciones'
        }, follow=True)

        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'dicom_app/group_detail.html')

        # Verificar DB
        part = Participant.objects.filter(first_name='Mario', last_name='Rossi').first()
        self.assertIsNotNone(part)
        self.assertEqual(str(part.birth_date), '1990-05-15')
        self.assertEqual(part.sex, 'M')
        self.assertEqual(part.email, 'mario@example.com')

        ep = ExperimentParticipant.objects.filter(experiment=self.exp1, participant=part).first()
        self.assertIsNotNone(ep)
        self.assertEqual(ep.group, self.group1_exp1)

    def test_04_search_existing_participants_ajax(self):
        """4. Búsqueda AJAX de participantes existentes por nombre y apellido."""
        p1 = Participant.objects.create(subject_id='SUB-EX-001', first_name='Carlos', last_name='Gomez')
        p2 = Participant.objects.create(subject_id='SUB-EX-002', first_name='Ana', last_name='Martinez')

        url = f"{reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})}?action=search&q=Carlos"
        res = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(len(data['participants']), 1)
        self.assertEqual(data['participants'][0]['first_name'], 'Carlos')

    def test_05_associate_existing_participant_caso1(self):
        """5 (Caso 1). Asociar participante existente que no está en el experimento sin duplicar Participant."""
        part = Participant.objects.create(subject_id='SUB-EX-010', first_name='Lucia', last_name='Fernandez')

        url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.post(url, data={
            'mode': 'existing',
            'participant_id': part.id
        }, follow=True)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(Participant.objects.filter(first_name='Lucia', last_name='Fernandez').count(), 1)

        ep = ExperimentParticipant.objects.filter(experiment=self.exp1, participant=part).first()
        self.assertIsNotNone(ep)
        self.assertEqual(ep.group, self.group1_exp1)

    def test_06_existing_participant_already_in_group_caso2(self):
        """5 (Caso 2). Participante ya en el mismo grupo no se duplica y muestra aviso."""
        part = Participant.objects.create(subject_id='SUB-EX-013', first_name='Diego', last_name='Torres')
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=part, group=self.group1_exp1)

        url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.post(url, data={
            'mode': 'existing',
            'participant_id': part.id
        }, follow=True)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(ExperimentParticipant.objects.filter(experiment=self.exp1, participant=part).count(), 1)

    def test_07_assign_group_to_participant_without_group_caso3(self):
        """5 (Caso 3). Participante en el experimento sin grupo asignado se asigna al grupo actual."""
        part = Participant.objects.create(subject_id='SUB-EX-014', first_name='Sofia', last_name='Lopez')
        ep = ExperimentParticipant.objects.create(experiment=self.exp1, participant=part, group=None)

        url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.post(url, data={
            'mode': 'existing',
            'participant_id': part.id
        }, follow=True)

        self.assertEqual(res.status_code, 200)
        ep.refresh_from_db()
        self.assertEqual(ep.group, self.group1_exp1)

    def test_08_move_participant_from_other_group_caso4(self):
        """5 (Caso 4). Mover participante desde otro grupo del mismo experimento requiere confirmación."""
        part = Participant.objects.create(subject_id='SUB-EX-015', first_name='Gabriel', last_name='Sosa')
        ep = ExperimentParticipant.objects.create(experiment=self.exp1, participant=part, group=self.group2_exp1)

        url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})

        # Vía AJAX sin confirmación
        res1 = self.client.post(url, data={
            'mode': 'existing',
            'participant_id': part.id,
            'confirm_move': 'false'
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        data1 = res1.json()
        self.assertEqual(data1['status'], 'confirm_required')
        ep.refresh_from_db()
        self.assertEqual(ep.group, self.group2_exp1)

        # Vía AJAX con confirmación
        res2 = self.client.post(url, data={
            'mode': 'existing',
            'participant_id': part.id,
            'confirm_move': 'true'
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        data2 = res2.json()
        self.assertEqual(data2['status'], 'success')
        ep.refresh_from_db()
        self.assertEqual(ep.group, self.group1_exp1)

    def test_09_associate_participant_from_another_experiment_caso5(self):
        """5 (Caso 5). Asociar participante perteneciente a otro experimento sin alterar el anterior."""
        part = Participant.objects.create(subject_id='SUB-EX-017', first_name='Valeria', last_name='Rios')
        ExperimentParticipant.objects.create(experiment=self.exp2, participant=part, group=self.group1_exp2)

        url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.post(url, data={
            'mode': 'existing',
            'participant_id': part.id
        }, follow=True)

        self.assertEqual(res.status_code, 200)
        self.assertTrue(ExperimentParticipant.objects.filter(experiment=self.exp2, participant=part).exists())
        self.assertTrue(ExperimentParticipant.objects.filter(experiment=self.exp1, participant=part, group=self.group1_exp1).exists())

    def test_10_unauthorized_user_cannot_access_or_associate(self):
        """Acceso y permisos. Usuario sin permisos no puede acceder ni asociar participantes de otros experimentos."""
        self.client.force_login(self.user2)
        url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 404)

    def test_11_consent_validation(self):
        """11. Validación de notas de consentimiento PDF."""
        pdf = SimpleUploadedFile("consent.pdf", b"%PDF-1.4 mock content", content_type="application/pdf")
        url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.post(url, data={
            'mode': 'create',
            'first_name': 'Esteban',
            'last_name': 'Quito',
            'consent_file': pdf
        }, follow=True)
        self.assertEqual(res.status_code, 200)

        part = Participant.objects.get(first_name='Esteban', last_name='Quito')
        self.assertTrue(ConsentFile.objects.filter(participant=part, experiment=self.exp1).exists())

        txt = SimpleUploadedFile("bad.txt", b"Invalid content", content_type="text/plain")
        res2 = self.client.post(url, data={
            'mode': 'create',
            'first_name': 'Noelia',
            'last_name': 'Perez',
            'consent_file': txt
        })
        self.assertEqual(res2.status_code, 200)
        self.assertFalse(Participant.objects.filter(first_name='Noelia').exists())

    def test_12_group_name_rendered_without_badge(self):
        """12. El nombre del grupo se renderiza como texto normal sin badge azul."""
        part = Participant.objects.create(subject_id='SUB-EX-099', first_name='Elena', last_name='Vidal')
        ep = ExperimentParticipant.objects.create(experiment=self.exp1, participant=part, group=self.group1_exp1)

        # 1. Página de creación
        url_create = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res_create = self.client.get(url_create)
        html_create = res_create.content.decode('utf-8')
        self.assertIn("Grupo:", html_create)
        self.assertIn(self.group1_exp1.name, html_create)
        self.assertNotIn(f'class="badge" style="background-color: #2B7A9B; font-size: 0.85rem; font-weight: 600; padding: 4px 10px; border-radius: 12px;">{self.group1_exp1.name}</span>', html_create)

        # 2. Página de participación existente
        url_detail = reverse('participant_experiment_dicoms', kwargs={'participant_id': part.pk, 'experiment_id': self.exp1.pk})
        res_detail = self.client.get(url_detail)
        html_detail = res_detail.content.decode('utf-8')
        self.assertIn("Grupo:", html_detail)
        self.assertIn(self.group1_exp1.name, html_detail)
        self.assertNotIn(f'class="badge" style="background-color: #2B7A9B; font-size: 0.85rem; font-weight: 600; padding: 4px 10px; border-radius: 12px;">{self.group1_exp1.name}</span>', html_detail)

    def test_13_dicom_table_and_upload_button_rendered(self):
        """13. UI unificada de Archivos DICOM: botón + Subir DICOM, tabla y control de archivos seleccionados."""
        url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res_get = self.client.get(url)
        html = res_get.content.decode('utf-8')

        # Verificar botón + Subir DICOM
        self.assertIn('id="btn-upload-dicom"', html)
        self.assertIn('+ Subir DICOM', html)
        self.assertIn('triggerDicomFileSelection()', html)

        # Verificar input picker oculto con múltiple y .dcm
        self.assertIn('id="hidden-dicom-picker"', html)
        self.assertIn('accept=".dcm"', html)
        self.assertIn('multiple', html)

        # Verificar tabla y encabezados acordes a participant_experiment_dicoms.html
        self.assertIn('id="table-selected-dicoms"', html)
        self.assertIn('Nombre del archivo', html)
        self.assertIn('Tamaño', html)
        self.assertIn('Estado', html)
        self.assertIn('Acciones', html)
        self.assertIn('No hay archivos seleccionados.', html)

        # Verificar lógica de validación de extensión en JavaScript
        self.assertIn('.endsWith(\'.dcm\')', html)
        self.assertIn('Archivo no válido. Solo se permiten archivos DICOM con extensión .dcm.', html)
        self.assertIn('accumulatedDicomFiles', html)
        self.assertIn('removeDicomFile', html)

    def test_14_multiple_valid_dicoms_processed_and_saved(self):
        """14. Todos los archivos DICOM válidos seleccionados se envían y procesan al guardar."""
        import io
        import pydicom
        from pydicom.dataset import Dataset, FileMetaDataset

        def build_dcm(name):
            fm = FileMetaDataset()
            fm.MediaStorageSOPClassUID = pydicom.uid.MRImageStorage
            fm.MediaStorageSOPInstanceUID = pydicom.uid.generate_uid()
            fm.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
            ds = Dataset()
            ds.file_meta = fm
            ds.is_little_endian = True
            ds.is_implicit_VR = False
            ds.SOPClassUID = fm.MediaStorageSOPClassUID
            ds.SOPInstanceUID = fm.MediaStorageSOPInstanceUID
            ds.PatientName = name
            ds.Modality = "MR"
            bio = io.BytesIO()
            pydicom.dcmwrite(bio, ds, write_like_original=False)
            return bio.getvalue()

        dcm1 = SimpleUploadedFile("scan1.dcm", build_dcm("PAT_1"), content_type="application/dicom")
        dcm2 = SimpleUploadedFile("scan2.dcm", build_dcm("PAT_2"), content_type="application/dicom")

        url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res_post = self.client.post(url, data={
            'mode': 'create',
            'first_name': 'Roberto',
            'last_name': 'Gomez',
            'dicom_files': [dcm1, dcm2]
        }, follow=True)

        self.assertEqual(res_post.status_code, 200)

        part = Participant.objects.get(first_name='Roberto', last_name='Gomez')
        dicom_files = DicomFile.objects.filter(participant=part, experiment=self.exp1)
        self.assertEqual(dicom_files.count(), 2)

    def test_15_server_rejects_non_dcm_extension(self):
        """15. El servidor rechaza archivos que no tengan extensión .dcm y muestra advertencia."""
        not_dcm = SimpleUploadedFile("imagen.png", b"fake png data", content_type="image/png")

        url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res_post = self.client.post(url, data={
            'mode': 'create',
            'first_name': 'Marcos',
            'last_name': 'Rechazado',
            'dicom_files': [not_dcm]
        }, follow=True)

        self.assertEqual(res_post.status_code, 200)
        messages_list = list(res_post.context['messages'])
        warning_msg = next((m.message for m in messages_list if 'Solo se permiten archivos DICOM con extensión .dcm' in m.message), None)
        self.assertIsNotNone(warning_msg)

        part = Participant.objects.get(first_name='Marcos', last_name='Rechazado')
        self.assertEqual(DicomFile.objects.filter(participant=part).count(), 0)

    def test_16_server_rejects_corrupted_dicom_content(self):
        """16. El servidor valida el contenido y rechaza archivos con extensión .dcm corruptos sin reportar éxito falso."""
        corrupt_dcm = SimpleUploadedFile("corrupto.dcm", b"NOT_A_REAL_DICOM_CONTENT", content_type="application/dicom")

        url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res_post = self.client.post(url, data={
            'mode': 'create',
            'first_name': 'Carla',
            'last_name': 'Corrupta',
            'dicom_files': [corrupt_dcm]
        }, follow=True)

        self.assertEqual(res_post.status_code, 200)
        messages_list = list(res_post.context['messages'])
        error_msg = next((m.message for m in messages_list if 'Error procesando corrupto.dcm' in m.message), None)
        self.assertIsNotNone(error_msg)

        part = Participant.objects.get(first_name='Carla', last_name='Corrupta')
        self.assertEqual(DicomFile.objects.filter(participant=part).count(), 0)

    def test_17_creation_without_dicom_files_succeeds(self):
        """17. La creación de participantes sin archivos DICOM sigue funcionando normalmente."""
        url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res_post = self.client.post(url, data={
            'mode': 'create',
            'first_name': 'Ignacio',
            'last_name': 'SinDicom'
        }, follow=True)

        self.assertEqual(res_post.status_code, 200)
        part = Participant.objects.get(first_name='Ignacio', last_name__iexact='SinDicom')
        self.assertTrue(ExperimentParticipant.objects.filter(experiment=self.exp1, participant=part, group=self.group1_exp1).exists())
        self.assertEqual(DicomFile.objects.filter(participant=part).count(), 0)

    def test_18_existing_participant_experiment_dicoms_screen_remains_intact(self):
        """18. La pantalla de participación existente participant_experiment_dicoms.html continúa funcionando intacta."""
        part = Participant.objects.create(subject_id='SUB-EX-EXIST', first_name='Camila', last_name='Existente')
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=part, group=self.group1_exp1)

        url_detail = reverse('participant_experiment_dicoms', kwargs={'participant_id': part.pk, 'experiment_id': self.exp1.pk})
        res_detail = self.client.get(url_detail)

        self.assertEqual(res_detail.status_code, 200)
        html = res_detail.content.decode('utf-8')
        self.assertIn('Participación en el Experimento', html)
        self.assertIn('+ Subir DICOM', html)
        self.assertIn(reverse('upload_participant_dicom', kwargs={'experiment_id': self.exp1.pk, 'participant_id': part.pk}), html)

    def test_19_consent_clear_x_button_rendered_and_functional(self):
        """19. La X roja para quitar el consentimiento seleccionado se muestra a la derecha del selector y tiene la estética unificada."""
        url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        # Selector de PDF
        self.assertIn('id="id_consent_file"', html)
        # Botón X de consentimiento
        self.assertIn('id="btn-clear-consent"', html)
        self.assertIn('clearConsentFile()', html)
        self.assertIn('btn-remove-x', html)
        self.assertIn('btn-outline-danger', html)
        self.assertIn('fa-times', html)
        self.assertIn('title="Quitar archivo"', html)
        self.assertIn('aria-label="Quitar archivo"', html)
        # Lógica de limpiar consentimiento y actualización
        self.assertIn('updateConsentClearBtn', html)

    def test_20_dicom_removal_x_button_unified(self):
        """20. El botón X de eliminación de archivos DICOM seleccionados utiliza la clase unificada btn-remove-x y fa-times."""
        url = reverse('add_participant_to_group', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        html = res.content.decode('utf-8')

        self.assertIn('class="btn btn-sm btn-outline-danger btn-remove-x"', html)
        self.assertIn('removeDicomFile', html)

    def test_21_unified_x_buttons_across_screens(self):
        """21. Todas las X de eliminación en detalle de experimento, detalle de grupo y listado de participantes usan fa-times y btn-remove-x."""
        # 1. Detalle del experimento (eliminar grupo y quitar miembro)
        url_exp = reverse('experiment_detail', kwargs={'pk': self.exp1.pk})
        res_exp = self.client.get(url_exp)
        self.assertEqual(res_exp.status_code, 200)
        html_exp = res_exp.content.decode('utf-8')
        self.assertIn('btn-remove-x', html_exp)
        self.assertIn('fa-times', html_exp)
        self.assertNotIn('>X</button>', html_exp)

        # 2. Detalle del grupo (desvincular participante)
        part = Participant.objects.create(subject_id='SUB-P4-GRP', first_name='Lucas', last_name='Grupo')
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=part, group=self.group1_exp1)
        url_grp = reverse('group_detail', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res_grp = self.client.get(url_grp)
        self.assertEqual(res_grp.status_code, 200)
        html_grp = res_grp.content.decode('utf-8')
        self.assertIn('btn-remove-x', html_grp)
        self.assertIn('fa-times', html_grp)
        self.assertNotIn('>X</button>', html_grp)

        # 3. Listado de participantes (eliminar participante)
        url_part_dash = reverse('participant_dashboard')
        res_part_dash = self.client.get(url_part_dash)
        self.assertEqual(res_part_dash.status_code, 200)
        html_part_dash = res_part_dash.content.decode('utf-8')
        self.assertIn('btn-remove-x', html_part_dash)
        self.assertIn('fa-times', html_part_dash)
        self.assertNotIn('>X</button>', html_part_dash)

    def test_22_unified_plus_buttons_across_screens(self):
        """22. Todos los botones + compactos en detalle de experimento y detalle de grupo usan la clase btn-add-plus y fa-plus."""
        # 1. Detalle de experimento: botón de agregar grupo y botón de agregar miembro del equipo
        url_exp = reverse('experiment_detail', kwargs={'pk': self.exp1.pk})
        res_exp = self.client.get(url_exp)
        self.assertEqual(res_exp.status_code, 200)
        html_exp = res_exp.content.decode('utf-8')
        self.assertIn('class="btn-add-plus"', html_exp)
        self.assertIn('fa-plus', html_exp)
        # Botón de crear grupo
        self.assertIn('onclick="openCreateGroupModal()" class="btn-add-plus"', html_exp)
        # Botón de agregar miembro
        self.assertIn('id="open-members-modal-btn" onclick="openMembersModal()" class="btn-add-plus"', html_exp)

        # 2. Detalle de grupo: botón de agregar participante
        url_grp = reverse('group_detail', kwargs={'pk': self.exp1.pk, 'group_id': self.group1_exp1.pk})
        res_grp = self.client.get(url_grp)
        self.assertEqual(res_grp.status_code, 200)
        html_grp = res_grp.content.decode('utf-8')
        self.assertIn('id="btn-add-participant-group" onclick="openAddParticipantSearchModal()" class="btn-add-plus"', html_grp)
        self.assertIn('fa-plus', html_grp)

    def test_23_team_members_modal_rendered_and_functional(self):
        """23. El botón + de Miembros del Equipo abre el modal con el selector y el submodal de creación rápida."""
        url_exp = reverse('experiment_detail', kwargs={'pk': self.exp1.pk})
        res_exp = self.client.get(url_exp)
        self.assertEqual(res_exp.status_code, 200)
        html_exp = res_exp.content.decode('utf-8')

        # Elementos del modal de miembros existentes
        self.assertIn('id="modal-manage-members"', html_exp)
        self.assertIn('id="select-member-id"', html_exp)
        self.assertIn('id="confirm-add-members"', html_exp)
        self.assertIn('onclick="closeMembersModal()"', html_exp)
        self.assertIn('id="trigger-create-member"', html_exp)

        # Elementos del sub-modal de creación rápida
        self.assertIn('id="modal-member-quick"', html_exp)
        self.assertIn('id="new-member-name-detail"', html_exp)
        self.assertIn('id="new-member-role-detail"', html_exp)
        self.assertIn('id="save-member-quick"', html_exp)
        self.assertIn('onclick="closeQuickMemberModal()"', html_exp)
        self.assertIn('Seleccionar Rol', html_exp)
        self.assertIn('Líder Científico/a', html_exp)
        self.assertIn('Bioestadístico/a o Científico/a de Datos', html_exp)

    def test_24_team_member_quick_creation_flow(self):
        """24. Flujo completo de creación y asociación de miembro al experimento."""
        # 1. Crear miembro vía AJAX con rol predefinido válido
        create_url = reverse('create_member_ajax')
        res_create = self.client.post(create_url, data=json.dumps({
            'full_name': 'Dra. María González',
            'role': 'Líder Científico/a'
        }), content_type='application/json')
        self.assertEqual(res_create.status_code, 200)
        data = res_create.json()
        self.assertEqual(data['status'], 'success')
        member_id = data['id']

        # 2. Asociar al experimento
        add_url = reverse('add_members_to_experiment', kwargs={'pk': self.exp1.pk})
        res_add = self.client.post(add_url, data=json.dumps({
            'member_ids': [member_id]
        }), content_type='application/json')
        self.assertEqual(res_add.status_code, 200)

        # 3. Verificar que aparece en el detalle del experimento
        url_exp = reverse('experiment_detail', kwargs={'pk': self.exp1.pk})
        res_exp = self.client.get(url_exp)
        self.assertEqual(res_exp.status_code, 200)
        html_exp = res_exp.content.decode('utf-8')
        self.assertIn('María González', html_exp)
        self.assertIn('Líder Científico/a', html_exp)

        # 4. Validar rechazo de miembro vacío
        res_invalid = self.client.post(create_url, data=json.dumps({
            'full_name': '',
            'role': ''
        }), content_type='application/json')
        self.assertEqual(res_invalid.status_code, 400)

        # 5. Validar rechazo de rol no permitido (servidor)
        res_invalid_role = self.client.post(create_url, data=json.dumps({
            'full_name': 'Dr. Test Invalido',
            'role': 'Rol Inventado Que No Existe'
        }), content_type='application/json')
        self.assertEqual(res_invalid_role.status_code, 400)
        self.assertEqual(res_invalid_role.json().get('message'), 'El rol seleccionado no es válido.')
