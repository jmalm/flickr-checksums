#!/usr/bin/env python2.5

# Copyright 2009 Mark Longair

#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.

# This depends on a couple of packages:
#   apt-get install python-pysqlite2 python-flickrapi

import os
import sys
import re
import xml
import tempfile
import time
from subprocess import call, Popen, PIPE
import flickrapi
from common import *

# There are more details about the meaning of these size
# codes here:
#
#   http://www.flickr.com/services/api/misc.urls.html

valid_size_codes = ( "s", "t", "m", "-", "b", "o" )
v = [ '"'+x+'"' for x in valid_size_codes ]
valid_size_codes_sentence = ", ".join(v[0:-1]) + " or " + v[-1]


class Throttler:
    MAX_REQUESTS_PER_PERIOD = 3600
    PERIOD_IN_SECONDS = 3600

    def __init__(self):
        self.reset()
    
    def register(self):
        self.n_requests += 1
        if self.n_requests > self.MAX_REQUESTS_PER_PERIOD - 10:
            time_left = self.start + self.PERIOD_IN_SECONDS - time.time()
            if time_left > 0:
                sleep_time = int(time_left + 10)
                print("Flickr API usage almost exceeded {0} within {2} seconds. Sleeping {1} seconds.".format(
                    self.MAX_REQUESTS_PER_PERIOD, sleep_time, self.PERIOD_IN_SECONDS))
                time.sleep(sleep_time)
            self.reset()
    
    def reset(self):
        self.n_requests = 0
        self.start = time.time()


throttler = Throttler()


class SqliteDb:
    def __init__(self, db_filename):
        from sqlite3 import dbapi2 as sqlite

        self.connection = sqlite.connect(db_filename)
        self.cursor = self.connection.cursor()
        self.cursor.execute("CREATE TABLE IF NOT EXISTS `done` "
                            "( `photo_id` text unique, "
                            "  `md5` text, "
                            "  `sha1` text )")

    def find(self, photo_id=None, md5=None, sha1=None):
        if photo_id:
            self.cursor.execute("SELECT * FROM done WHERE photo_id = ?", (photo_id,))
        elif md5:
            self.cursor.execute("SELECT * FROM done WHERE md5 = ?", (md5,))
        if sha1:
            self.cursor.execute("SELECT * FROM done WHERE sha1 = ?", (sha1,))
        return [dict(photo_id=i, md5=m, sha1=s) for i, m, s in self.cursor.fetchall()]

    def add_to_done(self, photo_id, md5, sha1):
        self.cursor.execute("INSERT INTO done VALUES ( ?, ?, ? )", (photo_id, md5, sha1,))
        self.connection.commit()
    
    def remove_photo(self, photo_id):
        self.cursor.execute("DELETE FROM done WHERE photo_id = ?", (photo_id,))
        self.connection.commit()


# Return the Flickr NSID for a username or alias:
def get_nsid(username_or_alias, flickr):
    try:
        # If someone provides their real username (i.e. [USERNAME] in
        # "About [USERNAME]" on their profile page, then this call
        # should work:
        throttler.register()
        user = flickr.people_findByUsername(username=username_or_alias)
    except flickrapi.exceptions.FlickrError:
        # However, people who've set an alias for their Flickr URLs
        # sometimes think their username is that alias, so try that
        # afterwards.  (That's [ALIAS] in
        # http://www.flickr.com/photos/[ALIAS], for example.)
        try:
            throttler.register()
            username = flickr.urls_lookupUser(url="http://www.flickr.com/people/"+username_or_alias)
            user_id = username.getchildren()[0].getchildren()[0].text
            throttler.register()
            user = flickr.people_findByUsername(username=user_id)
        except flickrapi.exceptions.FlickrError:
            return None
    return user.getchildren()[0].attrib['nsid']

# Return a dictionary with any machine tag checksums found for a photo
# element:
def get_photo_checksums(photo):
    md5_match = re.compile(md5_machine_tag_prefix + r'([0-9a-f]{32})')
    sha1_match = re.compile(sha1_machine_tag_prefix + r'([0-9a-f]{40})')

    result = {}
    try:
        tags = [photo.attrib['tags']]
    except KeyError:
        try:
            tags = [photo.attrib['machine_tags']]
        except KeyError:
            tags = [t.attrib['raw'] for t in photo.find('tags')]

    for t in tags:
        m_md5 = md5_match.search(t)
        if m_md5 and len(m_md5.group(1)) == 32:
            print("Got MD5sum machine tag")
            result['md5'] = m_md5.group(1)
        m_sha1 = sha1_match.search(t)
        if m_sha1 and len(m_sha1.group(1)) == 40:
            print("Got SHA1sum machine tag")
            result['sha1'] = m_sha1.group(1)

    return result

def info_to_url(photo_info,size=""):
    a = photo_info.getchildren()[0].attrib
    if size in ( "", "-" ):
        return 'http://farm%s.static.flickr.com/%s/%s_%s.jpg' %  (a['farm'], a['server'], a['id'], a['secret'])
    elif size in ( "s", "t", "m", "b" ):
        return 'http://farm%s.static.flickr.com/%s/%s_%s_%s.jpg' %  (a['farm'], a['server'], a['id'], a['secret'], size)
    elif size == "o":
        return 'http://farm%s.static.flickr.com/%s/%s_%s_o.%s' %  (a['farm'], a['server'], a['id'], a['originalsecret'], a['originalformat'])
    else:
        raise Exception("Unknown size ("+size+") passed to info_to_url()")


def add_checksum(options, flickr):
    db_filename = os.path.join(os.environ['HOME'],'.flickr-photos-checksummed.db')
    db = SqliteDb(db_filename)

    nsid = get_nsid(options.add_tags, flickr)
    if not nsid:
        print("Couldn't find the username or alias '"+options.add_tags)

    print("Got nsid: %s for '%s'" % ( nsid, options.add_tags ))

    throttler.register()
    user_info = flickr.people_getInfo(user_id=nsid)
    photos_url = user_info.getchildren()[0].find('photosurl').text

    per_page = 500
    page = 1

    while True:
        print("Getting page {0} (photos {1} to {2})".format(page, (page - 1) * per_page + 1, page * per_page))
        throttler.register()
        photos = flickr.photos_search(user_id=nsid, per_page=str(per_page), page=page, media='photo', extras='machine_tags,url_o')
        photo_elements = photos.getchildren()[0]
        n_flickr_requests_last_photo = throttler.n_requests
        print("----------------------------------------------------------------")
        for photo in photo_elements:
            print("Flickr API requests: {0} ({1} in {2} s)".format(
                throttler.n_requests - n_flickr_requests_last_photo, throttler.n_requests,
                int(time.time() - throttler.start)))
            n_flickr_requests_last_photo = throttler.n_requests
            title = photo.attrib['title']
            print("===== {0} (page {1}) =====".format(title, page))
            if db.find(photo_id=photo.attrib['id']):
                continue
            print("Photo page URL is: "+photos_url+photo.attrib['id'])
            
            # We got the info we need in the search request directly.
            #throttler.register()
            #photo_info = flickr.photos_getInfo(photo_id=photo.attrib['id']).getchildren()[0]

            # Check if the checksums are already there:
            checksums = get_photo_checksums(photo)
            print("Existing checksums were: "+", ".join(list(checksums.keys())))
            if ('md5' in checksums) and ('sha1' in checksums):
                # Then there's no need to download the image...
                pass
            else:
                # Otherwise fetch the original image,
                # calculate its checksums and set those tags:
                checksums = fetch_and_tag(photo, flickr)
            db.add_to_done(photo.attrib['id'], checksums['md5'], checksums['sha1'])
        if len(photo_elements) < per_page:
            break
        page += 1


def fetch_and_tag(photo, flickr):
    farm_url = photo.attrib['url_o']
    print("farm_url is: "+farm_url)

    import certifi
    import urllib3
    pool = urllib3.PoolManager(cert_reqs='CERT_REQUIRED',
                               ca_certs=certifi.where())
    response = pool.request('GET', farm_url)

    import hashlib
    real_md5sum = hashlib.md5(response.data).hexdigest()
    real_sha1sum = hashlib.sha1(response.data).hexdigest()
    print("Calculated MD5: "+real_md5sum)
    print("Calculated SHA1: "+real_sha1sum)

    print("Setting tags...")
    throttler.register()
    flickr.photos_addTags(photo_id=photo.attrib['id'],
        tags=" ".join([md5_machine_tag_prefix + real_md5sum,
                       sha1_machine_tag_prefix + real_sha1sum]))
    print("... done.")

    return dict(md5=real_md5sum, sha1=real_sha1sum)


class MalformedChecksum(Exception):
    pass


class PhotoNotFound(Exception):
    pass


class MultiplePhotosFound(Exception):
    pass


def get_photo_by_checksum(flickr, md5='', sha1=''):
    # Setup the tag to search for:
    if md5:
        if not re.search('^'+checksum_pattern+'$',md5):
            message = ("The MD5sum ('"+md5+"') was malformed.\n"
                       "It must be 32 letters long, each one of 0-9 or a-f.")
            raise MalformedChecksum(message)
        search_tag = md5_machine_tag_prefix + md5
    elif sha1:
        if not re.search('^'+checksum_pattern+'$',sha1):
            message = ("The SHA1sum ('"+md5+"') was malformed.\n"
                       "It must be 40 letters long, each one of 0-9 or a-f.")
            raise MalformedChecksum(message)
        search_tag = sha1_machine_tag_prefix + sha1
    else:
        raise RuntimeError("Either md5 or sha1 must be provided.")

    throttler.register()
    photos = flickr.photos_search(user_id="me",tags=search_tag, extras='url_s,url_t,url_m,url_o')  # "s", "t", "m", "-", "b", "o"
    photo_elements = photos.getchildren()[0]
    if 0 == len(photo_elements):
        raise PhotoNotFound()
    if 1 != len(photo_elements):
        message = "Expected exactly 1 result searching for tag "+search_tag+"; actually got "+str(len(photo_elements))
        message += "\nThe photos were:"
        for p in photo_elements:
            message += "\n  http://www.flickr.com/photos/"+p.attrib['owner']+"/"+p.attrib['id']+" (\""+p.attrib['title']+"\")"
        raise MultiplePhotosFound(message)
    return photo_elements[0]


def main():
    from argparse import ArgumentParser

    parser = ArgumentParser()
    parser.add_argument('-a', '--add-tags', dest='add_tags',
                    metavar='USERNAME',
                    help='add checksum machine tags for [USERNAME]\'s photos')
    parser.add_argument('-m', dest='md5',
                    metavar='MD5SUM',
                    help='find my photo on Flickr with MD5sum [MD5SUM]')
    parser.add_argument('-s', dest='sha1',
                    metavar='SHA1SUM',
                    help='find my photo on Flickr with SHA1sum [SHA1SUM]')
    parser.add_argument('-p', dest='photo_page', default=False, action='store_true',
                    help='Output the photo page URL (the default with -m and -s)')
    parser.add_argument('--size',dest='size',metavar='SIZE',
                    help='Output the URL for different sized images ('+valid_size_codes_sentence+')')
    parser.add_argument('--short',dest='short', default=False, action='store_true',
                    help='Output the short URL for the image')

    options = parser.parse_args()

    mutually_exclusive_options = [ options.add_tags, options.md5, options.sha1 ]

    if 1 != len([x for x in mutually_exclusive_options if x]):
        print("You must specify exactly one of '-a', '-m' or 's':")
        parser.print_help()
        sys.exit(1)

    if options.photo_page and options.size:
        print("options.photo_page is "+str(options.photo_page))
        print("You can specify at most one of -p and --size")
        parser.print_help()
        sys.exit(1)

    if options.size and (options.size not in valid_size_codes):
        print("The argument to --size must be one of: "+valid_size_codes_sentence)

    flickr = flickrapi.FlickrAPI(configuration['api_key'],configuration['api_secret'])
    throttler.register()
    flickr.authenticate_via_browser(perms='write')

    if options.md5 or options.sha1:
        photo = get_photo_by_checksum(flickr, md5=options.md5, sha1=options.sha1)
        photo_id = photo.attrib['id']
        throttler.register()
        photo_info = flickr.photos_getInfo(photo_id=photo_id).getchildren()[0]

        just_photo_page_url = not (options.size or options.short)
        if just_photo_page_url:
            throttler.register()
            user_info = flickr.people_getInfo(user_id=photo.attrib['owner']).getchildren()[0]
            print(user_info.find('photosurl').text+photo_id)
        elif options.size:
            print(info_to_url(photo_info,size=options.size))
        if options.short:
            print(short_url(photo_id))
    else:
        add_checksum(options, flickr)


if __name__ == '__main__':
    main()