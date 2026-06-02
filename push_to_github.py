#!/usr/bin/env python3
"""
Helper: push a local file to a GitHub repo via Contents API.

Usage:
    GITHUB_TOKEN=<pat> python push_to_github.py <local_file> <repo_path> <commit_msg>

Example:
    GITHUB_TOKEN=ghp_xxx python push_to_github.py /tmp/2026-06-03.html docs/2026-06-03.html "digest: 2026-06-03"

Requires env var GITHUB_TOKEN (fine-grained PAT, Contents: read + write).
"""
import sys, os, base64, json
import urllib.request, urllib.error

OWNER = "royyiyangliu"
REPO  = "Infodigest"

def push_file(local_path: str, repo_path: str, commit_msg: str) -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise EnvironmentError("GITHUB_TOKEN environment variable is not set.")

    with open(local_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    api_url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{repo_path}"
    headers = {
        "Authorization": f"token {token}",
        "Content-Type": "application/json",
        "User-Agent": "Infodigest-Agent/1.0",
        "Accept": "application/vnd.github+json",
    }

    # Check if file already exists (need its SHA for updates)
    sha = None
    try:
        req = urllib.request.Request(api_url, headers=headers)
        resp = urllib.request.urlopen(req)
        existing = json.loads(resp.read().decode())
        sha = existing.get("sha")
        print(f"[INFO] {repo_path} exists (sha={sha[:8]}), will update.")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"[INFO] {repo_path} does not exist, will create.")
        else:
            raise

    payload: dict = {"message": commit_msg, "content": content_b64}
    if sha:
        payload["sha"] = sha

    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode(),
        method="PUT",
        headers=headers,
    )
    resp = urllib.request.urlopen(req)
    result = json.loads(resp.read().decode())
    short_sha = result["commit"]["sha"][:8]
    print(f"[OK] {repo_path} committed ({short_sha})")
    return result


def rebuild_index(token: str) -> str:
    """
    List all YYYY-MM-DD_summary.json files in docs/data/, return new index.html content.
    Links to digest.html?date=YYYY-MM-DD (JS template).
    """
    api_url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/docs/data"
    headers = {
        "Authorization": f"token {token}",
        "User-Agent": "Infodigest-Agent/1.0",
        "Accept": "application/vnd.github+json",
    }
    req = urllib.request.Request(api_url, headers=headers)
    resp = urllib.request.urlopen(req)
    files = json.loads(resp.read().decode())

    import re
    dates = sorted(
        [f["name"].replace("_summary.json", "") for f in files
         if re.match(r"\d{4}-\d{2}-\d{2}_summary\.json", f["name"])],
        reverse=True,
    )

    items_html = "\n".join(
        f'    <li>\n'
        f'      <a href="digest.html?date={d}">\n'
        f'        <span class="date">{d}</span>\n'
        f'        <span class="arrow">›</span>\n'
        f'      </a>\n'
        f'    </li>'
        for d in dates
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI 信息日报</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: "PingFang SC", "Helvetica Neue", "Microsoft YaHei", Arial, sans-serif;
    background: #f5f6fa; color: #1a1a2e; line-height: 1.7;
    min-height: 100vh; display: flex; flex-direction: column;
  }}
  header {{
    background: linear-gradient(135deg, #0f2027, #203a43, #2c5364);
    color: #fff; padding: 48px 40px 36px; text-align: center;
  }}
  header h1 {{ font-size: 32px; font-weight: 700; letter-spacing: 1px; margin-bottom: 10px; }}
  header p {{ font-size: 15px; color: #a0c4d8; }}
  main {{ max-width: 720px; margin: 48px auto; padding: 0 24px; flex: 1; }}
  h2 {{ font-size: 14px; font-weight: 700; letter-spacing: 1.2px; text-transform: uppercase;
       color: #9ca3af; margin-bottom: 16px; }}
  .list {{ list-style: none; }}
  .list li {{
    background: #fff; border: 1px solid #e8ecf4; border-radius: 10px;
    margin-bottom: 10px; transition: box-shadow .2s, border-color .2s;
  }}
  .list li:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,.08); border-color: #c8d6e8; }}
  .list a {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 18px 22px; text-decoration: none; color: #1a3a5c;
  }}
  .list a:hover {{ color: #1d6fa4; }}
  .list .date {{ font-size: 16px; font-weight: 600; }}
  .list .arrow {{ color: #c8d6e8; font-size: 18px; }}
  footer {{ text-align: center; padding: 24px; font-size: 12px; color: #adb5bd;
           border-top: 1px solid #e8ecf4; background: #fff; }}
</style>
</head>
<body>
<header>
  <h1>AI 信息日报</h1>
  <p>播客 · 文章 · 产业动态 · 每日自动更新</p>
</header>
<main>
  <h2>历史存档</h2>
  <ul class="list">
{items_html}
  </ul>
</main>
<footer>AI Information Digest · Epoch AI · SemiAnalysis · Citrini · a16z · GameDev Report · 11 档播客</footer>
</body>
</html>"""


if __name__ == "__main__":
    if len(sys.argv) == 4:
        push_file(sys.argv[1], sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 2 and sys.argv[1] == "--rebuild-index":
        token = os.environ.get("GITHUB_TOKEN", "")
        html = rebuild_index(token)
        tmp = "/tmp/index.html"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(html)
        push_file(tmp, "docs/index.html", "index: rebuild")
    else:
        print(__doc__)
        sys.exit(1)
