from django.core.management.base import BaseCommand


class Command(BaseCommand):
    def handle(self, *args, **options):
        from squeezemail.tasks import run_steps

        run_steps.delay()
