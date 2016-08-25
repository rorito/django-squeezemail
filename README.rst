    **This repo is mainly used as a place to put my pre-alpha ideas for squeezemail at the moment. It's not meant to be used in production at the moment.**

===========
Squeezemail
===========
A Django email drip/autoresponder primarily used by marketers to send their mailing list subscribers emails depending on
how long they've been on a mailing list, what they may have been tagged with, whether they opened the previous email,
and filter/exclude queries defined by you.

"Broadcast" (send to all) emails also supported.

Why?
====
After using django-drip (the package that this project is based on) for a couple years, I realized I was creating over
a hundred drips that all basically had the same custom queries, and I thought I could get a little more functionality
out of them if I hard coded those parts in, and also be less prone to human error.

With django-drip, sending a broadcast out to 100,000+ subscribers took 27+ hours, and all cronjobs would have to be paused so it
 wouldn't send a user the same email more than once. Lots of babysitting for a big list.

I found my database was absolutely massive from the 'SentDrip' model used by django-drip (8 million records).

Features
========
Scalable.
Hardcoded 'delay' field for each drip, which allow you to enter in how many days you want to delay each drip.
Multiple mailing lists.
Abstract Subscriber model to customize your own or use module/subscriber.py if you want a generic subscriber model.
Sequences (think of them as user funnels) to subscribe the user to send them down.
Ability to send a drip based on if the subscriber opened the previous email in the sequence they're on.
Open/Click tracking.
Subject & body split testing. (note: not yet fully implemented)
Lots of checks put in to ensure subscribers don't receive the same email twice, even if a cronjob is set to run every second.
Small 'SendDrip' model, with bare minimum fields.
Schedule a drip to send after a specific date & time. (doesn't send ON the datetime, only checks if the current time is after the set datetime)
Feincms with tinyMCE instead of just a body field.

To Be Implemented
=================
Split testing for both subject and body.
Send open/click/split-test stats to Google Analytics as they come in.
More feincms content types (images).

==========
Quickstart
==========
This quickstart assumes you have a working Celery worker running.
If you don't, follow this first: http://docs.celeryproject.org/en/latest/django/first-steps-with-django.html

1. Install Squeezemail over pip:
`pip install django-squeezemail`


2. Create a new Django app, which can be called anything you want. This is the app we use to extend squeezemail. We'll call it 'subscribers' in this quickstart.
`
./manage.py startapp subscribers
`
You don't even have to create a new app, but this is a way to keep everything as clean as possible.


3. Add FeinCMS, Squeezemail, and your newly created app to your installed apps in settings.py
`
'feincms',
'feincms.module.medialibrary',
'squeezemail',
'subscribers',
`


4. Add to settings.py:
`DEFAULT_HTTP_PROTOCOL = 'http'`
This is for link building. If your site is http, set to http, if it's ssl, set to https.


5. Add squeezemail's url to your project's urls.py.
`
url(r'^squeezemail/', include('squeezemail.urls', namespace="squeezemail")),
`
It doesn't have to be /squeezemail/, it can be whatever you want.


6. Add some content types for your drips in subscribers' models.py.
`
from squeezemail.content.richtext import TextOnlyDripContent
from squeezemail.models import Drip, MailingList


Drip.register_templates({
  'key': 'drip',
  'title': 'Default',
  'path': 'squeezemail/body.html',
  'regions': (
       ('body', 'Main Body'),
       ('split_test', 'Split Test Body'),
       ),
  })

Drip.create_content_type(TextOnlyDripContent)
`
You can create your own FeinCMS content types and add them here in the future as well.
You could add images, coupon snippets, etc.


7. Set squeezemail's migrations to your new app, subscribers, in your settings.py.
`
MIGRATION_MODULES = {
    'squeezemail': 'subscribers.squeezemail_migrations'
}
`
This is so you can add your own FeinCMS content types. All squeezemail migrations will be managed by you, and will be located here.


8. Run makemigrations and migrate.
`
./manage.py makemigrations squeezemail
./manage.py migrate squeezemail
`

9. Run collectstatic:
`./manage.py collectstatic`


10. Add some drips in the admin and add yourself as a Subscriber, then run:
`./manage.py send_drips`
It's recommended to add a cronjob to this so it'll auto send every x hours.

You should see your worker receive at least 1 task (if there was a relevant user to send a drip to), and send out an email to that user.


Special Thanks
==============
Bryan Helmig & Zapier for django-drip (https://github.com/zapier/django-drip), which this project is based off of.

Marc Egli's Pennyblack for inspiration to use feincms in a newsletter.

pmclanahan's django-celery-email (https://github.com/pmclanahan/django-celery-email) for his clever chunked function with celery.
