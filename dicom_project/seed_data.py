
import os
import django
from django.utils import timezone
import random

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dicom_project.settings')
django.setup()

from dicom_app.models import Participant, Member, Experiment

def create_seed_data():
    print("🌱 Seeding data...")

    # Create Experiments
    experiments = []
    for i in range(1, 6):
        exp, created = Experiment.objects.get_or_create(
            name=f"Experiment {i}",
            defaults={
                'description': f"Description for Experiment {i}",
                'status': 'Active'
            }
        )
        experiments.append(exp)
        if created:
            print(f"Created Experiment: {exp.name}")

    # Create Participants
    for i in range(1, 11):
        subject_id = f"SUB-{i:03d}"
        participant, created = Participant.objects.get_or_create(
            subject_id=subject_id,
            defaults={
                'first_name': f"Participant",
                'last_name': f"{i}",
                'email': f"participant{i}@example.com",
                'phone': f"555-01{i:02d}",
                'details': f"seed data participant {i}"
            }
        )
        # Add random experiments script
        if created:
            participant.experiments.set(random.sample(experiments, k=random.randint(1, 3)))
            print(f"Created Participant: {participant}")
        
    # Create Members
    roles = [choice[0] for choice in Member.ROLE_CHOICES]
    for i in range(1, 11):
        member, created = Member.objects.get_or_create(
            email=f"member{i}@example.com", # assuming email is unique enough or used for lookup in get_or_create if we added it to lookup args, but here we just check email/names
            first_name=f"Member",
            last_name=f"{i}",
            defaults={
                'role': random.choice(roles)
            }
        )
        if created:
            member.experiments.set(random.sample(experiments, k=random.randint(1, 3)))
            print(f"Created Member: {member}")

    print("✅ Seed data generation complete: 10 Participants, 10 Members, 5 Experiments.")

if __name__ == "__main__":
    create_seed_data()
