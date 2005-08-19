# The contents of this file are subject to the BitTorrent Open Source License
# Version 1.0 (the License).  You may not copy or use this file, in either
# source code or executable form, except in compliance with the License.  You
# may obtain a copy of the License at http://www.bittorrent.com/license/.
#
# Software distributed under the License is distributed on an AS IS basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied.  See the License
# for the specific language governing rights and limitations under the
# License.

# written by Matt Chisholm

import os
import sys
import urllib
import pickle
import threading
from sha import sha

from BitTorrent import ERROR, WARNING, BTFailure, version, app_name
from BitTorrent import GetTorrent
from BitTorrent.bencode import bdecode, bencode
from BitTorrent.platform import os_version, spawn, get_temp_dir, doc_root
from BitTorrent.ConvertedMetainfo import ConvertedMetainfo

# needed for py2exe to include the public key lib
from Crypto.PublicKey import DSA

version_host = 'http://version.bittorrent.com/'
download_url = 'http://bittorrent.com/download.html'

# based on Version() class from ShellTools package by Matt Chisholm,
# used with permission
class Version(list):
    def __str__(self):
        return '.'.join(map(str, self))

    def is_beta(self):
        return self[1] % 2 == 1

    def from_str(self, text):
        return Version( [int(t) for t in text.split('.')] )

    def name(self):
        if self.is_beta():
            return 'beta'
        else:
            return 'stable'
    
    from_str = classmethod(from_str)

currentversion = Version.from_str(version)

availableversion = None

DEBUG = False

class Updater(object):
    def __init__(self, threadwrap, newversionfunc, startfunc, installfunc, errorfunc):
        self.threadwrap     = threadwrap  # for calling back to UI from thread
        self.newversionfunc = newversionfunc # alert to new version UI function
        self.startfunc      = startfunc   # start torrent UI function
        self.installfunc    = installfunc # install torrent UI function
        self.errorfunc      = errorfunc   # report error UI function
        self.infohash = None
        self.version = currentversion
        self.asked_for_install = False
        self.version_site = version_host
        if os.name == 'nt':
            self.version_site += 'win32/'
            if os_version != 'XP':
                self.version_site += 'legacy/'

    def debug(self, message):
        if DEBUG:
            self.threadwrap(self.errorfunc, WARNING, message)

    def get_available(self):
        url = self.version_site + currentversion.name()
        self.debug('Updater.get_available() hitting url %s' % url)
        try:
            u = urllib.urlopen(url)
            s = u.read()
            s = s.strip()
        except:
            raise BTFailure(_("Could not get latest version from %s")%url)
        try:
            assert len(s) == 5
            availableversion = Version.from_str(s)
        except:
            raise BTFailure(_("Could not parse new version string from %s")%url)
        self.version = availableversion
        self.debug('Updater.get_available() got %s' % str(self.version))
        return self.version


    def get(self):
        try:
            self.get_available()
        except BTFailure, e:
            self.threadwrap(self.errorfunc, WARNING, e)
            return 

        if self.version <= currentversion:
            self.debug('Updater.get() not updating old version %s' % str(self.version))
            return

        if not self.can_install():
            self.debug('Updater.get() cannot install on this os')
            return

        self.installer_name = self.calc_installer_name()
        self.installer_url  = self.version_site + self.installer_name + '.torrent'
        self.installer_dir  = self.calc_installer_dir()

        self.torrentfile = None
        torrentfile, terrors = GetTorrent.get_url(self.installer_url)
        signfile = urllib.urlopen(self.installer_url + '.sign')
        try:
            signature = pickle.load(signfile)
        except:
            self.debug('Updater.get() failed to load signfile %s' % signfile)
            signature = None
        
        if terrors:
            self.threadwrap(self.errorfunc, WARNING, '\n'.join(terrors))

        if torrentfile and signature:
            public_key_file = open(os.path.join(doc_root, 'public.key'), 'rb')
            public_key = pickle.load(public_key_file)
            h = sha(torrentfile).digest()
            if public_key.verify(h, signature):
                self.torrentfile = torrentfile
                b = bdecode(torrentfile)
                self.infohash = sha(bencode(b['info'])).digest()
                self.total_size = b['info']['length']
                self.debug('Updater.get() got torrent file and signature')
            else:
                self.debug('Updater.get() torrent file signature failed to verify.')
                pass
        else:
            self.debug('Updater.get() doesn\'t have torrentfile %s and signature %s' %
                       (str(type(torrentfile)), str(type(signature))))

    def installer_path(self):
        if self.installer_dir is not None:
            return os.path.join(self.installer_dir,
                                self.installer_name)
        else:
            return None
        
    def check(self):
        t = threading.Thread(target=self._check,
                             args=())
        t.start()

    def _check(self):
        self.get()
        if self.version > currentversion:
            self.threadwrap(self.newversionfunc, self.version, download_url)

    def can_install(self):
        if DEBUG:
            return True
        if os.name == 'nt':
            return True
        else:
            return False

    def calc_installer_name(self):
        if os.name == 'nt':
            ext = 'exe'
        elif os.name == 'posix' and DEBUG: 
            ext = 'tar.gz' 
        else:
            return
        
        parts = [app_name, str(self.version)]
        if self.version.is_beta():
            parts.append('Beta')
        name = '-'.join(parts)
        name += '.' + ext
        return name

    def set_installer_dir(self, path):
        self.installer_dir = path
        
    def calc_installer_dir(self):
        if hasattr(self, 'installer_dir'):
            return self.installer_dir
        
        temp_dir = get_temp_dir()
        if temp_dir is not None:
            return temp_dir
        else:
            self.errorfunc(WARNING,
                           _("Could not find a suitable temporary location to "
                             "save the %s %s installer.") % (app_name, self.version))

    def installer_downloaded(self):
        if self.installer_path() and os.access(self.installer_path(), os.F_OK):
            size = os.stat(self.installer_path())[6]
            if size == self.total_size:
                return True
            else:
                #print 'installer is wrong size, is', size, 'should be', self.total_size
                return False
        else:
            #print 'installer does not exist'
            return False

    def download(self):
        if self.torrentfile is not None:
            self.startfunc(self.torrentfile, self.installer_path())
        else:
            self.errorfunc(WARNING, _("No torrent file available for %s %s "
                                      "installer.")%(app_name, self.version))

    def start_install(self):
        if not self.asked_for_install:
            self.asked_for_install = True
            if self.installer_downloaded():
                self.installfunc()
            else:
                self.errorfunc(WARNING,
                               _("%s %s installer appears to be corrupt "
                                 "or missing.")%(app_name, self.version))

    def launch_installer(self):
        if os.name == 'nt':
            os.startfile(self.installer_path())
        else:
            self.errorfunc(WARNING, _("Cannot launch installer on this OS"))