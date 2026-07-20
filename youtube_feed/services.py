import json
import re
import xml.etree.ElementTree as ET
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


def extract_json_object(html, marker):
    marker_index = html.find(marker)
    if marker_index == -1:
        return {}

    start_index = html.find("{", marker_index)
    if start_index == -1:
        return {}

    depth = 0
    in_string = False
    escape = False

    for index in range(start_index, len(html)):
        char = html[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start_index:index + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


def extract_initial_data(html):
    # YouTube page ke embedded JSON se video list nikalti hai, API key ki jarurat nahi.
    for marker in ("var ytInitialData =", "ytInitialData", "window[\"ytInitialData\"]"):
        data = extract_json_object(html, marker)
        if data:
            return data
    return {}


def extract_channel_id(html):
    patterns = (
        r'"channelId":"(UC[^"]+)"',
        r'"externalId":"(UC[^"]+)"',
        r'<meta itemprop="channelId" content="([^"]+)"',
    )
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return ""


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
        if value.get("content"):
            return value["content"]
        runs = value.get("runs") or []
        return "".join(run.get("text", "") for run in runs)
    return ""


def get_best_thumbnail(thumbnail_data):
    if isinstance(thumbnail_data, list):
        for item in thumbnail_data:
            thumbnail = get_best_thumbnail(item)
            if thumbnail:
                return thumbnail
        return ""
    thumbnails = (thumbnail_data or {}).get("thumbnails") or []
    if not thumbnails:
        image_sources = (thumbnail_data or {}).get("sources") or []
        if image_sources:
            return image_sources[-1].get("url", "").split("?")[0]
        return ""
    return thumbnails[-1].get("url", "").split("?")[0]


def get_video_id(renderer):
    if renderer.get("videoId"):
        return renderer["videoId"]
    if renderer.get("contentId"):
        return renderer["contentId"]

    endpoint = renderer.get("navigationEndpoint") or {}
    if not endpoint:
        endpoint = renderer.get("rendererContext", {}).get("commandContext", {}).get("onTap", {}).get("innertubeCommand", {})
    if endpoint.get("watchEndpoint", {}).get("videoId"):
        return endpoint["watchEndpoint"]["videoId"]
    if endpoint.get("reelWatchEndpoint", {}).get("videoId"):
        return endpoint["reelWatchEndpoint"]["videoId"]

    inner_command = renderer.get("onTap", {}).get("innertubeCommand", {})
    if inner_command.get("reelWatchEndpoint", {}).get("videoId"):
        return inner_command["reelWatchEndpoint"]["videoId"]
    if inner_command.get("watchEndpoint", {}).get("videoId"):
        return inner_command["watchEndpoint"]["videoId"]

    command = endpoint.get("commandMetadata", {}).get("webCommandMetadata", {})
    if not command:
        command = inner_command.get("commandMetadata", {}).get("webCommandMetadata", {})
    url = command.get("url") or ""
    match = re.search(r"(?:v=|/shorts/)([A-Za-z0-9_-]{8,})", url)
    return match.group(1) if match else ""


def video_from_renderer(renderer, video_type):
    video_id = get_video_id(renderer)
    if not video_id:
        return None

    title = get_text(renderer.get("title") or renderer.get("headline") or renderer.get("accessibilityText"))
    if not title:
        title = get_text(renderer.get("metadata", {}).get("lockupMetadataViewModel", {}).get("title"))
    if not title:
        title = get_text(renderer.get("rendererContext", {}).get("accessibilityContext", {}).get("label"))
    if video_type == "short" and title:
        title = re.sub(r",\s*[\d,.]+\s+views?\s+-\s+play Short$", "", title, flags=re.IGNORECASE)
    if video_type == "video" and title:
        title = re.sub(r"\s+\d+\s+(?:seconds?|minutes?|hours?)$", "", title, flags=re.IGNORECASE)
    url_path = f"/shorts/{video_id}" if video_type == "short" else f"/watch?v={video_id}"
    thumbnail_data = renderer.get("thumbnail")
    if not thumbnail_data:
        thumbnail_data = renderer.get("onTap", {}).get("innertubeCommand", {}).get("reelWatchEndpoint", {}).get("thumbnail")
    if not thumbnail_data:
        thumbnail_data = renderer.get("contentImage", {}).get("thumbnailViewModel", {}).get("image")
    metadata_rows = (
        renderer.get("metadata", {})
        .get("lockupMetadataViewModel", {})
        .get("metadata", {})
        .get("contentMetadataViewModel", {})
        .get("metadataRows", [])
    )
    metadata_parts = []
    for row in metadata_rows:
        metadata_parts.extend(row.get("metadataParts", []))
    metadata_text = [get_text(part.get("text")) for part in metadata_parts]
    return {
        "id": video_id,
        "title": title or "YouTube Video",
        "type": video_type,
        "url": urljoin(YOUTUBE_BASE_URL, url_path),
        "thumbnail_url": get_best_thumbnail(thumbnail_data or renderer.get("thumbnailOverlays")),
        "duration": get_text(renderer.get("lengthText")),
        "published": get_text(renderer.get("publishedTimeText")) or (metadata_text[1] if len(metadata_text) > 1 else ""),
        "views": get_text(renderer.get("viewCountText") or renderer.get("shortViewCountText")) or (metadata_text[0] if metadata_text else ""),
    }


def parse_videos(initial_data, video_type):
    items = []
    seen = set()
    renderer_keys = ("reelItemRenderer", "shortsLockupViewModel") if video_type == "short" else (
        "videoRenderer",
        "gridVideoRenderer",
        "compactVideoRenderer",
        "lockupViewModel",
    )

    for node in walk_json(initial_data):
        renderer = None
        for renderer_key in renderer_keys:
            if node.get(renderer_key):
                renderer = node[renderer_key]
                break
        if renderer:
            item = video_from_renderer(renderer, video_type)
            if not item or item["id"] in seen:
                continue
            seen.add(item["id"])
            items.append(item)
        if len(items) >= 24:
            break
    return items


def parse_rss_videos(xml_text):
    items = []
    namespace = {
        "atom": "http://www.w3.org/2005/Atom",
        "media": "http://search.yahoo.com/mrss/",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }
    root = ET.fromstring(xml_text)
    for entry in root.findall("atom:entry", namespace):
        video_id = (entry.findtext("yt:videoId", default="", namespaces=namespace) or "").strip()
        if not video_id:
            continue
        media_group = entry.find("media:group", namespace)
        thumbnail_url = ""
        description = ""
        if media_group is not None:
            thumbnail = media_group.find("media:thumbnail", namespace)
            if thumbnail is not None:
                thumbnail_url = thumbnail.attrib.get("url", "")
            description = media_group.findtext("media:description", default="", namespaces=namespace) or ""
        items.append({
            "id": video_id,
            "title": entry.findtext("atom:title", default="YouTube Video", namespaces=namespace),
            "type": "video",
            "url": urljoin(YOUTUBE_BASE_URL, f"/watch?v={video_id}"),
            "thumbnail_url": thumbnail_url or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "duration": "",
            "published": entry.findtext("atom:published", default="", namespaces=namespace),
            "views": description[:80],
        })
        if len(items) >= 24:
            break
    return items


def fetch_rss_videos(channel_id):
    if not channel_id:
        return []
    request = Request(
        f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urlopen(request, timeout=12) as response:
        return parse_rss_videos(response.read().decode("utf-8", errors="ignore"))


def get_channel_videos(force_refresh=False):
    cache_key = f"youtube-channel-feed:{get_channel_handle()}"
    cached = cache.get(cache_key)
    if cached and not force_refresh:
        return cached

    handle = get_channel_handle()
    channel_url = f"{YOUTUBE_BASE_URL}/{handle}"
    videos = []
    shorts = []
    channel_html = ""
    channel_id = ""

    try:
        channel_html = fetch_youtube_page(f"/{handle}")
        channel_id = extract_channel_id(channel_html)
    except Exception:
        channel_html = ""
        channel_id = ""

    try:
        videos_html = fetch_youtube_page(f"/{handle}/videos")
        videos = parse_videos(extract_initial_data(videos_html), "video")
    except Exception:
        videos = []

    if not videos:
        try:
            videos = fetch_rss_videos(channel_id)
        except Exception:
            videos = []

    try:
        shorts_html = fetch_youtube_page(f"/{handle}/shorts")
        shorts = parse_videos(extract_initial_data(shorts_html), "short")
    except Exception:
        shorts = []

    if not shorts and channel_html:
        shorts = parse_videos(extract_initial_data(channel_html), "short")

    payload = {
        "channel": {
            "handle": handle,
            "title": "Nidhivan Ras",
            "url": channel_url,
            "channel_id": channel_id,
        },
        "videos": videos,
        "shorts": shorts,
    }
    cache.set(cache_key, payload, 60 * 10)
    return payload
