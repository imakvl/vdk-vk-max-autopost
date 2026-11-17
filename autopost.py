import json, os, time, re
from pathlib import Path
import requests

VK_TOKEN = os.environ['VK_TOKEN']
MAX_TOKEN = os.environ['MAX_TOKEN']
CHAT_ID = os.environ['MAX_CHAT_ID']
STATE = Path('state.json')
VK_API = 'https://api.vk.com/method/wall.get'
MAX_API = 'https://platform-api2.max.ru'
HEADERS = {'Authorization': MAX_TOKEN}


def vk_posts():
    r = requests.get(VK_API, params={'domain': 'myvdk', 'count': 100, 'v': '5.199', 'access_token': VK_TOKEN}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if 'error' in data:
        raise RuntimeError(f"VK API: {data['error']['error_code']} {data['error']['error_msg']}")
    return [p for p in data['response']['items'] if not p.get('is_pinned') and not p.get('marked_as_ads')]


def photos(post):
    result = []
    for a in post.get('attachments', []):
        if a.get('type') != 'photo':
            continue
        sizes = a.get('photo', {}).get('sizes', [])
        if sizes:
            best = max(sizes, key=lambda s: s.get('width', 0) * s.get('height', 0))
            if best.get('url'):
                result.append(best['url'])
    return result[:12]


def upload_photo(url):
    # Скачиваем фотографию из ВКонтакте
    image = requests.get(url, timeout=45)
    image.raise_for_status()

    if len(image.content) > 50 * 1024 * 1024:
        raise RuntimeError('Image exceeds MAX 50 MB limit')

    # Получаем ссылку для загрузки в MAX
    upload = requests.post(
        f'{MAX_API}/uploads',
        params={'type': 'image'},
        headers=HEADERS,
        timeout=30
    )
    upload.raise_for_status()

    upload_data = upload.json()
    upload_url = upload_data['url']

    # Загружаем фотографию
    sent = requests.post(
        upload_url,
        files={
            'data': (
                'photo.jpg',
                image.content,
                image.headers.get('Content-Type', 'image/jpeg')
            )
        },
        timeout=90
    )
    sent.raise_for_status()

    # Получаем токен фотографии из ответа MAX
    data = sent.json()

    token = data.get('token')

    if not token:
        photos_data = data.get('photos', {})
        photo = photos_data.get('0', {})
        token = photo.get('token')

    if not token:
        raise RuntimeError(
            'MAX image upload returned no token'
        )

    # Возвращаем вложение для публикации
    return {
        'type': 'image',
        'payload': {
            'token': token
        }
    }


def send(post):
    attachments = [upload_photo(url) for url in photos(post)]
    text = post.get('text', '').strip()
    if not text and not attachments:
        print(f"Skipping unsupported post {post['id']}")
        return
    payload = {'text': text, 'attachments': attachments}
    for attempt in range(4):
        r = requests.post(f'{MAX_API}/messages', params={'chat_id': CHAT_ID}, headers={**HEADERS, 'Content-Type': 'application/json'}, json=payload, timeout=60)
        if r.ok:
            print(f"Sent VK post {post['id']}")
            return
        if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            time.sleep(3 * (attempt + 1))
            continue
        raise RuntimeError(f'MAX HTTP {r.status_code}: {r.text[:500]}')

def is_advertisement(post):
    text = post.get('text', '')

    # Русская и английская маркировка рекламы
    if re.search(
        r'(?<!\w)(?:ерид|erid)\s*[:=№#-]?\s*[A-Za-z0-9_-]+',
        text,
        re.IGNORECASE
    ):
        return True

    # Рекламная пометка ВКонтакте
    if post.get('marked_as_ads') in (1, True):
        return True

    return False

def is_repost(post):
    # Проверяем, содержит ли запись историю репоста
    return bool(post.get('copy_history'))

def is_daily_hashtag_post(text):
    hashtags = set(
        tag.casefold()
        for tag in re.findall(r"#[\w]+", text or "")
    )

    required = {
        "#vdk",
        "#vladivostok",
        "#владивосток",
    }

    return required.issubset(hashtags)

def main():
    posts = vk_posts()

    if not posts:
        print('No VK posts')
        return

    if not STATE.exists():
        STATE.write_text(
            json.dumps({
                'last_id': max(p['id'] for p in posts)
            }, indent=2) + '\n'
        )
        print('Initialized: existing posts skipped')
        return

    state = json.loads(STATE.read_text())
    last_id = int(state['last_id'])

    pending = sorted(
        (p for p in posts if p['id'] > last_id),
        key=lambda p: p['id']
    )

    if len(pending) >= 100:
        raise RuntimeError(
            'At least 100 new posts: increase polling frequency'
        )

published = 0
skipped_ads = 0
skipped_reposts = 0
skipped_daily = 0

for p in pending:

    if is_advertisement(p):
        print(f"SKIPPED AD: VK post {p['id']}")
        skipped_ads += 1

    elif is_repost(p):
        print(f"SKIPPED REPOST: VK post {p['id']}")
        skipped_reposts += 1

    elif is_daily_hashtag_post(p.get('text', '')):
        print(f"SKIPPED DAILY POST: VK post {p['id']}")
        skipped_daily += 1

    else:
        send(p)
        published += 1

        # Сохраняем ID каждой обработанной записи,
        # включая пропущенные публикации
        state['last_id'] = p['id']

        STATE.write_text(
            json.dumps(state, indent=2) + '\n'
        )

    print(
        f'Published: {published}, '
        f'Skipped ads: {skipped_ads}, '
        f'Skipped reposts: {skipped_reposts}, '
        f'Skipped daily: {skipped_daily}'
    )


if __name__ == '__main__':
    main()
