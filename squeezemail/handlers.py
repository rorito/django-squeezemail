import sys
import logging

import html2text
from django.utils.safestring import mark_safe

from squeezemail.renderer import renderer

PY3 = sys.version_info > (3, 0)
import re
if PY3:
    from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl
else:
    from urlparse import urlparse, urlunparse, parse_qsl
    from urllib import urlencode
from django.conf import settings
from django.core.urlresolvers import reverse
from django.template import Context, Template
from django.template.loader import render_to_string
from django.utils.functional import cached_property
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags
from django.contrib.sites.models import Site
try:
    # Django >= 1.9
    from django.utils.module_loading import import_module
except ImportError:
    from django.utils.importlib import import_module
from content_editor.contents import contents_for_item
from content_editor.renderer import PluginRenderer
from .utils import get_token_for_user
from . import SQUEEZE_CELERY_EMAIL_CHUNK_SIZE, SQUEEZE_DEFAULT_HTTP_PROTOCOL
from .tasks import send_drip
from .models import SendDrip, Subscriber, RichText, Image
from .utils import chunked


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

    def __init__(self, drip, subscriber):
        self.drip = drip
        self.subscriber = subscriber
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

    def render_body(self):
        # import the custom renderer and do renderer.plugins() instead
        contents = contents_for_item(self.drip, plugins=[Image, RichText])
        # assert False, contents['body']
        body = renderer.render(contents['body']) #TODO: get split test feincms content here
        return body

    @property
    def context(self):
        if not self._context:
            user_token = self.get_user_token
            context = Context({
                'subscriber': self.subscriber,
                'user': self.subscriber.user,
                'drip': self.drip,
                'user_token': user_token,
                })
            context['content'] = mark_safe(self.replace_urls(Template(self.render_body()).render(context)))
            self._context = context
        return self._context

    @cached_property
    def subject_model(self):
        return self.drip.choose_split_test_subject

    @property
    def subject(self):
        if not self._subject:
            self._subject = Template(self.subject_model.text).render(self.context)
        return self._subject

    @property
    def body(self):
        if not self._body:
            self._body = render_to_string('squeezemail/body.html', self.context)
        return self._body

    @property
    def plain(self):
        if not self._plain:
            h = html2text.HTML2Text()
            h.ignore_images = True
            self._plain = h.handle(self.body)
        return self._plain

    @property
    def message(self):
        if not self._message:
            self._message = EmailMultiAlternatives(self.subject, self.plain, self.from_email, [self.subscriber.user.email])
            self._message.attach_alternative(self.body, 'text/html')
        return self._message

    def replace_urls(self, content):
        offset = 0
        for match in HREF_RE.finditer(content):
            link = match.group(1)
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
        site_domain = Site.objects.get_current().domain
        parsed_url = urlparse(raw_url)

        if parsed_url.netloc is '':
            # stick the scheme and netloc in the url if it's missing. This is so urls aren't just '/sublocation/'
            parsed_url = parsed_url._replace(scheme=SQUEEZE_DEFAULT_HTTP_PROTOCOL, netloc=site_domain)

        url_params = dict(parse_qsl(parsed_url.query))

        target_url = parsed_url._replace(query='')

        # where the user will be redirected to after clicking this link
        url_params['sq_target'] = urlunparse(target_url)

        # add user_id and drip_id to the params
        url_params.update(self.extra_url_params())

        parsed_url_list = list(parsed_url)
        parsed_url_list[4] = urlencode(url_params)

        new_url = urlparse('')._replace(
            scheme=SQUEEZE_DEFAULT_HTTP_PROTOCOL,
            netloc=site_domain,
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
            'sq_subscriber_id': self.subscriber.id,
            'sq_drip_id': self.drip.id,
            'sq_user_token': self.get_user_token,
            'sq_subject_id': self.subject_model.id
        }
        return params

    @property
    def get_user_token(self):
        if not self._user_token:
            self._user_token = str(get_token_for_user(self.subscriber.user))
        return self._user_token


class HandleDrip(object):
    """
    A base object for defining a Drip.
    You can extend this manually and set it as your default drip handler class.
    """
    def __init__(self, *args, **kwargs):
        self.drip_model = kwargs.get('drip_model')
        self._queryset = kwargs.get('queryset')
        self.step = kwargs.get('step', None)

    def get_queryset(self):
        if not self._queryset:
            self._queryset = self.queryset()
        return self._queryset

    def queryset(self):
        """
        If there was no queryset passed in, our queryset is all active subscribers with our custom
        queryset rules applied to it (if the drip has any).
        """
        base_qs = Subscriber.objects.filter(is_active=True)
        qs = self.drip_model.apply_queryset_rules(base_qs).distinct()
        return qs

    def apply_queryset_rules(self):
        return

    def step_run(self):
        self.create_unsent_drips()
        next_step = self.step.get_next_step()
        if next_step:
            results = self.create_tasks_for_unsent_drips(next_step_id=next_step.id)
        else:
            results = self.create_tasks_for_unsent_drips()
        return results

    def campaign_run(self):
        return

    def broadcast_run(self):
        self.create_unsent_drips()
        results = self.create_tasks_for_unsent_drips()
        return results

    def create_unsent_drips(self):
        """
        Create SendDrip objects for every subscriber_id in the queryset, which is how we avoid sending the same drip to
        a subscriber more than once.
        """
        drip_id = self.drip_model.id
        subscriber_id_list = self.get_queryset().values_list('id', flat=True)

        for subscriber_id in subscriber_id_list:
            try:
                sentdrip = SendDrip.objects.create(drip_id=drip_id, subscriber_id=subscriber_id, sent=False)
            except Exception as e:
                logger.warning("Failed to create SendDrip for subscriber_id %i & drip_id %i. (%r)", subscriber_id, drip_id, e)
        return

    def create_tasks_for_unsent_drips(self, **kwargs):
        """
        Grab all of the SendDrips that haven't been sent yet, and queue up some celery tasks for them.
        """
        result_tasks = []
        kwargs['drip_id'] = self.drip_model.id
        # Get a fresh list of all user IDs that haven't received this drip yet.
        subscriber_id_list = SendDrip.objects.filter(drip_id=self.drip_model.id, sent=False).values_list('subscriber_id', flat=True)
        chunk_size = SQUEEZE_CELERY_EMAIL_CHUNK_SIZE
        for chunk in chunked(subscriber_id_list, chunk_size):
            result_tasks.append(send_drip.delay(chunk, **kwargs))
        logging.info('drips queued')
        return result_tasks
