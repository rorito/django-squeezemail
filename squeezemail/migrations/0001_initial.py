# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import feincms.contrib.richtext
import django.utils.timezone
from django.conf import settings
import feincms.extensions


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Click',
            fields=[
                ('id', models.AutoField(serialize=False, primary_key=True, auto_created=True, verbose_name='ID')),
                ('date', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='Drip',
            fields=[
                ('id', models.AutoField(serialize=False, primary_key=True, auto_created=True, verbose_name='ID')),
                ('date', models.DateTimeField(auto_now_add=True)),
                ('lastchanged', models.DateTimeField(auto_now=True)),
                ('parent_opened', models.NullBooleanField(help_text="Only send to users who opened parent drip. True will only send to users who opened parent drip, False will only send to users who didn't. Choose Null if this isn't applicable to your drip.")),
                ('parent_clicked', models.NullBooleanField(help_text="Only send to users who clicked a link in parent drip's body content. True will only send to users who clicked parent drip, False will only send to users who didn't. Choose Null if this isn't applicable to your drip.")),
                ('delay', models.IntegerField(default=1, help_text="Delay in how many days from when the subscriber started their current sequence. 0 is same day (immediate), 1 is one day old before sending. If a parent is selected, delays off of when the parent was sent to the user instead.Use 1 (or more) if a parent is selected, otherwise they'll get 2 emails in 1 day.", verbose_name='Day Delay')),
                ('name', models.CharField(max_length=255, help_text='A unique name for this drip.', unique=True, verbose_name='Drip Name')),
                ('send_after', models.DateTimeField(null=True, blank=True)),
                ('enabled', models.BooleanField(default=False)),
                ('note', models.TextField(max_length=255, null=True, help_text='This is only seen by staff.', blank=True)),
                ('from_email', models.EmailField(max_length=254, null=True, help_text='Set a custom from email.', blank=True)),
                ('from_email_name', models.CharField(max_length=150, null=True, help_text='Set a name for a custom from email.', blank=True)),
                ('message_class', models.CharField(max_length=120, default='default', blank=True)),
                ('template_key', models.CharField(max_length=255, default='drip', choices=[('drip', 'Default')], verbose_name='template')),
                ('parent', models.ForeignKey(null=True, to='squeezemail.Drip', help_text="Choosing a drip parent will 'delay' off of when the parent was sent. to delay this drip from when the parent was sent to the user", related_name='children', blank=True)),
            ],
            options={
                'abstract': False,
            },
            bases=(models.Model, feincms.extensions.ExtensionsMixin),
        ),
        migrations.CreateModel(
            name='DripSubject',
            fields=[
                ('id', models.AutoField(serialize=False, primary_key=True, auto_created=True, verbose_name='ID')),
                ('subject', models.CharField(max_length=150)),
                ('enabled', models.BooleanField(default=True)),
                ('drip', models.ForeignKey(related_name='subjects', to='squeezemail.Drip')),
            ],
        ),
        migrations.CreateModel(
            name='MailingList',
            fields=[
                ('id', models.AutoField(serialize=False, primary_key=True, auto_created=True, verbose_name='ID')),
                ('name', models.CharField(max_length=75)),
            ],
        ),
        migrations.CreateModel(
            name='Open',
            fields=[
                ('id', models.AutoField(serialize=False, primary_key=True, auto_created=True, verbose_name='ID')),
                ('date', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='QuerySetRule',
            fields=[
                ('id', models.AutoField(serialize=False, primary_key=True, auto_created=True, verbose_name='ID')),
                ('date', models.DateTimeField(auto_now_add=True)),
                ('lastchanged', models.DateTimeField(auto_now=True)),
                ('method_type', models.CharField(max_length=12, default='filter', choices=[('filter', 'Filter'), ('exclude', 'Exclude')])),
                ('field_name', models.CharField(max_length=128, verbose_name='Field name of User')),
                ('lookup_type', models.CharField(max_length=12, default='exact', choices=[('exact', 'exactly'), ('iexact', 'exactly (case insensitive)'), ('contains', 'contains'), ('icontains', 'contains (case insensitive)'), ('regex', 'regex'), ('iregex', 'contains (case insensitive)'), ('gt', 'greater than'), ('gte', 'greater than or equal to'), ('lt', 'less than'), ('lte', 'less than or equal to'), ('startswith', 'starts with'), ('endswith', 'starts with'), ('istartswith', 'ends with (case insensitive)'), ('iendswith', 'ends with (case insensitive)')])),
                ('field_value', models.CharField(max_length=255, help_text='Can be anything from a number, to a string. Or, do `now-7 days` or `today+3 days` for fancy timedelta.')),
                ('drip', models.ForeignKey(related_name='queryset_rules', to='squeezemail.Drip')),
            ],
        ),
        migrations.CreateModel(
            name='SendDrip',
            fields=[
                ('id', models.AutoField(serialize=False, primary_key=True, auto_created=True, verbose_name='ID')),
                ('date', models.DateTimeField(auto_now_add=True)),
                ('sent', models.BooleanField(default=False)),
                ('drip', models.ForeignKey(related_name='send_drips', to='squeezemail.Drip')),
                ('user', models.ForeignKey(related_name='send_drips', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Sequence',
            fields=[
                ('id', models.AutoField(serialize=False, primary_key=True, auto_created=True, verbose_name='ID')),
                ('name', models.CharField(max_length=75)),
                ('mailinglist', models.ForeignKey(related_name='sequences', to='squeezemail.MailingList')),
            ],
        ),
        migrations.CreateModel(
            name='Spam',
            fields=[
                ('id', models.AutoField(serialize=False, primary_key=True, auto_created=True, verbose_name='ID')),
                ('date', models.DateTimeField(auto_now_add=True)),
                ('sentdrip', models.OneToOneField(to='squeezemail.SendDrip')),
            ],
        ),
        migrations.CreateModel(
            name='Subscriber',
            fields=[
                ('id', models.AutoField(serialize=False, primary_key=True, auto_created=True, verbose_name='ID')),
                ('sequence_date', models.DateTimeField(default=django.utils.timezone.now, verbose_name='Started Sequence Date')),
                ('subscribe_date', models.DateTimeField(default=django.utils.timezone.now, verbose_name='Subscribe Date')),
                ('unsubscribe_date', models.DateTimeField(null=True, blank=True, verbose_name='Unsubscribe Date')),
                ('is_active', models.BooleanField(default=True, verbose_name='Active')),
                ('mailinglist', models.ForeignKey(related_name='subscribers', to='squeezemail.MailingList')),
                ('sequence', models.ForeignKey(related_name='subscribers', to='squeezemail.Sequence')),
                ('user', models.ForeignKey(related_name='squeeze_subscriptions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name_plural': 'Subscribers',
                'verbose_name': 'Subscriber',
            },
        ),
        migrations.CreateModel(
            name='TextOnlyDripContent',
            fields=[
                ('id', models.AutoField(serialize=False, primary_key=True, auto_created=True, verbose_name='ID')),
                ('text', feincms.contrib.richtext.RichTextField(blank=True, verbose_name='text')),
                ('region', models.CharField(max_length=255)),
                ('ordering', models.IntegerField(default=0, verbose_name='ordering')),
                ('parent', models.ForeignKey(related_name='textonlydripcontent_set', to='squeezemail.Drip')),
            ],
            options={
                'db_table': 'squeezemail_drip_textonlydripcontent',
                'verbose_name': 'text only content',
                'abstract': False,
                'ordering': ['ordering'],
                'verbose_name_plural': 'text only contents',
                'permissions': [],
            },
        ),
        migrations.CreateModel(
            name='Unsubscribe',
            fields=[
                ('id', models.AutoField(serialize=False, primary_key=True, auto_created=True, verbose_name='ID')),
                ('date', models.DateTimeField(auto_now_add=True)),
                ('sentdrip', models.OneToOneField(to='squeezemail.SendDrip')),
            ],
        ),
        migrations.AddField(
            model_name='open',
            name='sentdrip',
            field=models.OneToOneField(to='squeezemail.SendDrip'),
        ),
        migrations.AddField(
            model_name='drip',
            name='sequence',
            field=models.ForeignKey(null=True, to='squeezemail.Sequence', help_text="IMPORTANT: Choose a sequence even if a parent is selected. If no sequence is selected, it's assumed to be a broadcast email and will ONLY filter off the queryset you select below. If left empty, it grabs ALL users by default, even those who are not on a mailing list.", related_name='drips', blank=True),
        ),
        migrations.AddField(
            model_name='click',
            name='sentdrip',
            field=models.OneToOneField(to='squeezemail.SendDrip'),
        ),
        migrations.AlterUniqueTogether(
            name='subscriber',
            unique_together=set([('user', 'sequence')]),
        ),
        migrations.AlterUniqueTogether(
            name='senddrip',
            unique_together=set([('drip', 'user')]),
        ),
    ]
