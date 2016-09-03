#!/usr/bin/env python2
import pygtk
pygtk.require('2.0')
import gtk, notify2
from dbus.mainloop.glib import DBusGMainLoop
from threading import Lock
lock = Lock()

import re, urlparse

class LinkHolder(object):
    __slots__ = ('url', 'title', 'plain', 'type')
    def __init__(self, url=None, title=None, plain=None, type=None):
        self.url = url
        self.title = title
        self.plain = plain or url
        self.type = type
    def clear(self):
        self.url = self.plain = self.title = self.type = None
    def __nonzero__(self):
        return bool(self.url or self.plain or self.title)
    def __repr__(self):
        return "LinkHolder(%s, %s, %s, %s)" % (repr(self.url), repr(self.title), repr(self.plain), repr(self.type))
    @property
    def html(self):
        return '<a href="%s">%s</a>'%(self.url, self.title) if (self.title and self.url) else None
    @property
    def markdown(self):
        return '[%s](%s)'%(self.title, self.url)
    @property
    def mediawiki(self):
        return '[%s %s]'%(self.title, self.url)

class ImageHolder(LinkHolder):
    @property
    def html(self):
        return '<img src="%s"/>'%self.url if self.url else None
    @property
    def markdown(self):
        return '![%s](%s)'%(self.title or '',self.url)

class URLHandler(object):
    netloc = scheme = None
    def __init__(self, text):
        self.text = text
        url = urlparse.urlparse(text)

        if self.scheme is None: check_scheme = True
        elif hasattr(self.scheme, '__call__'): check_scheme = self.scheme(url.netloc)
        elif isinstance(self.scheme, basestring): check_scheme = (url.scheme==self.scheme)
        else: check_scheme = (url.scheme in self.scheme)

        if self.netloc is None: check_netloc = True
        elif hasattr(self.netloc, '__call__'): check_netloc = self.netloc(url.netloc)
        elif isinstance(self.netloc, basestring): check_netloc = (url.netloc==self.netloc)
        else: check_netloc = (url.netloc in self.netloc)
        
        if check_scheme and check_netloc:
            self.link = self.handle(url, url.path.split('/'))
        else:
            self.link = None

    @staticmethod
    def handle(link, url, path):
        pass
    
class SMBPathMatcher(URLHandler):
    scheme = ('smb','smbfs')
    def handle(self, url, path):
        uncpath = '\\\\' + url.netloc + '\\'.join(path)
        return LinkHolder(uncpath, '<tt>%s</tt>'%uncpath, type="Windows UNC path")

class WikipediaMatcher(URLHandler):
    scheme = ('http','https')
    netloc = staticmethod(lambda d: d.endswith(('.wikipedia.org','.wiktionary.org')))
    def handle(self, url, path):
        if len(path)>=3 and path[1]=='wiki':
            name = '/'.join(path[2:]).replace('_',' ')
            l = LinkHolder(self.text, name, type="%s article" % url.netloc.split('.')[-2])
            return l

class GithubMatcher(URLHandler):
    scheme = ('http','https')
    netloc = staticmethod(lambda d: d.startswith('github.') or d=='github.com')
    def handle(self, url, path):
        if len(path)>=5:
            owner, project, type, object = path[1:5]
            if type=='commit':
                object=object[:8]
            elif object.isdigit():
                object='#'+object
            return LinkHolder(self.text, "%s %s %s" % (project, type, object), type="Github "+type)

class BitbucketMatcher(URLHandler):
    scheme = ('http','https')
    netloc = ('bitbucket.org',)
    def handle(self, url, path):
        if len(path)>=5 and path[3]=='commits':
            return LinkHolder(self.text, "%s commit %s" % (path[2], path[4][:8]), type="Bitbucket commit")
        elif len(path)>=5 and path[3]=='branch':
            return LinkHolder(self.text, "%s branch %s" % (path[2], '/'.join(path[4:])), type="Bitbucket branch")
        elif len(path)>=5 and path[3]=='pull-requests':
            return LinkHolder(self.text, "%s pull-request #%s" % (path[2], path[4]), type="Bitbucket pull-request")

class JIRAMatcher(URLHandler):
    scheme = ('http','https')
    netloc = staticmethod(lambda d: d.endswith('.atlassian.net'))
    def handle(self, url, path):
        if len(path)>=3 and path[1]=='browse':
            return LinkHolder(self.text, path[2], type="JIRA task")
        elif len(path)>=4 and path[1]=='projects' and path[3]=='issues':
            return LinkHolder(self.text, path[3], type="JIRA task")

class ImageMatcher(URLHandler):
    scheme = ('http','https')
    def handle(self, url, path):
        fn = path[-1] if path else None
        ext = fn.split('.')[-1].upper() if (fn and '.' in fn) else None
        if ext in ('JPG','JPEG','PNG'):
            return ImageHolder(self.text, fn, type="%s image" % ext)

clip_handlers = [ WikipediaMatcher, GithubMatcher, BitbucketMatcher, SMBPathMatcher, JIRAMatcher, ImageMatcher ]

########################################
            
def get_func(clipboard, selectiondata, info, holder):
    if not holder.link:
        return
    target = selectiondata.get_target()
    #print '\n\nget', clipboard, selectiondata, info, lh
    #print target
    #print "Got request for clipboard as %s" % target

    fake_target = holder.force_text if ((target.startswith('text/plain') or target=="UTF8_STRING") and holder.force_text) else target
    
    if fake_target=="text/html": selectiondata.set(target, 8, holder.link.html)
    elif fake_target=="text/markdown": selectiondata.set(target, 8, holder.link.markdown)
    elif fake_target=="text/mediawiki": selectiondata.set(target, 8, holder.link.mediawiki)
    elif fake_target in ("UTF8_STRING",'text/plain'): selectiondata.set(target, 8, holder.link.plain)
    else: raise RuntimeError("unknown clipboard target: %s" % target)

    if holder.notif:
        holder.notif.close()
    target_name = {"html":"HTML","markdown":"Markdown","mediawiki":"MediaWiki","plain":"plain text","UTF8_STRING":"plain text"}[fake_target.split('/')[-1]]
    holder.notif = notif = notify2.Notification("Pasted %s" % (holder.link.type or 'link'), "Rendered as "+target_name, "edit-paste")
    if holder.link.url:
        notif.add_action('text/markdown', 'Markdown', force_text, holder)
        notif.add_action('text/mediawiki', 'MediaWiki', force_text, holder)
        notif.add_action('text/plain', 'Plain', force_text, holder)
    notif.show()

def clear_func(clipboard, holder):
    #print '\n\nclear', args, kwargs
    #clip.set_with_data([('text/html',0,1),('UTF8_STRING',0,0)], get_func, clear_func, textholder)
    #textholder[0] = None
    print "Cleared clipboard."
    holder.reset()

def force_text(notif, action, holder):
    print "Will output %s instead of plain text" % action
    holder.force_text = action
    
def owner_change(clipboard, event, holder):
    #print '\n\nowner_change', clipboard, event, linkholder
    if holder:
        return # prevent infinite loop
    
    text = clipboard.wait_for_text()
    if not text:
        return # nothing to do

    #print "Got text: %s" % repr(text)
    for clip_handler in clip_handlers:
        holder.link = link = clip_handler(text).link
        if link:
            print "Matched with %s: %s" % (clip_handler.__name__, link)
            targets = [('UTF8_STRING',0,0)]
            if link.url:
                targets += [('text/html',0,1),('text/markdown',0,2)]
                notif = holder.notif = notify2.Notification("Copied %s" % (link.type or 'link'), link.url, "edit-copy")
                notif.add_action('text/markdown', 'Markdown', force_text, holder)
                notif.add_action('text/mediawiki', 'MediaWiki', force_text, holder)
                notif.add_action('text/plain', 'Plain', force_text, holder)
            else:
                notif = holder.notif = notify2.Notification("Copied %s" % (link.type or 'text'), link.plain, "edit-copy").show()
            notif.show()
            clipboard.set_with_data(targets, get_func, clear_func, holder)
            break
    else:
        print "Got non-matching text (ignored)."

class Holder(object):
    def __init__(self):
        self.link = self.notif = self.force_text = None
    def __nonzero__(self):
        return bool(self.link or self.notif or self.force_text)
    def reset(self):
        self.link = self.notif = self.force_text = None

ml = DBusGMainLoop(set_as_default=True)
notify2.init('ecliptic', ml)
holder = Holder()
clip = gtk.clipboard_get()
clip.connect("owner_change", owner_change, holder)
gtk.main()
