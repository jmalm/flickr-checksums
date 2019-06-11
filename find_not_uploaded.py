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

# You might use this, for example, as:
#
#   find ~/photos/ -name '*.jpg' -print0 | xargs -0 ./find-not-uploaded.py

import os
import sys
import re
from argparse import ArgumentParser
from flickr_checksum_tags import get_photo_by_checksum, PhotoNotFound, MultiplePhotosFound, SqliteDb
from common import configuration, expand_paths, md5sum
import flickrapi
import glob


def is_not_uploaded(filename, db, flickr, verbose=False):
    # Calculate md5 checksum.
    md5 = md5sum(filename)
    if verbose:
        print("filename was: "+filename)
        print("with md5 sum: "+md5)
    
    try:
        # First, look for entry in the local database.
        db_entries = db.find(md5=md5)
        if len(db_entries) == 1:
            photo_id = db_entries[0]['photo_id']
        elif len(db_entries) > 1:
            raise MultiplePhotosFound()
        else:
            # No entry found, try to find it on Flickr.
            photo = get_photo_by_checksum(flickr, md5=md5)
            photo_id = photo.attrib['id']
    except MultiplePhotosFound:
        if verbose:
            print("  ... multiple copies uploaded")
    except PhotoNotFound:
        if verbose:
            print("  ... not uploaded")
        return True
    else:
        if verbose:
            print("  ... already uploaded")
            print("  " + photo_id)
    return False


def main():
    parser = ArgumentParser()
    parser.add_argument('photos', nargs='+', metavar='PHOTO')
    parser.add_argument('-v', '--verbose', dest='verbose', default=False,
                    action='store_true',
                    help='Turn on verbose output')
    args = parser.parse_args()
    paths = expand_paths(args.photos)

    flickr = flickrapi.FlickrAPI(configuration['api_key'],configuration['api_secret'])
    flickr.authenticate_via_browser(perms='write')

    db_filename = os.path.join(os.environ['HOME'],'.flickr-photos-checksummed.db')
    db = SqliteDb(db_filename)

    for filename in paths:
        if is_not_uploaded(filename, db, flickr, args.verbose):
            print(filename)

if __name__ == '__main__':
    main()
