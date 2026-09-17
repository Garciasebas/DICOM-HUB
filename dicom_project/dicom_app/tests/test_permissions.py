import json
import uuid
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from dicom_app.models import Experiment, Participant, Member, DicomFile, ParticipantGroup, ExperimentParticipant

def json_bytes(data):
    return json.dumps(data).encode('utf-8')

class PermissionsAndIsolationTestCase(TestCase):
    def setUp(self):
        self.inv1 = User.objects.create_user(username='test_perm_inv1', password='investigador123')
        self.inv2 = User.objects.create_user(username='test_perm_inv2', password='investigador123')
        self.admin = User.objects.create_superuser(username='admin_test_perm', password='password123')

        self.client1 = Client()
        self.client1.login(username='test_perm_inv1', password='investigador123')

        self.client2 = Client()
        self.client2.login(username='test_perm_inv2', password='investigador123')

        self.client_admin = Client()
        self.client_admin.login(username='admin_test_perm', password='password123')

        self.uid = str(uuid.uuid4())[:8]

        self.part_shared = Participant.objects.create(
            first_name=f'SharedPart_{self.uid}',
            last_name='Test',
            subject_id=f'SUB_SH_{self.uid}'
        )
        self.member_shared = Member.objects.create(
            first_name=f'SharedMem_{self.uid}',
            last_name='Test',
            role='Neurólogo/a'
        )

        url_create = reverse('experiment_create')
        self.exp1_name = f'Exp_Inv1_{self.uid}'
        res_create1 = self.client1.post(url_create, data={
            'name': self.exp1_name,
            'description': 'Experimento de Investigador 1'
        })
        self.assertIn(res_create1.status_code, [200, 302])
        self.exp1 = Experiment.objects.get(name=self.exp1_name)
        group1 = ParticipantGroup.objects.create(experiment=self.exp1, name="Grupo 1")
        ExperimentParticipant.objects.create(experiment=self.exp1, participant=self.part_shared, group=group1)
        self.exp1.members.add(self.member_shared)

        self.dicom1 = DicomFile.objects.create(
            participant=self.part_shared,
            experiment=self.exp1,
            patient_name=f'Patient_Inv1_{self.uid}',
            file='dicoms/inv1.dcm'
        )

    def test_01_creator_assigned_correctly(self):
        self.assertEqual(self.exp1.created_by, self.inv1)

    def test_02_inv1_sees_own_experiment_in_dashboard(self):
        res_dash1 = self.client1.get(reverse('dashboard'))
        self.assertEqual(res_dash1.status_code, 200)
        self.assertIn(self.exp1_name, res_dash1.content.decode('utf-8'))

    def test_03_inv2_does_not_see_inv1_experiment_in_dashboard(self):
        res_dash2 = self.client2.get(reverse('dashboard'))
        self.assertEqual(res_dash2.status_code, 200)
        self.assertNotIn(self.exp1_name, res_dash2.content.decode('utf-8'))

    def test_04_inv2_gets_404_on_direct_access_to_inv1_experiment(self):
        res_detail2 = self.client2.get(reverse('experiment_detail', kwargs={'pk': self.exp1.pk}))
        self.assertEqual(res_detail2.status_code, 404)

    def test_05_inv2_cannot_edit_inv1_experiment_name(self):
        res_update_name = self.client2.post(
            reverse('update_experiment_name', kwargs={'pk': self.exp1.pk}),
            data=json_bytes({'name': 'Nombre Hackeado'}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertIn(res_update_name.status_code, [404, 500])
        self.exp1.refresh_from_db()
        self.assertEqual(self.exp1.name, self.exp1_name)

    def test_06_inv2_cannot_delete_inv1_experiment(self):
        res_delete2 = self.client2.post(reverse('experiment_delete', kwargs={'pk': self.exp1.pk}))
        self.assertEqual(res_delete2.status_code, 404)
        self.assertTrue(Experiment.objects.filter(pk=self.exp1.pk).exists())

    def test_07_inv2_cannot_modify_inv1_experiment_via_ajax(self):
        res_ajax_add = self.client2.post(
            reverse('add_participants_to_experiment', kwargs={'pk': self.exp1.pk}),
            data=json_bytes({'participant_ids': [self.part_shared.pk]}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertIn(res_ajax_add.status_code, [404, 500])

    def test_08_inv2_cannot_access_inv1_dicom_file_detail(self):
        res_dicom_det2 = self.client2.get(reverse('dicomfile_detail', kwargs={'pk': self.dicom1.pk}))
        self.assertEqual(res_dicom_det2.status_code, 404)

    def test_09_inv2_cannot_access_inv1_dicom_image_view(self):
        res_dicom_img2 = self.client2.get(reverse('dicom_image_view', kwargs={'dicom_id': self.dicom1.pk}))
        self.assertEqual(res_dicom_img2.status_code, 404)

    def test_10_inv2_cannot_edit_inv1_dicom_patient_name(self):
        res_dicom_edit2 = self.client2.post(
            reverse('dicomfile_detail', kwargs={'pk': self.dicom1.pk}),
            data={'patient_name': 'Hacked_Patient'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_dicom_edit2.status_code, 404)
        self.dicom1.refresh_from_db()
        self.assertEqual(self.dicom1.patient_name, f'Patient_Inv1_{self.uid}')

    def test_11_inv1_can_access_own_experiment_detail(self):
        res_detail1 = self.client1.get(reverse('experiment_detail', kwargs={'pk': self.exp1.pk}))
        self.assertEqual(res_detail1.status_code, 200)

    def test_12_admin_can_access_and_edit_any_experiment(self):
        res_admin_detail = self.client_admin.get(reverse('experiment_detail', kwargs={'pk': self.exp1.pk}))
        self.assertEqual(res_admin_detail.status_code, 200)

        new_name = f'{self.exp1_name}_EditedByAdmin'
        res_admin_update = self.client_admin.post(
            reverse('update_experiment_name', kwargs={'pk': self.exp1.pk}),
            data=json_bytes({'name': new_name}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_admin_update.status_code, 200)
        self.exp1.refresh_from_db()
        self.assertEqual(self.exp1.name, new_name)

    def test_13_dashboard_search_respects_isolation(self):
        exp2_name = f'Exp_Inv2_{self.uid}'
        exp2 = Experiment.objects.create(name=exp2_name, description='Exp Inv 2', created_by=self.inv2)
        exp2.participants.add(self.part_shared)
        exp2.members.add(self.member_shared)

        res_search1 = self.client1.get(f"{reverse('dashboard')}?q=Exp_Inv")
        self.assertEqual(res_search1.status_code, 200)
        content1 = res_search1.content.decode('utf-8')
        self.assertIn(self.exp1.name, content1)
        self.assertNotIn(exp2_name, content1)

    def test_14_shared_participant_experiments_view_respects_isolation(self):
        exp2_name = f'Exp_Inv2_{self.uid}'
        exp2 = Experiment.objects.create(name=exp2_name, description='Exp Inv 2', created_by=self.inv2)
        exp2.participants.add(self.part_shared)
        exp2.members.add(self.member_shared)

        res_part_exp1 = self.client1.get(reverse('participant_experiments', kwargs={'participant_id': self.part_shared.pk}))
        self.assertEqual(res_part_exp1.status_code, 200)
        content_pe1 = res_part_exp1.content.decode('utf-8')
        self.assertIn(self.exp1.name, content_pe1)
        self.assertNotIn(exp2_name, content_pe1)

    def test_15_deleting_user_retains_experiments_with_created_by_null(self):
        user_temp = User.objects.create_user(username=f'temp_inv_{self.uid}', password='password123')
        exp_temp = Experiment.objects.create(name=f'Exp_Temp_{self.uid}', description='Temp', created_by=user_temp)
        exp_temp.participants.add(self.part_shared)
        exp_temp.members.add(self.member_shared)

        user_temp.delete()

        exp_temp.refresh_from_db()
        self.assertIsNone(exp_temp.created_by)

        res_admin_dash = self.client_admin.get(reverse('dashboard'))
        self.assertEqual(res_admin_dash.status_code, 200)
        self.assertIn(exp_temp.name, res_admin_dash.content.decode('utf-8'))

    def test_16_participant_and_member_preserved_upon_experiment_deletion(self):
        part_orphan = Participant.objects.create(first_name=f'OrphanPart_{self.uid}', last_name='Test', subject_id=f'SUB_ORP_{self.uid}')
        member_orphan = Member.objects.create(first_name=f'OrphanMem_{self.uid}', last_name='Test', role='Neurólogo/a')
        exp_delete_test = Experiment.objects.create(name=f'Exp_Delete_{self.uid}', description='Del', created_by=self.admin)
        exp_delete_test.participants.add(part_orphan)
        exp_delete_test.members.add(member_orphan)

        res_del = self.client_admin.post(reverse('experiment_delete', kwargs={'pk': exp_delete_test.pk}))
        self.assertIn(res_del.status_code, [200, 302])
        # Participant and Member should remain preserved
        self.assertTrue(Participant.objects.filter(pk=part_orphan.pk).exists())
        self.assertTrue(Member.objects.filter(pk=member_orphan.pk).exists())

    def test_17_dicom_file_set_null_on_experiment_or_participant_deletion(self):
        self.assertTrue(DicomFile.objects.filter(pk=self.dicom1.pk).exists())
        self.assertEqual(self.dicom1.experiment, self.exp1)
        self.assertEqual(self.dicom1.participant, self.part_shared)
