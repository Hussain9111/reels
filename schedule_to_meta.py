#!/usr/bin/env python3
"""Upload and schedule Stoic reels to Instagram via Meta Graph API.

Setup:
1. Go to https://developers.facebook.com/
2. Create an app, get App ID and generate an Access Token
3. Link your Instagram Business Account
4. Get your Instagram Business Account ID from Business Settings
5. Create a .env file with your credentials:
   META_ACCESS_TOKEN=your_token_here
   INSTAGRAM_BUSINESS_ACCOUNT_ID=your_account_id_here
   PAGE_ID=your_page_id_here (optional, for scheduling)

Usage:
  python schedule_to_meta.py output/reel_010.mp4 --caption "Your caption" --schedule-time "2026-08-31T10:00:00"
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: 'requests' library not found. Install with: pip install requests python-dotenv")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("Warning: 'python-dotenv' not found. Create a .env file manually.")
    load_dotenv = lambda: None

load_dotenv()

ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
INSTAGRAM_ACCOUNT_ID = os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID") or "17841475924664647"
PAGE_ID = os.getenv("PAGE_ID")
GRAPH_API_URL = "https://graph.facebook.com/v18.0"


def upload_reel(video_path=None, video_url=None, caption="", schedule_time=None):
    """Upload a reel to Instagram via Meta Graph API.

    Args:
        video_path: local .mp4 file (Instagram rejects local video for REELS)
        video_url:  PUBLIC url of the .mp4 (required for REELS)
        caption:    post caption/description
        schedule_time: ISO 8601 datetime string for scheduling; None = publish now

    Returns:
        dict with upload result or error
    """
    if not ACCESS_TOKEN or not INSTAGRAM_ACCOUNT_ID:
        return {"error": "Missing META_ACCESS_TOKEN or INSTAGRAM_BUSINESS_ACCOUNT_ID in .env"}

    if not video_url and not video_path:
        return {"error": "Provide --video-url (public URL). Instagram requires a URL for REELS."}

    print("Uploading reel via public URL..." if video_url else f"Uploading {Path(video_path).name}...")

    url = f"{GRAPH_API_URL}/{INSTAGRAM_ACCOUNT_ID}/media"
    params = {
        "access_token": ACCESS_TOKEN,
        "media_type": "REELS",
        "caption": caption,
    }
    if video_url:
        params["video_url"] = video_url
    if schedule_time:
        # Instagram expects scheduled_publish_time as an integer Unix timestamp
        try:
            ts = int(schedule_time)
        except ValueError:
            dt = datetime.fromisoformat(schedule_time)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ts = int(dt.timestamp())
        params["scheduled_publish_time"] = ts
        # Note: do NOT set publish_status=SCHEDULED; the timestamp alone schedules it
    else:
        params["publish_status"] = "PUBLISHED"

    try:
        if video_url:
            resp = requests.post(url, data=params, timeout=300)
        else:
            with open(video_path, "rb") as f:
                resp = requests.post(url, files={"video_data": f}, data=params, timeout=300)
    except requests.exceptions.RequestException as e:
        return {"error": f"Network error: {e}"}

    result = resp.json()
    if resp.status_code >= 400:
        error_msg = result.get("error", {}).get("message", f"HTTP {resp.status_code}")
        return {"error": error_msg, "details": result}

    media_id = result.get("id")
    if not media_id:
        return {"error": "No media ID returned", "response": result}

    if schedule_time:
        # Scheduled at create time; no further call needed
        print(f"[OK] Reel scheduled! Container ID: {media_id}")
        return {
            "success": True,
            "media_id": media_id,
            "status": "scheduled",
            "scheduled_time": schedule_time,
            "caption": caption,
        }

    # Reels need a second publish step + wait for video processing
    status_url = f"{GRAPH_API_URL}/{media_id}"
    for _ in range(40):
        try:
            st = requests.get(
                status_url,
                params={"access_token": ACCESS_TOKEN, "fields": "status,status_code"},
                timeout=30,
            ).json()
        except requests.exceptions.RequestException as e:
            return {"error": f"Status poll error: {e}", "container_id": media_id}
        if st.get("status") == "FINISHED":
            break
        if st.get("status") == "ERROR":
            return {"error": f"Video processing failed: {st.get('status_code')}", "details": st}
        time.sleep(3)

    pub_url = f"{GRAPH_API_URL}/{INSTAGRAM_ACCOUNT_ID}/media_publish"
    pub_params = {"access_token": ACCESS_TOKEN, "creation_id": media_id}
    try:
        pub = requests.post(pub_url, data=pub_params, timeout=300)
    except requests.exceptions.RequestException as e:
        return {"error": f"Publish network error: {e}", "container_id": media_id}
    pub_res = pub.json()
    if pub.status_code >= 400:
        msg = pub_res.get("error", {}).get("message", f"HTTP {pub.status_code}")
        return {"error": msg, "details": pub_res, "container_id": media_id}

    post_id = pub_res.get("id")
    print(f"[OK] Reel published! Post ID: {post_id}")
    return {
        "success": True,
        "media_id": media_id,
        "post_id": post_id,
        "status": "published",
        "caption": caption,
    }


def batch_upload(folder_path, caption_template=None, schedule_times=None):
    """Upload multiple reels from a folder.
    
    Args:
        folder_path: path to output folder with reel_*.mp4 files
        caption_template: template with {num}, {file}, {quote} placeholders
        schedule_times: list of ISO 8601 datetime strings, one per reel
    """
    if not os.path.isdir(folder_path):
        print(f"Error: Folder not found: {folder_path}")
        return
    
    reels = sorted([f for f in os.listdir(folder_path) if f.endswith(".mp4")])
    if not reels:
        print(f"No .mp4 files found in {folder_path}")
        return
    
    print(f"Found {len(reels)} reel(s). Uploading...\n")
    
    results = []
    for idx, reel_file in enumerate(reels, 1):
        reel_path = os.path.join(folder_path, reel_file)
        
        caption = caption_template or f"Stoic reel #{idx}"
        if caption_template:
            caption = caption_template.format(
                num=idx,
                file=reel_file,
                quote="Stoic wisdom"
            )
        
        schedule_time = None
        if schedule_times and idx <= len(schedule_times):
            schedule_time = schedule_times[idx - 1]
        
        result = upload_reel(reel_path, caption, schedule_time)
        results.append({"file": reel_file, **result})
        
        if result.get("error"):
            print(f"  ✗ {reel_file}: {result['error']}")
        else:
            print(f"  ✓ {reel_file}")
    
    print(f"\nResults: {sum(1 for r in results if r.get('success'))} succeeded, "
          f"{sum(1 for r in results if r.get('error'))} failed")
    
    return results


def main():
    ap = argparse.ArgumentParser(
        description="Upload Stoic reels to Instagram via Meta Business Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Upload and publish immediately
  python schedule_to_meta.py output/reel_010.mp4 --caption "Daily Stoic"
  
  # Upload and schedule for later
  python schedule_to_meta.py output/reel_010.mp4 \\
    --caption "Stoic wisdom" \\
    --schedule-time "2026-08-31T10:00:00"
  
  # Batch upload all reels from output folder
  python schedule_to_meta.py output/ --batch --caption-template "Stoic #{num}"
        """
    )
    ap.add_argument("path", nargs="?", help="video file or folder for --batch mode (omit when using --video-url)")
    ap.add_argument("--caption", default="", help="post caption")
    ap.add_argument("--schedule-time", help="ISO 8601 datetime to schedule (e.g., '2026-08-31T10:00:00')")
    ap.add_argument("--video-url", help="PUBLIC url of the .mp4 (required for REELS; Instagram rejects local files)")
    ap.add_argument("--batch", action="store_true", help="upload all .mp4 files from folder")
    ap.add_argument("--caption-template", help="caption template for batch mode (use {num}, {file}, {quote})")
    args = ap.parse_args()
    
    if args.batch:
        batch_upload(args.path, args.caption_template)
    elif args.video_url:
        result = upload_reel(video_url=args.video_url, caption=args.caption, schedule_time=args.schedule_time)
    elif args.path:
        result = upload_reel(args.path, args.caption, args.schedule_time)
    else:
        print("Error: provide a video file PATH, or use --video-url, or --batch.")
        sys.exit(1)
        if result.get("error"):
            print(f"Error: {result['error']}")
            if result.get("details"):
                print(json.dumps(result["details"], indent=2))
            sys.exit(1)
        else:
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
