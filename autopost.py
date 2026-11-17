import json
import os
import re
import tempfile
import time
from pathlib import Path

import requests
import yt_dlp

VK_TOKEN = os.environ['VK_TOKEN']
MAX_TOKEN = os.environ['MAX_TOKEN']
CHAT_ID = os.environ['MAX_CHAT_ID']
STATE = Path('state.json')
VK_API = 'https://api.vk.com/method/wall.get'
MAX_API = 'https://platform-api2.max.ru'
HEADERS = {'Authorization': MAX_TOKEN}
SESSION = requests.Session()


def vk_posts():
    response = SESSION.get(VK_API, params={
        'domain': 'myvdk', 'count': 100, 'v': '5.199',
        'access_token': VK_TOKEN,
    }, timeout=30)
    response.raise_for_status()
    data = response.json()
    if 'error' in data:
        err = data['error']
        raise RuntimeError(f"VK API: {err.get('error_code')} {err.get('error_msg')}")
    return [p for p in data['response']['items'] if not p.get('is_pinned')]


def photos(post):
    result = []
    for attachment in post.get('attachments', []):
        if attachment.get('type') != 'photo':
            continue
        sizes = [s for s in attachment.get('photo', {}).get('sizes', []) if s.get('url')]
        if sizes:
            best = max(sizes, key=lambda s: s.get('width', 0) * s.get('height', 0))
            result.append(best['url'])
    return result[:12]


def videos(post):
    result = []
    for attachment in post.get('attachments', []):
        if attachment.get('type') != 'video':
            continue
        video = attachment.get('video') or {}
        owner_id, video_id = video.get('owner_id'), video.get('id')
        if owner_id is None or video_id is None:
            raise RuntimeError(f"VK post {post['id']} contains video without owner/id")
        url = f'https://vk.com/video{owner_id}_{video_id}'
        if video.get('access_key'):
            url += f"?access_key={video['access_key']}"
        result.append(url)
    return result


def upload_slot(kind):
    response = SESSION.post(f'{MAX_API}/uploads', params={'type': kind}, headers=HEADERS, timeout=30)
    response.raise_for_status()
    data = response.json()
    if not data.get('url'):
        raise RuntimeError(f'MAX {kind} upload slot has no URL')
    return data['url'], data.get('token')


def upload_photo(url):
    image = SESSION.get(url, timeout=45)
    image.raise_for_status()
    if len(image.content) > 50 * 1024 * 1024:
        raise RuntimeError('Image exceeds 50 MB')
    upload_url, _ = upload_slot('image')
    sent = SESSION.post(upload_url, files={
        'data': ('photo.jpg', image.content, image.headers.get('Content-Type', 'image/jpeg')),
    }, timeout=90)
    sent.raise_for_status()
    data = sent.json()
    token = data.get('token') or (data.get('photos') or {}).get('0', {}).get('token')
    if not token:
        raise RuntimeError('MAX image upload returned no token')
    return {'type': 'image', 'payload': {'token': token}}


def upload_video(url):
    with tempfile.TemporaryDirectory(prefix='vk_video_') as folder:
        destination = Path(folder) / 'video.mp4'
        options = {
            'outtmpl': str(destination),
            'format': 'best[ext=mp4]/best',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'retries': 3,
            'socket_timeout': 30,
        }
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.download([url])
        if not destination.is_file() or destination.stat().st_size == 0:
            raise RuntimeError(f'VK video download failed: {url}')
        size_mb = destination.stat().st_size / (1024 * 1024)
        print(f'Downloaded VK video: {size_mb:.2f} MB', flush=True)
        upload_url, token = upload_slot('video')
        if not token:
            raise RuntimeError('MAX video upload slot returned no token')
        with destination.open('rb') as file:
            sent = SESSION.post(upload_url, files={
                'data': ('video.mp4', file, 'video/mp4'),
            }, timeout=300)
        sent.raise_for_status()
        print('MAX accepted video upload', flush=True)
        return {'type': 'video', 'payload': {'token': token}}


def send(post):
    text = post.get('text', '').strip()
    image_urls = photos(post)
    video_urls = videos(post)
    if not text and not image_urls and not video_urls:
        print(f"SKIPPED UNSUPPORTED: VK post {post['id']}")
        return False

    attachments = []
    for url in image_urls:
        attachments.append(upload_photo(url))
    for url in video_urls:
        attachments.append(upload_video(url))

    payload = {'text': text, 'attachments': attachments}
    for attempt in range(4):
        response = SESSION.post(
            f'{MAX_API}/messages', params={'chat_id': CHAT_ID},
            headers={**HEADERS, 'Content-Type': 'application/json'},
            json=payload, timeout=60,
        )
        if response.ok:
            print(f"Sent VK post {post['id']} with {len(image_urls)} image(s) and {len(video_urls)} video(s)")
            return True
        if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            time.sleep(3 * (attempt + 1))
            continue
        raise RuntimeError(f'MAX HTTP {response.status_code}: {response.text[:500]}')
    return False


def is_advertisement(post):
    text = post.get('text', '')
    return bool(post.get('marked_as_ads')) or bool(re.search(
        r'(?<!\w)(?:ерид|erid)\s*[:=№#-]?\s*[A-Za-z0-9_-]+',
        text, re.IGNORECASE,
    ))


def is_repost(post):
    return bool(post.get('copy_history'))


def is_daily_hashtag_post(text):
    hashtags = {tag.casefold() for tag in re.findall(r'#[\w]+', text or '')}
    return {'#vdk', '#vladivostok', '#владивосток'}.issubset(hashtags)


def save_state(state):
    temp = STATE.with_suffix('.tmp')
    temp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temp.replace(STATE)


def main():
    posts = vk_posts()
    if not posts:
        print('No VK posts')
        return
    if not STATE.exists():
        save_state({'last_id': max(p['id'] for p in posts)})
        print('Initialized: existing posts skipped')
        return

    state = json.loads(STATE.read_text(encoding='utf-8'))
    last_id = int(state['last_id'])
    pending = sorted((p for p in posts if p['id'] > last_id), key=lambda p: p['id'])
    if len(pending) >= 100:
        raise RuntimeError('At least 100 new posts: increase polling frequency')

    published = skipped_ads = skipped_reposts = skipped_daily = skipped_unsupported = 0
    for post in pending:
        if is_advertisement(post):
            print(f"SKIPPED AD: VK post {post['id']}")
            skipped_ads += 1
        elif is_repost(post):
            print(f"SKIPPED REPOST: VK post {post['id']}")
            skipped_reposts += 1
        elif is_daily_hashtag_post(post.get('text', '')):
            print(f"SKIPPED DAILY POST: VK post {post['id']}")
            skipped_daily += 1
        elif send(post):
            published += 1
        else:
            skipped_unsupported += 1

        state['last_id'] = post['id']
        save_state(state)

    print(f'Published: {published}, Skipped ads: {skipped_ads}, '
          f'Skipped reposts: {skipped_reposts}, Skipped daily: {skipped_daily}, '
          f'Skipped unsupported: {skipped_unsupported}')


if __name__ == '__main__':
    main()
