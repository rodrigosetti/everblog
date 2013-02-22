# Everblog

Everblog is a proxy for any public notebook in Evernote. It shows the contents
of the public notebook in a "blog style".

There's no need to register or sign-up. Just hit `/username/puburi/` the get a
index of a public notebook.

## Installation

You can run everblog with any WSGI compliant web-server. The WSGI main
application is `everblog.application`. If using Gunicorn (http://gunicorn.org),
you can run as:

    $ gunicorn everblog:application

Also, please read `config.py` and create a file `config_local.py` with you
local configurations (i.e. it's a good idea to let another server handle the
statics, mapped in `STATIC_URL`).

## Requirements

 * Evernote python SDK (http://github.com/evernote/evernote-sdk-python)
 * Jinja2 (http://jinja.pocoo.org)
 * Python Memcached (https://pypi.python.org/pypi/python-memcached/)

## TODO

 * Show tags.
 * Allow comments.

