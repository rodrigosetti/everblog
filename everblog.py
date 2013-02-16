#coding: utf-8

"""
A Web application that transforms an Evernote public notebook into a blog.
"""

import memcache
import re
from urlparse import parse_qsl

from evernote.edam.notestore import NoteStore
from evernote.edam.userstore import UserStore
import thrift.protocol.TBinaryProtocol as TBinaryProtocol
import thrift.transport.THttpClient as THttpClient

#: Number of post per page
PAGE_SIZE = 50

#: The memcache server list
MEMCACHE_SERVERS = ["localhost:11211"]

#: Used to create ids from/to guids
ID_SYMBOLS = '0123456789abcdefghijklmnopqrstuvwxyz'

#: The evernote user store thrift API URL
EVERNOTE_USER_STORE_URL = "https://www.evernote.com/edam/user"

class cached(object):
    """Cache using memcache method's return values using their positional
       parameters as kes.
    """

    def __init__(self, procedure):
        self.procedure = procedure

    def __call__(self, *args):
        global cache
        key = ':'.join(str(arg) for arg in args)
        value = cache.get(key)
        if value is None:
          value = self.procedure(*args)
          if value is not None: cache.set(key, value)
        return value

class Index(object):
    """A wrapper to a collection of posts. Index."""
    def __init__(self, name, note_list):
        self.name = name
        self.posts = [{'title': note.title,
                       'id': guid_to_id(note.guid)} for note in note_list.notes]
        self.has_next = note_list.totalNotes - (note_list.startIndex + len(note_list.notes)) > 0


class Post(object):
    """A representation of a post."""
    def __init__(self, note):
        self.title = note.title
        self.html = note.content

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
    s = int2str(int(id, 36), base=16)
    return "-".join([s[:8], s[8:12], s[12:16], s[16:20], s[20:]])

def note_store_connect(url):
    http_client = THttpClient.THttpClient(url)
    procotol = TBinaryProtocol.TBinaryProtocol(http_client)
    return NoteStore.Client(procotol)

def user_store_connect():
    http_client = THttpClient.THttpClient(EVERNOTE_USER_STORE_URL)
    procotol = TBinaryProtocol.TBinaryProtocol(http_client)
    return UserStore.Client(procotol)

@cached
def get_user(username):
    """Get user information for the username."""
    return user_store_connect().getPublicUserInfo(username)

@cached
def get_notes(note_store_url, notebook_guid, offset, limit):
    """Get a list of notes metadata from the notebook."""
    note_store = note_store_connect(note_store_url)
    note_filter = NoteStore.NoteFilter(notebookGuid=notebook_guid)
    result_spec = NoteStore.NotesMetadataResultSpec(includeTitle=True)
    return note_store.findNotesMetadata("", note_filter, offset, limit, result_spec)

@cached
def get_notebook(note_store_url, user_id, puburi):
    """Get the public notebook for this user_id and public URL"""
    note_store = note_store_connect(note_store_url)
    return note_store.getPublicNotebook(user_id, puburi)

@cached
def get_note(note_store_url, guid):
    """Get note with content from this guid."""
    note_store = note_store_connect(note_store_url)
    return note_store.getNote("", guid,
                              withContent=True,
                              withResourcesData=False,
                              withResourcesRecognition=False,
                              withResourcesAlternateData=False)

@cached
def get_index(username, puburi, page, page_size):
    """Get the index object from this username, puburi and page."""
    user = get_user(username)
    if not user: raise NotFoundException()
    notebook = get_notebook(user.noteStoreUrl, user.userId, puburi)
    if not notebook: raise NotFoundException()
    notes = get_notes(user.noteStoreUrl, notebook.guid,
                      (page-1)*page_size,
                      page_size)
    return Index(notebook.name, notes)

@cached
def get_post(username, puburi, post_id):
    user = get_user(username)
    notebook = get_notebook(user.noteStoreUrl, user.userId, puburi)
    if not notebook: raise NotFoundException()
    note = get_note(user.noteStoreUrl, id_to_guid(post_id))
    return Post(note)

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
    yield "<h1>%s</h1>" % index.name
    yield "<ul>"
    for post in index.posts:
        yield ('<li><a href="/%s/%s/%s" title="%s">%s</a></li>' %
               (username, puburi, post['id'], post['title'], post['title']))
    yield "</ul>"
    if index.has_next:
        yield ('<p><a href="/%s/%s/?page=%d" title="next page">Next page (%d)</a></p>' %
               (username, puburi, page+1, page+1))

POST_RE = re.compile(r'^/([\w_\-\+\.]{1,255})/([\w_\-\+\.]+)/([a-z0-9]+)/?$')
def post_handler(username, puburi, title_slug, **kwargs):
    """Handler for the /username/puburi/title-slug URL, shows the post's
       content.
    """
    # get post information
    post = get_post(username, puburi, title_slug)

    # render post to HTML
    yield "<h1>%s</h1>" % post.title
    yield '<div id="content">'
    yield post.html
    yield "</div>"

#: The list of matching regular expression paired with the callable handler
HANDLERS = ((INDEX_RE, index_handler),
            (POST_RE, post_handler))

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
    except Exception:
        start_response("500 Internal Server Error", [
            ("Content-Type", "text/plain"),
        ])
        return ["Server error."]

    start_response("200 OK", [
        ("Content-Type", "text/html"),
    ])
    return data

# Start memcache client
cache = memcache.Client(MEMCACHE_SERVERS)

