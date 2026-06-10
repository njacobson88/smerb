# Compression build plan (in progress)

User approved: brotli HTML (individual, recent) + solid tar.br compaction (>30d) + JXL screenshots everywhere, dashboard function preserved via backend display proxy. All conversions verify-before-replace. Backup bucket retains originals forever (mirror runs daily, never deletes).

## Key design decisions
- **Race avoidance**: conversions run on SCHEDULE (hourly), only touching objects >1h old — guarantees app has finished writing event docs (avoids merge-overwrite race with upload_service's set(merge)).
- **Auth for proxy**: reuse the object's existing `firebaseStorageDownloadTokens` as the capability token in proxy URLs (`/api/screenshot-view?path=...&token=...`). No new secret. Proxy is also behind the Dartmouth IP whitelist (browser <img> requests originate from whitelisted IPs).
- **Event doc updates**: object custom metadata has eventId+participantId. Try `update()` on `participants` collection, on NOT_FOUND try `dev_participants` (function deployed once; data may be from either env). Never `set(merge)` (would create orphans).
- **Download URL format**: https://firebasestorage.googleapis.com/v0/b/{bucket}/o/{urlencoded-path}?alt=media&token={token} — token value can be copied to new objects via metadata firebaseStorageDownloadTokens.
- **JXL**: cjxl --lossless_jpeg=1 -e 7 (hourly fn) / -e 9 (backfill). VERIFY djxl roundtrip == original bytes before replacing. New object screenshot_X.jxl (contentType image/jxl), delete .jpg after doc update. Binaries vendored: functions/bin/{cjxl,djxl}, dashboard/backend/bin/djxl (static linux x64, chmod +x at runtime).
- **HTML brotli**: node-native zlib.brotliCompressSync q11. page_X.html.gz → page_X.html.br (contentType text/html, contentEncoding br → browser auto-decompresses). Node storage client auto-decompresses gzip on download (decompress default true); brotli verify needs manual brotliDecompressSync.
- **Compaction**: daily schedule, html/*.br older than 30d, group by participant+UTC date (timestamp in filename page_<ms>), tar RAW html (decompressed) with member paths {pid}/{sessionId}/page_X.html, brotliCompress q10 lgwin 24 → html-archives/{pid}/{YYYY-MM-DD}.tar.br. Cap ~300MB raw per archive (split -partN). Verify: re-download, decompress, untar, hash-match EVERY member. Then update event docs (html.archive=gs path, html.storageUrl=FieldValue.delete()) and delete members. Limit groups per run to fit 1800s timeout; backlog drains daily.
- **Sequencing (critical)**: deploy backend (with TWILIO_VALIDATE_WEBHOOKS=false to preserve current webhook behavior — user flips on after a test call) BEFORE deploying JXL conversion fn or running JXL backfill, else dashboard images break in Chrome.
- **Backend changes needed**: (1) /api/screenshot-view endpoint (djxl reconstruct, image/jpeg, immutable cache); (2) sample-screenshot URL emission around main.py:472 generate_signed_url — emit proxy URL when object is .jxl; check line 2076 path (uses stored screenshotUrl — auto-OK since fn rewrites docs); (3) exports at main.py ~2615, 3126 — check if they embed URLs (OK) or download bytes (need djxl reconstruction).
- **Research findings recorded**: lossless video (x264 qp0) is 76% WORSE than per-file JXL on consecutive screenshots (JPEG noise defeats pixel prediction) — JXL is the ceiling. Dictionary brotli (−14% more) rejected: breaks browser-native decompression. Solid tar: 5.2× vs gzip on real corpus.

## Stage status
- [x] Research (video codecs, dictionaries, solid archiving, Firestore overhead — docs avg 1.1KB, not a lever)
- [x] jxl binaries vendored
- [ ] functions: htmlBrotliTranscode (hourly) — IN PROGRESS
- [ ] functions: compactOldHtml (daily)
- [ ] functions: convertScreenshotsToJxl (hourly) — deploy ONLY after backend
- [ ] backend: proxy endpoint + URL emission + exports
- [ ] frontend: nothing needed (URLs come from backend/docs)
- [ ] backfills: html brotli, then jxl (after backend deploy), with verification
- [ ] deploys: functions (html ones first), backend (TWILIO_VALIDATE_WEBHOOKS=false), then jxl fn + backfill
- [ ] commit/push per stage; final summary must mention: user must flip TWILIO_VALIDATE_WEBHOOKS=true after testing a 988 call
