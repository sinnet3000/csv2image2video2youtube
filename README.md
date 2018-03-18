# CSV2Img2Video2Youtube

This script reads a CSV file which contains links to images, and metadata for Youtube. The script takes the images and with FMPEG converts it to a video, then this video is uploaded to Youtube using the Metadata in the CSV file. 

The person using the script needed a throttle, so I implemented a very rudimentary throttle.

## How to use it

### Install software dependencies

sudo apt-get install ffmpeg

Python 2.7 (Ubuntu should have this version already installed)

pip install -r /path/to/requirements.txt

Create OAUTH2 secret to connect application to Youtube:

- Go to the Google console in https://cloud.google.com/console
- Create new project.
- Side menu: APIs & auth -> APIs
- Top menu: Enabled API(s): Enable all Youtube APIs.
- Side menu: APIs & auth -> Credentials.
- Create a Client ID: Add credentials -> OAuth 2.0 Client ID -> Other -> Name: youtube-upload -> Create -> OK
- Download JSON: Under the section "OAuth 2.0 client IDs". Save the file to your local system.
- Copy client_secret.json to script folder (rename to client_secret_json if neccesary)

## Running the script

python video_creator.py -f [name of csv] -t [throttle in mins (optional) ] &

Note: The ampersand at the end of the script is important. This is for sending the script to background, to avoid the process getting closed in case you exit the SSH connection or there is a sudden ssh disconnection caused by a network issue.

The first time the script is run. It will give a link to follow in your web browser (you can open this link from another computer, it's not neccesary to do it for the server), it will ask you to allow permissions to the application you created in google console. It will give you a token that you will need to paste in the command line, after this the application will start to work. The second time you run the application it won't be neccesary to do this unless for Youtube expires the token, but this didn't happen in my tests.

Note 2: Youtube will reject any description containing HTML code. The upload will fail if the description has HTML.
