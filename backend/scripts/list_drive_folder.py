"""List a publicly shared Google Drive folder, without credentials.

    python -m scripts.list_drive_folder <folder-id-or-url>
    python -m scripts.list_drive_folder <id> --recurse 2

The Drive connector on this machine authenticates to a different Google
account than the one these folders are shared from, so it returns "not
implemented" for them. A public folder page still embeds its own listing in
`window['_DRIVE_ivd']`, which is enough to see what is there and to build
direct download URLs, and needs no sign-in.

This reads a listing only. Nothing is downloaded.
"""
from __future__ import annotations

import argparse
import codecs
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
FOLDER_MIME = "application/vnd.google-apps.folder"


def folder_id(s: str) -> str:
    m = re.search(r"/folders/([-\w]{10,})", s)
    return m.group(1) if m else s.strip()


def listing(fid: str) -> list[dict]:
    url = f"https://drive.google.com/drive/folders/{fid}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        html = r.read().decode("utf-8", "replace")
    m = re.search(r"window\['_DRIVE_ivd'\]\s*=\s*'(.*?)';", html, re.S)
    if not m:
        return []
    data = json.loads(codecs.decode(m.group(1), "unicode_escape"))
    rows = data[0] if data and isinstance(data[0], list) else []
    out = []
    for e in rows:
        try:
            out.append({"id": e[0], "name": e[2], "mime": e[3],
                        "size": int(e[13]) if len(e) > 13 and str(e[13]).isdigit() else 0})
        except Exception:
            continue
    return out


def walk(fid: str, depth: int, indent: int = 0, seen: set | None = None) -> tuple[int, int]:
    seen = seen if seen is not None else set()
    if fid in seen:
        return 0, 0
    seen.add(fid)
    files = folders = 0
    for e in sorted(listing(fid), key=lambda x: (x["mime"] != FOLDER_MIME, x["name"].lower())):
        pad = "  " * indent
        if e["mime"] == FOLDER_MIME:
            folders += 1
            print(f"  {pad}[dir ] {e['name']}")
            if depth > 0:
                f, d = walk(e["id"], depth - 1, indent + 1, seen)
                files += f
                folders += d
        else:
            files += 1
            mb = f"{e['size'] / 1048576:.1f}MB" if e["size"] else "?"
            print(f"  {pad}       {e['name'][:70]:<70} {mb:>8}  {e['id']}")
    return files, folders


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder")
    ap.add_argument("--recurse", type=int, default=0,
                    help="how many levels of sub-folder to open")
    a = ap.parse_args()
    fid = folder_id(a.folder)
    print(f"https://drive.google.com/drive/folders/{fid}\n")
    files, folders = walk(fid, a.recurse)
    print(f"\n  {files} file(s), {folders} folder(s)")
    print("  download a file with "
          "https://drive.google.com/uc?export=download&id=<id>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
