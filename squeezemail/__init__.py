from django.conf import settings

"""
Here lies default settings.
"""

# If you need a custom way of creating subscribers, create your own custom manager and set it here.
SUBSCRIBER_MANAGER = getattr(settings, 'SUBSCRIBER_MANAGER', 'squeezemail.models.SubscriberManager')

# Set this to your custom Drip handler class if you need to customize how drips are... handled.
DRIP_HANDLER = getattr(settings, 'DRIP_HANDLER', 'squeezemail.handlers.HandleDrip')

# If you have 1,000 users to send to at once, a setting of 100 will cut it up into 10 queue 'chunks' of 100 each.
CELERY_EMAIL_CHUNK_SIZE = getattr(settings, 'CELERY_EMAIL_CHUNK_SIZE', 100)

# For building links.
DEFAULT_HTTP_PROTOCOL = getattr(settings, 'DEFAULT_HTTP_PROTOCOL', 'http')

# Use when you're running more than one squeezemail app on the same server (multiple Django projects).
# Note: Changing this changes your celery queue names. 'drips' changes to 'my_prefix_drips', so be sure to start
# your workers with the proper queue names.
SQUEEZE_PREFIX = getattr(settings, 'SQUEEZE_PREFIX', '')

