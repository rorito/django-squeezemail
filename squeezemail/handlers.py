import sys
import operator
import functools

PY3 = sys.version_info > (3, 0)

import re
if PY3:
    from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl
else:
    from urlparse import urlparse, urlunparse, parse_qsl
    from urllib import urlencode

from django.conf import settings
from django.core.urlresolvers import reverse
from django.db.models import Q
from django.template import Context, Template
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.functional import cached_property
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags
from django.contrib.sites.models import Site
from django.contrib.auth import get_user_model
from django.utils.timezone import now
try:
    # Django >= 1.9
    from django.utils.module_loading import import_module
except ImportError:
    from django.utils.importlib import import_module

from feincms.templatetags.feincms_tags import feincms_render_region

from .utils import get_token_for_user
from squeezemail import CELERY_EMAIL_CHUNK_SIZE
from .tasks import send_drip
from .models import SendDrip, Open, Drip
from .utils import chunked

import timedelta as djangotimedelta

import logging

logger = logging.getLogger(__name__)

HREF_RE = re.compile(r'href\="((\{\{[^}]+\}\}|[^"><])+)"')


def configured_message_classes():
    conf_dict = getattr(settings, 'DRIP_MESSAGE_CLASSES', {})
    if 'default' not in conf_dict:
        conf_dict['default'] = 'squeezemail.handlers.DripMessage'
    return conf_dict


def message_class_for(name):
    path = configured_message_classes()[name]
    mod_name, klass_name = path.rsplit('.', 1)
    mod = import_module(mod_name)
    klass = getattr(mod, klass_name)
    return klass


class DripMessage(object):

    def __init__(self, drip, user):
        self.drip = drip
        self.user = user
        self._context = None
        self._subject = None
        self._body = None
        self._plain = None
        self._message = None
        self._user_token = None

    @cached_property
    def from_email(self):
        if self.drip.from_email_name and self.drip.from_email:
            from_ = "%s <%s>" % (self.drip.from_email_name, self.drip.from_email)
        elif self.drip.from_email and not self.drip.from_email_name:
            from_ = self.drip.from_email
        else:
            from_ = getattr(settings, 'DRIP_FROM_EMAIL', settings.DEFAULT_FROM_EMAIL)
        return from_

    @property
    def from_email_name(self):
        return self.drip.from_email_name

    @property
    def context(self):
        if not self._context:
            user_token = self.get_user_token
            context = Context({
                'user': self.user,
                'drip': self.drip,
                'user_token': user_token,
                })
            context['content'] = self.replace_urls(Template(feincms_render_region(context, self.drip, "body")).render(context)) #TODO: get split test feincms content here
            self._context = context
        return self._context

    @cached_property
    def subject_model(self):
        return self.drip.choose_split_test_subject

    @property
    def subject(self):
        if not self._subject:
            self._subject = Template(self.subject_model.subject).render(self.context)
        return self._subject

    @property
    def body(self):
        if not self._body:
            self._body = render_to_string('squeezemail/body.html', self.context)
        return self._body

    @property
    def plain(self):
        if not self._plain:
            self._plain = strip_tags(self.body)
        return self._plain

    @property
    def message(self):
        if not self._message:
            self._message = EmailMultiAlternatives(
                self.subject, self.plain, self.from_email, [self.user.email])

            # check if there are html tags in the rendered template
            if len(self.plain) != len(self.body):
                self._message.attach_alternative(self.body, 'text/html')
        return self._message

    def replace_urls(self, content):
        offset = 0
        for match in HREF_RE.finditer(content):
            link = match.group(1)
            if "nourlrewrite" not in link:
                replacelink = self.encode_url(link)
                content = ''.join((content[:match.start(1)+offset], replacelink, content[match.end(1)+offset:]))
                offset += len(replacelink) - len(match.group(1))
        return content

    def encode_url(self, raw_url):
        """
        Returns a replacement link

        Example of how this works:
        Here's an ordinary link in your email. There may be many of these in each email.
        original_url = http://anydomain.com/?just=athingwedontcareabout&but=letsmakeitinteresting

        Turns into:
        new_url = http://YOURDOMAIN.com/squeezemail/link/?sq_user_id=1&sq_drip_id=1&sq_user_token=123456789&just=athingwedontcareabout&but=letsmakeitinteresting&sq_target=http://somedomain.com

        When someone goes to the above new_url link, it'll hit our function at /link/ which re-creates the original url, but also passes user_id, drip_id, etc
        with it in case it's needed and redirects to the target url with the params. This is also where we throw some stats at Google Analytics.
        """
        parsed_url = urlparse(raw_url)

        if parsed_url.netloc is '':
            # stick the scheme and netloc in the url if it's missing. This is so urls aren't just '/sublocation/'
            parsed_url = parsed_url._replace(scheme=settings.DEFAULT_HTTP_PROTOCOL, netloc=Site.objects.get_current().domain)

        url_params = dict(parse_qsl(parsed_url.query))

        target_url = parsed_url._replace(query='')

        # where the user will be redirected to after clicking this link
        url_params['sq_target'] = urlunparse(target_url)

        # add user_id and drip_id to the params
        url_params.update(self.extra_url_params())

        parsed_url_list = list(parsed_url)
        parsed_url_list[4] = urlencode(url_params)

        new_url = urlparse('')._replace(
            scheme=settings.DEFAULT_HTTP_PROTOCOL,
            netloc=Site.objects.get_current().domain,
            path=reverse('squeezemail:link'),
            query=parsed_url_list[4]
        )

        #rebuild new url
        new_url_with_extra_params = urlunparse(new_url)

        return new_url_with_extra_params

    def extra_url_params(self):
        # These params will be inserted in every link in the content of the email.
        # Useful for tracking clicks and knowing who clicked it on which drip
        params = {
            'sq_user_id': self.user.id,
            'sq_drip_id': self.drip.id,
            'sq_user_token': self.get_user_token,
            'sq_subject_id': self.subject_model.id
        }
        return params

    @property
    def get_user_token(self):
        if not self._user_token:
            self._user_token = str(get_token_for_user(self.user))
        return self._user_token


class HandleBase(object):
    """
    A base object for defining a Drip.

    You can extend this manually, or you can create full querysets
    and templates from the admin.
    """
    def __init__(self, drip_model, *args, **kwargs):
        self.drip_model = drip_model
        self.now_shift_kwargs = kwargs.get('now_shift_kwargs', {})


    #########################
    ### DATE MANIPULATION ###
    #########################

    def now(self):
        """
        This allows us to override what we consider "now", making it easy
        to build timelines of who gets what when.
        """
        return now() + self.timedelta(**self.now_shift_kwargs)

    def timedelta(self, *a, **kw):
        """
        If needed, this allows us the ability to manipuate the slicing of time.
        """
        from datetime import timedelta #TODO: can't we just use timezone.timedelta?
        return timedelta(*a, **kw)

    def walk(self, into_past=0, into_future=0):
        """
        Walk over a date range and create new instances of self with new ranges.
        """
        walked_range = []
        for shift in range(-into_past, into_future):
            kwargs = dict(drip_model=self.drip_model,
                          now_shift_kwargs={'days': shift})
            walked_range.append(self.__class__(**kwargs))
        return walked_range

    def apply_queryset_rules(self, qs):
        """
        First collect all filter/exclude kwargs and apply any annotations.
        Then apply all filters at once, and all excludes at once.
        """
        clauses = {
            'filter': [],
            'exclude': []}

        for rule in self.drip_model.queryset_rules.all():

            clause = clauses.get(rule.method_type, clauses['filter'])

            kwargs = rule.filter_kwargs(qs, now=self.now)
            clause.append(Q(**kwargs))

            qs = rule.apply_any_annotation(qs)

        if clauses['exclude']:
            qs = qs.exclude(functools.reduce(operator.or_, clauses['exclude']))
        qs = qs.filter(*clauses['filter'])

        return qs

    ##################
    ### MANAGEMENT ###
    ##################

    def get_queryset(self):
        try:
            return self._queryset
        except AttributeError:
            self._queryset = self.apply_queryset_rules(self.queryset()).distinct()
            return self._queryset

    def run(self):
        """
        Get the queryset, prune sent people, and send it.
        """
        self.prune()
        count = self.send()
        return count

    def prune(self):
        """
        Do an exclude for all Users who have a SendDrip already.
        """
        target_user_ids = self.get_queryset().values_list('id', flat=True)
        exclude_user_ids = SendDrip.objects.filter(date__lt=timezone.now(),
                                                   drip=self.drip_model,
                                                   user__id__in=target_user_ids)\
                                           .values_list('user_id', flat=True)
        self._queryset = self.get_queryset().exclude(id__in=exclude_user_ids)

    def send(self):
        """
        Send the message to each user on the queryset.

        Create SendDrip for each user that gets a message.

        Returns count of created SentDrips.
        """

        if not self.from_email:
            self.from_email = getattr(settings, 'DRIP_FROM_EMAIL', settings.DEFAULT_FROM_EMAIL)
        MessageClass = message_class_for(self.drip_model.message_class)

        count = 0
        for user in self.get_queryset():
            message_instance = MessageClass(self.drip_model, user)
            try:
                result = message_instance.message.send()
                if result:
                    SendDrip.objects.create(drip=self.drip_model, user=user, sent=True)
                    count += 1
            except Exception as e:
                logging.error("Failed to send drip %s to user %s: %s" % (self.drip_model.id, user, e))

        return count

    ####################
    ### USER DEFINED ###
    ####################

    def queryset(self):
        """
        Returns a queryset of auth.User who meet the
        criteria of the drip.

        Alternatively, you could create Drips on the fly
        using a queryset builder from the admin interface...
        """
        return get_user_model().objects


class HandleDrip(HandleBase):

    def get_sequence_user_ids(self):
        # Gets all the user_ids that are active and are within the timeframe to receive this drip
        sequence = self.drip_model.sequence
        now = timezone.now()
        delay = self.drip_model.delay

        lt = now-djangotimedelta.parse(delay)
        gte = lt - djangotimedelta.parse('1 days')

        user_ids = sequence.subscribers.filter(
            is_active=True,
            sequence_date__gte=gte,
            sequence_date__lt=lt
        ).values_list('user_id', flat=True)
        return user_ids

    def get_parent_sent_user_ids(self):
        now = timezone.now()
        parent_opened_required = self.drip_model.parent_opened
        #parent_clicked_required = self.drip_model.parent_clicked
        parent = self.drip_model.parent
        user_ids = None

        lt = now-djangotimedelta.parse(self.drip_model.delay)
        gte = lt - djangotimedelta.parse('1 days')
        # get users who received parent drip 'delay' days ago
        # (e.g. if drip.delay is 3, it'll get all users who received the parent drip 3 days ago
        # We only want SendDrips that have been sent.
        # A SendDrip's date gets a new timestamp when it's successfully sent.
        if parent_opened_required is None:

            user_ids = parent.send_drips.filter(sent=True,
                                                date__gte=gte,
                                                date__lt=lt,
                                                ).values_list('user_id', flat=True)
        else:
            parent_open_ids = Open.objects.filter(sentdrip__drip_id=parent.id).values_list('id', flat=True)
            if parent_opened_required is True:
                user_ids = parent.send_drips\
                    .filter(sent=True)\
                    .filter(open__in=parent_open_ids)\
                    .filter(date__gte=gte,
                            date__lt=lt
                            ).values_list('user_id', flat=True)
            elif parent_opened_required is False:
                user_ids = parent.send_drips\
                    .exclude(open__in=parent_open_ids)\
                    .filter(sent=True)\
                    .filter(date__gte=gte,
                            date__lt=lt
                            ).values_list('user_id', flat=True)
        return user_ids

    def get_queryset(self):
        try:
            return self._queryset
        except AttributeError:
            drip = self.drip_model
            sequence_id = drip.sequence_id
            parent_id = drip.parent_id

            if sequence_id and parent_id:
                # Retrieve all who are on the sequence and have received the parent drip x delay (days) ago
                seq_mailing_list_id = self.drip_model.sequence.mailinglist_id
                users_queryset = self.queryset()\
                    .filter(squeeze_subscriptions__mailinglist_id=seq_mailing_list_id)\
                    .filter(squeeze_subscriptions__sequence_id=sequence_id)\
                    .filter(squeeze_subscriptions__is_active=True)\
                    .filter(id__in=self.get_parent_sent_user_ids())
            elif sequence_id:
                seq_mailing_list_id = self.drip_model.sequence.mailinglist_id
                users_queryset = self.queryset()\
                    .filter(squeeze_subscriptions__mailinglist_id=seq_mailing_list_id)\
                    .filter(squeeze_subscriptions__sequence_id=sequence_id)\
                    .filter(squeeze_subscriptions__is_active=True)\
                    .filter(id__in=self.get_sequence_user_ids())
            elif parent_id:
                users_queryset = self.queryset()\
                    .filter(squeeze_subscriptions__is_active=True)\
                    .filter(id__in=self.get_parent_sent_user_ids())
            else:
                # If no sequence or parent selected, we grab ALL users, even those not on a mailing list.
                # Use the admin queryset to filter/exclude what you need.
                users_queryset = self.queryset()

            #
            # # If they have a drip parent, we should delay off of that by default
            # if self.drip_model.parent:
            #     users_queryset = self.queryset().filter(id__in=self.get_parent_sent_user_ids())
            # elif self.drip_model.sequence:
            #     users_queryset = self.queryset().filter(id__in=self.get_sequence_user_ids())
            # else:
            #     users_queryset = self.queryset()  # if no parent or sequence, it's a broadcast, so get all subscribers
            self._queryset = self.apply_queryset_rules(users_queryset).distinct()
            return self._queryset

    def run(self):
        """
        Everything starts here.

        1) Get the queryset (based off of self.queryset())
        2) Prune/remove user ids from queryset that have an existing senddrip already
        3) create an unsent SendDrip for all users on queryset
        4) Retrieve all unsent SendDrips for this drip and queue it in celery for sending.

        Steps 1-3's whole purpose is to create SendDrips (with sent=False) that need to be created for the drip.
        All step 4 does is retrieve all the SendDrips that still need to be sent. It doesn't even care about
        what step 1-3 did, it just grabs a new queryset of this drip's SendDrips that still need to be sent out.

        This is so if your celery queue unknowingly craps out for 24+ hours, you'll still have this thing
        running and creating a database "queue" essentially, but SendDrip objects are never deleted because they
        contain info on who got what and when. Our priority is to not send a user an email more than once,
        and we look for that in both the initial creation of a senddrip AND in the celery task.
        """
        self.prune()
        self.create_unsent_drips()
        return self.queue_emails()

    def prune(self):
        """
        Do an exclude for all Users who have a SendDrip already.
        """
        target_user_ids = self.get_queryset().values_list('id', flat=True)

        exclude_user_ids = SendDrip.objects.filter(drip=self.drip_model,
                                                   user__id__in=target_user_ids
                                                   ).values_list('user_id', flat=True)
        self._queryset = self.get_queryset().exclude(id__in=exclude_user_ids)

    def create_unsent_drips(self):
        """
        Create SendDrip objects for every user_id in the queryset. SendDrip.sent is False by default.
        If your celery/redis/whatever unknowingly dies for 24+ hours, this is a way to know who still needs to receive
        this drip.
        """
        drip_id = self.drip_model.id
        user_id_list = self.get_queryset().values_list('id', flat=True)

        if self.drip_model.parent_id:  # Check if this drip has a parent
            for user_id in user_id_list:
                # If there's a SendDrip that has the same parent, it means they're already on a set path.
                # We don't want to send them a drip for them not opening, then a dif drip for when they do open it.
                try:
                    sentdrip = SendDrip.objects.get(user_id=user_id, drip__parent_id=self.drip_model.parent_id)
                except SendDrip.DoesNotExist:
                    sentdrip = SendDrip.objects.create(user_id=user_id, drip_id=self.drip_model.id)

        else:
            for user_id in user_id_list:
                try:
                    sentdrip = SendDrip.objects.create(drip_id=drip_id, user_id=user_id)
                except Exception as e:
                    logger.warning("Failed to create SendDrip for user_id %i & drip_id %i. (%r)", user_id, drip_id, e)

    def queue_emails(self, **kwargs):
        result_tasks = []
        kwargs['drip_id'] = self.drip_model.id
        # Get a fresh list of all user IDs that haven't received this drip yet.
        user_id_list = SendDrip.objects.filter(drip_id=self.drip_model.id, sent=False).values_list('user_id', flat=True)
        chunk_size = CELERY_EMAIL_CHUNK_SIZE
        for chunk in chunked(user_id_list, chunk_size):
            result_tasks.append(send_drip.delay(chunk, **kwargs))
        logging.info('drips queued')
        return result_tasks

    def queryset(self):
        """
        Returns a queryset of auth.User who meet the
        criteria of the drip.

        IMPORTANT: If no sequence is set, it's assumed to be a broadcast email and sends to all users (whether they have
        a subscription or not). This is so you can broadcast a single email to a specific mailing list by adding
        'subscription__mailinglist_name' with the proper field value in the drip's queryset.
        """
        return get_user_model().objects


class HandleDrop(HandleBase):
    """
    Sends a single drip email to a user. Built initially to send a welcome email.
    """

    def __init__(self, drip_model, user, *args, **kwargs):
        self.drip_model = drip_model
        self.user = user

        if not self.user:
            raise AttributeError('You must define a user')

        self.now_shift_kwargs = kwargs.get('now_shift_kwargs', {})

    def run(self):
        """
        Get the queryset, prune sent people, and send it.

        We don't check if the drip is enabled here because
        this will mainly be for sending our single drips to
        a single user, enabled or not.
        """

        self.prune()
        count = self.send()

        return count

    def queryset(self):
        """
        Returns a queryset of auth.User who meet the
        criteria of the drip.

        Alternatively, you could create Drips on the fly
        using a queryset builder from the admin interface...
        """
        users = get_user_model().objects.filter(id=self.user.id)
        return users


def send_drop(user, drip_name):
    """
    Sends a single drip to a single user.
    Mostly used to send a welcome email after a user subscribes to the newsletter.

    The 'name' is required for some reason. The only requirement is that it exists, it seems.
    It has nothing to do with getting any object.
    """
    drip = Drip.objects.get(name=drip_name) #get drip
    return HandleDrop(drip_model=drip, user=user).run() #prunes and sends to user


class ReSendDrop(HandleDrop):
    """
    This will ignore any filters or if they've already received this email before.
    If someone emails asking for a lost email, this is what to use to re-send it to them.
    """

    def get_queryset(self):
        try:
            return self._queryset
        except AttributeError:
            self._queryset = self.queryset()
            return self._queryset

    def send(self):
        """
        Send the message to each user on the queryset. (should filter down to only 1 user)

        No SentDrip is created for the user since we assume the email has been sent in the past already.

        Returns count of created SentDrips. (should just be 1)
        """

        if not self.from_email:
            self.from_email = getattr(settings, 'DRIP_FROM_EMAIL', settings.DEFAULT_FROM_EMAIL)
        MessageClass = message_class_for(self.drip_model.message_class)

        count = 0

        for user in self.get_queryset():
            message_instance = MessageClass(self, user)
            result = message_instance.message.send()
            if result:
                count += 1

        return count

    def run(self):
        """
        Just send it. We don't care to prune or check if they've already received it or if they're active.
        """
        count = self.send()
        return count


def send_drop_to_email(email, drip_name):
    """
    Slightly simpler way to send a drop to an email without needing to pass the user
    """
    user = get_user_model().objects.get(email=email)
    welcome_email = Drip.objects.get(name=drip_name)
    return ReSendDrop(drip_model=welcome_email, user=user).run()