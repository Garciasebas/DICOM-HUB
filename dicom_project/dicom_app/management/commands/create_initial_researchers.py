from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = 'Crea o actualiza los 9 usuarios investigadores iniciales de forma segura e idempotente.'

    def handle(self, *args, **kwargs):
        password = 'investigador123'
        created_count = 0
        updated_count = 0

        for i in range(1, 10):
            username = f'investigador{i}'
            email = f'{username}@dicomhub.local'
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': email,
                    'is_staff': False,
                    'is_superuser': False,
                    'first_name': f'Investigador',
                    'last_name': f'{i}'
                }
            )
            user.set_password(password)
            user.save()

            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'Usuario de desarrollo creado: {username}'))
            else:
                updated_count += 1
                self.stdout.write(self.style.SUCCESS(f'Usuario de desarrollo actualizado: {username}'))

        self.stdout.write(self.style.SUCCESS(
            f'Finalizado: {created_count} creados, {updated_count} actualizados.'
        ))
