# ==============================================================================
# FULL AUTOMATION PIPELINE: GEMINI PROMPT + FREE AI VIDEO GENERATION + YOUTUBE UPLOAD
# ==============================================================================
# ==============================================================================
# FULL AUTOMATION PIPELINE: GEMINI PROMPT + FREE AI VIDEO GENERATION + YOUTUBE UPLOAD
# ==============================================================================

import os
import json
import sys
import tempfile
import requests
import time         # <-- ADDED for time.time() and potential delays
import random       # <-- ADDED for random.choice()
import io
import httplib2 
from google import genai
from pytrends.request import TrendReq
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# ... (The rest of your code remains the same) ...

# --- CONFIGURATION (Ensure these are set in GitHub Secrets) ---
# Secrets needed: GEMINI_API_KEY, YOUTUBE_REFRESH_TOKEN_FILE, HF_TOKEN
YOUTUBE_UPLOAD_SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]
GEMINI_MODEL = "gemini-2.5-flash"
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

# --- PART 1: GEMINI PROMPT GENERATION (The Brain) ---

def get_trending_topic():
    """Pulls a top trending topic from Google Trends for inspiration."""
    try:
        pytrends = TrendReq(hl='en-US', tz=360)
        df = pytrends.trending_searches(pn='united_states')
        top_trend = df.iloc[0, 0]
        return top_trend
    except Exception:
        # Fallback to a guaranteed high-dopamine topic
        fallback_topics = [
            "Hyper-realistic macro ASMR slicing a liquid metal cube.",
            "Cinematic slow-motion of a crystal wave freezing in mid-air.",
            "Cutting the moon like a birthday cake with a glowing laser knife."
        ]
        return random.choice(fallback_topics)

def generate_dopamine_prompt(topic):
    """Uses Gemini to generate a creative, structured prompt for video AI."""
    
    try:
        gemini_client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
    except KeyError:
        print("Error: GEMINI_API_KEY is not set.")
        return None

    # The Prompt: Guides the AI on style, theme, and format
    prompt = f"""
    You are a viral AI video generator. Convert this concept: '{topic}' 
    into a hyper-descriptive, highly satisfying, 8-second video prompt. 
    The style must be hyper-realistic, cinematic, and focused on unrealistic physical phenomena 
    (like slicing or melting).

    Format the output as a clean JSON object with the following keys:
    - "prompt": The hyper-detailed video generation prompt (max 250 chars).
    - "title": A clickbait YouTube Shorts title (under 60 characters).
    - "description": A short, viral-style description with a call-to-action (max 3 lines).
    - "tags": A list of 5 relevant viral hashtags.
    """
    
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

# --- PART 2: FREE AI VIDEO GENERATION (The Heavy Lifting) ---

def generate_ai_video(prompt_text):
    """
    *** WARNING: THIS FUNCTION REQUIRES A LIVE, WORKING, FREE AI VIDEO API ENDPOINT ***
    
    - It is highly unstable, as free APIs come and go quickly.
    - You MUST replace the API_URL with a current working free/open-source endpoint.
    - This example uses the structure for the Hugging Face Inference API.
    """
    # Replace this URL with a current, working free Text-to-Video API endpoint!
    API_URL = API_URL = "https://api-inference.huggingface.co/models/tencent/HunyuanVideo"
    
    HF_TOKEN = os.environ.get("HF_TOKEN")
    if not HF_TOKEN:
        print("HF_TOKEN secret is missing. Cannot generate video.")
        return None

    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    
    # Payload for a typical Text-to-Video model (adjust for your chosen API)
    payload = {
        "data": [
            prompt_text,
            8, # Video duration in seconds
            "9:16", # Aspect ratio for Shorts
            True, # Use random seed
        ]
    }

    print(f"Sending prompt to AI Video API: {API_URL}")
    
    try:
        # 1. Send the request
        response = requests.post(API_URL, headers=headers, json=payload, timeout=300) # 5-minute timeout
        response.raise_for_status() 
        result = response.json()

        # 2. Extract the video URL from the response (ADJUST THIS LINE!)
        # The structure depends on the API; this is a common placeholder
        video_url = result['data'][0]['video_url'] 

        # 3. Download the video content
        video_response = requests.get(video_url, stream=True)
        video_response.raise_for_status()

        # 4. Save to a temporary file for upload
        video_path = os.path.join(tempfile.gettempdir(), f"ai_video_{time.time()}.mp4")
        with open(video_path, 'wb') as f:
            for chunk in video_response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        print(f"Video downloaded successfully to: {video_path}")
        return video_path
    
    except requests.exceptions.RequestException as e:
        print(f"AI Video API Request Failed: {e}")
        return None
    except Exception as e:
        print(f"AI Video Generation/Download Failed: {e}. Check API response structure.")
        return None


# --- PART 3: YOUTUBE UPLOAD ---

def get_authenticated_youtube_service():
    """Reads the Refresh Token and builds the authenticated YouTube client."""
    try:
        token_json_string = os.environ.get('YOUTUBE_REFRESH_TOKEN_FILE')
        if not token_json_string:
            raise EnvironmentError("YOUTUBE_REFRESH_TOKEN_FILE secret is missing.")
            
        token_data = json.loads(token_json_string)
        
        credentials = Credentials.from_authorized_user_info(
            info=token_data, 
            scopes=YOUTUBE_UPLOAD_SCOPE
        )

        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        
        return build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, credentials=credentials)

    except Exception as e:
        print(f"Authentication failed: {e}")
        return None

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
            'privacyStatus': 'unlisted' # Recommended for initial testing
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
        # Optional: Clean up the temporary file after successful upload
        os.remove(final_video_path) 
    else:
        print("Final video creation failed. Upload skipped.")
        sys.exit(1)