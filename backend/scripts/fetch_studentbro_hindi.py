"""Mirror the studentbro.in "important question" PDFs for Malhar Hindi 6 and 7.

    python -m scripts.fetch_studentbro_hindi --book c6
    python -m scripts.fetch_studentbro_hindi --book c7 --force

One file per chapter into ``data/qbank/mirror/studentbro/<book>_hindi_malhar/``,
plus a ``manifest.json`` recording, per chapter, the URL that was actually
fetched, the filename the server offered, the byte count and the sha256.

WHY THE MANIFEST. The mirrored file name is ours, not the server's: studentbro
sanitises Devanagari chapter names into long underscore runs, so the name it
offers is neither stable nor readable. The extraction row must carry the real
URL rather than a local path, and the manifest is what lets the loader put it
there without re-fetching.

TWO HOPS, NOT ONE. ``/topic-pdf/.../<slug>`` is a landing page, not the file:
it answers 200 with ``text/html`` and a download button carrying the real
``data-pdf-url``. Fetching the slug URL straight into a ``.pdf`` therefore
yields a perfectly valid HTML document under a name that makes every later
reader call the corpus corrupt. The asset URL under ``/upload/pdf/`` is the
server's own sanitisation of the Devanagari chapter name, so it is a long run
of underscores and is not guessable -- it has to be read off the page.

TRUNCATION IS THE FAILURE TO FEAR. A reset connection yields a short file that
opens as a "corrupt PDF" and sends you looking for a parser bug. Every download
is checked against the response's own Content-Length and against the trailing
``%%EOF``, and a file that fails either is deleted rather than left on disk to
be parsed later.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MIRROR = Path(__file__).resolve().parents[1] / "data" / "qbank" / "mirror" / "studentbro"

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
}

# (printed chapter number or None for the un-numbered extras, slug)
BOOKS: dict[str, dict] = {
    "c6": {
        "dir": "c6_hindi_malhar",
        "listing": "https://studentbro.in/topics/important-question/english/6/hindimalhar",
        "base": "https://studentbro.in/topic-pdf/important-question/english/6/hindimalhar",
        "chapters": [
            (1, "1-matrubhumi"),
            (2, "2-gol"),
            (3, "3-pehli-boond"),
            (4, "4-har-ki-jeet"),
            (5, "5-rahim-ke-dohe"),
            (6, "6-meri-maa"),
            (7, "7-jalate-chalo"),
            (8, "8-sattriya-and-bihu-dance"),
            (9, "9-maiya-main-nahin-makhan-khayo"),
            (10, "10-exam-preparation"),
            (11, "11-chetak-ki-veerta"),
            (12, "12-hind-mahasagar-ma-chhoto-sa-hindustan"),
            (13, "13-ped-ki-baat"),
            (90, "vyakaran-vibhag"),
            (91, "lekhan-vibhag"),
        ],
    },
    "c7": {
        "dir": "c7_hindi_malhar",
        "listing": "https://studentbro.in/topics/important-question/english/7/5-hindi-malhar",
        "base": "https://studentbro.in/topic-pdf/important-question/english/7/5-hindi-malhar",
        "chapters": [
            (1, "1-maa-kah-ek-kahaani"),
            (2, "2-teen-buddhimaan"),
            (3, "3-phool-aur-kaanta"),
            (4, "4-paani-re-paani"),
            (5, "5-nahin-hona-beemaar"),
            (6, "6-giridhar-kaviraay-ki-kundaliya"),
            (7, "7-varsha-bahaar"),
            (8, "8-birju-maharaj-se-saakshaatkaar"),
            (9, "9-chidiya"),
            (10, "10-meera-ke-pad"),
        ],
    },
}


def _server_name(resp: requests.Response) -> str | None:
    disp = resp.headers.get("Content-Disposition") or ""
    for part in disp.split(";"):
        part = part.strip()
        for key in ("filename*=", "filename="):
            if part.lower().startswith(key):
                return part[len(key):].strip('"\' ')
    return None


_ASSET = re.compile(r'data-pdf-url=["\']([^"\']+\.pdf)["\']', re.I)


def asset_url(page_url: str, sess: requests.Session) -> str | None:
    """Read the real PDF link off a topic-pdf landing page."""
    resp = sess.get(page_url, headers=UA, timeout=120)
    resp.raise_for_status()
    found = _ASSET.findall(resp.text)
    if not found:
        return None
    # The page carries exactly one download button; if that ever changes, the
    # first is the one the button uses.
    return found[0]


def fetch_one(url: str, dest: Path, sess: requests.Session) -> dict:
    resp = sess.get(url, headers=UA, timeout=180)
    resp.raise_for_status()
    body = resp.content
    declared = resp.headers.get("Content-Length")
    ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip()

    problems = []
    if declared is not None and int(declared) != len(body):
        problems.append(f"Content-Length {declared} != {len(body)} bytes received")
    if not body.startswith(b"%PDF"):
        problems.append(f"does not start with %PDF (starts {body[:8]!r})")
    if b"%%EOF" not in body[-2048:]:
        problems.append("no %%EOF in the last 2 KiB -- truncated")
    if ctype != "application/pdf":
        problems.append(f"Content-Type {ctype!r}")

    if problems:
        return {"url": url, "ok": False, "bytes": len(body),
                "declared": declared, "problems": problems}

    dest.write_bytes(body)
    return {
        "url": url,
        "ok": True,
        "file": dest.name,
        "bytes": len(body),
        "declared": int(declared) if declared is not None else None,
        "content_type": ctype,
        "server_filename": _server_name(resp),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--book", choices=sorted(BOOKS), required=True)
    ap.add_argument("--force", action="store_true", help="re-download files already present")
    a = ap.parse_args()

    cfg = BOOKS[a.book]
    out = MIRROR / cfg["dir"]
    out.mkdir(parents=True, exist_ok=True)

    man_path = out / "manifest.json"
    manifest = {}
    if man_path.exists():
        manifest = json.loads(man_path.read_text(encoding="utf-8"))
    manifest.setdefault("listing", cfg["listing"])
    manifest.setdefault("files", {})

    sess = requests.Session()
    sess.headers.update(UA)

    bad = 0
    for number, slug in cfg["chapters"]:
        name = f"ch{number:02d}.pdf"
        dest = out / name
        if dest.exists() and not a.force:
            print(f"  ch{number:<3} {name:<12} already present ({dest.stat().st_size:,} bytes)")
            continue
        page = f"{cfg['base']}/{slug}"
        asset = asset_url(page, sess)
        if not asset:
            bad += 1
            print(f"  ch{number:<3} {name:<12} FAILED: no data-pdf-url on {page}")
            continue
        info = fetch_one(asset, dest, sess)
        if not info["ok"]:
            bad += 1
            print(f"  ch{number:<3} {name:<12} FAILED: {'; '.join(info['problems'])}")
            if dest.exists():
                dest.unlink()
            continue
        info["chapter"] = number
        info["slug"] = slug
        # `url` is the asset; `page_url` is the human-facing one that the
        # extraction row will cite, because the asset name is a server
        # artefact and the page is what a licensing review would look at.
        info["page_url"] = page
        manifest["files"][name] = info
        print(f"  ch{number:<3} {name:<12} {info['bytes']:>9,} bytes  "
              f"sha {info['sha256'][:12]}  {slug}")
        time.sleep(0.6)

    man_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nmanifest -> {man_path}")
    if bad:
        print(f"{bad} file(s) failed verification and were not kept")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
