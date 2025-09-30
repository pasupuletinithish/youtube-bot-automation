# main.py

import os
import json
import sys
import tempfile
import random
import requests
from requests.exceptions import RequestException
import shutil # For moving files after upload

# Google Libraries
from pytrends.request import TrendReq
from google import genai
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError


# --- CONFIGURATION & CONSTANTS ---
YOUTUBE_UPLOAD_SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]
GEMINI_MODEL = "gemini-2.5-flash"
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

# --- FOLDER SETUP ---
# CRITICAL: These paths are relative to the repository root on the GitHub runner
UPLOAD_QUEUE_DIR = "UPLOAD_QUEUE"
PROCESSED_DIR = "PROCESSED"


# --- UTILITY: FILE MANAGEMENT ---
def get_next_unprocessed_video():
    """Finds the first MP4/MOV file in the queue."""
    # Ensure directories exist (they should, but good for safety)
    os.makedirs(UPLOAD_QUEUE_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)

    try:
        # Get a list of files and sort them (to process oldest first)
        all_files = sorted(os.listdir(UPLOAD_QUEUE_DIR))
        
        for filename in all_files:
            if filename.lower().endswith(('.mp4', '.mov')):
                full_path = os.path.join(UPLOAD_QUEUE_DIR, filename)
                return full_path
        
        return None  # No unprocessed video found
    except Exception as e:
        print(f"Error accessing upload queue: {e}")
        return None

def mark_video_as_processed(video_path):
    """Moves the video file from the queue to the processed folder."""
    filename = os.path.basename(video_path)
    new_path = os.path.join(PROCESSED_DIR, filename)
    
    try:
        shutil.move(video_path, new_path)
        print(f"Cleanup Success: Moved '{filename}' to PROCESSED folder.")
    except Exception as e:
        print(f"Cleanup FAILED: Could not move file: {e}")


# --- AUTHENTICATION ---
# (The code remains stable and uses the individual secrets passed via env)
def get_authenticated_youtube_service():
    # ... (Authentication code omitted for brevity; assume it is the correct, final version) ...
    try:
        # 1. Read the simple string secrets from the environment
        refresh_token = os.environ.get('YOUTUBE_REFRESH_TOKEN')
        client_id = os.environ.get('CLIENT_ID')
        client_secret = os.environ.get('CLIENT_SECRET')

        if not refresh_token or not client_id or not client_secret:
            raise EnvironmentError("One or more YouTube credentials are missing.")
            
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri='https://oauth2.googleapis.com/token',
            client_id=client_id,
            client_secret=client_secret,
            scopes=YOUTUBE_UPLOAD_SCOPE
        )

        if credentials.refresh_token:
             print("Access token expired. Refreshing token...")
             credentials.refresh(Request())
        
        return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=credentials)

    except Exception as e:
        print(f"Authentication failed: {type(e).__name__}: {e}")
        return None


# --- PART 1: GEMINI METADATA GENERATION ---
# (Using a simplified prompt structure as the complex one caused 504 errors)
def get_trending_topic():
    # Fallback to avoid pytrends failure on cloud runners
    return "ASMR Satisfying Video" 

def get_fallback_metadata(topic):
    """Returns a reliable metadata structure."""
    return {
        "title": f"The Perfect Slice: {topic} [ASMR]",
        "description": "Watch this strangely satisfying loop. Drop your video in the upload queue!",
        "tags": ["#satisfying", "#ASMR", "#shorts", "#dopamine", "#unreal"]
    }

def generate_metadata(topic):
    """Tries Gemini API, falls back to hardcoded prompt on timeout/error."""
    try:
        gemini_client = genai.Client(
            api_key=os.environ['GEMINI_API_KEY'],
            http_options={'timeout': 120} 
        )
    except Exception:
        return get_fallback_metadata(topic) 

    # Prompt optimization for stability and speed
    prompt = f"""
    Generate a viral title, description, and tags for a YouTube Short video about: "{topic}".
    The style must be hyper-engaging and focused on the 'satisfying' trend.
    Format the output as clean JSON with keys: "title", "description", and "tags".
    """
    
    try:
        response = gemini_client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        json_output = response.text.strip().replace('```json', '').replace('```', '')
        return json.loads(json_output)
        
    except Exception:
        return get_fallback_metadata(topic)


# --- PART 2: YOUTUBE UPLOAD ---
def upload_video(youtube_service, file_path, title, description, tags):
    """Uploads the file to YouTube."""
    # ... (Upload code omitted for brevity; assume it is the correct, final version) ...
    if youtube_service is None: return

    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags,
            'categoryId': '22'
        },
        'status': {
            'privacyStatus': 'unlisted' 
        }
    }
    
    media_body = MediaFileUpload(file_path, chunksize=-1, resumable=True)

    print(f"Attempting to upload file: {title}")
    
    insert_request = youtube_service.videos().insert(
        part=", ".join(body.keys()),
        body=body,
        media_body=media_body
    )
    
    response = None
    while response is None:
        status, response = insert_request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")
    
    print(f"✅ Upload Complete! Video ID: {response.get('id')}")
    return response.get('id')


# --- MAIN EXECUTION LOOP ---
if __name__ == "__main__":
    
    # 1. AUTHENTICATION
    youtube_client = get_authenticated_youtube_service()
    if youtube_client is None:
        sys.exit(1)

    # 2. FIND VIDEO FILE
    final_video_path = get_next_unprocessed_video()
    
    if final_video_path is None:
        print("✅ Automation Skip: No new videos found in UPLOAD_QUEUE. Exiting.")
        sys.exit(0)

    # 3. GENERATE METADATA
    # The topic is based on the file name (e.g., if the file is 'emerald_slice.mp4', topic is 'emerald slice')
    video_filename_base = os.path.basename(final_video_path)
    video_topic = video_filename_base.replace(".mp4", "").replace(".mov", "").replace("_", " ")

    dopamine_data = generate_metadata(video_topic)
    
    if dopamine_data is None:
        print("Failed to generate valid content data. Stopping.")
        sys.exit(1)

    # 4. UPLOAD
    upload_video(
        youtube_client,
        final_video_path,
        dopamine_data['title'],
        dopamine_data['description'],
        dopamine_data['tags']
    )
    
    # 5. CLEANUP
    mark_video_as_processed(final_video_path)