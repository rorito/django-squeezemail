from content_editor.renderer import PluginRenderer
# from feincms3.renderer import TemplatePluginRenderer
#
#
# class CustomTemplatePluginRenderer(TemplatePluginRenderer, PluginRenderer):
#     pass
#
# renderer = CustomTemplatePluginRenderer()
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from .models import RichText, Image


def render_plugin_with_template(plugin):
    return render_to_string(
        '%s/plugins/%s.html' % (
            plugin._meta.app_label,
            plugin._meta.model_name,
        ),
        {'plugin': plugin},
    )

renderer = PluginRenderer()

renderer.register(
    RichText,
    lambda plugin: mark_safe(plugin.text)
)

# Render image to squeezemail/plugins/image.html template
renderer.register(Image, render_plugin_with_template)