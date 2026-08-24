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

    def test_01_researcher_sees_own_participants_and_members_in_form(self):
        url_create = reverse('experiment_create')
        res1 = self.client1.get(url_create)
        self.assertEqual(res1.status_code, 200)
        form1 = get_form_from_response(res1)
        self.assertIsNotNone(form1)
        self.assertIn(self.part_A, form1.fields['participants'].queryset)
        self.assertIn(self.member_A, form1.fields['members'].queryset)

    def test_02_researcher_does_not_see_other_researcher_participants_and_members(self):
        url_create = reverse('experiment_create')
        res1 = self.client1.get(url_create)
        form1 = get_form_from_response(res1)
        self.assertNotIn(self.part_B, form1.fields['participants'].queryset)
        self.assertNotIn(self.member_B, form1.fields['members'].queryset)

    def test_03_researcher_does_not_see_admin_participants_and_members(self):
        url_create = reverse('experiment_create')
        res1 = self.client1.get(url_create)
        form1 = get_form_from_response(res1)
        self.assertNotIn(self.part_C, form1.fields['participants'].queryset)
        self.assertNotIn(self.member_C, form1.fields['members'].queryset)

    def test_04_admin_sees_all_participants_and_members_in_form(self):
        url_create = reverse('experiment_create')
        res_admin = self.client_admin.get(url_create)
        self.assertEqual(res_admin.status_code, 200)
        form_admin = get_form_from_response(res_admin)
        self.assertIn(self.part_A, form_admin.fields['participants'].queryset)
        self.assertIn(self.part_B, form_admin.fields['participants'].queryset)
        self.assertIn(self.part_C, form_admin.fields['participants'].queryset)
        self.assertIn(self.member_A, form_admin.fields['members'].queryset)
        self.assertIn(self.member_B, form_admin.fields['members'].queryset)
        self.assertIn(self.member_C, form_admin.fields['members'].queryset)

    def test_05_backend_rejects_tampered_post_with_other_researcher_participant(self):
        url_create = reverse('experiment_create')
        res_post_part_B = self.client1.post(url_create, data={
            'name': 'Intento Hack Participante B',
            'description': 'Prueba POST no permitido',
            'participants': [self.part_B.pk],
            'members': [self.member_A.pk]
        })
        self.assertEqual(res_post_part_B.status_code, 200)
        form_err1 = get_form_from_response(res_post_part_B)
        self.assertIn('participants', form_err1.errors)
        self.assertFalse(Experiment.objects.filter(name='Intento Hack Participante B').exists())

    def test_06_backend_rejects_tampered_post_with_other_researcher_member(self):
        url_create = reverse('experiment_create')
        res_post_member_B = self.client1.post(url_create, data={
            'name': 'Intento Hack Miembro B',
            'description': 'Prueba POST no permitido',
            'participants': [self.part_A.pk],
            'members': [self.member_B.pk]
        })
        self.assertEqual(res_post_member_B.status_code, 200)
        form_err2 = get_form_from_response(res_post_member_B)
        self.assertIn('members', form_err2.errors)
        self.assertFalse(Experiment.objects.filter(name='Intento Hack Miembro B').exists())

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

    def test_09_new_researcher_with_no_experiments_has_empty_form_selects(self):
        inv_clean = User.objects.create_user(username=f'clean_inv_{self.uid}', password='password123')
        client_clean = Client()
        client_clean.login(username=f'clean_inv_{self.uid}', password='password123')
        res_clean = client_clean.get(reverse('experiment_create'))
        form_clean = get_form_from_response(res_clean)
        self.assertEqual(form_clean.fields['participants'].queryset.count(), 0)
        self.assertEqual(form_clean.fields['members'].queryset.count(), 0)

    def test_10_admin_can_create_experiment_selecting_any_participant_and_member(self):
        url_create = reverse('experiment_create')
        res_valid_admin = self.client_admin.post(url_create, data={
            'name': f'ExpAdmin_All_{self.uid}',
            'description': 'Exp creado por admin',
            'participants': [self.part_A.pk, self.part_B.pk, self.part_C.pk],
            'members': [self.member_A.pk, self.member_B.pk, self.member_C.pk]
        })
        self.assertIn(res_valid_admin.status_code, [200, 302])
        exp_admin_created = Experiment.objects.get(name=f'ExpAdmin_All_{self.uid}')
        self.assertEqual(exp_admin_created.participants.count(), 3)
        self.assertEqual(exp_admin_created.members.count(), 3)

    def test_11_plus_button_created_participant_and_member_isolated_to_creator(self):
        url_create = reverse('experiment_create')

        res_create_p = self.client1.post(
            reverse('create_participant_ajax'),
            data=json_bytes({'full_name': f'NuevoPart_{self.uid} Test'}),
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

        res_exp_new = self.client1.post(url_create, data={
            'name': f'Exp_NuevoInv1_{self.uid}',
            'description': 'Exp con nuevos participantes',
            'participants': [new_part_id],
            'members': [new_mem_id]
        })
        self.assertIn(res_exp_new.status_code, [200, 302])

        res_inv2_form = self.client2.get(url_create)
        form_inv2 = get_form_from_response(res_inv2_form)
        self.assertNotIn(Participant.objects.get(pk=new_part_id), form_inv2.fields['participants'].queryset)
        self.assertNotIn(Member.objects.get(pk=new_mem_id), form_inv2.fields['members'].queryset)
