import sys, json
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
from pathlib import Path

data = json.loads(Path("data/2026-06-02_digest.json").read_text(encoding="utf-8"))

print("=== 统计 ===")
print(f"  播客剧集: {data['stats']['new_podcast_episodes']}")
print(f"  文章数量: {data['stats']['new_articles']}")

print("\n=== 播客（每源一条示例）===")
seen = set()
for p in data["podcasts"]:
    if p["source"] not in seen:
        seen.add(p["source"])
        print(f"\n  [{p['source']}]")
        print(f"    标题: {p['title'][:60]}")
        print(f"    日期: {p['date'][:10]}  时长: {p['duration']}")
        print(f"    链接: {p['link'][:75]}")
        print(f"    摘要: {p['summary'][:80]}...")

print("\n=== 文章 ===")
for a in data["articles"]:
    print(f"\n  [{a['source']}] {a['title'][:55]}")
    print(f"    日期: {a['date'][:10]}  全文: {a['chars']:,} 字符")
    print(f"    文件: {a['text_file']}")
