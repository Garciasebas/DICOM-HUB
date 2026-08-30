import json
import uuid
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from dicom_app.models import Experiment, Participant, Member

def json_bytes(data):
    return json.dumps(data).encode('utf-8')

def get_form_from_response(res):
    if hasattr(res, 'context_data') and res.context_data and 'form' in res.context_data:
        return res.context_data['form']
    if hasattr(res, 'context') and res.context:
        if isinstance(res.context, list):
            for ctx in res.context:
                if ctx and 'form' in ctx:
                    return ctx['form']
        elif 'form' in res.context:
            return res.context['form']
    return None

class SelectorIsolationTestCase(TestCase):
    def setUp(self):
        # Cleanup any orphan participants/members from previous initial setup
        Participant.objects.filter(experiments__isnull=True).delete()
        Member.objects.filter(experiments__isnull=True).delete()

        self.inv1 = User.objects.create_user(username='test_sel_inv1', password='investigador123')
        self.inv2 = User.objects.create_user(username='test_sel_inv2', password='investigador123')
        self.admin = User.objects.create_superuser(username='admin_test_sel', password='password123')

        self.client1 = Client()
        self.client1.login(username='test_sel_inv1', password='investigador123')

        self.client2 = Client()
        self.client2.login(username='test_sel_inv2', password='investigador123')

        self.client_admin = Client()
        self.client_admin.login(username='admin_test_sel', password='password123')

        self.uid = str(uuid.uuid4())[:8]

        # Experiment A (Inv 1)
        self.part_A = Participant.objects.create(first_name=f'PartA_{self.uid}', last_name='Test', subject_id=f'SUB_A_{self.uid}')
        self.member_A = Member.objects.create(first_name=f'MemA_{self.uid}', last_name='Test', role='Neurólogo/a')
        self.exp_A = Experiment.objects.create(name=f'ExpA_{self.uid}', description='Exp A', created_by=self.inv1)
        self.exp_A.participants.add(self.part_A)
        self.exp_A.members.add(self.member_A)

        # Experiment B (Inv 2)
        self.part_B = Participant.objects.create(first_name=f'PartB_{self.uid}', last_name='Test', subject_id=f'SUB_B_{self.uid}')
        self.member_B = Member.objects.create(first_name=f'MemB_{self.uid}', last_name='Test', role='Radiólogo/a')
        self.exp_B = Experiment.objects.create(name=f'ExpB_{self.uid}', description='Exp B', created_by=self.inv2)
        self.exp_B.participants.add(self.part_B)
        self.exp_B.members.add(self.member_B)

        # Experiment C (Admin)
        self.part_C = Participant.objects.create(first_name=f'PartC_{self.uid}', last_name='Test', subject_id=f'SUB_C_{self.uid}')
        self.member_C = Member.objects.create(first_name=f'MemC_{self.uid}', last_name='Test', role='Investigador/a Principal')
        self.exp_C = Experiment.objects.create(name=f'ExpC_{self.uid}', description='Exp C', created_by=self.admin)
        self.exp_C.participants.add(self.part_C)
        self.exp_C.members.add(self.member_C)

    def test_01_researcher_sees_own_participants_and_members_in_detail_context(self):
        url_detail = reverse('experiment_detail', args=[self.exp_A.pk])
        res1 = self.client1.get(url_detail)
        self.assertEqual(res1.status_code, 200)
        self.assertIn(self.part_A.pk, res1.context['experiment_participants'].values_list('participant_id', flat=True))
        self.assertIn(self.member_A, res1.context['experiment'].members.all())

    def test_02_researcher_does_not_see_other_researcher_participants_and_members(self):
        url_detail = reverse('experiment_detail', args=[self.exp_A.pk])
        res1 = self.client1.get(url_detail)
        self.assertNotIn(self.part_B, res1.context['available_participants'])
        self.assertNotIn(self.member_B, res1.context['available_members'])

    def test_03_researcher_does_not_see_admin_participants_and_members(self):
        url_detail = reverse('experiment_detail', args=[self.exp_A.pk])
        res1 = self.client1.get(url_detail)
        self.assertNotIn(self.part_C, res1.context['available_participants'])
        self.assertNotIn(self.member_C, res1.context['available_members'])

    def test_04_admin_sees_all_available_participants_and_members(self):
        url_detail = reverse('experiment_detail', args=[self.exp_C.pk])
        res_admin = self.client_admin.get(url_detail)
        self.assertEqual(res_admin.status_code, 200)
        self.assertIn(self.part_A, res_admin.context['available_participants'])
        self.assertIn(self.part_B, res_admin.context['available_participants'])
        self.assertIn(self.member_A, res_admin.context['available_members'])
        self.assertIn(self.member_B, res_admin.context['available_members'])

    def test_05_backend_rejects_tampered_post_with_other_researcher_participant(self):
        from dicom_app.models import ParticipantGroup
        group_A = ParticipantGroup.objects.create(experiment=self.exp_A, name="Grupo A")
        url_add = reverse('add_participants_to_experiment', args=[self.exp_A.pk])
        res_post_part_B = self.client1.post(
            url_add,
            data=json_bytes({'participant_id': self.part_B.pk, 'group_id': group_A.pk}),
            content_type='application/json'
        )
        self.assertEqual(res_post_part_B.status_code, 403)
        self.assertNotIn(self.part_B, self.exp_A.participants.all())

    def test_06_backend_rejects_tampered_post_with_other_researcher_member(self):
        url_add = reverse('add_members_to_experiment', args=[self.exp_A.pk])
        res_post_member_B = self.client1.post(
            url_add,
            data=json_bytes({'member_ids': [self.member_B.pk]}),
            content_type='application/json'
        )
        self.assertEqual(res_post_member_B.status_code, 403)
        self.assertNotIn(self.member_B, self.exp_A.members.all())

    def test_07_ajax_duplicate_participant_creation_returns_400(self):
        res_ajax_part_dup = self.client1.post(
            reverse('create_participant_ajax'),
            data=json_bytes({'full_name': f'PartA_{self.uid} Test'}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_ajax_part_dup.status_code, 400)

    def test_08_ajax_duplicate_member_creation_returns_400(self):
        res_ajax_mem_dup = self.client1.post(
            reverse('create_member_ajax'),
            data=json_bytes({'full_name': f'MemA_{self.uid} Test', 'role': 'Neurólogo/a'}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_ajax_mem_dup.status_code, 400)

    def test_09_new_researcher_with_no_experiments_has_empty_available_selects(self):
        inv_clean = User.objects.create_user(username=f'clean_inv_{self.uid}', password='password123')
        client_clean = Client()
        client_clean.login(username=f'clean_inv_{self.uid}', password='password123')
        exp_clean = Experiment.objects.create(name=f'Exp_Clean_{self.uid}', description='Clean', created_by=inv_clean)
        res_clean = client_clean.get(reverse('experiment_detail', args=[exp_clean.pk]))
        self.assertEqual(res_clean.context['available_participants'].count(), 0)
        self.assertEqual(res_clean.context['available_members'].count(), 0)

    def test_10_admin_can_add_any_participant_and_member_from_detail(self):
        from dicom_app.models import ParticipantGroup
        group_C = ParticipantGroup.objects.create(experiment=self.exp_C, name="Grupo C")
        url_add_p = reverse('add_participants_to_experiment', args=[self.exp_C.pk])
        res_add_p = self.client_admin.post(
            url_add_p,
            data=json_bytes({'participant_ids': [self.part_A.pk, self.part_B.pk], 'group_id': group_C.pk}),
            content_type='application/json'
        )
        self.assertEqual(res_add_p.status_code, 200)

        url_add_m = reverse('add_members_to_experiment', args=[self.exp_C.pk])
        res_add_m = self.client_admin.post(
            url_add_m,
            data=json_bytes({'member_ids': [self.member_A.pk, self.member_B.pk]}),
            content_type='application/json'
        )
        self.assertEqual(res_add_m.status_code, 200)

        self.assertEqual(self.exp_C.participants.count(), 3)
        self.assertEqual(self.exp_C.members.count(), 3)

    def test_11_plus_button_created_participant_and_member_isolated_to_creator(self):
        from dicom_app.models import ParticipantGroup
        group_A = ParticipantGroup.objects.create(experiment=self.exp_A, name="Grupo A Test 11")
        res_create_p = self.client1.post(
            reverse('create_participant_ajax'),
            data=json_bytes({
                'full_name': f'NuevoPart_{self.uid} Test',
                'experiment_id': self.exp_A.pk,
                'group_id': group_A.pk
            }),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_create_p.status_code, 200)
        new_part_id = res_create_p.json().get('id')

        res_create_m = self.client1.post(
            reverse('create_member_ajax'),
            data=json_bytes({'full_name': f'NuevoMem_{self.uid} Test', 'role': 'Físico/a Medico/a'}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res_create_m.status_code, 200)
        new_mem_id = res_create_m.json().get('id')
        self.exp_A.members.add(new_mem_id)

        res_inv2_detail = self.client2.get(reverse('experiment_detail', args=[self.exp_B.pk]))
        self.assertNotIn(Participant.objects.get(pk=new_part_id), res_inv2_detail.context['available_participants'])
        self.assertNotIn(Member.objects.get(pk=new_mem_id), res_inv2_detail.context['available_members'])
