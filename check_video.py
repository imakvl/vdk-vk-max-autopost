import os
import requests

response = requests.get(
    "https://api.vk.com/method/wall.getById",
    params={
        "posts": "-46218861_1397117",
        "access_token": os.environ["VK_TOKEN"],
        "v": "5.199",
    },
    timeout=30,
)
response.raise_for_status()

data = response.json()

if "error" in data:
    raise RuntimeError(data["error"])

posts = data.get("response", {}).get("items", [])

if not posts:
    raise RuntimeError("VK post not found")

post = posts[0]
attachments = post.get("attachments", [])

print("Post ID:", post["id"])
print("Attachments:", len(attachments))

for index, attachment in enumerate(attachments, 1):
    kind = attachment.get("type")
    print(f"\nAttachment {index}: {kind}")

    if kind == "video":
        video = attachment.get("video", {})
        print("Video ID:", video.get("id"))
        print("Owner ID:", video.get("owner_id"))
        print("Title:", video.get("title"))
        print("Duration:", video.get("duration"))
        print("Access key present:", bool(video.get("access_key")))
        print("Player URL present:", bool(video.get("player")))
        print("Direct files present:", bool(video.get("files")))
        print("Can add:", video.get("can_add"))
        print("Is private:", video.get("is_private"))

print("\nDiagnostic completed. Nothing published.")
