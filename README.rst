**ATTENTION: This code is all subject to change. Not recommended for production use yet.**

**This is a re-write of my initial Squeezemail prototype. This version includes a whole new way of thinking about how subscribers get sent things. It's not as elegant as I would have hoped to build in Django's admin, but I think it's as good as Django's admin can do. A custom UI would be nice in the future.**

**If you're using the original prototype of squeezemail, this isn't compatible with the previous prototype because of the massive model changes.**

**Important Note:** Because of tree corruption issues with MPTT, squeezemail uses cte-forest, which means **Postgresql is a requirement to use Squeezemail until cte-forest supports other databases.**

===========
Squeezemail
===========
A Django email drip/autoresponder primarily used by marketers to send their mailing list subscribers emails depending on
how long they've been on a mailing list, what they may have been tagged with, previous email activity,
and filter/exclude queries defined by you. It allows you to build a funnel to throw subscribers in.

"Broadcast" (send to all) emails also supported.

Why?
====
After using django-drip (the package that this project was based on) for a couple years, I realized I was creating over
a hundred drips that all basically had the same custom queries, and I thought I could get a little more functionality
out of them if I hard coded those parts in, and also be less prone to human error.

With django-drip, sending a broadcast out to 100,000+ subscribers took 27+ hours, and all cronjobs would have to be paused so it wouldn't send a user the same email more than once. Lots of babysitting for a big list.

I found my database was absolutely massive from the 'SentDrip' model used by django-drip (8 million records).

Most importantly, I was looking for a way to 'funnel' users through steps without paying a ridiculous amount of money for a 3rd party solution.

Main Features
=============
- Multiple funnels that will start a subscriber on a specified step.
- A tree of 'Steps' that the subscriber is sent down. They flow through the steps depending on how you build it.
- Ability to send a drip based on if the subscriber opened the previous email in the sequence they're on.
- Open/Click/Spam/Unsubscribe tracking.
- Email Subject & body split testing.
- Small 'SendDrip' model, with bare minimum fields.
- Feincms3's content blocks and cte-forest.
- Send stats to google analytics.

Not fully implemented yet
=================
Body split testing.
Sending all stats to google analytics.
More feincms content types (images).

==========
Quickstart
==========
This quickstart assumes you have a working Celery worker running.
If you don't, follow this first: http://docs.celeryproject.org/en/latest/django/first-steps-with-django.html


1. Add all of the required apps to your settings.py:
::
    'feincms3',
    'cte_forest',
    'content_editor',
    'ckeditor',
    'versatileimagefield',
    'squeezemail',



2. Add to settings.py:
::
    DEFAULT_HTTP_PROTOCOL = 'http'
We rebuild all the links in each email to track clicks, so we need to know which protocol to use. If your site is http, set to http, if it's ssl, set to https.



3. Add squeezemail's url to your project's urls.py.
::
    url(r'^squeezemail/', include('squeezemail.urls', namespace="squeezemail")),

All rebuilt links point to yourdomain.com/squeezemail/..., but doesn't have to be /squeezemail/, it can just be /e/ if you'd like. Change that here.


4. Migrate.
::
    ./manage.py migrate squeezemail


5. Run collectstatic:
::
    ./manage.py collectstatic


10. Once you have a Funnel made with at least 1 Step and a Subscriber who's on a step with a GFK attached to it.
::
    ./manage.py run_steps
It's recommended to add a cronjob to this so it'll auto run every x hours.

You should see it go through all of the active steps you have, moving subscribers to each step depending on various things you specified.


How do I make a Funnel?
=====================
Django's admin isn't the most elegant UI for building this, but it works well enough to get by for now. You may be a little overwhelmed with all the models you see in the admin, but you start at 'Funnel'. All subscribers will be added to a funnel, which will start them on the first step of the funnel. I'll walk you through making a quick cold opt in funnel, and it should give you a good idea of how it works.

Create a **Funnel**.

Name your funnel **'Cold Optin'**, and add an **Entry step** to it. This'll be our root step.

We want to send a drip (an email) as the first thing we do. Change **Content type** to **drip**, then click the **magnifying glass** on **Object id**.

Click **Add Drip** and name it **'Cold Welcome Email'**.

**Enable it**, and in Main body, click Add new item and select **Rich text**. Add whatever you want here.

**Add a subject**. Let's just do 1 for now, but if you were to add more than 1, it would randomly select a subject to send to each user.

Ignore the query set rules. These drip query set rules you see here are better used for broadcast drips. If you do want to create queryset rules in funnels (you will want to sooner or later), you should use a step with a "decision" content type.

**Save** your drip, your step, and your funnel.

We now have a funnel that'll send a welcome email to all subscribers on the welcome email step, but they don't have a step to flow to once they've received the welcome email. Let's **create a new step** (go to Steps in the admin and add a new step).

Make the parent our previous **Cold Welcome Email** step, and select **'delay'** as our content type, then **add a new delay object with the magnifying glass**.

When creating a new delay, it defaults to **'1 days'**. That's good, save it, then save your new step.

You should see a (rough) tree of your steps starting to take shape.

Add a new subscriber with a subscription.
::
    >>> from squeezemail.models import Funnel
    >>> funnel = Funnel.objects.get(name='Cold Optin')
    >>> funnel.create_subscription('your@email.com') # can also be a Subscriber instance, but this will create a subscriber if it doesn't exist




Special Thanks
==============
Bryan Helmig & Zapier for django-drip (https://github.com/zapier/django-drip), which this project is based off of.

Marc Egli's Pennyblack for inspiration to use feincms in a newsletter.

pmclanahan's django-celery-email (https://github.com/pmclanahan/django-celery-email) for his clever chunked function with celery.
