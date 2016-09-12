#from datetime import datetime, timedelta

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from django.db import models
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.conf import settings
from django.utils.functional import cached_property

from django.utils import timezone

# from feincms.models import create_base_model
# just using this to parse, but totally insane package naming...
# https://bitbucket.org/schinckel/django-timedelta-field/
import timedelta as djangotimedelta

# from mptt.fields import TreeForeignKey
# from mptt.models import MPTTModel
from squeezemail import DRIP_HANDLER
from squeezemail import SUBSCRIBER_MANAGER
#from squeezemail.handlers import send_drop
from squeezemail.utils import class_for

from mptt.models import MPTTModel, TreeForeignKey
from content_editor.models import (
    Template, Region, create_plugin_base
)
from feincms3 import plugins


STATUS_CHOICES = (
    ('draft', 'Draft'),
    ('paused', 'Paused'),
    ('active', 'Active'),
)

METHOD_TYPES = (
    ('filter', 'Filter'),
    ('exclude', 'Exclude'),
)

LOOKUP_TYPES = (
    ('exact', 'exactly'),
    ('iexact', 'exactly (case insensitive)'),
    ('contains', 'contains'),
    ('icontains', 'contains (case insensitive)'),
    ('regex', 'regex'),
    ('iregex', 'contains (case insensitive)'),
    ('gt', 'greater than'),
    ('gte', 'greater than or equal to'),
    ('lt', 'less than'),
    ('lte', 'less than or equal to'),
    ('startswith', 'starts with'),
    ('endswith', 'starts with'),
    ('istartswith', 'ends with (case insensitive)'),
    ('iendswith', 'ends with (case insensitive)'),
)

STEP_TYPES = (
    ('path', 'Path'),
    ('action', 'Action'),
    ('decision', 'Decision'),
)


# class Funnel(models.Model):
#     pass


limit = models.Q(app_label='squeezemail', model='decision') | models.Q(app_label='squeezemail', model='delay')


class Step(MPTTModel):
    parent = TreeForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children', db_index=True)
    description = models.CharField(max_length=75, null=True, blank=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, limit_choices_to=limit)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')

    def __str__(self):
        return "%s" % self.description

    def run(self):
        # get all subscriptions on this step who are active
        qs = self.subscriptions.filter(is_active=True)
        # get what this step needs to do (e.g. decision)
        t = self.content_object
        ret = t.run(self, qs)
        return ret


# StepPlugin = create_plugin_base(Step)


class Delay(models.Model):
    delay = models.CharField(default='1 days', max_length=255)

    def __str__(self):
        return "Delay: %s" % self.delay

    def run(self, step, qs):
        next_step = step.get_children()[0]
        #get all subscriptions that landed on the step over 'delay' days ago, then assign them to the next step
        for subscription in qs:
            subscription.step_id = next_step.id
        return qs


class Decision(models.Model):
    description = models.CharField(max_length=75, null=True, blank=True)
    on_true = models.ForeignKey('squeezemail.Step', null=True, blank=True, related_name='decision_on_true')
    on_false = models.ForeignKey('squeezemail.Step', null=True, blank=True, related_name='decision_on_false')
    # date = models.DateTimeField(auto_now_add=True)
    # lastchanged = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Decision: %s" % self.description

    def run(self, step, qs):
        qs_rules = self.queryset_rules.all()
        qs_filtered = qs
        for rule in qs_rules:
            qs_filtered = rule.apply(qs_filtered)

        #TODO: qs_excluded will be assigned to on_false step

        for subscription in qs_filtered:
            subscription.step_id = self.on_true_id
            subscription.save()

        return qs


# class DecisionTrue(models.Model):
#     pass


class DripSubject(models.Model):
    drip = models.ForeignKey('squeezemail.Drip', related_name='subjects')
    text = models.CharField(max_length=150)
    enabled = models.BooleanField(default=True)


class Drip(MPTTModel):
    TYPE_CHOICES = (
        ('drip', 'Drip'),
        ('broadcast', 'Broadcast'),
    )
    parent = TreeForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True, blank=True, related_name='children', db_index=True)
    regions = [
        Region(key='body', title='Main Body'),
        # Region(key='split_test', title='Split Test Body',
        #        inherited=False),
    ]
    date = models.DateTimeField(auto_now_add=True)
    lastchanged = models.DateTimeField(auto_now=True)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='drip',
                            help_text="'Broadcast' drips will only send one time, and WILL SEND TO ALL USERS, whether "
                                      "or not they're on a mailing list or sequence delay fields. Use the queryset to"
                                      "filter/exclude which users will receive broadcast emails. "
                                      "Broadcast completely ignores sequence, parent, mailing list fields."
                                      "Choose 'Drip' for normal drips.")
    campaign = models.ForeignKey('squeezemail.Campaign', related_name='drips', blank=True, null=True, help_text="IMPORTANT: Choose a sequence even if a parent is selected. If no sequence is selected, it's assumed to be a broadcast email and will ONLY filter off the queryset you select below. If left empty, it grabs ALL users by default, even those who are not on a mailing list.")

    # parent_opened = models.NullBooleanField(help_text="Only send to users who opened parent drip. True will only send to users who opened parent drip, False will only send to users who didn't. Choose Null if this isn't applicable to your drip.")
    # parent_clicked = models.NullBooleanField(help_text="Only send to users who clicked a link in parent drip's body content. True will only send to users who clicked parent drip, False will only send to users who didn't. Choose Null if this isn't applicable to your drip.")

    delay = models.CharField(default=1, max_length=255, verbose_name="Day Delay", help_text="Delay in how many days from when the "
                                                                               "subscriber started their current "
                                                                               "sequence. 0 is same day (immediate), 1 "
                                                                               "is one day old before sending. If a "
                                                                               "parent is selected, delays off of when "
                                                                               "the parent drip was sent to the user instead."
                                                                               "Use 1 (or more) if a parent is selected, "
                                                                               "otherwise they'll get 2 emails in 1 day.")
    name = models.CharField(
        max_length=255,
        #unique=True,
        verbose_name='Drip Name',
        help_text='A unique name for this drip.')

    send_after = models.DateTimeField(blank=True, null=True)
    broadcast_sent = models.BooleanField(default=False, help_text="Only used for 'Broadcast' type emails.")
    enabled = models.BooleanField(default=False)

    note = models.TextField(max_length=255, null=True, blank=True, help_text="This is only seen by staff.")

    from_email = models.EmailField(null=True, blank=True,
        help_text='Set a custom from email.')
    from_email_name = models.CharField(max_length=150, null=True, blank=True,
        help_text="Set a name for a custom from email.")
    message_class = models.CharField(max_length=120, blank=True, default='default')

    # class Meta:
    #     unique_together = ('name', 'sequence')
        #ordering = ['tree_id', 'lft']

    @property
    def handler(self):
        handler_class = class_for(DRIP_HANDLER)
        handler = handler_class(drip_model=self)
        return handler

    def __str__(self):
        return "%s [Day %s]" % (self.name, self.delay)

    @cached_property
    def subject(self):
        return self.choose_split_test_subject.text

    @cached_property
    def get_split_test_subjects(self):
        return self.subjects.filter(enabled=True)

    @cached_property
    def split_subject_active(self):
        return self.get_split_test_subjects.count() > 1

    @cached_property
    def choose_split_test_subject(self):
        # Return a subject object to be able to get the subject text and the subject id
        random_subject = self.subjects.filter(enabled=True).order_by('?')[0]
        return random_subject

    def get_split_test_body(self):
        pass


class SendDrip(models.Model):
    """
    Keeps a record of all sent drips.
    Has OneToOne relations for open, click, spam, unsubscribe. Calling self.opened will return a boolean.
    If it exists, it returns True, and you can assume it has been opened.
    This is done this way to save database space, since the majority of sentdrips won't even be opened, and to add extra
    data (such as timestamps) to filter off, so you could see your open rate for a drip within the past 24 hours.
    """
    date = models.DateTimeField(auto_now_add=True)
    drip = models.ForeignKey('squeezemail.Drip', related_name='send_drips')
    subscriber = models.ForeignKey('squeezemail.Subscriber', related_name='send_drips')
    sent = models.BooleanField(default=False)

    class Meta:
        unique_together = ('drip', 'subscriber')

    @property
    def opened(self):
        return hasattr(self, 'open')

    @property
    def clicked(self):
        return hasattr(self, 'click')

    @property
    def spammed(self):
        return hasattr(self, 'spam')

    @property
    def unsubscribed(self):
        return hasattr(self, 'unsubscribe')


class Open(models.Model):
    sentdrip = models.OneToOneField(SendDrip)
    date = models.DateTimeField(auto_now_add=True)


class Click(models.Model):
    sentdrip = models.OneToOneField(SendDrip)
    date = models.DateTimeField(auto_now_add=True)


class Spam(models.Model):
    sentdrip = models.OneToOneField(SendDrip)
    date = models.DateTimeField(auto_now_add=True)


class Unsubscribe(models.Model):
    sentdrip = models.OneToOneField(SendDrip)
    date = models.DateTimeField(auto_now_add=True)


class QuerySetRule(models.Model):
    date = models.DateTimeField(auto_now_add=True)
    lastchanged = models.DateTimeField(auto_now=True)

    decision = models.ForeignKey('squeezemail.Decision', related_name='queryset_rules')

    drip = models.ForeignKey('squeezemail.Drip', related_name='queryset_rules')

    method_type = models.CharField(max_length=12, default='filter', choices=METHOD_TYPES)
    field_name = models.CharField(max_length=128, verbose_name='Field name of Subscriber')
    lookup_type = models.CharField(max_length=12, default='exact', choices=LOOKUP_TYPES)

    field_value = models.CharField(max_length=255,
        help_text=('Can be anything from a number, to a string. Or, do ' +
                   '`now-7 days` or `today+3 days` for fancy timedelta.'))

    def clean(self):
        User = get_user_model()
        try:
            self.apply(User.objects.all())
        except Exception as e:
            raise ValidationError(
                '%s raised trying to apply rule: %s' % (type(e).__name__, e))

    @property
    def annotated_field_name(self):
        field_name = self.field_name
        if field_name.endswith('__count'):
            agg, _, _ = field_name.rpartition('__')
            field_name = 'num_%s' % agg.replace('__', '_')

        return field_name

    def apply_any_annotation(self, qs):
        if self.field_name.endswith('__count'):
            field_name = self.annotated_field_name
            agg, _, _ = self.field_name.rpartition('__')
            qs = qs.annotate(**{field_name: models.Count(agg, distinct=True)})
        return qs

    def filter_kwargs(self, qs, now=timezone.now):
        # Support Count() as m2m__count
        field_name = self.annotated_field_name
        field_name = '__'.join([field_name, self.lookup_type])
        field_value = self.field_value

        # set time deltas and dates
        if self.field_value.startswith('now-'):
            field_value = self.field_value.replace('now-', '')
            field_value = now() - djangotimedelta.parse(field_value)
        elif self.field_value.startswith('now+'):
            field_value = self.field_value.replace('now+', '')
            field_value = now() + djangotimedelta.parse(field_value)
        elif self.field_value.startswith('today-'):
            field_value = self.field_value.replace('today-', '')
            field_value = now().date() - djangotimedelta.parse(field_value)
        elif self.field_value.startswith('today+'):
            field_value = self.field_value.replace('today+', '')
            field_value = now().date() + djangotimedelta.parse(field_value)

        # F expressions
        if self.field_value.startswith('F_'):
            field_value = self.field_value.replace('F_', '')
            field_value = models.F(field_value)

        # set booleans
        if self.field_value == 'True':
            field_value = True
        if self.field_value == 'False':
            field_value = False

        kwargs = {field_name: field_value}

        return kwargs

    def apply(self, qs, now=timezone.now):

        kwargs = self.filter_kwargs(qs, now)
        qs = self.apply_any_annotation(qs)

        if self.method_type == 'filter':
            return qs.filter(**kwargs)
        elif self.method_type == 'exclude':
            return qs.exclude(**kwargs)

        # catch as default
        return qs.filter(**kwargs)


class SubscriberManager(models.Manager):
    """
    Custom manager for Subscriber to provide extra functionality
    """
    use_for_related_fields = True

    def get_or_add(self, email, optin_list, **kwargs):
        """
        Gets a subscriber
        If subscriber doesn't exist, get an existing user by email
        if user doesn't exist, create a newsletter only user and subscribe them to the newsletter group
        """
        # mailinglist = MailingList.objects.get(name=optin_list)
        campaign = Campaign.objects.get(name=optin_list)

        try:
            #Try to get existing subscriber to this group
            subscriber = self.get(user__email=email)
        except self.model.DoesNotExist:
            from squeezemail.handlers import send_drop
            User = get_user_model()
            try:
                # Subscriber doesn't exist, so try to get an existing user by email
                user = User.objects.get(email=email)
            except ObjectDoesNotExist:
                #User doesn't exist, so create a newsletter only user
                user = User.objects.create_newsletter_user(email=email, **kwargs)

            #create a subscriber, being sure to get the most accurate time is absolutely required
            subscriber = self.create(user=user)
            # subscription = CampaignSubscription.objects.get
            # Email welcome email to only newly created subscriber
            send_drop(user=subscriber.user, drip_name="Newsletter Welcome Email")
        return subscriber

    def active(self):
        """
        Gives only the active subscribers
        """
        return self.filter(is_active=True)


subscriber_manager = class_for(SUBSCRIBER_MANAGER)()
#subscriber_manager = SubscriberManager()


class Campaign(models.Model):
    status = models.CharField(max_length=15, choices=STATUS_CHOICES)
    name = models.CharField(max_length=150)
    from_name = models.CharField(max_length=100)
    from_email = models.CharField(max_length=100)
    # send_on_days
    start_now = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def email_count(self):
        # How many drips/emails this campaign has
        return self.drips.count()

    def active_subscriber_count(self):
        return self.subscribers.filter(is_active=True)

    def unsubscribed_subscriber_count(self):
        return

    def email_open_rate(self):
        return

    def email_click_rate(self):
        return


class Subscriber(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, related_name="squeeze_subscriber")
    is_active = models.BooleanField(verbose_name="Active", default=True)
    created = models.DateTimeField(auto_now_add=True)

    # current_step = models.ForeignKey('squeezemail.Step')

    objects = subscriber_manager
    default_manager = subscriber_manager

    def __str__(self):
        return self.user.email

    def unsubscribe(self):
        if self.is_active:
            self.is_active = False
            self.unsubscribe_date = timezone.now()
            self.save()
        return

    # def move_to_campaign(self, campaign_pk):
    #     self.campaign_id = sequence_pk
    #     self.sequence_date = timezone.now()
    #     self.save()
    #     return

    def opened_email(self, drip):
        return self.send_drips.get(id=drip.id).opened


class Subscription(models.Model):
    campaign = models.ForeignKey('squeezemail.Campaign', related_name="subscriptions")
    subscriber = models.ForeignKey('squeezemail.Subscriber', related_name="subscriptions")
    subscribe_date = models.DateTimeField(verbose_name="Subscribe Date", default=timezone.now)
    is_active = models.BooleanField(verbose_name="Active", default=True)
    is_complete = models.BooleanField(default=False)
    # lap = models.IntegerField(default=1)
    last_send_drip = models.ForeignKey('squeezemail.SendDrip')
    step = models.ForeignKey('squeezemail.Step', related_name="subscriptions")


# class Subscriber(models.Model):
#     user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="squeeze_subscriptions")
#     mailinglist = models.ForeignKey('squeezemail.MailingList', related_name='subscribers')
#     sequence = models.ForeignKey('squeezemail.Sequence', related_name='subscribers', null=True, blank=True)
#     sequence_date = models.DateTimeField(verbose_name="Started Sequence Date", default=timezone.now, null=True, blank=True)
#     subscribe_date = models.DateTimeField(verbose_name="Subscribe Date", default=timezone.now)
#     unsubscribe_date = models.DateTimeField(verbose_name="Unsubscribe Date", null=True, blank=True)
#     is_active = models.BooleanField(verbose_name="Active", default=True)
#
#     objects = subscriber_manager
#     default_manager = subscriber_manager
#
#     class Meta:
#         verbose_name = "Subscriber"
#         verbose_name_plural = "Subscribers"
#         unique_together = ('user', 'sequence')
#
#     def __str__(self):
#         return self.user.email
#
#     def unsubscribe(self):
#         if self.is_active:
#             self.is_active = False
#             self.unsubscribe_date = timezone.now()
#             # if self.user.optin is True:
#             #     self.user.optin = False
#             #     self.user.save()
#             self.save()
#         return
#
#     def move_to_sequence(self, sequence_pk):
#         self.sequence_id = sequence_pk
#         self.sequence_date = timezone.now()
#         self.save()
#         return


# class Funnel(MPTTModel):
#     parent = TreeForeignKey(
#         'self',
#         on_delete=models.CASCADE,
#         null=True, blank=True, related_name='children', db_index=True)
#     name = models.TextField() #Main Funnel
#     status = models.TextField(choices=STATUS_CHOICES, default='draft') #active, draft, paused, all...?
#     created = models.DateTimeField(auto_now_add=True)
    # subscriber
    # drip
    # tags
    # prospect #boolean
#
#
# class Action(models.Model):
#     label = models.TextField()
#
#
# class Event(models.Model):
#     subscriber = models.ForeignKey(settings.AUTH_USER_MODEL, related_name="events")
#     action = models.ForeignKey('squeezemail.Action')
#     occurred_at = models.DateTimeField(auto_now_add=True)



DripPlugin = create_plugin_base(Drip)


class RichText(plugins.RichText, DripPlugin):
    pass
