# coding: utf-8

from binascii import hexlify
from xml.dom import Node
from xml.dom.minidom import parseString

#: To which html tag the en-note should be transformed
EN_NOTE_TAG = u'div'

class HTMLNote(object):
    """A converter from an Evernote note into it's HTML representation."""

    def __init__(self, note, shard_id):
        self.text = note.content
        self.shard_id = shard_id
        resources = [] if note.resources is None else note.resources
        self.hash_resources = dict((unicode(hexlify(r.data.bodyHash)), r) for r in resources)

    def to_html(self, img_width=800):
        document = parseString(self.text)
        self._dom_to_html(document, document, img_width)
        return document.toxml()

    def _dom_to_html(self, document, element, img_width):

        # Do some mapping from ENML tags to HTML
        if element.nodeName == 'en-note':
            element.tagName = EN_NOTE_TAG
        elif element.nodeName == 'en-todo':
            element.tagName = u'input'
            element.setAttribute('type', 'checkbox')
        elif element.nodeName == 'en-media':

            # get the resource info GUID from hash
            resource = self.hash_resources[element.getAttribute('hash')]

            # decide to show it as an "img" or "a" depending on the mime
            if resource.mime.startswith('image'):
                element.tagName = 'img'
                element.setAttribute('src',
                                 "https://www.evernote.com/shard/%s/res/%s/%s?resizeSmall=1&width=%d" %
                                     (self.shard_id, resource.guid, resource.attributes.fileName, img_width))
                element.setAttribute('width', str(img_width))
                if element.hasAttribute('height'): element.removeAttribute('height')
            else:
                element.tagName = 'a'
                element.setAttribute('href',
                                 "https://www.evernote.com/shard/%s/res/%s/%s" %
                                     (self.shard_id, resource.guid, resource.attributes.fileName))
                element.appendChild(document.createTextNode(resource.attributes.fileName))

        # For each of it's children, exclude the ones that are
        # not Element or Text
        to_remove = []
        for child in element.childNodes:
            if child.nodeType not in (Node.ELEMENT_NODE, Node.TEXT_NODE):
                # not a valid node, remove
                to_remove.append(child)
            elif child.nodeName == 'en-crypt':
                # don't support en-crypt. Remove it.
                to_remove.append(child)
            else:
                # process recursively the child
                self._dom_to_html(document, child, img_width)

        for child in to_remove:
            element.removeChild(child)

