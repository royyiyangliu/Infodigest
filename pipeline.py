"""
Podcast transcription pipeline.
Usage: python pipeline.py <apple_podcast_url_or_xiaoyuzhoufm_url>
"""
import os, sys, time, json, re, requests, xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

API_KEY = os.environ["DASHSCOPE_API_KEY"]
SUBMIT_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"
TASK_URL = "https://dashscope.aliyuncs.com/api/v1/tasks"

SUBMIT_HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "X-DashScope-Async": "enable",
}
POLL_HEADERS = {"Authorization": f"Bearer {API_KEY}"}


# ── URL parsing ────────────────────────────────────────────────────────────────

def parse_apple_podcast(url: str) -> tuple[str, str, str, str]:
    """Return (audio_url, episode_title, language, podcast_name)."""
    m = re.search(r"/id(\d+)\?i=(\d+)", url)
    if not m:
        raise ValueError(f"Cannot extract IDs from URL: {url}")
    podcast_id, episode_id = m.group(1), m.group(2)

    # Get feed URL and podcast name from iTunes
    lookup = requests.get(
        f"https://itunes.apple.com/lookup?id={podcast_id}&entity=podcast",
        timeout=30,
    ).json()
    podcast_name = lookup["results"][0].get("collectionName", "Unknown Podcast")
    feed_url = lookup["results"][0]["feedUrl"]
    print(f"[parse] Podcast: {podcast_name}")
    print(f"[parse] Feed URL: {feed_url}")

    rss = requests.get(feed_url, timeout=60).text
    root = ET.fromstring(rss)

    lang_el = root.find("./channel/language")
    language = (lang_el.text or "en").strip().lower()[:2]

    # Match episode: guid contains episode_id OR title match from URL slug
    url_title_slug = re.search(r"/podcast/([^/]+)/id", url)
    url_slug = url_title_slug.group(1) if url_title_slug else ""

    chosen = None
    for item in root.findall("./channel/item"):
        guid = item.findtext("guid", "")
        title = item.findtext("title", "")
        if episode_id in guid:
            chosen = item; break
        # Fallback: match slug keywords against title
        if url_slug:
            slug_words = set(url_slug.lower().replace("-", " ").split())
            title_words = set(title.lower().split())
            if len(slug_words & title_words) >= 3:
                chosen = item; break

    if chosen is None:
        # Last resort: first item
        chosen = root.findall("./channel/item")[0]
        print("[parse] Warning: episode not matched, using first item")

    title = chosen.findtext("title", "unknown").strip()
    enclosure = chosen.find("enclosure")
    if enclosure is None:
        raise ValueError("No enclosure found in episode")
    audio_url = enclosure.get("url")
    print(f"[parse] Title: {title}")
    print(f"[parse] Language: {language}")
    print(f"[parse] Audio: {audio_url[:80]}...")
    return audio_url, title, language, podcast_name


def parse_xiaoyuzhoufm(url: str) -> tuple[str, str, str, str]:
    """Return (audio_url, episode_title, language, podcast_name) for xiaoyuzhoufm."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    html = resp.text

    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if not m:
        raise ValueError("Cannot find __NEXT_DATA__ in xiaoyuzhoufm page")

    data = json.loads(m.group(1))
    ep = data["props"]["pageProps"]["episode"]

    audio_url = ep["enclosure"]["url"]
    title = ep["title"].strip()
    podcast_name = ep.get("podcast", {}).get("title", "小宇宙播客").strip()
    # xiaoyuzhoufm episodes are predominantly Chinese
    language = "zh"

    print(f"[parse] Podcast: {podcast_name}")
    print(f"[parse] Title: {title}")
    print(f"[parse] Language: {language}")
    print(f"[parse] Audio: {audio_url[:80]}...")
    return audio_url, title, language, podcast_name


# ── Directory setup ────────────────────────────────────────────────────────────

def safe_slug(s: str, max_len: int = 60) -> str:
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s.strip())
    return s[:max_len].rstrip("-")


def make_episode_dir(title: str, source_url: str) -> Path:
    date_str = datetime.now().strftime("%y%m%d")
    slug = safe_slug(title)
    dir_name = f"{date_str}-{slug}"
    ep_dir = Path(__file__).parent / dir_name
    ep_dir.mkdir(exist_ok=True)
    (ep_dir / "source.url").write_text(source_url + "\n")
    print(f"[dir] Created: {ep_dir}")
    return ep_dir


# ── Transcription ──────────────────────────────────────────────────────────────

def resolve_redirect(url: str) -> str:
    """Follow redirects and return the final URL (needed for signed CDN links)."""
    r = requests.head(url, timeout=30, allow_redirects=True)
    return r.url


def submit_job(audio_url: str, language: str) -> str:
    # Some hosts (Substack) redirect to signed CDN URLs; resolve first
    final_url = resolve_redirect(audio_url)
    if final_url != audio_url:
        print(f"[asr] Resolved to CDN URL: {final_url[:80]}...")
    lang_hints = [language] if language in ("zh", "en") else ["zh"]
    payload = {
        "model": "fun-asr",
        "input": {"file_urls": [final_url]},
        "parameters": {
            "diarization_enabled": True,
            "language_hints": lang_hints,
        },
    }
    resp = requests.post(SUBMIT_URL, headers=SUBMIT_HEADERS, json=payload, timeout=30)
    if not resp.ok:
        print(f"Submit error {resp.status_code}: {resp.text}")
        resp.raise_for_status()
    task_id = resp.json()["output"]["task_id"]
    print(f"[asr] Submitted task: {task_id}")
    return task_id


def poll_job(task_id: str, max_wait: int = 3600) -> dict:
    deadline = time.time() + max_wait
    interval = 10
    while time.time() < deadline:
        resp = requests.get(f"{TASK_URL}/{task_id}", headers=POLL_HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        status = data["output"]["task_status"]
        print(f"[asr] Status: {status}", flush=True)
        if status == "SUCCEEDED":
            return data
        if status in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Task {status}: {json.dumps(data, ensure_ascii=False)}")
        time.sleep(interval)
    raise TimeoutError(f"Task not done after {max_wait}s")


def extract_transcript(result: dict) -> str:
    """Download transcript JSON and return plain text with speaker labels."""
    results = result["output"]["results"]
    transcript_url = results[0]["transcription_url"]
    r = requests.get(transcript_url, timeout=60)
    tr = json.loads(r.content)

    lines = []
    for transcript in tr.get("transcripts", []):
        for sentence in transcript.get("sentences", []):
            speaker = sentence.get("speaker_id", "?")
            text = sentence.get("text", "").strip()
            t_ms = sentence.get("begin_time", 0)
            t_fmt = f"{t_ms//60000:02d}:{(t_ms%60000)//1000:02d}"
            lines.append(f"[{t_fmt}] Speaker{speaker}: {text}")

    return "\n".join(lines)


# ── Manifest ──────────────────────────────────────────────────────────────────

def update_manifest(ep_dir: Path, title: str, podcast: str, language: str,
                    description: str = "") -> None:
    """Add or update an entry in docs/podcast-episodes.json."""
    manifest_path = Path(__file__).parent / "docs" / "podcast-episodes.json"
    episodes = json.loads(manifest_path.read_text()) if manifest_path.exists() else []

    ep_id = ep_dir.name
    summary_path = f"podcast/{ep_id}/summary.html"
    date_str = datetime.now().strftime("%Y-%m-%d")

    # Remove existing entry with same id, then prepend the new one
    episodes = [e for e in episodes if e.get("id") != ep_id]
    episodes.insert(0, {
        "id": ep_id,
        "title": title,
        "podcast": podcast,
        "date": date_str,
        "language": language,
        "path": summary_path,
        "description": description,
    })

    manifest_path.write_text(json.dumps(episodes, ensure_ascii=False, indent=2) + "\n")
    print(f"[manifest] Updated docs/podcast-episodes.json ({len(episodes)} entries)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <apple_podcast_url>")
        sys.exit(1)

    url = sys.argv[1]
    if "xiaoyuzhoufm.com" in url:
        audio_url, title, language, podcast_name = parse_xiaoyuzhoufm(url)
    else:
        audio_url, title, language, podcast_name = parse_apple_podcast(url)
    ep_dir = make_episode_dir(title, url)

    task_id = submit_job(audio_url, language)
    print("[asr] Polling (may take several minutes for long episodes)...")
    result = poll_job(task_id)

    transcript = extract_transcript(result)
    transcript_path = ep_dir / "transcript.txt"
    transcript_path.write_text(transcript, encoding="utf-8")
    print(f"[done] Transcript saved: {transcript_path}")
    print(f"[done] Lines: {transcript.count(chr(10))+1}")
    print(f"[done] Next step: read {transcript_path} and write docs/podcast/{ep_dir.name}/summary.html,")
    print(f"       then fill in description in docs/podcast-episodes.json")

    update_manifest(ep_dir, title, podcast_name, language)


if __name__ == "__main__":
    main()
