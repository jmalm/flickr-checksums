#!/usr/bin/env python2.5

# Copyright 2009 Mark Longair
# Copyright 2018 Jakob Malm

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
from subprocess import call, Popen, PIPE
import flickrapi
from argparse import ArgumentParser
from common import *
from flickr_checksum_tags import SqliteDb
from find_not_uploaded import is_not_uploaded

parser = ArgumentParser()
parser.add_argument('paths', nargs='+', metavar='FILENAME', help="file to upload")
parser.add_argument('--public', dest='public', default=False, action='store_true',
                    help='make the image viewable by anyone')
parser.add_argument('--family', dest='family', default=False, action='store_true',
                    help='make the image viewable by contacts marked as family')
parser.add_argument('--friends', dest='friends', default=False, action='store_true',
                    help='make the image viewable by contacts marked as friends')
parser.add_argument('-v', '--verbose', dest='verbose', default=False, action='store_true',
                    help='verbose output')
parser.add_argument('-t', '--title', dest='title',
                    metavar='TITLE',
                    help='set the title of the photo')
parser.add_argument('--date-uploaded', dest='date_uploaded',
                    metavar='DATE',
                    help='set the date and time when the photo was uploaded')
parser.add_argument('--date-taken', dest='date_taken',
                    metavar='DATE',
                    help='set the date and time when the photo was taken')
parser.add_argument('--reupload', action='store_true',
                    help="Don't check if already uploaded.")

args = parser.parse_args()
paths = expand_paths(args.paths)

date_pattern = r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$'
date_error_message = 'must be of the form "YYYY-MM-DD HH:MM:SS'

if args.date_uploaded and not re.search(date_pattern,args.date_uploaded):
    print("The --date-uploaded argument must be "+date_error_message)

if args.date_taken and not re.search(date_pattern,args.date_taken):
    print("The --date-taken argument must be "+date_error_message)

flickr = flickrapi.FlickrAPI(configuration['api_key'],configuration['api_secret'])
flickr.authenticate_via_browser(perms='write')

def progress(percent,done):
    if done and args.verbose:
        print("Finished.")
    elif args.verbose:
        print(""+str(int(round(percent)))+"%")

db_filename = os.path.join(os.environ['HOME'],'.flickr-photos-checksummed.db')
db = SqliteDb(db_filename)

for path in paths:
    if args.reupload or is_not_uploaded(path, db, flickr):
        pass  # Continue with the upload.
    else:
        if args.verbose:
            print("Skipping {0} -- already uploaded".format(path))
        continue

    real_sha1 = sha1sum(path)
    real_md5 = md5sum(path)

    tags = sha1_machine_tag_prefix + real_sha1 + " " + md5_machine_tag_prefix + real_md5

    print("Uploading {0}".format(path))
    result = flickr.upload(filename=path,
                        callback=progress,
                        title=(args.title or os.path.basename(path)),
                        tags=tags,
                        is_public=int(args.public),
                        is_family=int(args.family),
                        is_friend=int(args.friends))

    photo_id = result.getchildren()[0].text
    if args.verbose:
        print("photo_id of uploaded photo: "+str(photo_id))
        print("Uploaded to: "+short_url(photo_id))
    
    db.add_to_done(photo_id, real_md5, real_sha1)

    if args.date_uploaded or args.date_taken:
        if args.verbose:
            print("Setting dates:")
            if args.date_uploaded:
                print("  Date uploaded: "+args.date_uploaded)
            if args.date_taken:
                print("  Date taken: "+args.date_taken)
        result = flickr.photos_setDates(photo_id=photo_id,
                                        date_posted=args.date_uploaded,
                                        date_taken=args.date_taken,
                                        date_taken_granularity=0)
