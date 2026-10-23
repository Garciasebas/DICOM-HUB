import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from dicom_app.models import Experiment, Participant, ParticipantGroup, ExperimentParticipant, Member

class Phase2ExperimentGroupsTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser(
            username='phase2_admin',
            email='phase2@test.com',
            password='password123'
        )
        self.client.force_login(self.user)

        self.exp_a = Experiment.objects.create(name="Estudio Alfa", description="Descripcion Alfa", created_by=self.user)
        self.exp_b = Experiment.objects.create(name="Estudio Beta", description="Descripcion Beta", created_by=self.user)

        self.group_a_control = ParticipantGroup.objects.create(experiment=self.exp_a, name="Control")
        self.group_a_exp = ParticipantGroup.objects.create(experiment=self.exp_a, name="Experimental")
        self.group_b_control = ParticipantGroup.objects.create(experiment=self.exp_b, name="Control")

        self.part_1 = Participant.objects.create(subject_id="SUBJ-001", first_name="Juan", last_name="Perez")
        self.part_2 = Participant.objects.create(subject_id="SUBJ-002", first_name="Maria", last_name="Lopez")

        self.member_1 = Member.objects.create(first_name="Dr. Carlos", last_name="Gomez", role="Neurólogo/a")

    def test_01_create_experiment_without_participants_or_members(self):
        """1 & 2. Crear experimento solamente con nombre y descripción (sin participantes ni miembros iniciales)."""
        url = reverse('experiment_create')
        res = self.client.post(url, data={'name': 'Nuevo Estudio', 'description': 'Solo datos basicos'})
        self.assertIn(res.status_code, [200, 302])
        exp = Experiment.objects.filter(name='Nuevo Estudio').first()
        self.assertIsNotNone(exp)
        self.assertEqual(exp.participants.count(), 0)
        self.assertEqual(exp.members.count(), 0)

    def test_03_create_group_associated_to_experiment(self):
        """3. Crear grupo asociado a un experimento vía AJAX sin descripción."""
        url = reverse('create_group_ajax', args=[self.exp_a.pk])
        res = self.client.post(url, data=json.dumps({'name': 'Placebo'}), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        group = ParticipantGroup.objects.filter(experiment=self.exp_a, name='Placebo').first()
        self.assertIsNotNone(group)
        self.assertEqual(group.description, '')

    def test_03b_create_group_with_description(self):
        """3b. Crear grupo asociado a un experimento vía AJAX con descripción."""
        url = reverse('create_group_ajax', args=[self.exp_a.pk])
        payload = {
            'name': 'Grupo Tratamiento A',
            'description': 'Grupo de pacientes sometidos a tratamiento A con resonancia semanal.'
        }
        res = self.client.post(url, data=json.dumps(payload), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['description'], payload['description'])
        group = ParticipantGroup.objects.get(experiment=self.exp_a, name='Grupo Tratamiento A')
        self.assertEqual(group.description, payload['description'])

    def test_04_disallow_duplicate_group_name_in_same_experiment(self):
        """4. No permitir grupos duplicados dentro del mismo experimento."""
        url = reverse('create_group_ajax', args=[self.exp_a.pk])
        res = self.client.post(url, data=json.dumps({'name': 'Control'}), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn("Ya existe un grupo llamado 'Control'", data['message'])

    def test_05_allow_same_group_name_in_different_experiments(self):
        """5. Permitir el mismo nombre de grupo en experimentos diferentes."""
        # 'Control' ya existe en exp_a y exp_b
        self.assertTrue(ParticipantGroup.objects.filter(experiment=self.exp_a, name='Control').exists())
        self.assertTrue(ParticipantGroup.objects.filter(experiment=self.exp_b, name='Control').exists())

    def test_06_add_existing_participant_with_group(self):
        """6. Agregar participante existente a un experimento y grupo obligatoriamente."""
        url = reverse('add_participants_to_experiment', args=[self.exp_a.pk])
        res = self.client.post(url, data=json.dumps({
            'participant_id': self.part_1.pk,
            'group_id': self.group_a_control.pk
        }), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        
        ep = ExperimentParticipant.objects.filter(experiment=self.exp_a, participant=self.part_1).first()
        self.assertIsNotNone(ep)
        self.assertEqual(ep.group, self.group_a_control)

    def test_07_disallow_adding_same_participant_twice_to_same_experiment(self):
        """7. No permitir agregar el mismo participante dos veces al mismo experimento."""
        ExperimentParticipant.objects.create(experiment=self.exp_a, participant=self.part_1, group=self.group_a_control)
        
        url = reverse('add_participants_to_experiment', args=[self.exp_a.pk])
        res = self.client.post(url, data=json.dumps({
            'participant_id': self.part_1.pk,
            'group_id': self.group_a_exp.pk
        }), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertEqual(data['status'], 'error')

    def test_08_disallow_assigning_group_from_another_experiment(self):
        """8. No permitir asignar un participante a un grupo perteneciente a otro experimento."""
        url = reverse('add_participants_to_experiment', args=[self.exp_a.pk])
        res = self.client.post(url, data=json.dumps({
            'participant_id': self.part_1.pk,
            'group_id': self.group_b_control.pk  # Perteneciente a exp_b
        }), content_type='application/json')
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn("El grupo seleccionado no pertenece a este experimento", data['message'])

    def test_09_create_new_participant_and_assign_group(self):
        """9. Crear participante nuevo y asociarlo a un grupo en el experimento actual."""
        url = reverse('create_participant_ajax')
        res = self.client.post(url, data=json.dumps({
            'full_name': 'Pedro Picapiedra',
            'experiment_id': self.exp_a.pk,
            'group_id': self.group_a_exp.pk
        }), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        
        created_part = Participant.objects.get(pk=data['id'])
        ep = ExperimentParticipant.objects.get(experiment=self.exp_a, participant=created_part)
        self.assertEqual(ep.group, self.group_a_exp)

    def test_10_change_participant_group(self):
        """10. Cambiar el grupo de un participante ya asociado al experimento."""
        ep = ExperimentParticipant.objects.create(experiment=self.exp_a, participant=self.part_1, group=self.group_a_control)
        
        url = reverse('assign_participant_group_ajax', args=[self.exp_a.pk])
        res = self.client.post(url, data=json.dumps({
            'participant_id': self.part_1.pk,
            'group_id': self.group_a_exp.pk
        }), content_type='application/json')
        self.assertEqual(res.status_code, 200)
        
        ep.refresh_from_db()
        self.assertEqual(ep.group, self.group_a_exp)

    def test_11_render_sin_grupo_for_legacy_relations(self):
        """11. Detalle del experimento ya no muestra "Sin grupo" porque se eliminó la sección de participantes."""
        ExperimentParticipant.objects.create(experiment=self.exp_a, participant=self.part_1, group=None)
        
        url = reverse('experiment_detail', args=[self.exp_a.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertNotIn('Sin grupo', res.content.decode('utf-8'))

    def test_12_remove_participant_from_experiment(self):
        """12. Eliminar/desvincular participante manteniendo la integridad existente."""
        ExperimentParticipant.objects.create(experiment=self.exp_a, participant=self.part_1, group=self.group_a_control)
        
        url = reverse('remove_participant_from_experiment', args=[self.exp_a.pk, self.part_1.pk])
        res = self.client.post(url)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(ExperimentParticipant.objects.filter(experiment=self.exp_a, participant=self.part_1).exists())

    def test_13_member_management_from_experiment_detail(self):
        """13. Mantener la gestión de miembros funcionando desde el Detalle del Experimento."""
        url_add = reverse('add_members_to_experiment', args=[self.exp_a.pk])
        res_add = self.client.post(url_add, data=json.dumps({
            'member_ids': [self.member_1.pk]
        }), content_type='application/json')
        self.assertEqual(res_add.status_code, 200)
        self.assertIn(self.member_1, self.exp_a.members.all())

        url_remove = reverse('remove_member_from_experiment', args=[self.exp_a.pk, self.member_1.pk])
        res_remove = self.client.post(url_remove)
        self.assertEqual(res_remove.status_code, 200)
        self.assertNotIn(self.member_1, self.exp_a.members.all())
