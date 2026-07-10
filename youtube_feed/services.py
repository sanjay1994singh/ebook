import json
import re
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache


YOUTUBE_BASE_URL = "https://www.youtube.com"


def get_channel_handle():
    # .env me YOUTUBE_CHANNEL_HANDLE=@NidhivanRas set kar sakte hain.
    return getattr(settings, "YOUTUBE_CHANNEL_HANDLE", "@NidhivanRas").strip() or "@NidhivanRas"


def fetch_youtube_page(path):
    url = urljoin(YOUTUBE_BASE_URL, path)
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
        },
    )
    with urlopen(request, timeout=12) as response:
        return response.read().decode("utf-8", errors="ignore")


def extract_initial_data(html):
    # YouTube page ke embedded JSON se video list nikalti hai, API key ki jarurat nahi.
    patterns = (
        r"var ytInitialData\s*=\s*(\{.*?\});</script>",
        r"window\[['\"]ytInitialData['\"]\]\s*=\s*(\{.*?\});</script>",
        r"ytInitialData\"\]\s*=\s*(\{.*?\});</script>",
    )
    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    return {}


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def get_text(value):
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get("simpleText"):
            return value["simpleText"]
        runs = value.get("runs") or []
        return "".join(run.get("text", "") for run in runs)
    return ""


def get_best_thumbnail(thumbnail_data):
    thumbnails = (thumbnail_data or {}).get("thumbnails") or []
    if not thumbnails:
        return ""
    return thumbnails[-1].get("url", "").split("?")[0]


def video_from_renderer(renderer, video_type):
    video_id = renderer.get("videoId")
    if not video_id:
        return None

    title = get_text(renderer.get("title") or renderer.get("headline"))
    url_path = f"/shorts/{video_id}" if video_type == "short" else f"/watch?v={video_id}"
    return {
        "id": video_id,
        "title": title or "YouTube Video",
        "type": video_type,
        "url": urljoin(YOUTUBE_BASE_URL, url_path),
        "thumbnail_url": get_best_thumbnail(renderer.get("thumbnail")),
        "duration": get_text(renderer.get("lengthText")),
        "published": get_text(renderer.get("publishedTimeText")),
        "views": get_text(renderer.get("viewCountText") or renderer.get("shortViewCountText")),
    }


def parse_videos(initial_data, video_type):
    items = []
    seen = set()
    renderer_key = "reelItemRenderer" if video_type == "short" else "videoRenderer"

    for node in walk_json(initial_data):
        renderer = node.get(renderer_key)
        if not renderer:
            continue
        item = video_from_renderer(renderer, video_type)
        if not item or item["id"] in seen:
            continue
        seen.add(item["id"])
        items.append(item)
        if len(items) >= 24:
            break
    return items


def get_channel_videos():
    cache_key = f"youtube-channel-feed:{get_channel_handle()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    handle = get_channel_handle()
    channel_url = f"{YOUTUBE_BASE_URL}/{handle}"
    videos = []
    shorts = []

    try:
        videos_html = fetch_youtube_page(f"/{handle}/videos")
        videos = parse_videos(extract_initial_data(videos_html), "video")
    except Exception:
        videos = []

    try:
        shorts_html = fetch_youtube_page(f"/{handle}/shorts")
        shorts = parse_videos(extract_initial_data(shorts_html), "short")
    except Exception:
        shorts = []

    payload = {
        "channel": {
            "handle": handle,
            "title": "Nidhivan Ras",
            "url": channel_url,
        },
        "videos": videos,
        "shorts": shorts,
    }
    cache.set(cache_key, payload, 60 * 30)
    return payload
