from hashlib import md5

from celery import shared_task, task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.core.mail import get_connection
from django.core.cache import cache

from django.utils import timezone

from squeezemail.models import SendDrip, Drip, Subscriber, Open, Click, DripSubject


# from squeezemail.utils import email_to_dict, dict_to_email
# from .models import Drip
#from utils.celery.tasks import lock_task
#from subscriptions.drops import Drop


# @task()
# def send_drop(user, drip_name, name):
#     """
#     Sends a single drip to a single user.
#     Mostly used to send a welcome email after a user subscribes to the newsletter.
#
#     The 'name' is required for some reason. The only requirement is that it exists, it seems.
#     It has nothing to do with getting any object.
#     """
#     welcome_email = Drip.objects.get(name=drip_name) #get drip
#     return Drop(drip_model=welcome_email, user=user, name=name).run() #prunes and sends to user


#@lock_task(60*10)
# @shared_task()
# def send_drips():
#     for drip in Drip.objects.filter(enabled=True):
#         drip.drip.run()

LOCK_EXPIRE = (60 * 60) * 24  # Lock expires in 24 hours if it never gets unlocked

@task(bind=True)
def send_drip(self, user_id_list, backend_kwargs=None, **kwargs):
    drip_id = kwargs['drip_id']
    # The cache key consists of the task name and the MD5 digest
    # of the feed URL.

    drip_url_hexdigest = md5(str(drip_id).encode('utf-8')).hexdigest() #TODO: salt this instead
    lock_id = '{0}-lock-{1}'.format(self.name, drip_url_hexdigest)

    # cache.add fails if the key already exists
    acquire_lock = lambda: cache.add(lock_id, 'true', LOCK_EXPIRE)
    # memcache delete is very slow, but we have to use it to take
    # advantage of using add() for atomic locking
    release_lock = lambda: cache.delete(lock_id)

    logger.debug('Attempting to aquire lock for drip_id %i', drip_id)
    if acquire_lock():
        try:
            from squeezemail.handlers import message_class_for
            # backward compat: handle **kwargs and missing backend_kwargs
            combined_kwargs = {}
            if backend_kwargs is not None:
                combined_kwargs.update(backend_kwargs)
            combined_kwargs.update(kwargs)



            try:
                drip = Drip.objects.get(id=drip_id)
                MessageClass = message_class_for(drip.message_class)
            except Drip.DoesNotExist:
                logger.warning("Drip %i doesn't exist" % drip_id)
                return

            conn = get_connection(backend=settings.EMAIL_BACKEND, **combined_kwargs)
            try:
                conn.open()
            except Exception as e:
                logger.exception("Cannot reach EMAIL_BACKEND %s. (%r)", settings.EMAIL_BACKEND, e)

            messages_sent = 0

            for user_id in user_id_list:
                try:
                    if drip.parent_id:  # Check if this drip has a parent
                        # Should only return 1,
                        # if multiple return, we don't send because one is sent/sending with the same parent
                        sentdrip = SendDrip.objects.get(user_id=user_id, drip__parent_id=drip.parent_id)
                        if sentdrip.sent:
                            continue  # go to next loop, it's already been sent.
                    else:
                        sentdrip = SendDrip.objects.get(user_id=user_id, drip_id=drip_id, sent=False)

                    try:
                        if sentdrip.sent is False:
                            user = get_user_model().objects.get(id=user_id)

                            message_instance = MessageClass(drip, user)

                            sent = conn.send_messages([message_instance.message])
                            if sent is not None:
                                sentdrip.sent = True
                                sentdrip.date = timezone.now()
                                sentdrip.save()
                                messages_sent += 1
                                logger.debug("Successfully sent email message to %r.", user.email)
                    except ObjectDoesNotExist as e: #user doesn't exist
                        logger.warning("User_id %i does not exist. (%r)", user_id, e)
                        continue
                    except Exception as e:
                        logger.warning("Failed to send email message to %i. (%r)", user_id, e)
                        #send_drip.retry([[message], combined_kwargs], exc=e, throw=False)
                        continue
                except SendDrip.MultipleObjectsReturned:
                    logger.warning("Multiple SentDrips returned for user_id: %i, drip_id: %i", user_id, drip_id)
                    continue
                except SendDrip.DoesNotExist:
                    # an unsent sentdrip doesn't exist, don't do anything
                    logger.warning("Can't find a SendDrip object for user_id: %i, drip_id: %i", user_id, drip_id)
                    continue
            conn.close()
        finally:
            release_lock()
            logger.info("Drip_id %i chunk successfully sent: %i", drip_id, messages_sent)
        return
    logger.debug('Drip_id %i is already being sent by another worker', drip_id)
    return


@shared_task()
def process_open(**kwargs):
    url_kwargs = kwargs

    user_token = url_kwargs.get('sq_user_token', None)
    user_id = url_kwargs.get('sq_user_id', None)
    drip_id = url_kwargs.get('sq_drip_id', None)

    subject_id = url_kwargs.get('sq_subject_id', None)
    split = url_kwargs.get('sq_split', None)

    if user_token:  # if a user token is passed in and matched, we're allowed to do database writing
        user = get_user_model().objects.get(pk=user_id)
        token_matched = user.match_token(user_token)

        if token_matched:
            logger.debug("Successfully matched token to user %r.", user.email)
            sentdrip = SendDrip.objects.get(drip_id=drip_id, user_id=user_id)
            if not sentdrip.opened:
                Open.objects.create(sentdrip=sentdrip)
                logger.info("Sentdrip.open created")

                subject = DripSubject.objects.get(id=subject_id).subject

                # utm_source=drip
                # utm_campaign=sentdrip.drip.name
                # utm_medium=email
                # utm_content=split ('A' or 'B')
                # target=target # don't need this for opens, but would be useful in clicks
                # event = 'open'?
        else:
            logger.info("user_token didn't match user id token")

    logger.info("Email open processed for drip %r and user %r", drip_id, user_id)
    return


@shared_task()
def process_click(**kwargs):
    url_kwargs = kwargs

    user_token = url_kwargs.get('sq_user_token', None)
    user_id = url_kwargs.get('sq_user_id', None)
    drip_id = url_kwargs.get('sq_drip_id', None)
    movetosequence = url_kwargs.get('sq_movetosequence', None)
    tag = url_kwargs.get('sq_tag', None)

    if user_token:  # if a user token is passed in and matched, we're allowed to do database writing
        user = get_user_model().objects.get(pk=user_id)
        token_matched = user.match_token(user_token)

        if token_matched:
            logger.debug("Successfully matched token to user %r.", user.email)

            sentdrip = SendDrip.objects.get(drip_id=drip_id, user_id=user_id)
            if not sentdrip.opened:
                Open.objects.create(sentdrip=sentdrip)
                logger.warning("Sentdrip.open from click")

            if not sentdrip.clicked:
                Click.objects.create(sentdrip=sentdrip)
                logger.debug('Click created')

            if movetosequence:
                try:
                    subscriber = user.subscriptions.get(sequence__drips__id=drip_id)
                    subscriber.move_to_sequence(movetosequence)
                except Subscriber.DoesNotExist as e:
                    logger.warning("Subscriber for sequence__drips__id=%i does not exist. (%r)", drip_id, e)

            if tag:
                #TODO: tag 'em
                pass

            #TODO: process stats (send stuff to google analytics)
        else:
            logger.info("user link didn't match token")

    logger.info("Email click processed")
    return


#SendDripTask = send_drip

try:
    from celery.utils.log import get_task_logger
    logger = get_task_logger(__name__)
except ImportError:
    logger = send_drip.get_logger()