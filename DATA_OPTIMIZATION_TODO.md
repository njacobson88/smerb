# Data Capture & Sync Optimization Checklist

## P0 - Data Loss Prevention (COMPLETED)
- [x] Add network-aware sync (skip uploads when offline)
- [x] Add max retry count (5) for failed uploads (prevent poison events)
- [x] Fix screenshot sync bug (don't mark synced if file upload failed)
- [x] Use Firestore batch writes for OCR results and HTML status logs

## P1 - Storage Optimization (COMPLETED)
- [x] Downscale screenshots before JPEG compression (Retina -> 750px max width)
- [x] Lower JPEG quality from 85 to 70 (~40% size reduction, visually acceptable)
- [x] Compress HTML files with gzip before storing to disk (~90% size reduction)
- [x] Delete local files after confirmed upload (screenshots + HTML)
- [x] Add disk space monitoring (2GB cap, pauses capture when exceeded)

## P2 - Performance (COMPLETED)
- [x] Move JPEG compression to a Dart isolate (compute() offloads from main thread)
- [x] Add SQLite indexes on Events(synced, eventType, participantId) + all synced columns
- [x] Fix getScreenshotsPendingOcr to use SQL LEFT JOIN instead of loading all into memory
- [x] Debounce MutationObserver in DOM observers (200ms debounce on callbacks)
- [x] Add data retention policy (prune synced local data older than 7 days, runs hourly)

## P3 - Nice to Have (COMPLETED)
- [x] Add 30-second timeout on file uploads to prevent hanging syncs
- [x] Track upload bytes and log data volume per sync cycle
- [x] Change screenshot capture interval from 1s to 3s (~67% volume reduction)
- [x] Sync newest events first (prioritize recent data)
- [x] Batch Firestore writes for non-screenshot event uploads

## Data Volume Estimates (after all optimizations)
- Screenshots: ~60KB JPEG each, every 3s = ~72MB/hour active use (was ~900MB/hour)
- HTML captures: ~50-200KB gzipped (was 500KB-2MB raw)
- Local files auto-deleted after upload confirmation
- 2GB disk cap prevents device storage exhaustion
- Synced data pruned after 7 days
- SQLite queries use indexes for O(log n) lookups
- JPEG compression on background isolate (no UI jank)
- DOM observers debounced (200ms)
- Non-screenshot events batched (up to 450 per Firestore write)
- Upload timeouts prevent hanging syncs (30s per file)
- Recent data syncs first
