# ==============================================================================
# FINAL AUTOMATION PIPELINE: GEMINI PROMPT + AI VIDEO + YOUTUBE UPLOAD
# ==============================================================================

import os
import json
import sys
import tempfile
import time
import random
import requests
from requests.exceptions import RequestException # Specific request error handling

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
# CRITICAL: REPLACE with your specific, live Hugging Face Inference Endpoint URL
AI_VIDEO_API_URL = "https://api-inference.huggingface.co/models/tencent/HunyuanVideo" 


# --- AUTHENTICATION (Reads from the clean 'auth_token.json' file) ---
def get_authenticated_youtube_service():
    """Reads the Refresh Token from the local file and builds the authenticated YouTube client."""
    try:
        # 1. Get the local file path from the environment variable set in the YAML file
        TOKEN_FILE_PATH = os.environ.get('YOUTUBE_TOKEN_PATH')
        
        if not TOKEN_FILE_PATH or not os.path.exists(TOKEN_FILE_PATH):
            raise FileNotFoundError(f"Authentication file ({TOKEN_FILE_PATH}) is missing.")
            
        # 2. Load the JSON content from the clean local file
        with open(TOKEN_FILE_PATH, 'r') as f:
            token_data = json.load(f)
        
        # 3. Create Credentials object 
        credentials = Credentials.from_authorized_user_info(
            info=token_data, 
            scopes=YOUTUBE_UPLOAD_SCOPE
        )

        # 4. If token is expired, refresh it (Crucial for automation!)
        if credentials.expired and credentials.refresh_token:
            print("Access token expired. Refreshing token...")
            credentials.refresh(Request())
        
        # 5. Build the YouTube service object
        return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=credentials)

    except Exception as e:
        print(f"Authentication failed: {type(e).__name__}: {e}")
        return None

# --- PART 1: GEMINI PROMPT GENERATION ---
def get_trending_topic():
    """Pulls a top trending topic from Google Trends for inspiration."""
    try:
        pytrends = TrendReq(hl='en-US', tz=360)
        df = pytrends.trending_searches(pn='united_states')
        top_trend = df.iloc[0, 0]
        return top_trend
    except Exception:
        # Fallback to a high-dopamine topic if pytrends fails
        fallback_topics = [
            "Hyper-realistic macro ASMR slicing a liquid diamond.",
            "Cinematic slow-motion of a crystal wave freezing in mid-air.",
            "A volcano being eaten like ice cream, cinematic colors."
        ]
        return random.choice(fallback_topics)

def generate_dopamine_prompt(topic):
    """Uses Gemini to generate a creative, structured prompt for video AI."""
    
    try:
        # 1. Initialize client with timeout set in http_options (THE FIX)
        gemini_client = genai.Client(
            api_key=os.environ['GEMINI_API_KEY'],
            http_options={'timeout': 1000} # 10s connect, 60s read
        )
    except KeyError:
        print("Error: GEMINI_API_KEY is not set.")
        return None

    prompt = f"""
    You are a prompt engineer for a fast AI video generator. 
    Your task is to take the concept: '{topic}' and convert it into the required JSON output.
    
    CRITICAL: Keep the resulting prompt short and visually direct. 
    DO NOT reason or add unnecessary text to the prompt or JSON.

    Format the output as a clean JSON object with the following keys:
    - "prompt": A single, high-impact, short visual prompt (MAX 15 words).
    - "title": A viral YouTube Shorts title (MAX 60 characters).
    - "tags": A list of 5 keywords.
    """
    
    print(f"Generating prompt for topic: {topic}")
    
    # 2. Call generate_content (NO timeout argument here)
    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt
    )
    
    # Safely parse the JSON response
    try:
        json_output = response.text.strip().replace('```json', '').replace('```', '')
        return json.loads(json_output)
    except Exception as e:
        print(f"Error parsing Gemini JSON: {e}")
        return None

# --- PART 2: FREE AI VIDEO GENERATION ---
def generate_ai_video(prompt_text):
    """Connects to the Hugging Face Inference API to generate and download a video."""
    
    HF_TOKEN = os.environ.get("HF_TOKEN")
    if not HF_TOKEN:
        print("HF_TOKEN secret is missing.")
        return None

    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    
    # Payload adjusted for a typical Hugging Face T2V model
    payload = {
        "inputs": prompt_text,
        "parameters": {
            "num_frames": 24 * 8, 
            "guidance_scale": 9.0,
            "height": 768,
            "width": 512, 
            "video_length": 8, 
        }
    }

    print(f"Sending prompt to AI Video API: {AI_VIDEO_API_URL}")
    
    try:
        # 1. Send the request
        response = requests.post(AI_VIDEO_API_URL, headers=headers, json=payload, timeout=400) 
        response.raise_for_status() 
        
        # 2. The API returns the raw video bytes in the response content
        video_bytes = response.content

        # 3. Save to a temporary file for upload
        video_path = os.path.join(tempfile.gettempdir(), f"ai_video_{time.time()}.mp4")
        
        if len(video_bytes) < 1000:
            print("Error: AI Video API returned an empty or corrupt file.")
            print(f"Raw response start: {response.text[:200]}...")
            return None
        
        with open(video_path, 'wb') as f:
            f.write(video_bytes)
        
        print(f"Video downloaded successfully to: {video_path}")
        return video_path
    
    except requests.exceptions.RequestException as e:
        print(f"AI Video API Request Failed (Check API_URL & Token): {e}")
        return None
    except Exception as e:
        print(f"Video Generation/Download Failed: {e}.")
        return None


# --- PART 3: YOUTUBE UPLOAD ---
def upload_video(youtube_service, file_path, title, description, tags):
    """Uploads the video file to YouTube."""
    if youtube_service is None: return

    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags,
            'categoryId': '22' # People & Blogs is a safe general category
        },
        'status': {
            'privacyStatus': 'unlisted' 
        }
    }
    
    media_body = MediaFileUpload(file_path, chunksize=-1, resumable=True)

    print(f"Attempting to upload video: {title}")
    
    insert_request = youtube_service.videos().insert(
        part=", ".join(body.keys()),
        body=body,
        media_body=media_body
    )
    
    # Resumable upload loop
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

    # 2. PROMPT GENERATION
    dopamine_data = generate_dopamine_prompt(get_trending_topic())
    
    if dopamine_data is None:
        print("Failed to generate valid content data. Stopping.")
        sys.exit(1)

    # 3. VIDEO GENERATION
    final_video_path = generate_ai_video(dopamine_data['prompt'])

    # 4. UPLOAD
    if final_video_path and os.path.exists(final_video_path):
        upload_video(
            youtube_client,
            final_video_path,
            dopamine_data['title'],
            dopamine_data['description'],
            dopamine_data['tags']
        )
        # Clean up the temporary file after successful upload
        os.remove(final_video_path) 
    else:
        print("Final video creation failed. Upload skipped.")
        sys.exit(1)
    