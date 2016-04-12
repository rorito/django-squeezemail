#import base64
import json

from django import forms
from django.contrib import admin

from .models import Drip, SendDrip, QuerySetRule, DripSubject, MailingList, Sequence, Subscriber
from .handlers import configured_message_classes, message_class_for
from django.contrib.auth import get_user_model

from feincms.admin import item_editor, tree_editor


class DripSplitSubjectInline(admin.TabularInline):
    model = DripSubject
    extra = 1


class QuerySetRuleInline(admin.TabularInline):
    model = QuerySetRule


class DripForm(forms.ModelForm):
    message_class = forms.ChoiceField(
        choices=((k, '%s (%s)' % (k, v)) for k, v in configured_message_classes().items())
    )

    class Meta:
        model = Drip
        exclude = []


class MailingListAdmin(admin.ModelAdmin):
    pass


class SequenceAdmin(admin.ModelAdmin):
    pass


class SubscriberAdmin(admin.ModelAdmin):
    pass


class DripAdmin(item_editor.ItemEditor):
    # fieldsets = [
    #     (None, {
    #         'fields': ['enabled', 'name', 'message_class'],
    #         }),
    #     #('Important things', {'fields': ('DripSplitSubjectInline',)}),
    #     item_editor.FEINCMS_CONTENT_FIELDSET,
    #     ]
    list_display = ('name', 'enabled', 'message_class')
    inlines = [
        DripSplitSubjectInline,
        QuerySetRuleInline
    ]
    form = DripForm

    raw_id_fields = ['parent']

    av = lambda self, view: self.admin_site.admin_view(view)

    def timeline(self, request, drip_id, into_past, into_future):
        """
        Return a list of people who should get emails.
        """
        from django.shortcuts import render, get_object_or_404

        drip = get_object_or_404(Drip, id=drip_id)

        shifted_drips = []
        seen_users = set()
        for shifted_drip in drip.handler.walk(into_past=int(into_past), into_future=int(into_future)+1):
            shifted_drip.prune()
            shifted_drips.append({
                'drip': shifted_drip,
                'qs': shifted_drip.get_queryset().exclude(id__in=seen_users)
            })
            seen_users.update(shifted_drip.get_queryset().values_list('id', flat=True))

        return render(request, 'squeezemail/timeline.html', locals())

    def view_drip_email(self, request, drip_id, into_past, into_future, user_id):
        from django.shortcuts import render, get_object_or_404
        from django.http import HttpResponse
        drip = get_object_or_404(Drip, id=drip_id)
        User = get_user_model()
        user = get_object_or_404(User, id=user_id)

        drip_message = message_class_for(drip.message_class)(drip, user)
        html = ''
        mime = ''
        if drip_message.message.alternatives:
            for body, mime in drip_message.message.alternatives:
                if mime == 'text/html':
                    html = body
                    mime = 'text/html'
        else:
            html = drip_message.message.body
            mime = 'text/plain'

        return HttpResponse(html, content_type=mime)

    def build_extra_context(self, extra_context):
        from .utils import get_simple_fields
        extra_context = extra_context or {}
        User = get_user_model()
        extra_context['field_data'] = json.dumps(get_simple_fields(User))
        return extra_context

    def add_view(self, request, form_url='', extra_context=None):
        return super(DripAdmin, self).add_view(
            request, extra_context=self.build_extra_context(extra_context))

    def change_view(self, request, object_id, form_url='', extra_context=None):
        return super(DripAdmin, self).change_view(
            request, object_id, extra_context=self.build_extra_context(extra_context))

    def get_urls(self):
        from django.conf.urls import patterns, url
        urls = super(DripAdmin, self).get_urls()
        my_urls = patterns('',
            url(
                r'^(?P<drip_id>[\d]+)/timeline/(?P<into_past>[\d]+)/(?P<into_future>[\d]+)/$',
                self.av(self.timeline),
                name='drip_timeline'
            ),
            url(
                r'^(?P<drip_id>[\d]+)/timeline/(?P<into_past>[\d]+)/(?P<into_future>[\d]+)/(?P<user_id>[\d]+)/$',
                self.av(self.view_drip_email),
                name='view_drip_email'
            )
        )
        return my_urls + urls

admin.site.register(MailingList, MailingListAdmin)
admin.site.register(Sequence, SequenceAdmin)
admin.site.register(Drip, DripAdmin)
admin.site.register(Subscriber, SubscriberAdmin)


class SentDripAdmin(admin.ModelAdmin):
    list_display = [f.name for f in SendDrip._meta.fields]
    ordering = ['-id']
admin.site.register(SendDrip, SentDripAdmin)
