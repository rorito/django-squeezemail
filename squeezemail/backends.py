from django.conf import settings
from djcelery_email.backends import CeleryEmailBackend

# from .tasks import send_drip
from .utils import chunked, email_to_dict


class SqueezeEmailBackend(CeleryEmailBackend):
    def __init__(self, fail_silently=False, **kwargs):
        super(SqueezeEmailBackend, self).__init__(fail_silently)
        self.init_kwargs = kwargs

    # def send_drips(self, email_messages):
    #     result_tasks = []
    #     messages = [email_to_dict(msg) for msg in email_messages]
    #     for chunk in chunked(messages, settings.CELERY_EMAIL_CHUNK_SIZE):
    #         result_tasks.append(send_drip.delay(chunk, self.init_kwargs))
    #     return result_tasks

    def send_broadcast(self, email_messages):
        pass