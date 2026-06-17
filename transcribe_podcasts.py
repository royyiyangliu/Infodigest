#!/usr/bin/env python3
"""
Transcribe self-scraped podcasts via Alibaba DashScope (百炼) Fun-ASR.

Run AFTER fetch.py. Reads the day's digest JSON, finds podcasts that have an
`audio_url` but no transcript yet (`text_file` is null), submits them all to
DashScope, polls until each finishes, saves the transcript text under
`data/YYYY-MM-DD/podcasts/`, and fills `text_file` + `chars` back into the digest.

Podcasts sourced from follow-builders already carry a transcript (text_file set),
so they are skipped automatically. Podcasts without an audio_url are skipped too.

Usage:
    python transcribe_podcasts.py [YYYY-MM-DD]   # default: today (Beijing time)

Requires the DASHSCOPE_API_KEY environment variable.
"""
import os, sys, json, re
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).parent
DATA = BASE / "data"


def make_slug(text, max_len=45):
    """Mirror fetch.py's slug logic so filenames stay consistent."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "_", slug).strip("_-")
    return slug[:max_len]


def write_transcript_file(podcasts_dir, meta, transcript):
    """Save a transcript .txt with the same header style as articles/podcasts."""
    src_slug   = make_slug(meta.get("source", "podcast"))
    title_slug = make_slug(meta.get("title", "untitled"))
    filename   = f"{src_slug}__{title_slug}.txt"
    filepath   = podcasts_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"Source  : {meta.get('source','')}\n")
        f.write(f"Title   : {meta.get('title','')}\n")
        f.write(f"Date    : {meta.get('date','')}\n")
        f.write(f"Link    : {meta.get('link','')}\n")
        f.write(f"{'─'*60}\n\n")
        f.write(transcript)

    return filename


def main():
    # ── Validate environment ───────────────────────────────────────────────────
    if not os.environ.get("DASHSCOPE_API_KEY"):
        print("[ERROR] 环境变量 DASHSCOPE_API_KEY 未配置，无法转录。")
        sys.exit(1)

    # Importing pipeline reads DASHSCOPE_API_KEY at module load, so import here
    # (after the env check) to give a clean error rather than a KeyError traceback.
    from pipeline import (submit_job, poll_job, extract_transcript,
                          mirror_audio, FileDownloadFailed)

    # ── Resolve target date ─────────────────────────────────────────────────────
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        date_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

    print(f"播客转录 (DashScope Fun-ASR)  {date_str}")
    print("=" * 60)

    json_path = DATA / f"{date_str}_digest.json"
    if not json_path.exists():
        print(f"[跳过] 当日 digest 不存在: {json_path}")
        return

    digest   = json.loads(json_path.read_text(encoding="utf-8"))
    podcasts = digest.get("podcasts", [])

    # Podcasts we can and need to transcribe: has audio_url, no transcript yet
    todo = [p for p in podcasts if p.get("audio_url") and not p.get("text_file")]

    if not todo:
        print("没有需要转录的播客（均已有转录或无音频直链）。")
        return

    print(f"待转录: {len(todo)} 集\n")

    podcasts_dir = DATA / date_str / "podcasts"
    podcasts_dir.mkdir(parents=True, exist_ok=True)

    # ── Phase 1: submit all jobs (fast, non-blocking) ──────────────────────────
    jobs = []  # list of (podcast_dict, task_id)
    for p in todo:
        lang = p.get("lang", "zh")
        title = p.get("title", "")[:55]
        print(f"[提交] [{lang}] {title}")
        try:
            task_id = submit_job(p["audio_url"], lang)
            jobs.append((p, task_id))
        except Exception as e:
            print(f"    [ERROR] 提交失败，跳过: {e}")

    if not jobs:
        print("\n所有任务提交失败，退出。")
        return

    # ── Phase 2: poll each job and save transcript ──────────────────────────────
    print(f"\n等待转录完成（长音频可能需要数分钟）...\n")
    done_count = 0
    for p, task_id in jobs:
        title = p.get("title", "")[:55]
        print(f"[轮询] {title}")
        try:
            try:
                result = poll_job(task_id)
            except FileDownloadFailed:
                # DashScope couldn't fetch the origin (e.g. Substack/Anchor block its
                # downloader). Re-host the audio ourselves and resubmit. Only the failed
                # episode falls back here; the others were already polled in parallel.
                print(f"    [回退] DashScope 无法抓取源 URL，改为自托管后重试...")
                mirror_url = mirror_audio(p["audio_url"], tag=task_id)
                result = poll_job(submit_job(mirror_url, p.get("lang", "zh")))
            transcript = extract_transcript(result)
        except Exception as e:
            print(f"    [ERROR] 转录失败，保留 text_file=null: {e}")
            continue

        if not transcript.strip():
            print(f"    [WARN] 转录为空，跳过。")
            continue

        filename = write_transcript_file(podcasts_dir, p, transcript)
        p["text_file"] = f"data/{date_str}/podcasts/{filename}"
        p["chars"]     = len(transcript)
        done_count += 1
        print(f"    ✓ 已保存 {filename}  ({len(transcript):,} 字符)")

    # ── Write digest back ───────────────────────────────────────────────────────
    digest.setdefault("stats", {})["transcribed_this_run"] = done_count
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"成功转录: {done_count}/{len(jobs)} 集")
    print(f"已更新: {json_path}")


if __name__ == "__main__":
    main()
