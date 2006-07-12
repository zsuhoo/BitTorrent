# The contents of this file are subject to the BitTorrent Open Source License
# Version 1.1 (the License).  You may not copy or use this file, in either
# source code or executable form, except in compliance with the License.  You
# may obtain a copy of the License at http://www.bittorrent.com/license/.
#
# Software distributed under the License is distributed on an AS IS basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied.  See the License
# for the specific language governing rights and limitations under the
# License.

# Written by John Hoffman and Uoti Urpala

import os
from BitTorrent.hash import sha

_ = _ # put _ into the module namespace so the console doesn't override it

from BitTorrent.bencode import bencode, bdecode
from BitTorrent.btformats import check_message


NOISY = False

def parsedir(directory, parsed, files, blocked, errfunc,
             include_metainfo=True):
    """Recurses breadth-first starting from the passed 'directory'
       looking for .torrrent files.  Stops recursing in any given
       branch at the first depth that .torrent files are encountered.

       The directory, parsed, files, and blocked arguments are passed
       from the previous iteration of parsedir.

       @param directory: root of the breadth-first search for .torrent files.
       @param parsed: dict mapping infohash on to a dict containing
          torrent-specific info.
          
          Ex: consider movie 'Sea' referenced by metainfo file c.torrent.
          infohash -> 
          { path:'/a/b/c.torrent', file:'c.torrent', length:90911, name:'Sea',
            metainfo:<metainfo>} 
       @param files: dict mapping path -> [(modification time, size), infohash]
       @param blocked: dict used as set.  keys are list of paths of files
          that were not parsed on a prior call to parsedir for some reason.
          Valid reasons are that the .torrent file is unparseable or that a
          torrent with a matching infohash is alread in the parsed set.
       @param errfunc: error-reporting callback.
       @param include_metainfo:
       @return: The tuple (new parsed, new files, new blocked, added, removed)
          where 'new parsed', 'new files', and 'new blocked' are updated
          versions of 'parsed', 'files', and 'blocked' respectively. 'added'
          and 'removed' contain the changes made to the first three members
          of the tuple.  'added' and 'removed' are dicts mapping from
          infohash on to the same torrent-specific info dict that is in
          or was in parsed.
       """
    
    if NOISY:
        errfunc('checking dir')
    dirs_to_check = [directory]
    new_files = {}          # maps path -> [(modification time, size),infohash]
    new_blocked = {}        # used as a set.
    while dirs_to_check:    # first, recurse directories and gather torrents
        directory = dirs_to_check.pop()
        newtorrents = False
        try:
            dir_contents = os.listdir(directory)
        except (IOError, OSError), e:
            errfunc(_("Could not read directory ") + directory)
            continue
        for f in dir_contents:
            if f.endswith('.torrent'):
                newtorrents = True
                p = os.path.join(directory, f)
                try:
                    new_files[p] = [(os.path.getmtime(p),os.path.getsize(p)),0]
                except (IOError, OSError), e:
                    errfunc(_("Could not stat ") + p + " : " + unicode(e.args[0]))
        if not newtorrents:
            for f in dir_contents:
                p = os.path.join(directory, f)
                if os.path.isdir(p):
                    dirs_to_check.append(p)

    new_parsed = {}
    to_add = []
    added = {}
    removed = {}
    # files[path] = [(modification_time, size),infohash], hash is 0 if the file
    # has not been successfully parsed
    for p,v in new_files.items():   # re-add old items and check for changes
        oldval = files.get(p)
        if oldval is None:     # new file
            to_add.append(p)
            continue
        h = oldval[1]
        if oldval[0] == v[0]:   # file is unchanged from last parse
            if h:
                if p in blocked:      # parseable + blocked means duplicate
                    to_add.append(p)  # other duplicate may have gone away
                else:
                    new_parsed[h] = parsed[h]
                new_files[p] = oldval
            else:
                new_blocked[p] = None  # same broken unparseable file
            continue
        if p not in blocked and h in parsed:  # modified; remove+add
            if NOISY:
                errfunc(_("removing %s (will re-add)") % p)
            removed[h] = parsed[h]
        to_add.append(p)

    to_add.sort()
    for p in to_add:                # then, parse new and changed torrents
        new_file = new_files[p]
        v = new_file[0]             # new_file[0] is the file's (mod time,sz).
        if new_file[1] in new_parsed:  # duplicate, i.e., have same infohash.
            if p not in blocked or files[p][0] != v:
                errfunc(_("**warning** %s is a duplicate torrent for %s") %
                        (p, new_parsed[new_file[1]]['path']))
            new_blocked[p] = None
            continue

        if NOISY:
            errfunc('adding '+p)
        try:
            ff = open(p, 'rb')
            d = bdecode(ff.read())
            check_message(d)
            h = sha(bencode(d['info'])).digest()
            new_file[1] = h
            if new_parsed.has_key(h):
                errfunc(_("**warning** %s is a duplicate torrent for %s") %
                        (p, new_parsed[h]['path']))
                new_blocked[p] = None
                continue

            a = {}
            a['path'] = p
            f = os.path.basename(p)
            a['file'] = f
            i = d['info']
            l = 0
            nf = 0
            if i.has_key('length'):
                l = i.get('length',0)
                nf = 1
            elif i.has_key('files'):
                for li in i['files']:
                    nf += 1
                    if li.has_key('length'):
                        l += li['length']
            a['numfiles'] = nf
            a['length'] = l
            a['name'] = i.get('name', f)
            def setkey(k, d = d, a = a):
                if d.has_key(k):
                    a[k] = d[k]
            setkey('failure reason')
            setkey('warning message')
            setkey('announce-list')
            if include_metainfo:
                a['metainfo'] = d
        except:
            errfunc(_("**warning** %s has errors") % p)
            new_blocked[p] = None
            continue
        try:
            ff.close()
        except:
            pass
        if NOISY:
            errfunc(_("... successful"))
        new_parsed[h] = a
        added[h] = a

    for p,v in files.iteritems():       # and finally, mark removed torrents
        if p not in new_files and p not in blocked:
            if NOISY:
                errfunc(_("removing %s") % p)
            removed[v[1]] = parsed[v[1]]

    if NOISY:
        errfunc(_("done checking"))
    return (new_parsed, new_files, new_blocked, added, removed)
