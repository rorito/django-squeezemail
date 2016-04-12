from django.core.management import BaseCommand


class Command(BaseCommand):
    help = 'Unsubscribes and unchecks the optin field on the user model for all the users who reported an email as spam'
    def handle(self, *args, **options):
        from sendgrid_events.models import Event
        num = 0
        for event in Event.objects.filter(kind='spamreport'):
            user = event.user
            if user.has_active_newsletter_subscription():
                subscriptions = user.subscriptions.filter(is_active=True)
                for sub in subscriptions:
                    sub.unsubscribe()
                    num += 1

        print num #prints to console