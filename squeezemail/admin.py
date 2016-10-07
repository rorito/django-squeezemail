import json

import html2text
from django import forms
from django.contrib import admin
from django.template import Context
from django.contrib.contenttypes.admin import GenericTabularInline

from feincms3.admin import TreeAdmin
from feincms3.plugins import AlwaysChangedModelForm

from .models import Drip, SendDrip, QuerySetRule, DripSubject, Subscriber, Decision,\
    Delay, Step, Modify, Funnel, Image, RichText
from .handlers import configured_message_classes, message_class_for

from content_editor.admin import (
    ContentEditor, ContentEditorInline
)


class QuerySetRuleInline(GenericTabularInline):
    model = QuerySetRule

    def _media(self):
        return forms.Media(
            css={
                'all': ('css/queryset_rules.css',)
            },
        )
    media = property(_media)


class StepAdmin(TreeAdmin):
    model = Step
    generic_raw_id_fields = ['content_object']
    raw_id_fields = ('parent',)
    list_display = ('indented_title', 'move_column', 'get_active_subscribers_count')


class DecisionAdmin(admin.ModelAdmin):
    model = Decision
    inlines = [
        QuerySetRuleInline,
    ]

    def build_extra_context(self, extra_context):
        from .utils import get_simple_fields
        extra_context = extra_context or {}
        extra_context['field_data'] = json.dumps(get_simple_fields(Subscriber))
        return extra_context

    def add_view(self, request, form_url='', extra_context=None):
        return super(DecisionAdmin, self).add_view(
            request, extra_context=self.build_extra_context(extra_context))

    def change_view(self, request, object_id, form_url='', extra_context=None):
        return super(DecisionAdmin, self).change_view(
            request, object_id, extra_context=self.build_extra_context(extra_context))


class FunnelAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'get_subscription_count')


admin.site.register(Step, StepAdmin)
admin.site.register(Modify)
admin.site.register(Delay)
admin.site.register(Decision, DecisionAdmin)
admin.site.register(Funnel, FunnelAdmin)


class DripSplitSubjectInline(admin.TabularInline):
    model = DripSubject
    extra = 1


class DripForm(forms.ModelForm):
    message_class = forms.ChoiceField(
        choices=((k, '%s (%s)' % (k, v)) for k, v in configured_message_classes().items())
    )

    class Meta:
        model = Drip
        exclude = []


# class CampaignDripInline(admin.TabularInline):
#     model = CampaignDrip


# class CampaignAdmin(admin.ModelAdmin):
#     inlines = [CampaignDripInline]


class SubscriberAdmin(admin.ModelAdmin):
    pass


class RichTextInline(ContentEditorInline):
    """
    The only difference with the standard ``ContentEditorInline`` is that this
    inline adds the ``feincms3/plugin_ckeditor.js`` file which handles the
    CKEditor widget activation and deactivation inside the content editor.
    """
    model = RichText

    class Media:
        js = ('feincms3/plugin_ckeditor.js',)


class ImageInline(ContentEditorInline):
    form = AlwaysChangedModelForm
    model = Image
    extra = 0


class DripAdmin(ContentEditor):
    model = Drip
    # change_form_template = 'admin/squeezemail/drip/change_form.html'
    # fieldsets = [
    #     (None, {
    #         'fields': ['enabled', 'name', 'message_class'],
    #         }),
    #     #('Important things', {'fields': ('DripSplitSubjectInline',)}),
    #     item_editor.FEINCMS_CONTENT_FIELDSET,
    #     ]
    list_display=(
        # 'tree_actions',
        # 'indented_title',
        'name',
        'enabled',
        'message_class'
        # ...more fields if you feel like it...
    )
    # list_display_links=(
    #     'indented_title',
    # )
    # list_display = ('name', 'enabled', 'message_class')
    inlines = [
        DripSplitSubjectInline,
        QuerySetRuleInline,
        RichTextInline,
        ImageInline
    ]
    form = DripForm

    # raw_id_fields = ['parent']

    av = lambda self, view: self.admin_site.admin_view(view)

    def drip_broadcast_preview(self, request, drip_id):
        from django.shortcuts import render, get_object_or_404
        drip = get_object_or_404(Drip, id=drip_id)
        handler = drip.handler()
        handler.prune()  # Only show us subscribers that we're going to be sending to
        qs = handler.get_queryset()
        ctx = Context({
            'drip': drip,
            'queryset_preview': qs[:20],
            'count': qs.count(),

        })
        return render(request, 'admin/squeezemail/drip/broadcast_preview.html', ctx)

    def drip_broadcast_send(self, request, drip_id):
        from django.shortcuts import get_object_or_404
        from django.http import HttpResponse
        drip = get_object_or_404(Drip, id=drip_id)
        result_tasks = drip.handler().broadcast_run()
        mime = 'text/plain'
        return HttpResponse('Broadcast queued to celery. You may leave this page.', content_type=mime)

    def view_drip_email(self, request, drip_id, subscriber_id):
        from django.shortcuts import get_object_or_404
        from django.http import HttpResponse
        drip = get_object_or_404(Drip, id=drip_id)
        subscriber = get_object_or_404(Subscriber, id=subscriber_id)
        MessageClass = message_class_for(drip.message_class)
        drip_message = MessageClass(drip, subscriber)
        html = ''
        mime = ''
        if drip_message.message.alternatives:
            for body, mime in drip_message.message.alternatives:
                if mime == 'text/html':
                    html = body
                    mime = 'text/html'
        else:
            #TODO: consider adding ability to view plaintext email. Leaving this code here to expand upon.
            html = drip_message.message.body
            mime = 'text/plain'
        return HttpResponse(html, content_type=mime)

    def build_extra_context(self, extra_context):
        from .utils import get_simple_fields
        extra_context = extra_context or {}
        extra_context['field_data'] = json.dumps(get_simple_fields(Subscriber))
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
                r'^(?P<drip_id>[\d]+)/preview/(?P<subscriber_id>[\d]+)/$',
                self.av(self.view_drip_email),
                name='view_drip_email'
            ),
            url(
                r'^(?P<drip_id>[\d]+)/broadcast/$',
                self.av(self.drip_broadcast_preview),
                name='drip_broadcast_preview'
            ),
            url(
                r'^(?P<drip_id>[\d]+)/broadcast/send/$',
                self.av(self.drip_broadcast_send),
                name='drip_broadcast_send'
            )
        )
        return my_urls + urls

# admin.site.register(Campaign, CampaignAdmin)
# admin.site.register(CampaignSubscription)
admin.site.register(Drip, DripAdmin)
admin.site.register(Subscriber, SubscriberAdmin)


class SendDripAdmin(admin.ModelAdmin):
    list_display = [f.name for f in SendDrip._meta.fields]
    ordering = ['-id']

admin.site.register(SendDrip, SendDripAdmin)

# admin.site.register(
#     Drip, ContentEditor,
#     # inlines=[
#     #     RichTextInline,
#     #     # ContentEditorInline.create(model=Download),
#     # ],
# )