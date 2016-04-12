# from django.core import files
# from django.db import models
from django.core.urlresolvers import reverse
from django.forms.util import ErrorList
from django.template import Context, Template, TemplateSyntaxError
# from django.template.loader import render_to_string
# from django.utils.safestring import mark_safe
from django.utils.translation import ugettext_lazy as _
# from froala_editor.fields import FroalaField
#from pennyblack import settings
#from ..models.link import check_if_redirect_url, is_link

from feincms.content.richtext.models import RichTextContentAdminForm, RichTextContent
# from feincms.module.medialibrary.models import MediaFile

import re
# import os
# from PIL import Image
#import exceptions

HREF_RE = re.compile(r'href\="((\{\{[^}]+\}\}|[^"><])+)"')


# class FroalaContent(models.Model):
#     content = FroalaField()
#
#     class Meta:
#         abstract = True
#         #app_label = 'wienfluss'
#
#     def render(self, **kwargs):
#         request = kwargs.get('request')
#         return render_to_string('content/markupmirror/default.html', {
#             'content': self,
#             'request': request
#         })

class NewsletterSectionAdminForm(RichTextContentAdminForm):
    def clean(self):
        cleaned_data = super(NewsletterSectionAdminForm, self).clean()
        try:
            t = Template(cleaned_data['text'])
        except TemplateSyntaxError as e:
            self._errors["text"] = ErrorList([e])
        except KeyError:
            pass
        return cleaned_data

    # class Meta:
    #     exclude = ('image_thumb', 'image_width', 'image_height', 'image_url_replaced')

    # def __init__(self, *args, **kwargs):
    #     super(NewsletterSectionAdminForm, self).__init__(*args, **kwargs)
    #     self.fields.insert(0, 'title', self.fields.pop('title'))


class TextOnlyDripContent(RichTextContent):

    #form = NewsletterSectionAdminForm
    #feincms_item_editor_form = NewsletterSectionAdminForm

    # feincms_item_editor_includes = {
    #     'head': [ settings.TINYMCE_CONFIG_URL ],
    #     }

    # baselayout = "content/text_only/section.html"

    class Meta:
        abstract = True
        app_label = 'driprichtext'
        verbose_name = _('text only content')
        verbose_name_plural = _('text only contents')