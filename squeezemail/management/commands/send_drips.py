from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q


class Command(BaseCommand):
    def handle(self, *args, **options):
        from squeezemail.models import Drip

        for drip in Drip.objects.filter(enabled=True).filter(Q(send_after__lte=timezone.now()) | Q(send_after=None)):
            drip.handler.run()
