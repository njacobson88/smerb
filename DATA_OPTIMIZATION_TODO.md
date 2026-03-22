# Data Capture & Sync Optimization Checklist

## P0 - Data Loss Prevention (COMPLETED)
- [x] Add network-aware sync (skip uploads when offline)
- [x] Add max retry count (5) for failed uploads (prevent poison events)
- [x] Fix screenshot sync bug (don't mark synced if file upload failed)
- [x] Use Firestore batch writes for OCR results and HTML status logs

## P1 - Storage Optimization (biggest impact on data volume)
- [ ] Downscale screenshots before JPEG compression (Retina 2-3x -> 1x resolution)
- [ ] Lower JPEG quality from 85 to 70 (visually acceptable for screen content)
- [ ] Compress HTML files with gzip before storing to disk (~90% size reduction)
- [ ] Delete local files after confirmed upload (uncomment deletion, verify success first)
- [ ] Add disk space monitoring (warn/pause capture if usage exceeds threshold)

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

## Current Data Volume Estimates
- Screenshots: ~250KB JPEG each, up to 1/sec = ~900MB/hour active use
- HTML captures: 500KB-2MB each on DOM change, uncompressed
- HtmlStatusLogs: 1 row/sec in SQLite (fastest-growing table)
- OCR results: full extracted text stored unbounded in SQLite
