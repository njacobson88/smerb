#!/usr/bin/env python3
"""
Losslessly optimize existing screenshot JPEGs in Firebase Storage.
========================================================================
Re-compresses every screenshots/ JPEG with jpegtran (-optimize -progressive):
identical pixels, ~9-12% fewer bytes. New uploads are handled automatically by
the optimizeScreenshot Cloud Function; this backfills objects uploaded before
that function was deployed.

- Preserves all custom metadata including firebaseStorageDownloadTokens,
  so existing download URLs keep working.
- Sets losslessOptimized=true so the Cloud Function (and re-runs of this
  script) skip already-processed objects.
- Safe to interrupt and re-run: already-optimized objects are skipped.

Usage:
    python3 scripts/optimize_existing_screenshots.py --dry-run   # report only
    python3 scripts/optimize_existing_screenshots.py             # do it
Requires: jpegtran on PATH (brew install jpeg-turbo) or functions/node_modules
vendor binary; google-cloud-storage (pip install google-cloud-storage).
"""

import argparse
import concurrent.futures
import os
import shutil
import subprocess
import tempfile

from google.cloud import storage
from google.oauth2 import service_account

BUCKET = "r01-redditx-suicide.firebasestorage.app"
PREFIX = "screenshots/"
KEY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Keys", "r01-redditx-suicide-firebase-adminsdk-fbsvc-306bc4ee85.json",
)


def find_jpegtran():
    path = shutil.which("jpegtran")
    if path:
        return path
    vendor = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "functions", "node_modules", "jpegtran-bin", "vendor", "jpegtran",
    )
    if os.path.exists(vendor):
        return vendor
    raise SystemExit("jpegtran not found — brew install jpeg-turbo, or npm install in functions/")


def optimize_blob(bucket, blob, jpegtran, dry_run):
    meta = blob.metadata or {}
    if meta.get("losslessOptimized") == "true":
        return ("skipped", blob.name, blob.size, blob.size)
    if blob.content_type != "image/jpeg" or not blob.size or blob.size < 5000:
        return ("skipped", blob.name, blob.size or 0, blob.size or 0)

    original_size = blob.size  # capture now — upload_from_filename refreshes blob.size

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.jpg")
        dst = os.path.join(tmp, "out.jpg")
        blob.download_to_filename(src)
        subprocess.run(
            [jpegtran, "-optimize", "-progressive", "-copy", "all", "-outfile", dst, src],
            check=True, capture_output=True,
        )
        new_size = os.path.getsize(dst)

        if dry_run:
            return ("would-optimize", blob.name, original_size, new_size)

        blob.metadata = {**meta, "losslessOptimized": "true"}
        if new_size < original_size:
            # Re-upload optimized bytes with merged metadata (tokens preserved)
            blob.upload_from_filename(dst, content_type="image/jpeg")
            return ("optimized", blob.name, original_size, new_size)
        else:
            blob.patch()  # flag only, keep original bytes
            return ("no-gain", blob.name, original_size, original_size)


def main():
    parser = argparse.ArgumentParser(description="Backfill lossless screenshot optimization")
    parser.add_argument("--dry-run", action="store_true", help="Report savings without modifying anything")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    jpegtran = find_jpegtran()
    creds = service_account.Credentials.from_service_account_file(KEY_PATH)
    client = storage.Client(credentials=creds, project="r01-redditx-suicide")
    bucket = client.bucket(BUCKET)

    blobs = [b for b in bucket.list_blobs(prefix=PREFIX) if b.name.lower().endswith(".jpg")]
    print(f"Found {len(blobs)} screenshot JPEGs under {PREFIX}")

    totals = {"before": 0, "after": 0, "optimized": 0, "skipped": 0, "no-gain": 0, "failed": 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(optimize_blob, bucket, b, jpegtran, args.dry_run) for b in blobs]
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            try:
                status, name, before, after = fut.result()
            except Exception as e:
                totals["failed"] += 1
                print(f"  FAILED: {e}")
                continue
            if status in ("optimized", "would-optimize"):
                totals["optimized"] += 1
                totals["before"] += before
                totals["after"] += after
            else:
                totals[status] = totals.get(status, 0) + 1
            if i % 200 == 0:
                print(f"  ...{i}/{len(blobs)}")

    saved = totals["before"] - totals["after"]
    pct = (100 * saved / totals["before"]) if totals["before"] else 0
    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Done.")
    print(f"  optimized: {totals['optimized']}, no-gain: {totals['no-gain']}, "
          f"already done/skipped: {totals['skipped']}, failed: {totals['failed']}")
    print(f"  bytes: {totals['before']:,} -> {totals['after']:,}  (saved {saved:,}, {pct:.1f}%)")


if __name__ == "__main__":
    main()
