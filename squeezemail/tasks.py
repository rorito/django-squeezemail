from hashlib import md5

from celery import shared_task, task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.core.mail import get_connection
from django.core.cache import cache
from django.utils import timezone

from google_analytics_reporter.tracking import Event

from squeezemail import SQUEEZE_PREFIX
from .models import SendDrip, Drip, Subscriber, Open, Click, DripSubject
from .utils import get_token_for_email


LOCK_EXPIRE = (60 * 60) * 24  # Lock expires in 24 hours if it never gets unlocked

@task(bind=True)
def send_drip(self, subscriber_id_list, backend_kwargs=None, **kwargs):
    next_step_id = kwargs.get('next_step_id', None)
    drip_id = kwargs['drip_id']
    first_subscriber_id = subscriber_id_list[0]

    # The cache key consists of the squeeze_prefix (if it exists), drip id, first user id in the list and the MD5 digest.
    # This is to prevent a subscriber receiving 1 email multiple times if 2+ identical tasks are queued. The workers tend
    # to be so fast, that I've tested it without this and a subscriber was able to receive 1 email ~10 times when a bunch of
    # identical stale tasks were sitting in the queue waiting for celery to start.
    # Adding in the first_subscriber_id stops this from happening. Haven't figured out a better way yet.
    drip_id_hexdigest = md5(str(SQUEEZE_PREFIX).encode('utf-8') + str(drip_id).encode('utf-8') + '_'.encode('utf-8') + str(first_subscriber_id).encode('utf-8')).hexdigest()
    lock_id = '{0}-lock-{1}'.format(self.name, drip_id_hexdigest)

    # cache.add fails if the key already exists
    acquire_lock = lambda: cache.add(lock_id, 'true', LOCK_EXPIRE)
    # memcache delete is very slow, but we have to use it to take
    # advantage of using add() for atomic locking
    release_lock = lambda: cache.delete(lock_id)

    logger.debug('Attempting to aquire lock for drip_id %i', drip_id)
    if acquire_lock():
        messages_sent = 0
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

            for subscriber_id in subscriber_id_list:
                try:
                    sentdrip = SendDrip.objects.get(subscriber_id=subscriber_id, drip_id=drip_id)

                    try:
                        if sentdrip.sent is False:
                            subscriber = Subscriber.objects.get(id=subscriber_id)

                            message_instance = MessageClass(drip, subscriber)

                            sent = conn.send_messages([message_instance.message])
                            if sent is not None:
                                sentdrip.sent = True
                                sentdrip.date = timezone.now()
                                sentdrip.save()
                                messages_sent += 1
                                logger.debug("Successfully sent email message to subscriber %i.", subscriber.pk)
                                # Move subscriber to next step only after their drip has been sent
                                subscriber.move_to_step(next_step_id)
                    except ObjectDoesNotExist as e: #user doesn't exist
                        logger.warning("Subscriber_id %i does not exist. (%r)", subscriber_id, e)
                        continue
                    except Exception as e:
                        logger.warning("Failed to send email message to %i. (%r)", subscriber_id, e)
                        #send_drip.retry([[message], combined_kwargs], exc=e, throw=False)
                        continue
                except SendDrip.MultipleObjectsReturned:
                    logger.warning("Multiple SendDrips returned for subscriber_id: %i, drip_id: %i", subscriber_id, drip_id)
                    continue
                except SendDrip.DoesNotExist:
                    # a senddrip doesn't exist, shouldn't happen, but if it does, skip it
                    logger.warning("Can't find a SendDrip object for subscriber_id: %i, drip_id: %i", subscriber_id, drip_id)
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

    token = url_kwargs.get('sq_token', None)
    subscriber_id = url_kwargs.get('sq_subscriber_id', None)
    drip_id = url_kwargs.get('sq_drip_id', None)
    ga_cid = url_kwargs.get('sq_cid', None)

    subject_id = url_kwargs.get('sq_subject_id', None)
    split = url_kwargs.get('sq_split', None)

    if token:  # if a user token is passed in and matched, we're allowed to do database writing
        subscriber = Subscriber.objects.get(pk=subscriber_id)
        token_matched = subscriber.match_token(token)

        if token_matched:
            logger.debug("Successfully matched token to user %r.", subscriber.email)
            sentdrip = SendDrip.objects.get(drip_id=drip_id, subscriber_id=subscriber_id)
            if not sentdrip.opened:
                Open.objects.create(senddrip=sentdrip)
                logger.debug("SendDrip.open created")

                subject = DripSubject.objects.get(id=subject_id).text

                # utm_source=drip
                # utm_campaign=sentdrip.drip.name
                # utm_medium=email
                # utm_content=split ('A' or 'B')
                # target=target # don't need this for opens, but could be useful in clicks
                # event = 'open'?
                #TODO: switch from .debug to .send to actually send to google
                Event(user_id=subscriber.user_id, client_id=ga_cid)\
                    .debug(
                    category='email',
                    action='open',
                    document_path='/email/',
                    document_title=subject,
                    campaign_id=drip_id,
                    campaign_name=sentdrip.drip.name,
                    # campaign_source='', #broadcast or step?
                    campaign_medium='email',
                    campaign_content=split  # body split test
                )
        else:
            logger.info("subscriber token didn't match")

    logger.info("Email open processed for drip %r and subscriber %r", drip_id, subscriber_id)
    return


@shared_task()
def process_click(**kwargs):
    #TODO: pass subscriber_id through instead of user_id
    url_kwargs = kwargs

    token = url_kwargs.get('sq_token', None)
    subscriber_id = url_kwargs.get('sq_subscriber_id', None)
    drip_id = url_kwargs.get('sq_drip_id', None)
    ga_cid = url_kwargs.get('sq_cid', None)

    subject_id = url_kwargs.get('sq_subject_id', None)
    split = url_kwargs.get('sq_split', None)
    tag_id = url_kwargs.get('sq_tag_id', None)

    if token:  # if a user token is passed in and matched, we're allowed to do database writing
        subscriber = Subscriber.objects.get(pk=subscriber_id)
        token_matched = subscriber.match_token(token)

        if token_matched:
            logger.debug("Successfully matched token to user %r.", subscriber.email)
            sentdrip = SendDrip.objects.get(drip_id=drip_id, subscriber_id=subscriber_id)
            subject = DripSubject.objects.get(id=subject_id).text
            if not sentdrip.opened:
                Open.objects.create(senddrip=sentdrip)
                logger.debug("SendDrip.open created")
                # target=target # don't need this for opens, but could be useful in clicks
                Event(user_id=subscriber.user_id, client_id=ga_cid)\
                    .send(
                    category='email',
                    action='open',
                    document_path='/email/',
                    document_title=subject,
                    campaign_id=drip_id,
                    campaign_name=sentdrip.drip.name,
                    # campaign_source='', #broadcast or step?
                    campaign_medium='email',
                    campaign_content=split  # body split test
                )

            if not sentdrip.clicked:
                Click.objects.create(senddrip=sentdrip)
                logger.debug('Click created')

            if tag_id:
                #TODO: tag 'em
                pass

            Event(user_id=subscriber.user_id, client_id=ga_cid)\
                .send(
                category='email',
                action='open',
                document_path='/email/',
                document_title=subject,
                campaign_id=drip_id,
                campaign_name=sentdrip.drip.name,
                # campaign_source='', #broadcast or step?
                campaign_medium='email',
                campaign_content=split  # body split test
            )
        else:
            logger.info("user link didn't match token")

    logger.info("Email click processed")
    return

try:
    from celery.utils.log import get_task_logger
    logger = get_task_logger(__name__)
except ImportError:
    logger = send_drip.get_logger()