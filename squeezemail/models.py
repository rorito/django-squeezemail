import functools
import operator
import logging
# from collections import OrderedDict
from _md5 import md5

from cte_forest.models import CTENode
from cte_forest.fields import DepthField, PathField, OrderingField
from django.db.models import Q
from gfklookupwidget.fields import GfkLookupField
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from django.db import models
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.conf import settings
from django.utils.functional import cached_property
from django.core.cache import cache
from django.utils import timezone

# just using this to parse, but totally insane package naming...
# https://bitbucket.org/schinckel/django-timedelta-field/
import timedelta as djangotimedelta
# from mptt.models import MPTTModel

from squeezemail import SQUEEZE_DRIP_HANDLER
from squeezemail import SQUEEZE_PREFIX
from squeezemail import SQUEEZE_SUBSCRIBER_MANAGER
from squeezemail.utils import class_for

# from mptt.models import MPTTModel, TreeForeignKey
from content_editor.models import (
    Template, Region, create_plugin_base
)
from feincms3 import plugins

logger = logging.getLogger(__name__)

LOCK_EXPIRE = (60 * 60) * 24

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


class Funnel(models.Model):
    name = models.CharField(max_length=75)
    entry_step = models.ForeignKey('squeezemail.Step', related_name='funnels')
    subscribers = models.ManyToManyField('squeezemail.Subscriber', through='FunnelSubscription', related_name='funnels')

    def __str__(self):
        return self.name

    def create_subscription(self, subscriber, ignore_previous_history=False, *args, **kwargs):
        """
        Add/create a subscriber to go down this funnel path.
        Won't go down the path if the subscriber has already been on it unless ignore_previous_history is True.
        """
        created = False
        if isinstance(subscriber, Subscriber):
            subscription, created = self.subscriptions.get_or_create(subscriber=subscriber)
        else:
            # Assume an email as a string has been passed in
            subscriber = Subscriber.objects.get_or_add(email=subscriber)
            subscription, created = self.subscriptions.get_or_create(subscriber=subscriber)
        if created or ignore_previous_history:
            subscriber.move_to_step(self.entry_step_id)
        return subscription


step_choices = models.Q(app_label='squeezemail', model='decision') |\
        models.Q(app_label='squeezemail', model='delay') |\
        models.Q(app_label='squeezemail', model='drip') |\
        models.Q(app_label='squeezemail', model='modify')


class Step(CTENode):
    description = models.CharField(max_length=75, null=True, blank=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, limit_choices_to=step_choices, null=True, blank=True)
    object_id = GfkLookupField('content_type', null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    is_active = models.BooleanField(verbose_name="Active", default=True, help_text="If not active, subscribers will still be allowed to move to this step, but this step won't run until it's active. Consider this a good way to 'hold' subscribers on this step. Note: Step children won't run either.")
    position = models.PositiveIntegerField(db_index=True, editable=False, default=0)

    _cte_node_path = 'cte_path'
    _cte_node_order_by = ('position',)

    def __str__(self):
        return "%s" % self.description if self.description else str(self.content_object)

    @cached_property
    def lock_id(self):
        hexdigest = md5(str(SQUEEZE_PREFIX).encode('utf-8') +
                str('step_').encode('utf-8') +
                str(self.id).encode('utf-8') +
                '_'.encode('utf-8')).hexdigest()
        return '{0}-lock-{1}'.format('step', hexdigest)

    def acquire_lock(self):
        return cache.add(self.lock_id, 'true', LOCK_EXPIRE)

    def release_lock(self):
        return cache.delete(self.lock_id)

    def run(self):
        if self.acquire_lock():
            # get all subscribers currently on this step who are active
            qs = self.subscribers.filter(is_active=True)
            # do what this step needs to do (e.g. decision)
            ret = self.content_object.step_run(self, qs)
            self.release_lock()
            return ret
        else:
            logger.debug('Step %i is already running', self.id)

    def get_next_step(self):
        next_step_exists = self.children.exists()
        return self.children.all()[0] if next_step_exists else None  # Only get 1 child.

    def get_active_subscribers_count(self):
        return self.subscribers.filter(is_active=True).count()


class Modify(models.Model):
    """
    Attempts to run the specified method of a class in the form of
    step_choice (e.g. step_remove), and passes the subscriber to it.
    Useful for adding/removing a tag,
    """
    MODIFY_CHOICES = (
        ('add', 'Add'),
        ('move', 'Move'),
        ('remove', 'Remove'),
    )
    modify_type = models.CharField(max_length=75, choices=MODIFY_CHOICES)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = GfkLookupField('content_type')
    content_object = GenericForeignKey('content_type', 'object_id')

    class Meta:
        verbose_name = 'Modify'
        verbose_name_plural = 'Modifications'

    def get_method_name(self):
        # Get the method name to run on the content_object (e.g. 'step_add')
        return 'step_%s' % self.modify_type

    def step_run(self, step, qs):
        method_name = self.get_method_name()
        content_object = self.content_object
        for subscriber in qs:
            method_call = getattr(content_object, method_name)(subscriber=subscriber)
        return qs

    def clean(self):
        try:
            getattr(self.content_object, self.get_method_name())
        except Exception as e:
            raise ValidationError(
                '%s does not have method name %s: %s' % (type(e).__name__, self.get_method_name(), e))


#TODO: Add Tag model


class Delay(models.Model):
    duration = models.DurationField(default=timezone.timedelta(days=1), help_text="The preferred format for durations in Django is '%d %H:%M:%S.%f (e.g. 3 00:40:00 for 3 day, 40 minute delay)'")
    # resume_on_days = models.IntegerField(max_length=7, default=1111111)

    def __str__(self):
        return "Delay: %s" % self.duration

    def step_run(self, step, qs):
        next_step = step.get_next_step()
        now = timezone.now()
        for subscriber in qs:
            if next_step:
                # goal_time = subscriber.step_timestamp + djangotimedelta.parse(self.delay)
                goal_time = subscriber.step_timestamp + self.duration
                # if goal time is greater than or equal to now, move on to the next step
                if goal_time <= now:
                    subscriber.move_to_step(next_step.id)
        return qs


class Decision(models.Model):
    description = models.CharField(max_length=75, null=True, blank=True)
    on_true = models.ForeignKey('squeezemail.Step', null=True, blank=True, related_name='step_decision_on_true+')
    on_false = models.ForeignKey('squeezemail.Step', null=True, blank=True, related_name='step_decision_on_false+')

    queryset_rules = GenericRelation(
        'squeezemail.QuerySetRule',
        content_type_field='content_type_id',
        object_id_field='object_id',
    )

    def __str__(self):
        return "Decision: %s" % self.description

    def apply_queryset_rules(self, qs):
        """
        First collect all filter/exclude kwargs and apply any annotations.
        Then apply all filters at once, and all excludes at once.
        """
        clauses = {
            'filter': [],
            'exclude': []}

        for rule in self.queryset_rules.all():

            clause = clauses.get(rule.method_type, clauses['filter'])

            kwargs = rule.filter_kwargs(qs)
            clause.append(Q(**kwargs))

            qs = rule.apply_any_annotation(qs)

        if clauses['exclude']:
            qs = qs.exclude(functools.reduce(operator.or_, clauses['exclude']))
        qs = qs.filter(*clauses['filter'])
        return qs

    def step_run(self, step, qs):

        qs_true = self.apply_queryset_rules(qs).distinct()

        true_ids = qs_true.values_list('id', flat=True)
        qs_false = qs.exclude(id__in=true_ids)
        if self.on_true_id:
            for subscriber in qs_true:
                subscriber.move_to_step(self.on_true_id)

        if self.on_false_id:
            for subscriber in qs_false:
                subscriber.move_to_step(self.on_false_id)
        return qs


class EmailActivity(models.Model):
    TYPE_CHOICES = (
        ('open', 'Opened'),
        ('click', 'Clicked'),
        ('spam', 'Reported Spam'),
    )
    type = models.CharField(max_length=75, choices=TYPE_CHOICES)
    check_last = models.IntegerField(help_text="How many previously sent drips/emails to check", default=1)
    on_true = models.ForeignKey('squeezemail.Step', null=True, blank=True, related_name='step_email_activity_on_true+')
    on_false = models.ForeignKey('squeezemail.Step', null=True, blank=True, related_name='step_email_activity_on_true+')

    def step_run(self, step, qs):
        subscriber_id_list = qs.values_list('id', flat=True)
        qs_true = False
        qs_false = False
        true_ids = []

        # Get all of the last SendDrips that our subscribers have been sent
        last_send_drip_id_list = SendDrip.objects.filter(subscriber_id__in=subscriber_id_list, sent=True)\
            .order_by('-date')[:self.check_last].values_list('id', flat=True)

        if self.type is 'open':
            # Get the last check_last Opens from the subscriber list
            opened_senddrip_id_list = Open.objects.filter(drip_id__in=last_send_drip_id_list).values_list('sentdrip_id', flat=True)
            qs_true = qs.filter(send_drips__id=opened_senddrip_id_list)
            true_ids = qs_true.values_list('id', flat=True)

        if self.on_true_id:
            for subscriber in qs_true:
                subscriber.move_to_step(self.on_true_id)

        if self.on_false_id:
            qs_false = qs.exclude(id__in=true_ids)
            for subscriber in qs_false:
                subscriber.move_to_step(self.on_false_id)
        return qs


class DripSubject(models.Model):
    drip = models.ForeignKey('squeezemail.Drip', related_name='subjects')
    text = models.CharField(max_length=150)
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return self.text


class Drip(models.Model):
    TYPE_CHOICES = (
        ('drip', 'Drip'),
        ('broadcast', 'Broadcast'),
    )

    regions = [
        Region(key='body', title='Main Body'),
        # Region(key='split_test', title='Split Test Body',
        #        inherited=False),
    ]
    queryset_rules = GenericRelation(
        'squeezemail.QuerySetRule',
        content_type_field='content_type_id',
        object_id_field='object_id',
    )

    name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name='Drip Name',
        help_text='A unique name for this drip.')

    enabled = models.BooleanField(default=False)

    note = models.TextField(max_length=255, null=True, blank=True, help_text="This is only seen by staff.")

    from_email = models.EmailField(null=True, blank=True,
        help_text='Set a custom from email.')
    from_email_name = models.CharField(max_length=150, null=True, blank=True,
        help_text="Set a name for a custom from email.")
    message_class = models.CharField(max_length=120, blank=True, default='default')
    send_after = models.DateTimeField(blank=True, null=True, help_text="Only used for 'Broadcast' type emails. (not yet implemented)")
    broadcast_sent = models.BooleanField(default=False, help_text="Only used for 'Broadcast' type emails.")
    date = models.DateTimeField(auto_now_add=True)
    lastchanged = models.DateTimeField(auto_now=True)

    def handler(self, *args, **kwargs):
        kwargs['drip_model'] = self
        handler_class = class_for(SQUEEZE_DRIP_HANDLER)
        handler = handler_class(*args, **kwargs)
        return handler

    def __str__(self):
        return self.name

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

    def step_run(self, step, qs):
        pruned_queryset = self.prune_queryset(qs)
        self.handler(step=step, queryset=pruned_queryset).step_run()
        return qs

    def prune_queryset(self, queryset):
        # Exclude all subscribers who have a SendDrip already
        target_subscriber_ids = queryset.values_list('id', flat=True)
        exclude_subscriber_ids = SendDrip.objects.filter(drip_id=self.id, subscriber_id__in=target_subscriber_ids)\
            .values_list('subscriber_id', flat=True)
        pruned_queryset = queryset.exclude(id__in=exclude_subscriber_ids)
        return pruned_queryset

    def apply_queryset_rules(self, qs):
        """
        First collect all filter/exclude kwargs and apply any annotations.
        Then apply all filters at once, and all excludes at once.
        """
        clauses = {
            'filter': [],
            'exclude': []}

        for rule in self.queryset_rules.all():

            clause = clauses.get(rule.method_type, clauses['filter'])

            kwargs = rule.filter_kwargs(qs)
            clause.append(Q(**kwargs))

            qs = rule.apply_any_annotation(qs)

        if clauses['exclude']:
            qs = qs.exclude(functools.reduce(operator.or_, clauses['exclude']))
        qs = qs.filter(*clauses['filter'])
        return qs

    @cached_property
    def open_rate(self):
        total_sent = self.send_drips.filter(sent=True).count()
        total_opened = Open.objects.filter(drip_id=self.pk).count()
        return (total_opened / total_sent) * 100

    @cached_property
    def click_through_rate(self):
        total_sent = self.send_drips.filter(sent=True).count()
        total_clicked = Click.objects.filter(drip_id=self.pk).count()
        return (total_clicked / total_sent) * 100

    @cached_property
    def click_to_open_rate(self):
        """
        Click to open rate is the percentage of recipients who opened
        the email message and also clicked on any link in the email message.
        """
        total_opened = Open.objects.filter(drip_id=self.pk).count()
        total_clicked = Click.objects.filter(drip_id=self.pk).count()
        return (total_opened / total_clicked) * 100


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
    senddrip = models.OneToOneField(SendDrip, primary_key=True)
    date = models.DateTimeField(auto_now_add=True)


class Click(models.Model):
    senddrip = models.OneToOneField(SendDrip, primary_key=True)
    date = models.DateTimeField(auto_now_add=True)


class Spam(models.Model):
    senddrip = models.OneToOneField(SendDrip, primary_key=True)
    date = models.DateTimeField(auto_now_add=True)


class Unsubscribe(models.Model):
    senddrip = models.OneToOneField(SendDrip, primary_key=True)
    date = models.DateTimeField(auto_now_add=True)


class QuerySetRule(models.Model):
    date = models.DateTimeField(auto_now_add=True)
    lastchanged = models.DateTimeField(auto_now=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = GfkLookupField('content_type')
    content_object = GenericForeignKey('content_type', 'object_id')
    method_type = models.CharField(max_length=12, default='filter', choices=METHOD_TYPES)
    field_name = models.CharField(max_length=128, verbose_name='Field name of Subscription')
    lookup_type = models.CharField(max_length=12, default='exact', choices=LOOKUP_TYPES)

    field_value = models.CharField(max_length=255,
        help_text=('Can be anything from a number, to a string. Or, do ' +
                   '`now-7 days` or `today+3 days` for fancy timedelta.'))

    def clean(self):
        try:
            self.apply(Subscriber.objects.all())
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


class Campaign(models.Model):
    name = models.CharField(max_length=150)
    from_name = models.CharField(max_length=100, blank=True, null=True)
    from_email = models.CharField(max_length=100, blank=True, null=True)
    # send_on_days = models.IntegerField(max_length=7, default=1111111)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    drips = models.ManyToManyField('Drip', through='CampaignDrip', related_name='campaigns')

    def __str__(self):
        return self.name

    def drip_count(self):
        # How many drips/emails this campaign has
        return self.drips.count()

    def active_subscriptions_count(self):
        return self.subscriptions.filter(is_active=True, is_complete=False)

    def unsubscribed_subscriber_count(self):
        return self.subscriptions.filter(is_active=False, is_complete=False)

    @cached_property
    def open_rate(self):
        drip_id_list = self.drips.filter(enabled=True).values_list('id', flat=True)
        total_sent = SendDrip.objects.filter(drip_id__in=drip_id_list, sent=True).count()
        total_opened = Open.objects.filter(drip_id__in=drip_id_list).count()
        return (total_opened / total_sent) * 100

    @cached_property
    def click_through_rate(self):
        drip_id_list = self.drips.filter(enabled=True).values_list('id', flat=True)
        total_sent = SendDrip.objects.filter(drip_id__in=drip_id_list, sent=True).count()
        total_clicked = Click.objects.filter(drip_id__in=drip_id_list).count()
        return (total_clicked / total_sent) * 100

    @cached_property
    def click_to_open_rate(self):
        """
        Click to open rate is the percentage of recipients who opened
        the email message and also clicked on any link in the email message.
        """
        drip_id_list = self.drips.filter(enabled=True).values_list('id', flat=True)
        total_opened = Open.objects.filter(drip_id__in=drip_id_list).count()
        total_clicked = Click.objects.filter(drip_id__in=drip_id_list).count()
        return (self.click_through_rate / self.open_rate) * 100

    def step_run(self, step, subscribers):
        #TODO: Implement this.
        # We want only the subscribers who want to receive this campaign and are on the calling step.
        subscriptions = self.subscriptions.filter(is_complete=False, is_active=True)
        subscribers = subscribers.filter()
        subscribers_id_list = subscribers.values_list('id', flat=True)
        # subscriptions = self.subscriptions.filter(is_complete=False, is_active=True, subscriber_id__in=subscribers_id_list)

        # for drip in self.drips.filter(enabled=True):
        #     subscribers =
        #     drip.handler(queryset=).campaign_run()

        return


class CampaignDrip(models.Model):
    campaign = models.ForeignKey('squeezemail.Campaign', related_name='campaign_drips')
    drip = models.ForeignKey('squeezemail.Drip', related_name='campaign_drips')
    delay = models.CharField(default='1 days', max_length=25)
    order = models.IntegerField(default=1)

    def __str__(self):
        return "%s: %s delayed %s" % (self.campaign.name, self.drip.name, str(self.delay))

    class Meta:
        ordering = ('order', 'id')


class FunnelManager(models.Manager):
    pass


class SubscriberManager(models.Manager):
    """
    Custom manager for Subscriber to provide extra functionality
    """
    use_for_related_fields = True

    def get_or_add(self, email, *args, **kwargs):
        try:
            #Try to get existing subscriber
            subscriber = self.get(email=email)
        except self.model.DoesNotExist:
            try:
                # Subscriber doesn't exist. Does a user exist with the same email?
                user = get_user_model().objects.get(email=email)
                # Create a new subscriber and tie to user
                subscriber = self.create(user=user, email=email)
            except ObjectDoesNotExist:
                # User doesn't exist, so create just the subscriber
                subscriber = self.create(email=email)
        return subscriber

    def active(self):
        """
        Gives only the active subscribers
        """
        return self.filter(is_active=True)


subscriber_manager = class_for(SQUEEZE_SUBSCRIBER_MANAGER)()


class Subscriber(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, related_name="squeeze_subscriber", null=True, blank=True)
    email = models.EmailField(max_length=254, db_index=True, unique=True)
    is_active = models.BooleanField(verbose_name="Active", default=True)
    created = models.DateTimeField(default=timezone.now)
    step = models.ForeignKey('squeezemail.Step', related_name="subscribers", blank=True, null=True)
    step_timestamp = models.DateTimeField(verbose_name="Last Step Activity Timestamp", blank=True, null=True)

    objects = subscriber_manager
    default_manager = subscriber_manager

    def __str__(self):
        return self.email

    def get_email(self):
        return self.user.email if self.user_id else self.email

    def move_to_step(self, step_id):
        self.step_id = step_id
        self.step_timestamp = timezone.now()
        self.save()
        return

    def unsubscribe(self):
        if self.is_active:
            self.is_active = False
            self.save()
        return

    def opened_email(self, drip):
        return self.send_drips.get(id=drip.id).opened


class FunnelSubscription(models.Model):
    """
    Used to check if the Subscriber has been through a funnel already.
    """
    funnel = models.ForeignKey('squeezemail.Funnel', related_name='subscriptions')
    subscriber = models.ForeignKey('squeezemail.Subscriber', related_name="funnel_subscriptions")
    date = models.DateTimeField(default=timezone.now)

    default_manager = FunnelManager()
    objects = default_manager

    class Meta:
        unique_together = ('funnel', 'subscriber')


class CampaignSubscription(models.Model):
    campaign = models.ForeignKey('squeezemail.Campaign', related_name="subscriptions")
    subscriber = models.ForeignKey('squeezemail.Subscriber', related_name="campaign_subscriptions")
    subscribe_date = models.DateTimeField(verbose_name="Subscribe Date", default=timezone.now)
    is_active = models.BooleanField(verbose_name="Active", default=True)
    is_complete = models.BooleanField(default=False)
    last_send_drip = models.ForeignKey('squeezemail.SendDrip', null=True, blank=True)


DripPlugin = create_plugin_base(Drip)


class RichText(plugins.RichText, DripPlugin):
    pass


class Image(plugins.Image, DripPlugin):
    url = models.TextField(max_length=500, null=True, blank=True)