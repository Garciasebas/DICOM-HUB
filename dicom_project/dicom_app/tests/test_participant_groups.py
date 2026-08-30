from django.test import TestCase
from django.db import IntegrityError
from dicom_app.models import Experiment, Participant, ParticipantGroup, ExperimentParticipant

class ParticipantGroupsTestCase(TestCase):
    def setUp(self):
        self.exp_a = Experiment.objects.create(name="Experimento A", description="Estudio A")
        self.exp_b = Experiment.objects.create(name="Experimento B", description="Estudio B")

        self.part_1 = Participant.objects.create(
            subject_id="sub-01",
            first_name="Juan",
            last_name="Perez"
        )
        self.part_2 = Participant.objects.create(
            subject_id="sub-02",
            first_name="Maria",
            last_name="Gomez"
        )
        self.part_3 = Participant.objects.create(
            subject_id="sub-03",
            first_name="Carlos",
            last_name="Lopez"
        )

    def test_01_create_group_for_experiment(self):
        """Verifica que se puede crear un grupo asociado a un experimento."""
        group_control = ParticipantGroup.objects.create(experiment=self.exp_a, name="control")
        self.assertEqual(group_control.experiment, self.exp_a)
        self.assertEqual(group_control.name, "control")
        self.assertIn(group_control, self.exp_a.groups.all())

    def test_02_experiment_can_have_multiple_groups(self):
        """Verifica que un experimento puede tener varios grupos."""
        group_control = ParticipantGroup.objects.create(experiment=self.exp_a, name="control")
        group_exp = ParticipantGroup.objects.create(experiment=self.exp_a, name="experimental")
        
        self.assertEqual(self.exp_a.groups.count(), 2)
        self.assertIn(group_control, self.exp_a.groups.all())
        self.assertIn(group_exp, self.exp_a.groups.all())

    def test_03_group_belongs_to_single_experiment(self):
        """Verifica que un grupo pertenece a un único experimento."""
        group_control = ParticipantGroup.objects.create(experiment=self.exp_a, name="control")
        self.assertEqual(group_control.experiment, self.exp_a)
        self.assertNotIn(group_control, self.exp_b.groups.all())

    def test_04_participant_in_multiple_experiments(self):
        """Verifica que un participante puede participar en varios experimentos."""
        ExperimentParticipant.objects.create(experiment=self.exp_a, participant=self.part_1)
        ExperimentParticipant.objects.create(experiment=self.exp_b, participant=self.part_1)

        self.assertEqual(self.part_1.experiments.count(), 2)
        self.assertIn(self.exp_a, self.part_1.experiments.all())
        self.assertIn(self.exp_b, self.part_1.experiments.all())

    def test_05_participant_different_groups_in_different_experiments(self):
        """Verifica que un participante puede pertenecer a grupos diferentes en experimentos diferentes."""
        group_a_control = ParticipantGroup.objects.create(experiment=self.exp_a, name="control")
        group_b_exp = ParticipantGroup.objects.create(experiment=self.exp_b, name="experimental")

        ep_a = ExperimentParticipant.objects.create(
            experiment=self.exp_a,
            participant=self.part_1,
            group=group_a_control
        )
        ep_b = ExperimentParticipant.objects.create(
            experiment=self.exp_b,
            participant=self.part_1,
            group=group_b_exp
        )

        self.assertEqual(ep_a.group.name, "control")
        self.assertEqual(ep_b.group.name, "experimental")

    def test_06_participant_cannot_have_two_groups_in_same_experiment(self):
        """Verifica que un participante NO puede pertenecer a dos grupos dentro del mismo experimento."""
        group_control = ParticipantGroup.objects.create(experiment=self.exp_a, name="control")
        group_exp = ParticipantGroup.objects.create(experiment=self.exp_a, name="experimental")

        ExperimentParticipant.objects.create(
            experiment=self.exp_a,
            participant=self.part_1,
            group=group_control
        )

        with self.assertRaises(IntegrityError):
            ExperimentParticipant.objects.create(
                experiment=self.exp_a,
                participant=self.part_1,
                group=group_exp
            )

    def test_07_cannot_create_duplicate_group_name_in_same_experiment(self):
        """Verifica que no pueden existir dos grupos con el mismo nombre en el mismo experimento."""
        ParticipantGroup.objects.create(experiment=self.exp_a, name="control")

        with self.assertRaises(IntegrityError):
            ParticipantGroup.objects.create(experiment=self.exp_a, name="control")

    def test_08_same_group_name_in_different_experiments_is_allowed(self):
        """Verifica que dos grupos con el mismo nombre sí pueden existir en experimentos diferentes."""
        group_a = ParticipantGroup.objects.create(experiment=self.exp_a, name="control")
        group_b = ParticipantGroup.objects.create(experiment=self.exp_b, name="control")

        self.assertEqual(group_a.name, "control")
        self.assertEqual(group_b.name, "control")
        self.assertNotEqual(group_a.experiment, group_b.experiment)

    def test_09_backward_compatibility_null_group(self):
        """Verifica que la asignación sin grupo (group=None) funciona y preserva compatibilidad."""
        # Se agrega participante sin grupo asignado
        self.exp_a.participants.add(self.part_1)

        self.assertIn(self.part_1, self.exp_a.participants.all())
        self.assertIn(self.exp_a, self.part_1.experiments.all())

        ep = ExperimentParticipant.objects.get(experiment=self.exp_a, participant=self.part_1)
        self.assertIsNone(ep.group)

    def test_10_existing_queries_work_transparently(self):
        """Verifica que experiment.participants.all() y participant.experiments.all() funcionan transparentemente."""
        group_control = ParticipantGroup.objects.create(experiment=self.exp_a, name="control")
        ExperimentParticipant.objects.create(
            experiment=self.exp_a,
            participant=self.part_1,
            group=group_control
        )
        ExperimentParticipant.objects.create(
            experiment=self.exp_a,
            participant=self.part_2,
            group=group_control
        )

        participants = self.exp_a.participants.all()
        self.assertEqual(participants.count(), 2)
        self.assertIn(self.part_1, participants)
        self.assertIn(self.part_2, participants)
