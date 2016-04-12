from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect, HttpResponse

from .tasks import process_click, process_open


# def link_hash(request, link_hash):
#
#     #unencode link
#
#     link = request.build_absolute_uri()
#
#     return link_click(request, link)


def drip_open(request):
    """
    Mainly used by an img pixel embeded in every email.

    Returns a 204 No Content http response to save bandwidth.
    Thanks https://github.com/SpokesmanReview/Pixel-Tracker/blob/master/pixel_tracker/views.py
    """
    orig_params = {}
    sq_params = {}
    for key, value in request.GET.items():
        if key.startswith('sq_'):
            sq_params[key] = value
        else:
            orig_params[key] = value
    process_open.delay(**sq_params)
    return HttpResponse(status=204)


def link_click(request):
    """
    Decodes the link hash, makes sure their user_token matches ours, then process anything needed for stats, etc. then redirects to the link target
    """
    orig_params = {}
    sq_params = {}

    for key, value in request.GET.items():
        if key.startswith('sq_'):
            sq_params[key] = value
        else:
            orig_params[key] = value

    #send sq_params to task for further processing (stats, database operations for user, etc)
    process_click.delay(**sq_params)

    redirect_parsed_url = urlparse(sq_params['sq_target'])._replace(query=urlencode(orig_params))
    redirect_url = urlunparse(redirect_parsed_url)

    return HttpResponseRedirect(redirect_url)