import os
import time
import tempfile
from pathlib import Path

import requests
import yt_dlp

API = "https://platform-api2.max.ru"
TOKEN = os.environ["MAX_TOKEN"]
CHAT_ID = os.environ["MAX_CHAT_ID"]
HEADERS = {"Authorization": TOKEN}
VIDEO_URL = "https://vk.com/video-46218861_456244658"


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "video.mp4"

        print("1. Downloading video from VK...", flush=True)

        with yt_dlp.YoutubeDL({
            "format": "best[ext=mp4]/best",
            "outtmpl": str(path),
            "noplaylist": True,
            "quiet": True,
        }) as downloader:
            downloader.download([VIDEO_URL])

        if not path.exists():
            raise RuntimeError("Video was not downloaded")

        print(f"Downloaded: {path.stat().st_size / 1048576:.2f} MB", flush=True)

        print("2. Requesting MAX upload URL...", flush=True)
        response = requests.post(
            f"{API}/uploads",
            params={"type": "video"},
            headers=HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        upload_data = response.json()
        upload_url = upload_data["url"]
        token = upload_data.get("token")

        print("3. Uploading video...", flush=True)
        with path.open("rb") as file:
            uploaded = requests.post(
                upload_url,
                files={"data": ("video.mp4", file, "video/mp4")},
                timeout=180,
            )
        uploaded.raise_for_status()

        print("Upload HTTP status:", uploaded.status_code)
print("Upload Content-Type:", uploaded.headers.get("Content-Type"))
    print("Upload response length:", len(uploaded.content))

    uploaded.raise_for_status()

    if uploaded.content.strip():
        try:
            result = uploaded.json()
        except ValueError:
            print("Upload returned non-JSON response")
            print("Response preview:", uploaded.text[:300])
            raise RuntimeError("MAX upload response is not JSON")
    else:
        print("Upload returned empty response")
        result = {}

    token = result.get("token")

    if not token:
        raise RuntimeError("MAX did not return a video token")

    print("Video uploaded successfully", flush=True)

        payload = {
            "text": "Тест автопостинга видео ВКонтакте → MAX",
            "attachments": [
                {"type": "video", "payload": {"token": token}}
            ],
        }

        print("4. Waiting for video processing...", flush=True)

        for attempt in range(18):
            response = requests.post(
                f"{API}/messages",
                params={"chat_id": CHAT_ID},
                headers=HEADERS,
                json=payload,
                timeout=60,
            )

            if response.ok:
                message = response.json().get("message", {})
                print("SUCCESS: Video message published!", flush=True)
                print(f"Message ID: {message.get('body', {}).get('mid', message.get('mid', 'unknown'))}")
                return

            if response.status_code == 400:
                print(f"Video not ready, attempt {attempt + 1}/18", flush=True)
                time.sleep(10)
                continue

            raise RuntimeError(
                f"MAX HTTP {response.status_code}: {response.text[:500]}"
            )

        raise RuntimeError(
            "Video uploaded, but MAX did not accept the message"
        )


if __name__ == "__main__":
    main()
