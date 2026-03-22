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

## P2 - Performance (prevents degradation over time)
- [ ] Move JPEG compression to a Dart isolate (use compute() to offload from main thread)
- [ ] Add SQLite indexes on Events(synced, eventType, participantId)
- [ ] Fix getScreenshotsPendingOcr to use SQL LEFT JOIN instead of loading all into memory
- [ ] Debounce MutationObserver in DOM observers (200ms debounce on callbacks)
- [ ] Add data retention policy (prune synced local data older than N days)

## P3 - Nice to Have
- [ ] Resumable uploads for screenshots (Firebase Storage supports this)
- [ ] Upload progress tracking visible in the app
- [ ] Make screenshot capture interval configurable (1/sec may be excessive, 1/3sec could suffice)
- [ ] Prioritize recent data over old data during sync
- [ ] Add Firestore batch writes for non-screenshot event uploads

## Data Volume Estimates (after P1 optimizations)
- Screenshots: ~60KB JPEG each (down from ~250KB), up to 1/sec = ~216MB/hour active use
- HTML captures: ~50-200KB gzipped (down from 500KB-2MB raw)
- Local files auto-deleted after upload confirmation
- 2GB disk cap prevents device storage exhaustion
- HtmlStatusLogs: 1 row/sec in SQLite (fastest-growing table)
- OCR results: full extracted text stored unbounded in SQLite
