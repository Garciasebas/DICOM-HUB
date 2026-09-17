import json
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from dicom_app.models import Experiment, Participant, ParticipantGroup, ExperimentParticipant


class MultiExperimentAssignmentTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='inv_multi_exp', password='password123')
        self.client.login(username='inv_multi_exp', password='password123')

        # Test 1 & Grupo 1
        self.exp1 = Experiment.objects.create(name='Test 1', created_by=self.user)
        self.grp1 = ParticipantGroup.objects.create(experiment=self.exp1, name='Grupo 1')

        # Test 2 & Grupo 2
        self.exp2 = Experiment.objects.create(name='Test 2', created_by=self.user)
        self.grp2 = ParticipantGroup.objects.create(experiment=self.exp2, name='Grupo 2')

        # Participant
        self.participant = Participant.objects.create(
            subject_id='SUBJ-MULTI-001',
            first_name='Sebastian',
            last_name='Garcia'
        )

    def test_A_B_C_participant_added_to_multiple_experiments_with_different_groups(self):
        """A, B, C. Un participante puede agregarse a Test 1 (Grupo 1) y luego a Test 2 (Grupo 2) pasándole IDs como strings/ints."""
        url_add_exp1 = reverse('add_participants_to_experiment', args=[self.exp1.pk])
        # Test string ID payload from frontend modal
        res1 = self.client.post(
            url_add_exp1,
            data=json.dumps({'participant_id': str(self.participant.pk), 'group_id': self.grp1.pk}),
            content_type='application/json'
        )
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json()['status'], 'success')

        # Verify association in Exp 1
        ep1 = ExperimentParticipant.objects.get(experiment=self.exp1, participant=self.participant)
        self.assertEqual(ep1.group, self.grp1)

        # Now add same participant to Test 2 (Grupo 2)
        url_add_exp2 = reverse('add_participants_to_experiment', args=[self.exp2.pk])
        res2 = self.client.post(
            url_add_exp2,
            data=json.dumps({'participant_id': str(self.participant.pk), 'group_id': self.grp2.pk}),
            content_type='application/json'
        )
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json()['status'], 'success')

        # Verify association in Exp 2
        ep2 = ExperimentParticipant.objects.get(experiment=self.exp2, participant=self.participant)
        self.assertEqual(ep2.group, self.grp2)

        # Verify participant belongs to both experiments in distinct groups
        self.assertEqual(self.participant.experiments.count(), 2)

    def test_D_prevent_duplicate_participant_in_same_experiment(self):
        """D. No se permite duplicar al mismo participante dentro del mismo experimento."""
        url_add_exp1 = reverse('add_participants_to_experiment', args=[self.exp1.pk])
        
        # First assignment
        res1 = self.client.post(
            url_add_exp1,
            data=json.dumps({'participant_id': self.participant.pk, 'group_id': self.grp1.pk}),
            content_type='application/json'
        )
        self.assertEqual(res1.status_code, 200)

        # Duplicate attempt in same experiment
        res_dup = self.client.post(
            url_add_exp1,
            data=json.dumps({'participant_id': self.participant.pk, 'group_id': self.grp1.pk}),
            content_type='application/json'
        )
        self.assertEqual(res_dup.status_code, 400)
        self.assertEqual(res_dup.json()['status'], 'error')
        self.assertIn('ya pertenece a este experimento', res_dup.json()['message'])

    def test_E_permission_validation_rejects_other_user_participant(self):
        """E. Las validaciones de permisos continúan rechazando participantes pertenecientes únicamente a otros investigadores."""
        other_user = User.objects.create_user(username='other_inv', password='password123')
        other_exp = Experiment.objects.create(name='Other Exp', created_by=other_user)
        other_part = Participant.objects.create(subject_id='SUBJ-OTHER-01', first_name='Maria', last_name='Lopez')
        ExperimentParticipant.objects.create(experiment=other_exp, participant=other_part)

        url_add_exp1 = reverse('add_participants_to_experiment', args=[self.exp1.pk])
        res = self.client.post(
            url_add_exp1,
            data=json.dumps({'participant_id': str(other_part.pk), 'group_id': self.grp1.pk}),
            content_type='application/json'
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()['status'], 'error')
        self.assertIn('no están permitidos', res.json()['message'])
