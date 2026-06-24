"""
Podcast transcription pipeline.
Usage: python pipeline.py <apple_podcast_url_or_xiaoyuzhoufm_url>
"""
import os, sys, time, json, re, tempfile, requests, xml.etree.ElementTree as ET
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
    ep_dir = Path(__file__).parent / "docs" / "podcast" / dir_name
    ep_dir.mkdir(parents=True, exist_ok=True)
    (ep_dir / "source.url").write_text(source_url + "\n")
    print(f"[dir] Created: {ep_dir}")
    return ep_dir


# ── Transcription ──────────────────────────────────────────────────────────────

class FileDownloadFailed(Exception):
    """DashScope could not download the submitted audio URL (e.g. the origin CDN
    is region-restricted for the ASR service). Triggers the re-hosting fallback."""


def resolve_redirect(url: str) -> str:
    """Follow redirects and return the final URL (needed for signed CDN links)."""
    r = requests.head(url, timeout=30, allow_redirects=True)
    return r.url


def download_file(url: str, dest: str) -> str:
    """Stream-download a (possibly large) file to dest."""
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    f.write(chunk)
    return dest


def upload_to_litterbox(path: str, expiry: str = "72h") -> str:
    """Re-host a local file on litterbox (temporary, no credentials) and return
    the public URL. Used as a fallback when DashScope cannot fetch the origin."""
    name = os.path.basename(path)
    with open(path, "rb") as f:
        resp = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": expiry},
            files={"fileToUpload": (name, f, "audio/mpeg")},
            timeout=600,
        )
    resp.raise_for_status()
    url = resp.text.strip()
    if not url.startswith("http"):
        raise RuntimeError(f"litterbox upload failed: {url!r}")
    return url


def mirror_audio(audio_url: str, tag: str = "") -> str:
    """Download the origin audio ourselves and re-host it on litterbox, returning a
    DashScope-reachable mirror URL. Used as the fallback when DashScope cannot fetch
    the origin (FILE_DOWNLOAD_FAILED), e.g. Substack/Anchor block its downloader."""
    tmp = os.path.join(tempfile.gettempdir(), f"audio_{tag or 'x'}.mp3")
    try:
        download_file(resolve_redirect(audio_url), tmp)
        print(f"[asr] Downloaded {os.path.getsize(tmp)//(1<<20)} MB; uploading to litterbox...")
        mirror_url = upload_to_litterbox(tmp)
        print(f"[asr] Mirror URL: {mirror_url}")
        return mirror_url
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


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
            out = data.get("output", {})
            code = out.get("code")
            if not code:
                for r in out.get("results") or []:
                    if r.get("code"):
                        code = r["code"]; break
            if code == "FILE_DOWNLOAD_FAILED":
                raise FileDownloadFailed(json.dumps(data, ensure_ascii=False))
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

# ── Substack download bypass ──────────────────────────────────────────────────
# Substack 在 api.substack.com 这一跳按 IP 封禁数据中心出口（GitHub Actions / DashScope
# 的机房 IP 都会拿到 403），导致自抓的 Substack 播客转录失败。resolve.curve.to 是一个
# 透明代理：它在自己（不被封）的服务器上去取 Substack 音频、把字节直接转发回来，
# Actions 与 DashScope 都能访问。仅对 Substack 源启用，其它来源流程不变。
SUBSTACK_PROXY = "https://resolve.curve.to/resolve?url="


def is_substack_audio(url: str) -> bool:
    return "api.substack.com" in (url or "")


def curveto_wrap(url: str) -> str:
    """Wrap a Substack audio URL with the resolve.curve.to proxy (URL-encoded)."""
    from urllib.parse import quote
    return SUBSTACK_PROXY + quote(url, safe="")


def recover_download_failed(audio_url: str, language: str, tag: str = "") -> dict:
    """Recover after DashScope reports FILE_DOWNLOAD_FAILED on audio_url, returning a
    poll_job result (or raising if every level fails).

    The caller has already tried Level 1 (submitting the origin URL to DashScope).
    Level 2 (Substack only): hand the curve.to-proxied URL straight to DashScope.
    Level 3: download the audio ourselves — through the proxy for Substack, else the
             origin — re-host on litterbox, then resubmit.
    Non-Substack origins skip Level 2, so their behavior is unchanged (Level 3 only)."""
    proxied = curveto_wrap(audio_url) if is_substack_audio(audio_url) else audio_url

    if proxied != audio_url:
        try:
            print("    [回退1] 经 resolve.curve.to 代理后重新提交 DashScope...")
            return poll_job(submit_job(proxied, language))
        except FileDownloadFailed:
            print("    [回退1] DashScope 仍无法抓取代理链，转为自托管...")

    print("    [回退2] 自托管(下载音频 + litterbox 转存)后重试...")
    mirror_url = mirror_audio(proxied, tag=tag)
    return poll_job(submit_job(mirror_url, language))


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
    try:
        result = poll_job(task_id)
    except FileDownloadFailed:
        # Origin not fetchable by DashScope (FILE_DOWNLOAD_FAILED): Substack IP-blocks
        # datacenter egress, Anchor/Spotify staging CloudFront is region-restricted, etc.
        # Recover via curve.to proxy (Substack) and/or self-hosting on litterbox.
        print("[asr] DashScope could not fetch the origin URL; recovering...")
        result = recover_download_failed(audio_url, language, tag=task_id)

    transcript = extract_transcript(result)
    transcript_path = ep_dir / "transcript.txt"
    transcript_path.write_text(transcript, encoding="utf-8")
    print(f"[done] Transcript saved: {transcript_path}")
    print(f"[done] Lines: {transcript.count(chr(10))+1}")
    print(f"[done] Next step: read {transcript_path} and write {ep_dir}/summary.html,")
    print(f"       then fill in description in docs/podcast-episodes.json")

    update_manifest(ep_dir, title, podcast_name, language)


if __name__ == "__main__":
    main()
