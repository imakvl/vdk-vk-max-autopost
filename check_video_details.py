import os
import requests

video_id = "-46218861_456244658"

response = requests.get(
    "https://api.vk.com/method/video.get",
    params={
        "videos": video_id,
        "access_token": os.environ["VK_TOKEN"],
        "v": "5.199",
    },
    timeout=30,
)
response.raise_for_status()

data = response.json()

if "error" in data:
    error = data["error"]
    print("VK API error:", error.get("error_code"))
    print("Message:", error.get("error_msg"))
    raise SystemExit(1)

items = data.get("response", {}).get("items", [])

if not items:
    print("Video not found")
    raise SystemExit(1)

video = items[0]

print("Video ID:", video.get("id"))
print("Title:", video.get("title"))
print("Duration:", video.get("duration"))
print("Player URL present:", bool(video.get("player")))

files = video.get("files") or {}

print("Direct video files available:", bool(files))
print("Available file types:", list(files.keys()))

print("Video details check completed.")
