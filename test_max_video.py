import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests

MAX_API = "https://platform-api2.max.ru"
MAX_TOKEN = os.environ["MAX_TOKEN"]
VIDEO_URL = "https://vk.com/video-46218861_456244658"
VIDEO_FILE = Path("test_video/video.mp4")

HEADERS = {"Authorization": MAX_TOKEN}


def main():
    VIDEO_FILE.parent.mkdir(exist_ok=True)

    print("1. Downloading VK video...")

    subprocess.run(
        [
            "yt-dlp",
            "--no-playlist",
            "--no-warnings",
            "-f", "best[ext=mp4]/best",
            "-o", str(VIDEO_FILE),
            VIDEO_URL,
        ],
        check=True,
        timeout=180,
    )

    if not VIDEO_FILE.is_file():
        raise RuntimeError("Video file not found")

    size = VIDEO_FILE.stat().st_size
    print(f"Downloaded: {size / 1048576:.2f} MB")

    if size > 250 * 1048576:
        raise RuntimeError("Video exceeds MAX 250 MB limit")

    print("2. Requesting MAX video upload URL...")

    response = requests.post(
        f"{MAX_API}/uploads",
        params={"type": "video"},
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    upload_data = response.json()
    upload_url = upload_data["url"]
    token = upload_data.get("token")

    # Не выводим URL: он может содержать
    # временные параметры доступа.
    host = urlparse(upload_url).hostname
    print("Upload host:", host)
    print("Upload token received:", bool(token))

    print("3. Uploading video to MAX...")

    with VIDEO_FILE.open("rb") as video:
        result = requests.post(
            upload_url,
            files={
                "data": ("video.mp4", video, "video/mp4")
            },
            timeout=180,
        )

    result.raise_for_status()

    print("Upload HTTP status:", result.status_code)

    try:
        upload_result = result.json()
    except ValueError:
        upload_result = {}

    if not token:
        token = upload_result.get("token")

    if not token:
        raise RuntimeError(
            "Upload finished but no video token was returned"
        )

    print("Video token available: True")
    print("SUCCESS: Video uploaded to MAX!")
    print("No message was published.")


if __name__ == "__main__":
    main()
