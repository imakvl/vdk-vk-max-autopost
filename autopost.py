import json
import os
import re
import time
import tempfile
from pathlib import Path

import requests
import yt_dlp


VK_TOKEN = os.environ["VK_TOKEN"]
MAX_TOKEN = os.environ["MAX_TOKEN"]
CHAT_ID = os.environ["MAX_CHAT_ID"]

STATE = Path("state.json")
VK_API = "https://api.vk.com/method/wall.get"
MAX_API = "https://platform-api2.max.ru"
HEADERS = {"Authorization": MAX_TOKEN}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def vk_posts():
    response = requests.get(
        VK_API,
        params={
            "domain": "myvdk",
            "count": 100,
            "v": "5.199",
            "access_token": VK_TOKEN,
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        error = data["error"]
        raise RuntimeError(
            f"VK API: {error['error_code']} "
            f"{error['error_msg']}"
        )

    return [
        post for post in data["response"]["items"]
        if not post.get("is_pinned")
    ]


def photos(post):
    result = []

    for attachment in post.get("attachments", []):
        if attachment.get("type") != "photo":
            continue

        sizes = attachment.get("photo", {}).get("sizes", [])

        if sizes:
            best = max(
                sizes,
                key=lambda size:
                    size.get("width", 0)
                    * size.get("height", 0),
            )

            if best.get("url"):
                result.append(best["url"])

    return result[:12]


def videos(post):
    result = []

    for attachment in post.get("attachments", []):
        if attachment.get("type") != "video":
            continue

        video = attachment.get("video", {})
        owner_id = video.get("owner_id")
        video_id = video.get("id")

        if owner_id is None or video_id is None:
            continue

        url = f"https://vk.com/video{owner_id}_{video_id}"

        access_key = video.get("access_key")
        if access_key:
            url += f"?access_key={access_key}"

        result.append(url)

    return result


def request_upload(type_name):
    response = SESSION.post(
        f"{MAX_API}/uploads",
        params={"type": type_name},
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    if not data.get("url"):
        raise RuntimeError(
            f"MAX returned no {type_name} upload URL"
        )

    return data


def upload_photo(url):
    image = requests.get(url, timeout=45)
    image.raise_for_status()

    if len(image.content) > 50 * 1024 * 1024:
        raise RuntimeError("Image exceeds 50 MB")

    upload_data = request_upload("image")

    uploaded = requests.post(
        upload_data["url"],
        files={
            "data": (
                "photo.jpg",
                image.content,
                image.headers.get(
                    "Content-Type", "image/jpeg"
                ),
            )
        },
        timeout=90,
    )
    uploaded.raise_for_status()

    result = uploaded.json()

    token = result.get("token")

    if not token:
        token = (
            result.get("photos", {})
            .get("0", {})
            .get("token")
        )

    if not token:
        raise RuntimeError(
            "MAX did not return an image token"
        )

    return {
        "type": "image",
        "payload": {"token": token},
    }


def upload_video(url):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "video.mp4"

        print(f"Downloading VK video: {url}", flush=True)

        with yt_dlp.YoutubeDL({
            "format": "best[ext=mp4]/best",
            "outtmpl": str(path),
            "noplaylist": True,
            "quiet": True,
            "retries": 3,
        }) as downloader:
            downloader.download([url])

        if not path.exists():
            raise RuntimeError("VK video not downloaded")

        size_mb = path.stat().st_size / 1048576
        
        print(
            f"Video downloaded: {size_mb:.2f} MB",
            flush=True,
        )

        upload_data = request_upload("video")

        # MAX may return the video token at this stage.
        token = upload_data.get("token")

        with path.open("rb") as file:
            uploaded = requests.post(
                upload_data["url"],
                files={
                    "data": (
                        "video.mp4",
                        file,
                        "video/mp4",
                    )
                },
                timeout=300,
            )

        uploaded.raise_for_status()

        # The upload endpoint may return an empty body.
        if uploaded.content.strip():
            try:
                result = uploaded.json()
            except ValueError:
                result = {}

            token = token or result.get("token")

        if not token:
            raise RuntimeError(
                "MAX did not return a video token"
            )

        print("Video uploaded to MAX", flush=True)

        return {
            "type": "video",
            "payload": {"token": token},
        }


def send_message(text, attachments, has_video=False):
    payload = {
        "text": text,
        "attachments": attachments,
    }

    # Videos may need time for processing.
    attempts = 18 if has_video else 4

    for attempt in range(attempts):
        response = SESSION.post(
            f"{MAX_API}/messages",
            params={"chat_id": CHAT_ID},
            json=payload,
            timeout=60,
        )

        if response.ok:
            return response.json()

        if has_video and response.status_code == 400:
            print(
                f"Video processing: "
                f"attempt {attempt + 1}/{attempts}",
                flush=True,
            )
            if attempt < attempts - 1:
                time.sleep(10)
                continue

        if response.status_code in (
            429, 500, 502, 503, 504
        ) and attempt < attempts - 1:
            time.sleep(3 * (attempt + 1))
            continue

        raise RuntimeError(
            f"MAX HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    raise RuntimeError("MAX did not accept message")


def send(post):
    post_id = post["id"]
    text = post.get("text", "").strip()

    photo_urls = photos(post)
    video_urls = videos(post)

    # Avoid silently publishing text without
    # unsupported media attachments.
    unsupported = [
        attachment.get("type")
        for attachment in post.get("attachments", [])
        if attachment.get("type") not in (
            "photo", "video"
        )
    ]

    if unsupported:
        raise RuntimeError(
            f"VK post {post_id} has unsupported "
            f"attachments: {unsupported}"
        )

    attachments = []

    for url in photo_urls:
        attachments.append(upload_photo(url))

    for url in video_urls:
        attachments.append(upload_video(url))

    if not text and not attachments:
        print(f"Empty post {post_id}: skipped")
        return False

    send_message(
        text,
        attachments,
        has_video=bool(video_urls),
    )

    print(
        f"Sent VK post {post_id}: "
        f"{len(photo_urls)} photos, "
        f"{len(video_urls)} videos",
        flush=True,
    )

    return True


def is_advertisement(post):
    text = post.get("text", "")

    if re.search(
        r"(?<!\w)(?:ерид|erid)\s*[:=№#-]?"
        r"\s*[A-Za-z0-9_-]+",
        text,
        re.IGNORECASE,
    ):
        return True

    return post.get("marked_as_ads") in (1, True)


def is_repost(post):
    return bool(post.get("copy_history"))


def is_daily_hashtag_post(text):
    hashtags = {
        tag.casefold()
        for tag in re.findall(r"#[\w]+", text or "")
    }

    required = {
        "#vdk",
        "#vladivostok",
        "#владивосток",
    }

    return required.issubset(hashtags)
def save_state(state):
    temporary = STATE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(state, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(STATE)


def main():
    posts = vk_posts()

    if not posts:
        print("No VK posts")
        return

    if not STATE.exists():
        save_state({
            "last_id": max(p["id"] for p in posts)
        })
        print("Initialized: existing posts skipped")
        return

    state = json.loads(
        STATE.read_text(encoding="utf-8")
    )
    last_id = int(state["last_id"])

    pending = sorted(
        (
            post for post in posts
            if post["id"] > last_id
        ),
        key=lambda post: post["id"],
    )

    if len(pending) >= 100:
        raise RuntimeError(
            "At least 100 new posts: "
            "increase polling frequency"
        )

    published = 0
    skipped_ads = 0
    skipped_reposts = 0
    skipped_daily = 0

    for post in pending:
        post_id = post["id"]

        if is_advertisement(post):
            print(f"SKIPPED AD: {post_id}")
            skipped_ads += 1

        elif is_repost(post):
            print(f"SKIPPED REPOST: {post_id}")
            skipped_reposts += 1

        elif is_daily_hashtag_post(
            post.get("text", "")
        ):
            print(f"SKIPPED DAILY: {post_id}")
            skipped_daily += 1

        else:
            if send(post):
                published += 1

        # Save progress for every processed post,
        # including filtered posts.
        state["last_id"] = post_id
        save_state(state)

    print(
        f"Published: {published}, "
        f"Skipped ads: {skipped_ads}, "
        f"Skipped reposts: {skipped_reposts}, "
        f"Skipped daily: {skipped_daily}",
        flush=True,
    )


if __name__ == "__main__":
    main()
