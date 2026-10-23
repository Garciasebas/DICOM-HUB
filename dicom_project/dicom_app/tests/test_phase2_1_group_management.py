import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from dicom_app.models import Experiment, Participant, ParticipantGroup, ExperimentParticipant

class Phase21GroupManagementTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user1 = User.objects.create_user(username='inv_p21_1', password='password123')
        self.user2 = User.objects.create_user(username='inv_p21_2', password='password123')
        self.client.force_login(self.user1)

        self.exp1 = Experiment.objects.create(name="Estudio Neuro 1", description="Exp 1", created_by=self.user1)
        self.exp2 = Experiment.objects.create(name="Estudio Neuro 2", description="Exp 2", created_by=self.user2)

        self.group1_exp1 = ParticipantGroup.objects.create(experiment=self.exp1, name="Grupo Control 1")
        self.group2_exp1 = ParticipantGroup.objects.create(experiment=self.exp1, name="Grupo Experimento 1")
        self.group_exp2 = ParticipantGroup.objects.create(experiment=self.exp2, name="Grupo Externo")

        self.part1 = Participant.objects.create(subject_id="SUBJ-P21-1", first_name="Ana", last_name="Gomez")
        self.part2 = Participant.objects.create(subject_id="SUBJ-P21-2", first_name="Bruno", last_name="Diaz")
        self.part3 = Participant.objects.create(subject_id="SUBJ-P21-3", first_name="Carla", last_name="Mendoza")

        self.ep1 = ExperimentParticipant.objects.create(experiment=self.exp1, participant=self.part1, group=self.group1_exp1)
        self.ep2 = ExperimentParticipant.objects.create(experiment=self.exp1, participant=self.part2, group=self.group1_exp1)

    def test_01_view_group_participants(self):
        """TEST 1 — Ver participantes de un grupo."""
        url = reverse('get_group_participants_ajax', args=[self.exp1.pk, self.group1_exp1.pk])
        res = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['group_name'], 'Grupo Control 1')
        self.assertEqual(len(data['participants']), 2)
        
        participant_names = [p['name'] for p in data['participants']]
        self.assertIn("Ana Gomez", participant_names)
        self.assertIn("Bruno Diaz", participant_names)
        self.assertNotIn("Carla Mendoza", participant_names)

    def test_02_empty_group_view_participants(self):
        """TEST 2 — Grupo vacío."""
        empty_group = ParticipantGroup.objects.create(experiment=self.exp1, name="Grupo Vacio")
        url = reverse('get_group_participants_ajax', args=[self.exp1.pk, empty_group.pk])
        res = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['participants'], [])

    def test_03_disallow_delete_group_with_participants(self):
        """TEST 3 — Rechazar eliminación de un grupo que contiene participantes."""
        url = reverse('delete_group_ajax', args=[self.exp1.pk, self.group1_exp1.pk])
        res = self.client.post(url)
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn("No se puede eliminar el grupo porque contiene participantes", data['message'])

        # Check ParticipantGroup still exists
        self.assertTrue(ParticipantGroup.objects.filter(pk=self.group1_exp1.pk).exists())

        # Check Participants still exist and their group relation is untouched
        self.ep1.refresh_from_db()
        self.ep2.refresh_from_db()
        self.assertEqual(self.ep1.group, self.group1_exp1)
        self.assertEqual(self.ep2.group, self.group1_exp1)

    def test_04_delete_empty_group(self):
        """TEST 4 — Eliminar grupo vacío."""
        empty_group = ParticipantGroup.objects.create(experiment=self.exp1, name="Grupo Vacio A Eliminar")
        url = reverse('delete_group_ajax', args=[self.exp1.pk, empty_group.pk])
        res = self.client.post(url)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(ParticipantGroup.objects.filter(pk=empty_group.pk).exists())

    def test_05_security_cross_experiment_group_access_rejected(self):
        """TEST 5 — Seguridad (intentar acceder/eliminar grupo de otro experimento)."""
        # User 1 tries to access group belonging to exp2 (User 2)
        url_view = reverse('get_group_participants_ajax', args=[self.exp2.pk, self.group_exp2.pk])
        res_view = self.client.get(url_view)
        self.assertEqual(res_view.status_code, 404)

        url_delete = reverse('delete_group_ajax', args=[self.exp2.pk, self.group_exp2.pk])
        res_delete = self.client.post(url_delete)
        self.assertEqual(res_delete.status_code, 404)

        # User 1 tries to delete group_exp2 using exp1 URL
        url_cross = reverse('delete_group_ajax', args=[self.exp1.pk, self.group_exp2.pk])
        res_cross = self.client.post(url_cross)
        self.assertEqual(res_cross.status_code, 404)

    def test_06_delete_empty_group_does_not_affect_other_groups(self):
        """TEST 6 — Eliminar un grupo vacío no afecta a otros grupos."""
        empty_group = ParticipantGroup.objects.create(experiment=self.exp1, name="Grupo Vacio Secundario")
        self.ep3 = ExperimentParticipant.objects.create(experiment=self.exp1, participant=self.part3, group=self.group2_exp1)

        url = reverse('delete_group_ajax', args=[self.exp1.pk, empty_group.pk])
        res = self.client.post(url)
        self.assertEqual(res.status_code, 200)

        # Empty group deleted
        self.assertFalse(ParticipantGroup.objects.filter(pk=empty_group.pk).exists())

        # Other group still exists
        self.assertTrue(ParticipantGroup.objects.filter(pk=self.group2_exp1.pk).exists())

        # Participant in Group 2 still associated correctly
        self.ep3.refresh_from_db()
        self.assertEqual(self.ep3.group, self.group2_exp1)

    def test_07_experiment_detail_does_not_render_participant_section(self):
        """TEST 7 — Detalle del experimento ya no presenta la sección de participantes."""
        url = reverse('experiment_detail', args=[self.exp1.pk])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertNotIn('<h3 class="section-title-centered-large m-0">Participantes</h3>', content)
        self.assertNotIn('openParticipantsModal', content)
        self.assertIn('<h3 class="section-title-centered-large m-0">Grupos</h3>', content)
        self.assertIn('<h3 class="section-title-centered-large m-0">Miembros del Equipo</h3>', content)
