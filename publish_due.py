import json
import os
import sys
import subprocess
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import schedule_to_meta as sm

MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "publish_manifest.json")


def commit_manifest(reels, msg):
    if not os.getenv("GITHUB_ACTIONS"):
        return
    try:
        subprocess.run(["git", "config", "user.email", "bot@github.com"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "reels-bot"], check=True, capture_output=True)
        subprocess.run(["git", "add", "publish_manifest.json"], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", msg], check=True, capture_output=True)
        token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        repo = os.getenv("GITHUB_REPOSITORY")
        if token and repo:
            url = f"https://x-access-token:{token}@github.com/{repo}.git"
            subprocess.run(["git", "push", url, "HEAD"], check=True, capture_output=True)
        print("  committed manifest")
    except subprocess.CalledProcessError as e:
        print("  commit failed:", e)


def parse_dt(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def main():
    if not sm.ACCESS_TOKEN or not sm.INSTAGRAM_ACCOUNT_ID:
        print("Missing META_ACCESS_TOKEN or INSTAGRAM_BUSINESS_ACCOUNT_ID")
        sys.exit(1)

    with open(MANIFEST, encoding="utf-8") as f:
        reels = json.load(f)

    now = datetime.now(timezone.utc)
    for reel in reels:
        if reel.get("status") == "published":
            continue
        sched = reel.get("scheduled")
        if not sched:
            print(f"skip {reel.get('file')}: no scheduled time")
            continue
        dt = parse_dt(sched)
        if dt > now:
            print(f"wait {reel.get('file')}: due {dt.isoformat()} (not yet)")
            continue

        print(f"publishing {reel.get('file')} ...")
        res = sm.upload_reel(video_url=reel.get("url"), caption=reel.get("caption"))
        if res.get("error"):
            print(f"  error: {res['error']}")
            continue

        reel["status"] = "published"
        reel["post_id"] = res.get("post_id")
        reel["published_at"] = now.isoformat()
        print(f"  published -> {res.get('post_id')}")
        commit_manifest(reels, f"publish {reel.get('file')}")


if __name__ == "__main__":
    main()
