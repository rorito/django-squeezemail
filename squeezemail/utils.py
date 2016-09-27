import sys

from django.db import models
from django.db.models.fields.related import ForeignObjectRel
from django.db.models.fields.related import (
    ForeignObjectRel, ManyToManyRel, ManyToOneRel, OneToOneRel, RelatedField
)
from django.core.mail import EmailMultiAlternatives, EmailMessage
try:
    # Django >= 1.9
    from django.utils.module_loading import import_module
except ImportError:
    from django.utils.importlib import import_module

import hashlib

from django.conf import settings
_ver = sys.version_info
is_py2 = (_ver[0] == 2)
is_py3 = (_ver[0] == 3)

if is_py2:
    basestring = basestring
    unicode = unicode
elif is_py3:
    basestring = (str, bytes)
    unicode = str


def get_fields(Model,
               parent_field="",
               model_stack=None,
               stack_limit=3,
               excludes=['permissions', 'comment', 'content_type']):
    """
    Given a Model, return a list of lists of strings with important stuff:
    ...
    ['test_user__user__customuser', 'customuser', 'User', 'RelatedObject']
    ['test_user__unique_id', 'unique_id', 'TestUser', 'CharField']
    ['test_user__confirmed', 'confirmed', 'TestUser', 'BooleanField']
    ...

     """
    out_fields = []

    if model_stack is None:
        model_stack = []

    # github.com/omab/python-social-auth/commit/d8637cec02422374e4102231488481170dc51057
    if isinstance(Model, basestring):
        app_label, model_name = Model.split('.')
        Model = models.get_model(app_label, model_name)

    #fields = Model._meta.fields + Model._meta.many_to_many + tuple(Model._meta.get_all_related_objects())
    fields = Model._meta.get_fields()
    model_stack.append(Model)

    # do a variety of checks to ensure recursion isnt being redundant

    stop_recursion = False
    if len(model_stack) > stack_limit:
        # rudimentary CustomUser->User->CustomUser->User detection
        if model_stack[-3] == model_stack[-1]:
            stop_recursion = True

        # stack depth shouldn't exceed x
        if len(model_stack) > 5:
            stop_recursion = True

        # we've hit a point where we are repeating models
        if len(set(model_stack)) != len(model_stack):
            stop_recursion = True

    if stop_recursion:
        return [] # give empty list for "extend"

    for field in fields:
        field_name = field.name

        # if instance(field, Man)

        if isinstance(field, ForeignObjectRel):
            # from pdb import set_trace
            # set_trace()
            # print (field, type(field))
            field_name = field.field.related_query_name()

        if parent_field:
            full_field = "__".join([parent_field, field_name])
        else:
            full_field = field_name

        # print (field, field_name, full_field)

        if len([True for exclude in excludes if (exclude in full_field)]):
            continue

        # add to the list
        out_fields.append([full_field, field_name, Model, field.__class__])

        if not stop_recursion and \
                (isinstance(field, ForeignObjectRel) or isinstance(field, OneToOneRel) or isinstance(field, RelatedField) or isinstance(field, ManyToManyRel) or isinstance(field, ManyToOneRel)):

            # from pdb import set_trace
            # set_trace()

            if not isinstance(field, ForeignObjectRel):
                RelModel = field.model
                # print(RelModel)
            else:
                RelModel = field.related_model
                # print(RelModel)
            # if isinstance(field, OneToOneRel):
            #     print(field.related_model)
                # print(field.related_model)
            # print(RelModel)
            # if isinstance(field, OneToOneRel):
            #     RelModel = field.model
            #     out_fields.extend(get_fields(RelModel, full_field, True))
            # else:
            #     # RelModel = field.related.parent_model
            #     RelModel = field.related_model.parent_model

            out_fields.extend(get_fields(RelModel, full_field, list(model_stack)))

    return out_fields


def give_model_field(full_field, Model):
    """
    Given a field_name and Model:

    "test_user__unique_id", <AchievedGoal>

    Returns "test_user__unique_id", "id", <Model>, <ModelField>
    """
    field_data = get_fields(Model, '', [])

    for full_key, name, _Model, _ModelField in field_data:
        if full_key == full_field:
            return full_key, name, _Model, _ModelField

    raise Exception('Field key `{0}` not found on `{1}`.'.format(full_field, Model.__name__))


def get_simple_fields(Model, **kwargs):
    return [[f[0], f[3].__name__] for f in get_fields(Model, **kwargs)]


def chunked(iterator, chunksize):
    """
    Yields items from 'iterator' in chunks of size 'chunksize'.
    >>> list(chunked([1, 2, 3, 4, 5], chunksize=2))
    [(1, 2), (3, 4), (5,)]
    """
    chunk = []
    for idx, item in enumerate(iterator, 1):
        chunk.append(item)
        if idx % chunksize == 0:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def email_to_dict(message):
    if isinstance(message, dict):
        return message

    message_dict = {'subject': message.subject,
                    'body': message.body,
                    'from_email': message.from_email,
                    'to': message.to,
                    # 'bcc': message.bcc,
                    # ignore connection
                    'attachments': message.attachments, #TODO: need attachments and headers passed correctly
                    'headers': message.extra_headers,
                    #'cc': message.cc
                    #'user_id': message.user.id,
                    #'drip_id': message.drip.id
                    }

    # Django 1.8 support
    # https://docs.djangoproject.com/en/1.8/topics/email/#django.core.mail.EmailMessage
    if hasattr(message, 'reply_to'):
        message_dict['reply_to'] = message.reply_to

    if hasattr(message, 'alternatives'):
        message_dict['alternatives'] = message.alternatives
    if message.content_subtype != EmailMessage.content_subtype:
        message_dict["content_subtype"] = message.content_subtype
    if message.mixed_subtype != EmailMessage.mixed_subtype:
        message_dict["mixed_subtype"] = message.mixed_subtype
    return message_dict


def dict_to_email(messagedict):
    if isinstance(messagedict, dict) and "content_subtype" in messagedict:
        content_subtype = messagedict["content_subtype"]
        del messagedict["content_subtype"]
    else:
        content_subtype = None
    if isinstance(messagedict, dict) and "mixed_subtype" in messagedict:
        mixed_subtype = messagedict["mixed_subtype"]
        del messagedict["mixed_subtype"]
    else:
        mixed_subtype = None
    if hasattr(messagedict, 'from_email'):
        ret = messagedict
    elif 'alternatives' in messagedict:
        ret = EmailMultiAlternatives(**messagedict)
    else:
        ret = EmailMessage(**messagedict)
    if content_subtype:
        ret.content_subtype = content_subtype
        messagedict["content_subtype"] = content_subtype  # bring back content subtype for 'retry'
    if mixed_subtype:
        ret.mixed_subtype = mixed_subtype
        messagedict["mixed_subtype"] = mixed_subtype  # bring back mixed subtype for 'retry'
    return ret


def class_for(path):
    mod_name, klass_name = path.rsplit('.', 1)
    mod = import_module(mod_name)
    klass = getattr(mod, klass_name)
    return klass


def get_token_for_user(user):
    m = hashlib.md5(user.email.encode('utf-8') + settings.SECRET_KEY.encode('utf-8')).hexdigest().encode('utf-8')
    return m