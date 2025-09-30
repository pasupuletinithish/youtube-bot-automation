# ==============================================================================
# FINAL AUTOMATION PIPELINE: GEMINI PROMPT (w/ FALLBACK) + AI VIDEO + YOUTUBE UPLOAD
# ==============================================================================

import os
import json
import sys
import tempfile
import time
import random
import requests
import io 
from requests.exceptions import RequestException

# External Libraries
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
# CRITICAL: Replace with your specific, live Hugging Face Inference Endpoint URL
AI_VIDEO_API_URL = "https://api-inference.huggingface.co/models/runwayml/stable-diffusion-v1-5" 
FALLBACK_FILE = "fallback_prompts.json"


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

# --- PART 1: GEMINI PROMPT GENERATION (with Fallback) ---
def get_trending_topic():
    """Pulls a top trending topic from Google Trends for inspiration."""
    try:
        pytrends = TrendReq(hl='en-US', tz=360)
        df = pytrends.trending_searches(pn='united_states')
        top_trend = df.iloc[0, 0]
        return top_trend
    except Exception:
        # Fallback topic if pytrends itself fails
        return "Unrealistic ASMR slicing" 

def get_fallback_prompt():
    """Reads a random prompt from the local JSON file when API fails."""
    try:
        # Tries to load the fallback file you created locally
        with open(FALLBACK_FILE, 'r') as f:
            prompts = json.load(f)
        return random.choice(prompts)
    except Exception as e:
        print(f"FATAL: Could not read fallback file. {e}. Using hardcoded safe prompt.")
        # Hardcoded backup if the file itself is missing or corrupted
        return {
            "prompt": "Cinematic macro shot of a diamond dissolving into pure light. Slow-motion, 8K.",
            "title": "Diamond Dissolve ✨ (Fallback)",
            "description": "This is a safe fallback prompt used when the Gemini API times out.",
            "tags": ["#fallback", "#AIArt", "#shorts", "#asmr", "#satisfying"]
        }


def generate_dopamine_prompt(topic):
    """Tries Gemini API, falls back to local file on timeout."""
    
    try:
        # 1. Initialize client with a very high timeout (1000s)
        gemini_client = genai.Client(
            api_key=os.environ['GEMINI_API_KEY'],
            http_options={'timeout': 1000} 
        )
    except KeyError:
        print("Error: GEMINI_API_KEY is not set.")
        return get_fallback_prompt() # Fallback if key is missing
    except Exception:
        return get_fallback_prompt() # Fallback if client creation fails

    # The Prompt: Guides the AI on style, theme, and format
    prompt = f"""
    You are a prompt engineer for a fast AI video generator. 
    Your task is to take the concept: '{topic}' and convert it into the required JSON output.
    
    CRITICAL: Keep the resulting prompt short and visually direct (MAX 15 words). 
    DO NOT reason or add unnecessary text to the prompt or JSON.

    Format the output as a clean JSON object with the following keys:
    - "prompt": The single, high-impact visual prompt.
    - "title": A viral YouTube Shorts title (MAX 60 characters).
    - "description": A short, viral-style description with a call-to-action (max 3 lines).
    - "tags": A list of 5 relevant viral hashtags.
    """
    
    print(f"Generating prompt for topic: {topic}")
    
    try:
        # 2. Call generate_content (This is the slow part that times out)
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )
        
        # 3. Return the live Gemini result if successful
        json_output = response.text.strip().replace('```json', '').replace('```', '')
        return json.loads(json_output)
        
    except Exception as e:
        # 4. FALLBACK: Catch the 504 error and return local prompt
        print(f"\n⚠️ GEMINI API FAILED: {type(e).__name__}. Falling back to local prompt.")
        return get_fallback_prompt()


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
        # Long timeout necessary for video generation
        response = requests.post(AI_VIDEO_API_URL, headers=headers, json=payload, timeout=400) 
        response.raise_for_status() 
        
        # The API returns the raw video bytes in the response content
        video_bytes = response.content

        # Save to a temporary file for upload
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

    # 2. PROMPT GENERATION (Uses fallback on timeout)
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