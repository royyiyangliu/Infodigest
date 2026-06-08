#!/usr/bin/env python3
"""
AI Information Digest - Daily Fetcher
- Podcasts : title / date / episode-link / audio-url / summary
- Articles : title / date / link / full-text (saved as .txt)
Deduplication via SQLite; new items only on subsequent runs.
"""
import sys, subprocess
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
for pkg in ["feedparser", "requests", "beautifulsoup4"]:
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

import feedparser, requests, sqlite3, json, re
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse
from email.utils import parsedate_to_datetime

BASE = Path(__file__).parent
DATA = BASE / "data"
DB   = BASE / "digest.db"
DATA.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# ── Source list ───────────────────────────────────────────────────────────────
# type      : "podcast" | "article"
# apple_id  : Apple Podcasts numeric ID  →  resolved to RSS via iTunes API
# rss       : direct RSS/Atom URL        →  used as-is
# archive   : archive page URL           →  we discover the RSS from HTML <link>
SOURCES = [
    # ── 中文播客 ──────────────────────────────────────────────────────────────
    {"name": "张小珺Jùn｜商业访谈录",      "type": "podcast", "apple_id": "1634356920"},
    {"name": "卫诗婕｜漫谈Light the Star", "type": "podcast", "apple_id": "1754955836"},
    {"name": "罗永浩的十字路口",            "type": "podcast", "apple_id": "1834069371"},
    {"name": "硅谷101",                    "type": "podcast", "apple_id": "1498541229"},
    {"name": "晚点聊 LateTalk",            "type": "podcast", "apple_id": "1564877433"},
    {"name": "乱翻书",                     "type": "podcast", "apple_id": "1591595410"},
    # ── 英文播客 ──────────────────────────────────────────────────────────────
    {"name": "Lex Fridman Podcast",       "type": "podcast", "apple_id": "1434243584"},
    {"name": "Dwarkesh Podcast",          "type": "podcast", "apple_id": "1516093381"},
    {"name": "Latent Space",              "type": "podcast", "apple_id": "1674008350"},
    {"name": "No Priors",                 "type": "podcast", "apple_id": "1668002688"},
    {"name": "BG2Pod",                    "type": "podcast", "apple_id": "1727278168"},
    # ── 文章 ──────────────────────────────────────────────────────────────────
    {"name": "Epoch AI",      "type": "article", "rss": "https://epochai.substack.com/feed"},
    {"name": "SemiAnalysis",  "type": "article", "rss": "https://newsletter.semianalysis.com/feed"},
    {"name": "Citrini",       "type": "article", "archive": "https://www.citriniresearch.com/archive"},
    {"name": "a16z",          "type": "article", "archive": "https://www.a16z.news/archive"},
    {"name": "GameDev Report","type": "article", "rss": "https://gamedevreports.substack.com/feed"},
]

# ── Database ──────────────────────────────────────────────────────────────────
def init_db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS seen_items (
        guid TEXT PRIMARY KEY, source TEXT, title TEXT,
        link TEXT, pub_date TEXT, item_type TEXT, fetched_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS rss_cache (
        key TEXT PRIMARY KEY, rss_url TEXT, cached_at TEXT)""")
    con.commit()
    return con

def is_new(con, guid):
    return con.execute("SELECT 1 FROM seen_items WHERE guid=?", (guid,)).fetchone() is None

def mark_seen(con, guid, source, title, link, pub_date, item_type):
    con.execute(
        "INSERT OR IGNORE INTO seen_items VALUES (?,?,?,?,?,?,?)",
        (guid, source, title, link, pub_date, item_type,
         datetime.now(timezone.utc).isoformat()))
    con.commit()

# ── RSS URL resolution ────────────────────────────────────────────────────────
def itunes_lookup(apple_id, con):
    """Resolve Apple Podcasts ID → RSS URL, with DB cache."""
    row = con.execute("SELECT rss_url FROM rss_cache WHERE key=?", (apple_id,)).fetchone()
    if row:
        return row[0]
    try:
        r = requests.get(f"https://itunes.apple.com/lookup?id={apple_id}",
                         headers=HEADERS, timeout=10)
        results = r.json().get("results", [])
        rss_url = results[0].get("feedUrl", "") if results else ""
        if rss_url:
            con.execute("INSERT OR REPLACE INTO rss_cache VALUES (?,?,?)",
                        (apple_id, rss_url, datetime.now(timezone.utc).isoformat()))
            con.commit()
            return rss_url
    except Exception as e:
        print(f"    [iTunes] {e}")
    return None

def discover_rss(archive_url, con):
    """Find RSS feed for an archive page: check cache, try /feed, parse HTML <link>."""
    cache_key = f"archive:{archive_url}"
    row = con.execute("SELECT rss_url FROM rss_cache WHERE key=?", (cache_key,)).fetchone()
    if row:
        return row[0]

    candidates = []
    # Parse HTML for <link rel="alternate" type="...rss+xml"> or atom
    try:
        r = requests.get(archive_url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup.find_all("link", type=re.compile(r"(rss|atom)\+xml")):
            href = tag.get("href", "")
            if href:
                candidates.insert(0, urljoin(archive_url, href))
    except Exception:
        pass

    # Common RSS path guesses
    base = f"{urlparse(archive_url).scheme}://{urlparse(archive_url).netloc}"
    for path in ["/feed", "/feed.xml", "/rss", "/rss.xml", "/atom.xml"]:
        candidates.append(base + path)

    for url in candidates:
        try:
            feed = feedparser.parse(url, request_headers=HEADERS)
            if feed.entries:
                con.execute("INSERT OR REPLACE INTO rss_cache VALUES (?,?,?)",
                            (cache_key, url, datetime.now(timezone.utc).isoformat()))
                con.commit()
                return url
        except Exception:
            pass
    return None

def get_rss_url(source, con):
    if source.get("rss"):
        return source["rss"]
    if source.get("apple_id"):
        return itunes_lookup(source["apple_id"], con)
    if source.get("archive"):
        return discover_rss(source["archive"], con)
    return None

def fetch_apple_episode_urls(apple_id):
    """
    Query iTunes episode lookup API to get Apple Podcasts deep links.
    Returns dict: {"YYYY-MM-DD": "https://podcasts.apple.com/..."}
    Matches by release date; used to build episode-level Apple Podcasts links.
    """
    url = f"https://itunes.apple.com/lookup?id={apple_id}&entity=podcastEpisode&limit=200"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        ep_map = {}
        for item in r.json().get("results", []):
            if item.get("kind") != "podcast-episode":
                continue
            date = item.get("releaseDate", "")[:10]   # "YYYY-MM-DD"
            apple_url = item.get("trackViewUrl", "")
            if date and apple_url:
                ep_map[date] = apple_url
        return ep_map
    except Exception as e:
        print(f"    [WARN] Apple episode lookup failed: {e}")
        return {}

# ── Text helpers ──────────────────────────────────────────────────────────────
def format_duration(raw):
    """Normalize podcast duration to H:MM:SS or M:SS regardless of source format.
    Handles: '1:23:45', '83:45', '4830' (seconds), 4830 (int seconds).
    """
    if not raw:
        return ""
    s = str(raw).strip()
    if ":" in s:
        return s  # already formatted (H:MM:SS or M:SS)
    try:
        total = int(float(s))
        h, rem = divmod(total, 3600)
        m, sec = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{sec:02d}"
        return f"{m}:{sec:02d}"
    except (ValueError, TypeError):
        return s

def clean_html(html):
    text = BeautifulSoup(html or "", "html.parser").get_text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

def parse_date(entry):
    for key in ("published", "updated"):
        val = entry.get(key)
        if val:
            try:
                return parsedate_to_datetime(val).strftime("%Y-%m-%d %H:%M UTC")
            except Exception:
                return val
    return ""

def get_full_text(entry):
    """
    Priority: RSS <content> field → fetch article page → RSS <summary>
    Returns plain text.
    """
    # 1. RSS content field (Substack free posts include full text here)
    if entry.get("content"):
        text = clean_html(entry["content"][0].get("value", ""))
        if len(text) > 500:
            return text

    # 2. Fetch article page
    link = entry.get("link", "")
    if link:
        try:
            r = requests.get(link, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for tag in soup.find_all(["nav","footer","script","style","button","aside","header"]):
                    tag.decompose()
                body = (
                    soup.find("div", class_=re.compile(r"body|post.content|article.body|entry.content", re.I)) or
                    soup.find("article") or
                    soup.find("main")
                )
                if body:
                    text = clean_html(body.get_text(separator="\n"))
                    if len(text) > 300:
                        return text
        except Exception:
            pass

    # 3. Fallback: RSS summary
    return clean_html(entry.get("summary") or entry.get("description") or "")

# ── Fetch one source ──────────────────────────────────────────────────────────
def fetch_source(source, con, max_items, first_run):
    name  = source["name"]
    stype = source["type"]

    rss_url = get_rss_url(source, con)
    if not rss_url:
        print(f"    [SKIP] RSS 未找到")
        return [], []

    feed = feedparser.parse(rss_url, request_headers=HEADERS)
    if not feed.entries:
        print(f"    [SKIP] Feed 无条目 ({rss_url})")
        return [], []

    print(f"    RSS: {rss_url}")
    print(f"    Feed条目数: {len(feed.entries)}")

    new_podcasts, new_articles = [], []
    collected = 0

    # Only fetch items published within the last MAX_AGE_DAYS days.
    # RSS feeds are ordered newest-first, so we stop as soon as we exceed the cutoff.
    MAX_AGE_DAYS = 14
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%d")

    # Pre-fetch Apple Podcasts episode URLs for this source (podcasts only)
    apple_ep_map = {}
    if stype == "podcast" and source.get("apple_id"):
        print(f"    获取 Apple Podcasts 单集链接...")
        apple_ep_map = fetch_apple_episode_urls(source["apple_id"])
        print(f"    找到 {len(apple_ep_map)} 条 Apple 链接")

    for entry in feed.entries:
        if collected >= max_items:
            break

        guid = entry.get("id") or entry.get("guid") or entry.get("link") or ""
        if not guid:
            continue
        if not first_run and not is_new(con, guid):
            continue

        title    = entry.get("title", "Untitled").strip()
        link     = entry.get("link", "")
        pub_date = parse_date(entry)

        # Skip items older than MAX_AGE_DAYS (RSS is newest-first, so break early)
        if pub_date[:10] < cutoff_date:
            # Still mark as seen so we don't re-check on future runs
            mark_seen(con, guid, name, title, link, pub_date, stype)
            break

        if stype == "podcast":
            summary   = clean_html(entry.get("summary") or entry.get("description") or "")
            enclosures = entry.get("enclosures", [])
            audio_url  = enclosures[0].get("url", "") if enclosures else ""
            duration   = format_duration(entry.get("itunes_duration", ""))

            # Build Apple Podcasts episode URL: match by date (YYYY-MM-DD)
            # Chinese podcasts in Apple's store use UTC+8, causing a +1 day offset vs RSS UTC dates
            date_key  = pub_date[:10] if pub_date else ""
            apple_url = apple_ep_map.get(date_key, "")
            if not apple_url and date_key:
                try:
                    from datetime import datetime as _dt, timedelta as _td
                    next_day = (_dt.strptime(date_key, "%Y-%m-%d") + _td(days=1)).strftime("%Y-%m-%d")
                    apple_url = apple_ep_map.get(next_day, "")
                except Exception:
                    pass
            apple_url = apple_url or link   # fallback to original RSS link

            item = {
                "source":    name,
                "title":     title,
                "date":      pub_date,
                "link":      apple_url,   # Apple Podcasts episode link (fallback: original)
                "orig_link": link,        # Original RSS link (for reference)
                "audio_url": audio_url,
                "duration":  duration,
                "summary":   summary[:1500],
            }
            new_podcasts.append(item)
            print(f"    + [播客] {pub_date[:10]}  {title[:55]}")

        else:  # article
            print(f"    + [文章] {pub_date[:10]}  {title[:55]}  (抓全文...)")
            full_text = get_full_text(entry)
            summary   = clean_html(entry.get("summary") or entry.get("description") or "")[:600]
            meta = {
                "source":  name,
                "title":   title,
                "date":    pub_date,
                "link":    link,
                "summary": summary,
                "chars":   len(full_text),
            }
            new_articles.append((meta, full_text))
            print(f"           全文: {len(full_text):,} 字符")

        mark_seen(con, guid, name, title, link, pub_date, stype)
        collected += 1

    return new_podcasts, new_articles

# ── Save results ──────────────────────────────────────────────────────────────
def make_slug(text, max_len=45):
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "_", slug).strip("_-")
    return slug[:max_len]

def save_results(date_str, all_podcasts, all_articles):
    day_dir      = DATA / date_str
    articles_dir = day_dir / "articles"
    articles_dir.mkdir(parents=True, exist_ok=True)

    article_meta_list = []
    for meta, full_text in all_articles:
        src_slug   = make_slug(meta["source"])
        title_slug = make_slug(meta["title"])
        filename   = f"{src_slug}__{title_slug}.txt"
        filepath   = articles_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"Source  : {meta['source']}\n")
            f.write(f"Title   : {meta['title']}\n")
            f.write(f"Date    : {meta['date']}\n")
            f.write(f"Link    : {meta['link']}\n")
            f.write(f"{'─'*60}\n\n")
            f.write(full_text)

        meta_out = dict(meta)
        meta_out["text_file"] = f"data/{date_str}/articles/{filename}"
        article_meta_list.append(meta_out)

    # ── Merge with existing JSON for this date (don't overwrite) ──────────
    json_path = DATA / f"{date_str}_digest.json"
    existing_pods, existing_arts = [], []
    if json_path.exists():
        try:
            existing = json.loads(json_path.read_text(encoding="utf-8"))
            existing_pods = existing.get("podcasts", [])
            existing_arts = existing.get("articles", [])
        except Exception:
            pass

    # De-duplicate by title
    seen_titles = {p["title"] for p in existing_pods}
    merged_pods = existing_pods + [p for p in all_podcasts if p["title"] not in seen_titles]

    seen_titles = {a["title"] for a in existing_arts}
    merged_arts = existing_arts + [a for a in article_meta_list if a["title"] not in seen_titles]

    digest = {
        "fetch_date": date_str,
        "fetch_time": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "new_podcast_episodes": len(all_podcasts),
            "new_articles":         len(all_articles),
            "total_podcasts":       len(merged_pods),
            "total_articles":       len(merged_arts),
        },
        "podcasts": merged_pods,
        "articles": merged_arts,
    }

    json_path = DATA / f"{date_str}_digest.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)

    return json_path, articles_dir

# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    now = datetime.now(timezone(timedelta(hours=8)))  # 北京时间
    print(f"AI Information Digest  {now.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    con       = init_db()
    seen_count = con.execute("SELECT COUNT(*) FROM seen_items").fetchone()[0]
    first_run  = (seen_count == 0)
    max_items  = 3 if first_run else 20

    if first_run:
        print("[首次运行] 每个信源抓最新 3 条\n")
    else:
        print(f"[常规运行] 数据库已有 {seen_count} 条记录，仅抓新内容\n")

    all_podcasts, all_articles = [], []

    for source in SOURCES:
        label = "播客" if source["type"] == "podcast" else "文章"
        print(f"[{label}] {source['name']}")
        pods, arts = fetch_source(source, con, max_items=max_items, first_run=first_run)
        all_podcasts.extend(pods)
        all_articles.extend(arts)

    print(f"\n{'='*60}")
    print(f"新播客剧集 : {len(all_podcasts)}")
    print(f"新文章     : {len(all_articles)}")

    if not all_podcasts and not all_articles:
        print("今日无新内容，退出。")
        con.close()
        return

    date_str  = now.strftime("%Y-%m-%d")
    json_path, articles_dir = save_results(date_str, all_podcasts, all_articles)

    print(f"\n已保存:")
    print(f"  摘要 JSON : {json_path}")
    print(f"  文章全文  : {articles_dir}")
    print(f"  (共 {len(all_articles)} 个 .txt 文件)")
    con.close()

if __name__ == "__main__":
    main()
