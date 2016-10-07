from django.conf.urls import patterns, url

urlpatterns = [
   url(r'^link/$', 'squeezemail.views.link_click', name='link'),
   #url(r'^link/(?P<link_hash>[a-z0-9]+)/$', 'squeezemail.views.link_hash', name='link_hash'),
   #url(r'^(?P<tracking_pixel>.*?).png', tracking_pixel, name="tracking_pixel"),
   url(r'^pixel.png', 'squeezemail.views.drip_open', name="tracking_pixel"),
   url(r'^unsubscribe/$', 'squeezemail.views.unsubscribe', name='unsubscribe'),
]
