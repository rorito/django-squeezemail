from django.conf import settings

"""
Here lies default settings.
"""

# If you need a custom way of creating/managing subscribers, create your own custom manager and set it here.
SQUEEZE_SUBSCRIBER_MANAGER = getattr(settings, 'SQUEEZE_SUBSCRIBER_MANAGER', 'squeezemail.models.SubscriberManager')

# Set this to your custom Drip handler class if you need to customize how drips are... handled.
SQUEEZE_DRIP_HANDLER = getattr(settings, 'SQUEEZE_DRIP_HANDLER', 'squeezemail.handlers.HandleDrip')

# If you have 1,000 users to send to at once, a setting of 100 will cut it up into 10 queue 'chunks' of 100 each.
# For example, this allows you to have 4 workers work on a big email queue at the same time without bumping into each
# other. This helps solve the huge (100,000+) email broadcasts taking 24+ hours to send out.
# Be aware of your email server's send limits.
SQUEEZE_CELERY_EMAIL_CHUNK_SIZE = getattr(settings, 'SQUEEZE_CELERY_EMAIL_CHUNK_SIZE', 100)

# For building links in emails.
SQUEEZE_DEFAULT_HTTP_PROTOCOL = getattr(settings, 'SQUEEZE_DEFAULT_HTTP_PROTOCOL', 'http')

# Use when you're running more than one squeezemail app on the same server (multiple Django projects).
# Note: Changing this changes your celery queue names. 'drips' changes to 'my_prefix_drips', so be sure to start
# your celery workers with the queue names they need to work on, if you have different workers assigned to different
# tasks.
SQUEEZE_PREFIX = getattr(settings, 'SQUEEZE_PREFIX', '')

SQUEEZE_DEFAULT_FROM_EMAIL = getattr(settings, 'SQUEEZE_DEFAULT_FROM_EMAIL', settings.DEFAULT_FROM_EMAIL)

