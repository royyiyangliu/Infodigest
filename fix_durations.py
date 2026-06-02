"""Patch duration fields in existing summary JSONs."""
import sys, json
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

def fmt(raw):
    if not raw: return ""
    s = str(raw).strip()
    if ":" in s: return s
    try:
        total = int(float(s))
        h, rem = divmod(total, 3600)
        m, sec = divmod(rem, 60)
        return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"
    except: return s

fixed = 0
for f in Path("docs/data").glob("*_summary.json"):
    data = json.loads(f.read_text(encoding="utf-8"))
    for p in data.get("podcasts", []):
        orig = p.get("duration", "")
        new  = fmt(orig)
        if new != orig:
            p["duration"] = new
            fixed += 1
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {f.name}: {fixed} duration(s) fixed")
print(f"Total fixed: {fixed}")
