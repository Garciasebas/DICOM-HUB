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

    def test_03_delete_group_retains_participant_and_sets_group_null(self):
        """TEST 3 — Eliminar grupo (Participant and ExperimentParticipant continue existing, group=None)."""
        url = reverse('delete_group_ajax', args=[self.exp1.pk, self.group1_exp1.pk])
        res = self.client.post(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')

        # Check ParticipantGroup deleted
        self.assertFalse(ParticipantGroup.objects.filter(pk=self.group1_exp1.pk).exists())

        # Check Participant still exists
        self.assertTrue(Participant.objects.filter(pk=self.part1.pk).exists())
        self.assertTrue(Participant.objects.filter(pk=self.part2.pk).exists())

        # Check ExperimentParticipant still exists with group=None
        self.ep1.refresh_from_db()
        self.ep2.refresh_from_db()
        self.assertIsNone(self.ep1.group)
        self.assertIsNone(self.ep2.group)

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

    def test_06_delete_group_does_not_affect_other_groups(self):
        """TEST 6 — No afectar otros grupos."""
        self.ep3 = ExperimentParticipant.objects.create(experiment=self.exp1, participant=self.part3, group=self.group2_exp1)

        url = reverse('delete_group_ajax', args=[self.exp1.pk, self.group1_exp1.pk])
        res = self.client.post(url)
        self.assertEqual(res.status_code, 200)

        # Group 1 deleted
        self.assertFalse(ParticipantGroup.objects.filter(pk=self.group1_exp1.pk).exists())

        # Group 2 still exists
        self.assertTrue(ParticipantGroup.objects.filter(pk=self.group2_exp1.pk).exists())

        # Participant in Group 2 still associated correctly
        self.ep3.refresh_from_db()
        self.assertEqual(self.ep3.group, self.group2_exp1)

    def test_07_participant_remains_in_experiment_after_group_deleted(self):
        """TEST 7 — Participante continúa en el experimento."""
        url = reverse('delete_group_ajax', args=[self.exp1.pk, self.group1_exp1.pk])
        res = self.client.post(url)
        self.assertEqual(res.status_code, 200)

        # participant.experiments.all() includes experiment
        self.assertIn(self.exp1, self.part1.experiments.all())
        self.assertIn(self.exp1, self.part2.experiments.all())

        # experiment.participants.all() includes participant
        self.assertIn(self.part1, self.exp1.participants.all())
        self.assertIn(self.part2, self.exp1.participants.all())
