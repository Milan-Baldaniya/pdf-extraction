"""Upload question figures to DigitalOcean Spaces and repoint stored_url.

    python -m scripts.publish_question_figures --dry
    python -m scripts.publish_question_figures --apply
    python -m scripts.publish_question_figures --apply --standard 43 --subject 3975

Why this exists: the extraction stage stamps each figure with
`settings.queue_asset_base`, which defaults to http://127.0.0.1:8000/api/assets.
That address only resolves on the extraction machine, so every figure rendered
"Figure could not be loaded" in the app. The Class 9 Maths bank does not have
this problem because its images sit on Spaces under
public/lms_content_file/qbank/ - this puts the Class 10 figures in the same
place and rewrites the rows to match.

The object key is the asset's sha256 plus its extension, so re-running is
harmless: the same image always lands on the same key, and a figure shared by
two questions is stored once. Credentials come from the Laravel .env, which is
where the bucket is already configured; nothing is hardcoded here.

Only rows whose stored_url is unreachable (localhost, or empty) are touched. A
row already pointing at Spaces is left exactly as it is.
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.mariadb import SessionLocal, init_mariadb  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LARAVEL_ENV = Path(r"C:\Users\MILAN\Downloads\next_lms_erp\.env")
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output"

# Where the Class 9 Maths figures already live. Matching it keeps one convention.
KEY_PREFIX = "public/lms_content_file/qbank"
CDN_HOST = "https://s3-triz.fra1.cdn.digitaloceanspaces.com"

# A stored_url is "unreachable" if it points at the extraction box rather than
# at the CDN. These are the forms the pipeline has produced.
UNREACHABLE = re.compile(r"^\s*$|127\.0\.0\.1|localhost|^/|^file:", re.IGNORECASE)


def _cdn_object(sha: str) -> str | None:
    """Is this figure already on the CDN under its content hash?

    The object key is the asset's sha256, so a figure uploaded once stays
    uploaded even if its row later loses source_path - which is exactly what a
    reload does when the asset manifest omits `relative_path`. Without this,
    89 already-published figures were reported as "local file NOT found" and
    would have been left pointing at 127.0.0.1.
    """
    import urllib.error
    import urllib.request

    for ext in (".jpg", ".png", ".jpeg"):
        url = f"{CDN_HOST}/{KEY_PREFIX}/{sha}{ext}"
        request = urllib.request.Request(url, method="HEAD")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if response.status == 200:
                    return url
        except Exception:
            continue
    return None


def laravel_env() -> dict[str, str]:
    if not LARAVEL_ENV.exists():
        raise SystemExit(f"cannot read credentials: {LARAVEL_ENV} not found")
    out: dict[str, str] = {}
    for line in LARAVEL_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def client(env: dict[str, str]):
    import boto3

    missing = [k for k in ("DO_SPACES_KEY", "DO_SPACES_SECRET", "DO_SPACES_ENDPOINT",
                           "DO_SPACES_REGION", "DO_SPACES_BUCKET") if not env.get(k)]
    if missing:
        raise SystemExit(f"missing in the Laravel .env: {', '.join(missing)}")
    return boto3.client(
        "s3",
        endpoint_url=env["DO_SPACES_ENDPOINT"],
        region_name=env["DO_SPACES_REGION"],
        aws_access_key_id=env["DO_SPACES_KEY"],
        aws_secret_access_key=env["DO_SPACES_SECRET"],
    ), env["DO_SPACES_BUCKET"]


def local_file(source_path: str) -> Path | None:
    """Find the extracted image on disk from the manifest's relative path."""
    name = os.path.basename((source_path or "").replace("\\", "/"))
    if not name:
        return None
    direct = OUTPUT_DIR / source_path.replace("\\", "/")
    if direct.exists():
        return direct
    hits = list(OUTPUT_DIR.rglob(name))
    return hits[0] if hits else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--standard", type=int, default=43)
    ap.add_argument("--subject", type=int, default=3975)
    args = ap.parse_args()
    if not (args.dry or args.apply):
        ap.error("choose --dry or --apply")

    if not init_mariadb() or SessionLocal is None:
        raise SystemExit("Database not ready")
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                "SELECT a.id, a.asset_sha256, a.source_path, a.stored_url, a.mime "
                "  FROM lms_question_asset a "
                "  JOIN lms_question_master q ON q.id = a.question_id "
                " WHERE q.standard_id = :s AND q.subject_id = :su "
                " ORDER BY a.id"
            ),
            {"s": args.standard, "su": args.subject},
        ).fetchall()
    finally:
        db.close()

    todo, already, missing, repoint = [], 0, [], []
    for asset_id, sha, src, url, mime in rows:
        if url and not UNREACHABLE.search(url):
            already += 1
            continue
        path = local_file(src or "")
        if path is None:
            # Re-uploading is impossible without the file, but the figure may
            # already BE on the CDN under its content hash. Ask before calling
            # it unpublishable.
            found = _cdn_object(sha) if sha else None
            if found:
                repoint.append((asset_id, found))
            else:
                missing.append((asset_id, src))
            continue
        todo.append((asset_id, sha, path, mime))

    print(f"figures for standard {args.standard} / subject {args.subject}: {len(rows)}")
    print(f"  already on a reachable host : {already}")
    print(f"  to upload                   : {len(todo)}")
    print(f"  already on the CDN, repoint : {len(repoint)}")
    print(f"  local file NOT found        : {len(missing)}")
    for a, s in missing[:5]:
        print(f"      asset {a}: {s}")

    if repoint and not args.dry:
        db = SessionLocal()
        try:
            for asset_id, url in repoint:
                db.execute(
                    text("UPDATE lms_question_asset SET stored_url = :u WHERE id = :i"),
                    {"u": url, "i": asset_id})
            db.commit()
        finally:
            db.close()
        print(f"  repointed to the CDN        : {len(repoint)}")

    if not todo:
        return 0
    if args.dry:
        a, sha, path, _ = todo[0]
        print(f"\n  example: {path.name}")
        print(f"      -> {CDN_HOST}/{KEY_PREFIX}/{sha}{path.suffix.lower()}")
        print("\n  DRY RUN - nothing uploaded, nothing rewritten.")
        return 0

    env = laravel_env()
    s3, bucket = client(env)
    db = SessionLocal()
    # Fail fast on a locked row instead of waiting out the server's default 50
    # seconds. With 47 rows behind somebody else's open transaction that
    # default turns a two-minute job into forty minutes.
    try:
        db.execute(text("SET SESSION innodb_lock_wait_timeout = 3"))
        db.commit()
    except Exception:
        pass
    uploaded = failed = deferred = 0
    try:
        for asset_id, sha, path, mime in todo:
            key = f"{KEY_PREFIX}/{sha}{path.suffix.lower()}"
            content_type = mime or mimetypes.guess_type(path.name)[0] or "image/jpeg"
            try:
                # public-read: the app renders these straight into a page, so a
                # signed URL would expire out from under the question bank.
                s3.upload_file(
                    str(path), bucket, key,
                    ExtraArgs={"ACL": "public-read", "ContentType": content_type},
                )
            except Exception as exc:
                failed += 1
                print(f"   upload failed for asset {asset_id}: {type(exc).__name__}: {exc}")
                continue
            # Commit each row on its own. A single row locked by somebody
            # else's open transaction used to abort the whole run with "Lock
            # wait timeout exceeded", losing the other 46 uploads with it - the
            # file is already in the bucket by then, so the work was wasted.
            try:
                db.execute(
                    text("UPDATE lms_question_asset SET stored_url = :u WHERE id = :i"),
                    {"u": f"{CDN_HOST}/{key}", "i": asset_id},
                )
                db.commit()
                uploaded += 1
            except Exception as exc:
                db.rollback()
                deferred += 1
                if deferred <= 3:
                    print(f"   asset {asset_id} row is locked, left for a later run "
                          f"({type(exc).__name__}); the image is uploaded")
                continue
            if uploaded % 25 == 0:
                print(f"   {uploaded}/{len(todo)} …", flush=True)
    finally:
        db.close()

    print(f"\n  uploaded and repointed: {uploaded}")
    print(f"  failed                : {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
