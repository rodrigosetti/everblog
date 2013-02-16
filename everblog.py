#coding: utf-8

"""
A Web application that transforms an Evernote public notebook into a blog.
"""

import re
from urlparse import parse_qsl

INDEX_RE = re.compile(r'^/([\w_\-\+\.]{1,255})/([\w_\-\+\.]+)/?$')
def index(username, puburi, page=1, **kwars):
    """Handler for the /username/puburi/ URL, show the index of note"""

    # sanitize page parameter
    try:
        page = int(page)
        if page <= 0: page = 1
    except ValueError:
        page = 1

    return "username=%s, puburi=%s, page=%d\n" % (username, puburi, page)

NOTE_RE = re.compile(r'^/([\w_\-\+\.]{1,255})/([\w_\-\+\.]+)/([\w_\-\+\.]+)/?$')
def note(username, puburi, title, **kwargs):
    """Handler for the /username/puburi/title-slug URL, shows the note's
       content.
    """

    return "username=%s, puburi=%s, title=%s\n" % (username, puburi, title)

#: The list of matching regular expression paired with the callable handler
HANDLERS = ((INDEX_RE, index),
            (NOTE_RE, note))

class NotFoundException(Exception):
    """Exception to be raise by the handlers if they want to return a 404."""
    pass

def application(environment, start_response):
    """WSGI Application handler: check if the URL matches any of the handlers.
       if if does, call it with the captured regular expression values and
       parsed query-string as keyword parameters.
    """
    url = environment['PATH_INFO']
    query_params = dict(parse_qsl(environment['QUERY_STRING']))
    try:
        for regexp, handler in HANDLERS:
            m = regexp.match(url)
            if m:
                data = handler(*m.groups(), **query_params)
                break
        else:
            raise NotFoundException()
    except NotFoundException:
        start_response("404 Not found", [
            ("Content-Type", "text/plain"),
        ])
        return ["Not found."]

    start_response("200 OK", [
        ("Content-Type", "text/plain"),
        ("Content-Length", str(len(data)))
    ])
    return iter([data])

