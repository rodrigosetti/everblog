#coding: utf-8

"""
A Web application that transforms an Evernote public notebook into a blog.
"""

import os
import re
from urlparse import parse_qsl

from evernote.edam.error.ttypes import EDAMUserException, EDAMSystemException, EDAMNotFoundException
from evernote.edam.type.ttypes import NoteSortOrder
from evernote.edam.notestore import NoteStore
from evernote.edam.userstore import UserStore
import jinja2
import memcache
import thrift.protocol.TBinaryProtocol as TBinaryProtocol
import thrift.transport.THttpClient as THttpClient

from config import *
from enml import HTMLNote

#: Used to create ids from/to guids
ID_SYMBOLS = '0123456789abcdefghijklmnopqrstuvwxyz'

#: The evernote user store thrift API URL
EVERNOTE_USER_STORE_URL = "https://www.evernote.com/edam/user"

#: Seconds in an hour
HOUR = 60*60

class cached(object):
    """Cache using memcache method's return values using their positional
       parameters as kes.
    """

    def __init__(self, timeout=0):
        self.timeout = timeout

    def __call__(self, procedure):
        global cache

        def decorated(*args):
            key = ':'.join(str(arg) for arg in args)
            value = cache.get(key)
            if value is None:
              value = procedure(*args)
              if value is not None: cache.set(key, value, self.timeout)
            return value

        return decorated

class Index(object):
    """A wrapper to a collection of posts. Index."""
    def __init__(self, name, note_list):
        self.name = name
        self.posts = [{'title': note.title.decode('utf-8'),
                       'id': guid_to_id(note.guid)} for note in note_list.notes]
        self.has_next = note_list.totalNotes - (note_list.startIndex + len(note_list.notes)) > 0

class Post(object):
    """A representation of a post."""
    def __init__(self, note, shard_id, page=1):
        self.title = note.title.decode('utf-8')
        self.html = HTMLNote(note, shard_id).to_html()
        self.page = page

def int2str(num, base=16):
    """Transforms an integer into an arbitrary base string."""
    num, rem = divmod(num, base)
    ret = ''
    while num:
        ret = ID_SYMBOLS[rem] + ret
        num, rem = divmod(num, base)
    return ID_SYMBOLS[rem] + ret

def guid_to_id(guid):
    """Transforms a guid to an internal id representation."""
    return int2str(int(''.join(guid.split('-')), 16), base=36)

def id_to_guid(id):
    """Transforms the internal id representation into a guid."""
    s = int2str(int(id, 36), base=16).rjust(32, '0')
    return "-".join([s[:8], s[8:12], s[12:16], s[16:20], s[20:]])

def note_store_connect(url):
    http_client = THttpClient.THttpClient(url)
    procotol = TBinaryProtocol.TBinaryProtocol(http_client)
    return NoteStore.Client(procotol)

def user_store_connect():
    http_client = THttpClient.THttpClient(EVERNOTE_USER_STORE_URL)
    procotol = TBinaryProtocol.TBinaryProtocol(http_client)
    return UserStore.Client(procotol)

@cached()
def get_user(username):
    """Get user information for the username."""
    try:
        return user_store_connect().getPublicUserInfo(username)
    except EDAMNotFoundException as e:
        raise NotFoundException(data="User does not exist.")

@cached(12*HOUR)
def get_notes(note_store_url, notebook_guid, offset, limit):
    """Get a list of notes metadata from the notebook."""
    note_store = note_store_connect(note_store_url)
    note_filter = NoteStore.NoteFilter(order=NoteSortOrder.CREATED,
                                       ascending=False,
                                       notebookGuid=notebook_guid)
    result_spec = NoteStore.NotesMetadataResultSpec(includeTitle=True)
    note_list = note_store.findNotesMetadata("", note_filter, offset, limit, result_spec)
    if not note_list.notes: raise NotFoundException(data="Empty page.")
    else:
        return note_list

@cached(12*HOUR)
def get_note_offset(note_store_url, notebook_guid, note_guid):
    note_store = note_store_connect(note_store_url)
    note_filter = NoteStore.NoteFilter(order=NoteSortOrder.CREATED,
                                       ascending=False,
                                       notebookGuid=notebook_guid)
    return note_store.findNoteOffset("", note_filter, note_guid)

@cached(48*HOUR)
def get_notebook(note_store_url, user_id, puburi):
    """Get the public notebook for this user_id and public URL"""
    note_store = note_store_connect(note_store_url)
    try:
        return note_store.getPublicNotebook(user_id, puburi)
    except EDAMNotFoundException as e:
        raise NotFoundException(data="Notebook does not exist or is not public.")

@cached(24*HOUR)
def get_note(note_store_url, guid):
    """Get note with content from this guid."""
    note_store = note_store_connect(note_store_url)
    return note_store.getNote("", guid,
                              withContent=True,
                              withResourcesData=False,
                              withResourcesRecognition=False,
                              withResourcesAlternateData=False)

def get_index(username, puburi, page, page_size):
    """Get the index object from this username, puburi and page."""
    user = get_user(username)
    notebook = get_notebook(user.noteStoreUrl, user.userId, puburi)
    notes = get_notes(user.noteStoreUrl, notebook.guid,
                      (page-1)*page_size,
                      page_size)
    return Index(notebook.name, notes)

def get_post(username, puburi, post_id):
    user = get_user(username)
    notebook = get_notebook(user.noteStoreUrl, user.userId, puburi)
    note = get_note(user.noteStoreUrl, id_to_guid(post_id))
    page = (get_note_offset(user.noteStoreUrl, notebook.guid, note.guid) / PAGE_SIZE) + 1
    return Post(note, user.shardId, page)

ROOT_RE = re.compile(r'^/?$')
def root_handler():
    raise HttpRedirectPermanently(DEFAULT_ROOT)

USER_RE = re.compile(r'^/([\w_\-\+\.]{1,255})/?$')
def user_handler(username):
    raise HttpRedirectPermanently("/%s/%s" % (username, DEFAULT_PUBURI))

INDEX_RE = re.compile(r'^/([\w_\-\+\.]{1,255})/([\w_\-\+\.]+)/?$')
def index_handler(username, puburi, page=1, **kwars):
    """Handler for the /username/puburi/ URL, show the index of post"""

    # sanitize page parameter
    try:
        page = int(page)
        if page <= 0: page = 1
    except ValueError:
        page = 1

    # get index information
    index = get_index(username, puburi, page, PAGE_SIZE)

    # render index into HTML
    template = template_env.get_template('index.html')
    data = template.render(STATIC_URL=STATIC_URL, index=index,
                           username=username, puburi=puburi, page=page)
    return [data.encode('utf-8')], [("Content-Type", "text/html")]

POST_RE = re.compile(r'^/([\w_\-\+\.]{1,255})/([\w_\-\+\.]+)/([a-z0-9]+)/?$')
def post_handler(username, puburi, post_id, **kwargs):
    """Handler for the /username/puburi/title-slug URL, shows the post's
       content.
    """
    # get post information
    post = get_post(username, puburi, post_id)

    # render post to HTML
    template = template_env.get_template('post.html')
    data = template.render(STATIC_URL=STATIC_URL, post=post, username=username,
                           puburi=puburi, post_id=post_id)
    return [data.encode('utf-8')], [("Content-Type", "text/html")]

STATIC_RE = re.compile(r'^/static/(\w[\w\-_\/]+(?:\.css|\.js|\.html))$')
@cached()
def static_handler(path):
    """Debug handler for static files"""
    filename = os.path.join(STATIC_ROOT, path)
    if not os.path.exists(filename):
        raise NotFoundException(data="")

    if path.endswith('.css'): mime = 'text/css'
    elif path.endswith('.js'): mime = 'application/javascript'
    else: mime = 'application/octet-stream'

    with open(filename) as f:
        return [f.read()], [('Content-Type', mime)]

#: The list of matching regular expression paired with the callable handler
HANDLERS = ((ROOT_RE, root_handler),
            (USER_RE, user_handler),
            (INDEX_RE, index_handler),
            (POST_RE, post_handler),
            (STATIC_RE, static_handler))

class HttpException(Exception):
    """A non-OK http status"""
    def __init__(self, status, headers=(), data=''):
        super(HttpException, self).__init__(status)
        self.status = status
        self.headers = headers
        self.data = data

class NotFoundException(HttpException):
    """A 404 http status"""
    def __init__(self,
                 headers=[("Content-Type", "text/plain")],
                 data="Not found."):
        super(NotFoundException, self).__init__("404 Not found", headers, data)

class HttpRedirectPermanently(HttpException):
    def __init__(self, location):
        super(HttpRedirectPermanently, self).__init__("301 Moved Permanently",
                                                      [("Location", location)])

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
                data, headers = handler(*m.groups(), **query_params)
                break
        else:
            raise NotFoundException()
    except HttpException as e:
        start_response(e.status, e.headers)
        return [e.data]

    start_response("200 OK", headers)
    return data

# Start memcache client
cache = memcache.Client(MEMCACHE_SERVERS)

#: Create the template loader (for HTML pages)
template_env = jinja2.Environment(loader=jinja2.FileSystemLoader(
                        os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                     "templates"))))

