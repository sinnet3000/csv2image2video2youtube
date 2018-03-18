#!/usr/bin/env python

import csv
import argparse
import requests
import shutil
import tempfile
import validators
import os
import subprocess
from PIL import Image

import httplib
import httplib2
import random
import time
import sys

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow

import google.auth.transport
import google.oauth2.credentials
import json
import os.path

# Explicitly tell the underlying HTTP transport library not to retry, since
# we are handling retry logic ourselves.
httplib2.RETRIES = 1

# Maximum number of times to retry before giving up.
MAX_RETRIES = 10

# Always retry when these exceptions are raised.
RETRIABLE_EXCEPTIONS = (httplib2.HttpLib2Error, IOError, httplib.NotConnected,
                        httplib.IncompleteRead, httplib.ImproperConnectionState,
                        httplib.CannotSendRequest, httplib.CannotSendHeader,
                        httplib.ResponseNotReady, httplib.BadStatusLine)

# Always retry when an apiclient.errors.HttpError with one of these status
# codes is raised.
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]

# The CLIENT_SECRETS_FILE variable specifies the name of a file that contains
# the OAuth 2.0 information for this application, including its client_id and
# client_secret. You can acquire an OAuth 2.0 client ID and client secret from
# the {{ Google Cloud Console }} at
# {{ https://cloud.google.com/console }}.
# Please ensure that you have enabled the YouTube Data API for your project.
# For more information about using OAuth2 to access the YouTube Data API, see:
#   https://developers.google.com/youtube/v3/guides/authentication
# For more information about the client_secrets.json file format, see:
#   https://developers.google.com/api-client-library/python/guide/aaa_client_secrets
CLIENT_SECRETS_FILE = 'client_secret.json'

# This OAuth 2.0 access scope allows an application to upload files to the
# authenticated user's YouTube channel, but doesn't allow other types of access.
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
API_SERVICE_NAME = 'youtube'
API_VERSION = 'v3'

VALID_PRIVACY_STATUSES = ('public', 'private', 'unlisted')


# Authorize the request and store authorization credentials.
def get_authenticated_service():
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
    credentials_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'credential.json')
    credentials = None
    if os.path.exists(credentials_path):
        credentials = load_credentials()
    if credentials is None:
        credentials = flow.run_console()
        save_credentials(credentials)

    return build(API_SERVICE_NAME, API_VERSION, credentials=credentials)


def save_credentials(credentials):
    credentials_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'credential.json')
    with open(credentials_path, 'w') as f:
        json.dump({
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }, f)


def load_credentials():
    migrate = False
    credentials_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'credential.json')
    with open(credentials_path, 'r') as f:
        credentials_data = json.load(f)
        if 'access_token' in credentials_data:
            migrate = True
            del credentials_data['access_token']
            credentials_data['scopes'] = SCOPES
    if migrate:
        with open(credentials_path, 'w') as f:
            json.dump(credentials_data, f)
    credentials = google.oauth2.credentials.Credentials(token=None,
                                                        **credentials_data)
    http_request = google.auth.transport.requests.Request()
    credentials.refresh(http_request)
    return credentials


def initialize_upload(youtube, options):
    tags = None
    if options['keywords']:
        tags = options['keywords'].split(',')

    body = dict(
        snippet=dict(
            title=options['title'],
            description=options['description'],
            tags=tags,
            categoryId=options['category']
        ),
        status=dict(
            privacyStatus=options['privacyStatus']
        )
    )

    # Call the API's videos.insert method to create and upload the video.
    insert_request = youtube.videos().insert(
        part=','.join(body.keys()),
        body=body,
        # The chunksize parameter specifies the size of each chunk of data, in
        # bytes, that will be uploaded at a time. Set a higher value for
        # reliable connections as fewer chunks lead to faster uploads. Set a lower
        # value for better recovery on less reliable connections.
        #
        # Setting 'chunksize' equal to -1 in the code below means that the entire
        # file will be uploaded in a single HTTP request. (If the upload fails,
        # it will still be retried where it left off.) This is usually a best
        # practice, but if you're using Python older than 2.6 or if you're
        # running on App Engine, you should set the chunksize to something like
        # 1024 * 1024 (1 megabyte).
        media_body=MediaFileUpload(options['file'], chunksize=-1, resumable=True)
    )

    return resumable_upload(insert_request)


def upload_thumbnail(youtube, video_id, file):
    youtube.thumbnails().set(
        videoId=video_id,
        media_body=file
    ).execute()


# This method implements an exponential backoff strategy to resume a
# failed upload.
def resumable_upload(request):
    response = None
    error = None
    retry = 0
    while response is None:
        try:
            print 'Uploading file...'
            status, response = request.next_chunk()
            if response is not None:
                if 'id' in response:
                    print 'Video id "%s" was successfully uploaded.' % response['id']
                    return response['id']
                else:
                    exit('The upload failed with an unexpected response: %s' % response)
        except HttpError, e:
            if e.resp.status in RETRIABLE_STATUS_CODES:
                error = 'A retriable HTTP error %d occurred:\n%s' % (e.resp.status,
                                                                     e.content)
            else:
                raise
        except RETRIABLE_EXCEPTIONS, e:
            error = 'A retriable error occurred: %s' % e

        if error is not None:
            print error
            retry += 1
            if retry > MAX_RETRIES:
                exit('No longer attempting to retry.')

            max_sleep = 2 ** retry
            sleep_seconds = random.random() * max_sleep
            print 'Sleeping %f seconds and then retrying...' % sleep_seconds
            time.sleep(sleep_seconds)



def parse_csv(filename):
    reader = csv.DictReader(open(filename, 'rb'))
    dict_list = []
    for line in reader:
        dict_list.append(line)
    return dict_list


def throttle_range(value):
    ivalue = int(value)
    if 30 < ivalue < 1:
        raise argparse.ArgumentTypeError(
            "%s is an invalid throttle range. (Valid value is between 30 and 1 videos per hour" % value)
    return ivalue


parser = argparse.ArgumentParser(description='Parse csv to create videos from images and upload to Youtube')
parser.add_argument('-t', '--throttle', help='Throttle value in videos per hour', required=False, default=30,
                    type=throttle_range)
parser.add_argument('-f', '--filename', help='CSV file with the video data', required=True)
args = vars(parser.parse_args())

videos = parse_csv(args['filename'])

# Each video takes around 2 minutes to process so the max value would be 30 videos per hour.
if int(args['throttle']) < 30:
    throttle_value = (60 - (int(args['throttle']) * 2)) * 60
else:
    throttle_value = 1200

headers = {
    'User-Agent': "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2227.0 Safari/537.36"}

# Upload to Youtube
youtube = get_authenticated_service()

for video in videos:
    print "Starting to work with video: " + video['Title'] + "..."

    images = []
    for k in sorted(video):
        if k.lower().startswith('image') and validators.url(video[k]):
            images.append(video[k])

    # Download images
    temp_directory_name = tempfile.mkdtemp()
    counter = 0

    thumbail_name = os.path.join(temp_directory_name, "thumbail.jpg")

    for url in images:
        print "Downloading image from: " + url
        file_name = os.path.join(temp_directory_name, "image-" + str(counter).zfill(3) + ".png")

        response = requests.get(url, stream=True, headers=headers)
        image = Image.open(response.raw)
        if (counter == 0):
            thumbail = image.resize((1280, 720), Image.ANTIALIAS).convert('RGB')
            thumbail.save(thumbail_name, optimize=True, quality=95, format='JPEG')
            thumbail.close
        image.save(file_name, format='PNG')
        image.close()
        del response
        counter += 1

    end_image = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'end.png')

    # Copy two times last image as workaround to FFMPEG bug.
    for x in range(0, 2):
        end_tmp_path = file_name = os.path.join(temp_directory_name, "image-" + str(counter).zfill(3) + ".png")
        shutil.copyfile(end_image, end_tmp_path)
        counter += 1

    # Create video...

    output_filename = os.path.join(temp_directory_name, 'output.mp4')
    input_filename = os.path.join(temp_directory_name, 'image-%03d.png')

    print "Starting to create video..."

    ffmpeg_cmd = 'ffmpeg -framerate 1/7 -i ' + input_filename + ' -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p ' \
                                                                '-vf scale=-2:720 ' + output_filename
    subprocess.call(ffmpeg_cmd, shell=True)

    print "Video with title: " + video['Title'] + "created... (not uploaded yet)"

    youtube_args = {'category': '22', 'description': video['Body (HTML)'], 'file': output_filename,
                    'keywords': video['Tags'],
                    'privacyStatus': 'public', 'title': video['Title']}

    try:
        video_id = initialize_upload(youtube, youtube_args)
        print "Video with title: " + video['Title'] + ' uploaded...'
    except HttpError, e:
        print 'An HTTP error %d occurred:\n%s' % (e.resp.status, e.content)

    try:
        upload_thumbnail(youtube, video_id, thumbail_name)
    except HttpError, e:
        print "An HTTP error %d occurred:\n%s" % (e.resp.status, e.content)
    else:
        print "The custom thumbnail was successfully set."

    print "Waiting " + str(throttle_value / int(len(videos))) + " seconds"
    time.sleep(throttle_value / int(len(videos)))

    shutil.rmtree(temp_directory_name)

print "Job finished"
