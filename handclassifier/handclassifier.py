"""A quick-and-dirty python GUI for facilitating hand-classifying text and
web content into arbitrary categories.

The basic framework is to use a tkinter gui window to present the possible
classes for each document, with the document itself presented in another
window:

* ManualTextClassifier presents text in a tkinter window
* ManualBrowserClassifierSingle uses the system web browser to render content
* ManualWaybackClassifierSingle looks up the wanted document by URL in an
  OpenWayback installation (http://www.netpreserve.org/openwayback) using the
  system web browser
* ManualWaybackClassifierLink looks up the wanted source document by URL in an
  OpenWayback installation (http://www.netpreserve.org/openwayback) using the
  system web browser and displays the link target to be classified.
* ManualWaybackPlusMongoDBClassifierSingle is equivalent to the Wayback
  classifier, but adds a fallback "Load from MongoDB" button to pull the text
  from a MongoDB instance

This code is largely by Tom Nicholls, based upon earlier work by Jonathan
Bright.

Copyright 2013-2017, Tom Nicholls and Jonathan Bright
contact: tom.nicholls@oii.ox.ac.uk

This work is available under the terms of the GNU General Purpose Licence
This program is free software: you can redistribute it and/or modify
it under the terms of version 2 of the GNU General Public License as published
by the Free Software Foundation.
This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.
You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>
"""

#Params, imports. The try/except blocks are for Python 2/3 handling
from __future__ import print_function
try:
    import tkinter
except ImportError:
    import Tkinter as tkinter
import sys
import os
import csv
import string
# These needed for the browser version
import webbrowser
import tempfile
import string
import atexit
import os
import re
try:
    from urllib.parse import unquote
except ImportError:
    from urllib import unquote
# This for the MongoDB version
import pymongo

class ManualTextClassifier(object):
    """Hand classify a set of text items using tkinter.

    items -- a list of 2+-tuples containing an identifier (such as a
        URL) for the output, the content itself, and any number of optional
        additional fields to be stored in the output csv. This could 
        usefully include, for example, Content-Type if it is wanted to
        preserve this in the output to help train a classifier. 
    labels -- a list of classification options to select from (default: [0,1])
    output -- a binary output stream (default: stdout)
    winx -- the desired width of the classification window in pixels (default:
        1280). Currently not used. 
    winy -- the desired height of the classification window in pixels (default:
        880).
    nprevclass -- the number of previously classified objects (in case
        of batch operation) (default: 0)
    callback -- a function to be called (with parameters identifier,
        classification) once a determination is made (default: None).
    csvdialect -- a csv.writer dialect to use when writing results (default:
        excel-tab).
    debug -- a text output stream for printing debug messages (default: None)
    pair -- classify the relationship between a pair of items; the second title
        and text should be passed as the third and fourth elements of
        the 'items' tuple (default: False)

    This class is also used as the base class for other classifiers in this
    module."""
    def __init__(self, items, labels=[0,1], output=sys.stdout,
                 winx=1280, winy=880, nprevclass=0, callback=None,
                 csvdialect='excel-tab', debug=None, pair=False):
        self.items = items
        self.idx = -1
        self.numclassified = {}
        self.nprevclass = nprevclass
        self._callback = callback
        self.labels = labels
        if len(labels) < 2:
            raise Exception("Classifier needs at least 2 labels")
        for label in self.labels:
            self.numclassified[label] = 0

        if debug:
            self._debug = debug
        else:
            self._debug = open(os.devnull, 'w')

        self.pair = pair

        self._output = output
        self._csvwriter = csv.writer(self._output, dialect=csvdialect)

        self.root = tkinter.Tk()
        self.buttons = []

        self._setup_root_window(winx, winy)
        self._setup_content()
        self.update_content()

        for i, label in enumerate(labels):
            self.buttons.append(
                tkinter.Button(
                    self.root,
                    text=label,
                    command= lambda j=label: self._on_button_click(j)))
            self.buttons[-1].grid(column=1+int(self.pair), row=1+i, sticky="SW", padx=10)

    def _setup_content(self):
        titlewidth = 90
        if self.pair:
            titlewidth = titlewidth // 2
        # Article title / URL label
        self.text_title = tkinter.Label(self.root, text="", anchor="w",
                                    fg="black", justify="left",
                                    font=("Helvetica", 16),
                                    width=titlewidth)
        self.text_title.grid(column=0,row=0, sticky='EW', padx=10)
        # Main box with content to classify
        self.content = self._get_content_object()
        self.content.grid(column=0, row=1, rowspan=20, sticky='NSEW', padx=10)

#        self.scrollbar = tkinter.Scrollbar(self.root,
#                                           command=self.content.yview)
#        self.scrollbar.grid(column=0, row=1, rowspan=20, sticky='NSE')
#        self.content.config(yscrollcommand=self.scrollbar.set)

        if self.pair:
            self.text_title_2 = tkinter.Label(self.root, text="", anchor="w",
                                        fg="black", justify="left",
                                        font=("Helvetica", 16),
                                        width=titlewidth)
            self.text_title_2.grid(column=1,row=0, sticky='EW', padx=10)


            # Second main box with content to classify
            self.content_2 = self._get_content_object()
            self.content_2.grid(column=1, row=1, rowspan=20, sticky='NSEW', padx=10)

#            self.scrollbar_2 = tkinter.Scrollbar(self.root,
#                                                 command=self.content_2.yview)
#            self.scrollbar_2.grid(column=1, row=1, rowspan=20, sticky='NSE')
#            self.content_2.config(yscrollcommand=self.scrollbar_2.set)

    def _get_content_object(self):
        return tkinter.Text(self.root, wrap=tkinter.WORD)

    def _setup_root_window(self, winx, winy):
        self.set_root_window_size(winx, winy)
        self.root.wm_title("Classifier")

    def set_root_window_size(self, winx, winy):
        """Set the size of the root classifier window.

        FIXME: Currently ignores winx and uses an alternative algorithm to lay
            out the window.

        winx -- width (px)
        winy -- height (px)
        """
        # FIXME: This is all a horrible hack.
        # self.root.geometry(''+str(winx)+'x'+str(winy))
        self.root.rowconfigure(1, minsize=30)
        allocated = 30
        for i in range(2, 1+len(self.labels)):
            self.root.rowconfigure(i, minsize=20)
            allocated += 20
        size = (winy - allocated) // (20 - len(self.labels))
        print("row size =", size, file=self._debug)
        for i in range(1+len(self.labels),21):
            self.root.rowconfigure(i, minsize=size)

    def set_title(self, t, t2=None):
        """Set the content window title(s).

        t -- title,
        t2 -- second title (default: None)"""
        self.text_title.config(text=t)
        if self.pair:
            self.text_title_2.config(text=t2)

    def clear_content(self):
        """Clear the content window."""
        self.content.delete(1.0, tkinter.END)
        if self.pair:
            self.content_2.delete(1.0, tkinter.END)

    def set_content(self):
        """(Indirectly) fill the content window with the next item."""
        self._set_text_content()

    def _set_text_content(self):
        self.clear_content()
        self.content.insert(tkinter.INSERT, self.items[self.idx][1])
        if self.pair:
            self.content_2.insert(tkinter.INSERT, self.items[self.idx][3])

    def update_content(self):
        """Update the content window with the next item to be classified."""
        self.idx += 1
        try:
            if self.pair:
                self.set_title(self.items[self.idx][0], self.items[self.idx][2])
            else:
                self.set_title(self.items[self.idx][0])
            self.set_content()
        except IndexError:
            print("Finished!", file=self._debug)
            self.root.destroy()
            self.root.quit()

    def write_result(self, item, result):
        """Write a hand classification to the output file as a CSV line.

        The written line is of the form:
            item[0],result,[item[2][item[3][...]]] (though in the CSV format
                specified in the class constructor).

        item -- one element of the items list passed to the class constructor.
            This will be a 2+-tuple containing an identifier (such as a
            URL) for the output, the content itself, and any number of optional
            additional fields to be stored in the output csv. This could 
            usefully include, for example, Content-Type if it is wanted to
            preserve this in the output to help train a classifier. 
        result -- a textual category
        """
        if self.pair:
            output = [item[0], item[2], result]+list(item[4:])
        else:
            output = [item[0], result]+list(item[2:])

        if self.nprevclass > 0:
            print(self.idx+1, '/', self.idx+self.nprevclass+1,
                    output, file=self._debug)
        else:
            print(self.idx+1,
                    output, file=self._debug)

        # Unfortunately, Python 2 and Python 3 have quite incompatible csv
        # modules: 3 expects unicode, 2 can't really handle unicode at all :-/
        if not sys.version_info > (3,):
            output = [s.encode('utf-8') for s in output]
        self._csvwriter.writerow(output)
        # Paranoia
        self._output.flush()

    def _on_button_click(self, result):
        """Handle a click on one of the result buttons.

        Normally run as a callback, writes the new result and triggers the
        content window to be updated with the next item of content. Also calls
        the callback function given to the class constructor if present.

        result -- the category to apply to the current item
        """ 
        itemlabel = self.items[self.idx]
        self.write_result(itemlabel, result)
        if self._callback:
            self._callback(itemlabel, result)
        self.update_content()

class ManualTextClassifierSingle(ManualTextClassifier):
    pass

class ManualBrowserClassifierSingle(ManualTextClassifier):
    """Hand classify a set of web items using tkinter and the system web
    browser.

    This is a subclass of ManualTextClassifierSingle. It overrides
    set_content() to display web content in the system browser rather than
    text in a separate window.

    It does not provide clear_content(), as this is not possible using
    python's webbrowser interface, and has a null implementation of
    set_title() for similar reasons.

    It does not (yet) handle the case where pair=True."""
    def __init__(self, *args, **kw):
        self._tempfns = []
        atexit.register(self._close_tempfiles)
        super(ManualBrowserClassifierSingle, self).__init__(*args, **kw)
        if self.pair:
            print("Pair classification not yet implemented in-browser")
            raise NotImplementedError

    def _get_content_object(self):
        # No window object in that sense
        raise NotImplementedError

    def _setup_root_window(self, winx, winy):
        (super(ManualBrowserClassifierSingle,self).
            _setup_root_window(winx, winy))
        # As we'll keep spawning web browser windows, stay on top
        self.root.attributes("-topmost", True)

    def _setup_content(self):
        self.content = webbrowser.get()

    def set_title(self, t):
        """Silently fails to change the content window title -- this is not
        possible through a web browser as we do not control the title."""
        pass

    def clear_content(self):
        """Not implemented -- cannot do this with the system web browser."""
        pass

    def set_content(self):
        """(Indirectly) load the web browser with the next item."""
        self._set_browser_content()

    def _set_browser_content(self, origurl = None, page_content=None):
        if not origurl:
            origurl=self.items[self.idx][0]
        if not page_content:
            page_content= self.items[self.idx][1]
        # Mangle URL into filename, so it shows up in the titlebar.
        # Take the first 100 characters, to avoid hitting OS limits.
        # Try Py3, fall back to Py2
        f = b'/#* '
        t = b'____'
        if sys.version_info >= (3,):
            trantab = bytes.maketrans(f,t)
        else:
            trantab = string.maketrans(f,t)
        suf= '__'+unquote(origurl).translate(trantab)[:100]+'.html'
        with tempfile.NamedTemporaryFile(suffix=suf, delete=False) as fh:
            self._tempfns.append(fh.name)
            fh.write(page_content.encode('utf-8'))
            url = 'file://'+fh.name
            self.content.open(url, new=0, autoraise=False)

    def _close_tempfiles(self):
        for fn in self._tempfns:
            try:
                os.unlink(fn)
            except OSError:
                print("File", fn, "already deleted.", file=self._debug)

class LinkClassifierMixin(object):
    """Mixin to hand classify a set of web links. Provides an additional window
    indicating the source and destination URLs for the link to be classified.

    The destination of the link to be classified is passed as the third
    element of each tuple in 'items'.

    items -- a list of 3+-tuples containing an identifier (such as a
        URL) for the output, the content itself, the target of the link to be
        classified and any number of optional additional fields to be stored 
        in the output csv. This could usefully include, for example,
        Content-Type if it is wanted to preserve this in the output to help
        train a classifier. 
    """
    def __init__(self, items, *args, **kw):
        try:
            _ = items[0][2]
        except IndexError:
            raise IndexError("When using LinkClassifierMixin the items tuples "
                             "must be of length 3+")
        # Set up the root environment and other stuff first
        super(LinkClassifierMixin, self).__init__(*args, items=items, **kw)
        # And then add a little link window
        self.linkwindow = tkinter.Toplevel(self.root)
        self._setup_link_window()
        # This will have been skipped during the root environment setup
        self._set_link_content()

    def _setup_link_window(self):
        # Main box with link names
        self.link_content = tkinter.Text(self.linkwindow,
                                         wrap=tkinter.WORD)
        self.link_content.grid(column=0, row=1, rowspan=2,
                               sticky='NSEW', padx=10)
        # Force to top
        self.linkwindow.attributes("-topmost", True)

    def clear_content(self):
        """Clear the links window."""
        try:
            self.link_content.delete(1.0, tkinter.END)
        except AttributeError:
            # Not set up yet
            pass
        # And cooperatively clear the main content window
        super(LinkClassifierMixin, self).clear_content()

    def _set_link_content(self):
        self.clear_content()
        try:
            self.link_content.insert(tkinter.INSERT,
                                     (self.items[self.idx][0]+'\n'+
                                      self.items[self.idx][2]))
        except AttributeError:
            # Not set up yet
            pass

    def set_content(self):
        """(Indirectly) fill the link windows with the next item."""
        self._set_link_content()
        # Cooperatively set the main content window
        super(LinkClassifierMixin, self).set_content()

class ManualWaybackClassifierSingle(ManualBrowserClassifierSingle):
    """Hand classify a set of HTML items using an OpenWayback installation,
    tkinter and the system web browser.

    This is a subclass of ManualBrowserClassifierSingle. It overrides
    set_content() to retrieve the HTMl content from OpenWayback rather than
    the items list passed to the constructor. As a result, the content
    part of the items tuple is irrelevant and can be None to save
    memory if desired.

    wburl -- the URL of the OpenWayback installation to be used (default:
        http://localhost:8080/wayback/
    """
    def __init__(self, wburl='http://localhost:8080/wayback/', *args, **kw):
        self.wburl = wburl
        super(ManualWaybackClassifierSingle, self).__init__(*args, **kw)

    def set_content(self):
        """(Indirectly) load the web browser with the next item."""
        self._set_wayback_content()

    def _set_wayback_content(self):
        # XXX: Make this configurable (via __init__?)
        url = self.items[self.idx][0]
#        url = re.sub(r'^https?://', '', url)
        url = self.wburl+url
        self.content.open(url, new=0, autoraise=False)

class ManualWaybackPlusMongoDBClassifierSingle(ManualWaybackClassifierSingle):
    """Hand classify a set of web items using an OpenWayback installation,
    a MongoDB database containing alternative textual content, tkinter and
    the system web browser.

    This is a subclass of ManualWaybackClassifierSingle. It adds an
    additional button to the classification window to retrieve text from
    a MongoDB database if needed. This is useful to allow a fallback in
    case the OpenWayback instance does not have (or cannot handle) the
    page required. It was implemented to handle WARC 'conversion' records
    with plain text versions of PDF/Word documents, which are not currently
    handled by OpenWayback.

    mongodb -- the name of the MongoDB database
    collection -- the name of the MongoDB collection
    client -- a pymongo client (default: pymongo.mongo_client.MongoClient()
        which by default tries to connect to the local machine)
    """
    def __init__(self, mongodb, collection, urlfield='url',
        contentfield='content',
        client=pymongo.mongo_client.MongoClient(), *args, **kw):
        self.mongoclient = client
        self.db = pymongo.database.Database(self.mongoclient, mongodb)
        self.collection = pymongo.collection.Collection(self.db, collection)
        self.urlfield = urlfield
        self.contentfield = contentfield

        super(ManualWaybackPlusMongoDBClassifierSingle, self).__init__(*args,
                                                                       **kw)
        self.fallbackbutton = tkinter.Button(self.root,
                    text='Load from MongoDB',
                    command=self._set_mongo_content)
        self.fallbackbutton.grid(column=1, row=len(self.buttons)+1,
                                 sticky="SW", padx=10)
    
    def _set_mongo_content(self):
        """Get fallback content from MongoDB and load it into the web browser.

        Runs on callback from the 'Load from MongoDB' button. Uses the
        configured pymongo client, database and collection to get text with
        a key matching the object we're currently classifying. 
        """
        url = self.items[self.idx][0]
        try:
            # This is a bit horrid.
            page_content = ((u'<html><head><meta http-equiv="Content-Type" '
                             u'content="text/html;charset=UTF-8"><head>'
                             u'<body><pre>')+
                             self.collection.find_one(
                                 {self.urlfield: url})[self.contentfield]+
                             u'</pre></body></html>')
        except Exception as e:
            page_content = ("Unable to fetch text from MongoDB for "+url+
                            ".\n\n(Collection is "+str(self.collection)+
                            ").\n\n"+str(e)+".\n\n")
            raise e
        finally:
            self._set_browser_content(page_content=page_content)

