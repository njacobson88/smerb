import 'package:flutter_test/flutter_test.dart';
import 'package:smerb_app/features/storage/services/local_media_retention.dart';

void main() {
  group('shouldKeep', () {
    test('unsynced file is never deleted, however old or OCR-less', () {
      expect(LocalMediaRetention.shouldKeep(referenced: true, synced: false, ocrDone: false, ageDays: 400), isTrue);
    });

    test('orphan (no event row) is deleted even if brand new', () {
      expect(LocalMediaRetention.shouldKeep(referenced: false, synced: false, ocrDone: false, ageDays: 0), isFalse);
    });

    test('uploaded + OCR done -> delete', () {
      expect(LocalMediaRetention.shouldKeep(referenced: true, synced: true, ocrDone: true, ageDays: 0), isFalse);
    });

    test('uploaded, OCR pending -> keep inside grace, delete after', () {
      expect(LocalMediaRetention.shouldKeep(referenced: true, synced: true, ocrDone: false, ageDays: 2), isTrue);
      expect(LocalMediaRetention.shouldKeep(referenced: true, synced: true, ocrDone: false, ageDays: 6.9), isTrue);
      expect(LocalMediaRetention.shouldKeep(referenced: true, synced: true, ocrDone: false, ageDays: 7), isFalse);
      expect(LocalMediaRetention.shouldKeep(referenced: true, synced: true, ocrDone: false, ageDays: 30), isFalse);
    });
  });

  group('filesToDelete — the 2026-10-21 incident shape', () {
    test('orphans from pruned rows + stale OCR-less files go; fresh and unsynced stay', () {
      final disk = <String, double>{
        '/s/orphan_pruned_row.jpg': 45,        // row pruned at 30d, file left behind
        '/s/synced_no_ocr_old.jpg': 12,        // uploaded, OCR never ran
        '/s/synced_no_ocr_fresh.jpg': 1,       // uploaded today, OCR may still run
        '/s/synced_ocr_done.jpg': 0.1,         // both done
        '/s/not_uploaded.jpg': 20,             // offline for weeks: must keep
      };
      final refs = <String, ({bool synced, bool ocrDone})>{
        '/s/synced_no_ocr_old.jpg': (synced: true, ocrDone: false),
        '/s/synced_no_ocr_fresh.jpg': (synced: true, ocrDone: false),
        '/s/synced_ocr_done.jpg': (synced: true, ocrDone: true),
        '/s/not_uploaded.jpg': (synced: false, ocrDone: false),
      };
      final del = LocalMediaRetention.filesToDelete(filesOnDisk: disk, referencedFiles: refs)..sort();
      expect(del, ['/s/orphan_pruned_row.jpg', '/s/synced_no_ocr_old.jpg', '/s/synced_ocr_done.jpg']);
    });

    test('a path shared by deduped events is kept while any referencing event still needs it', () {
      // Caller already folded the dedup group into one entry: synced only if ALL synced.
      final del = LocalMediaRetention.filesToDelete(
        filesOnDisk: {'/s/shared.jpg': 3},
        referencedFiles: {'/s/shared.jpg': (synced: false, ocrDone: true)},
      );
      expect(del, isEmpty);
    });

    test('empty disk / empty db are no-ops', () {
      expect(LocalMediaRetention.filesToDelete(filesOnDisk: {}, referencedFiles: {}), isEmpty);
    });
  });

  group('CachePressureValve', () {
    const cap = 2048 * 1024 * 1024;
    test('nothing to free below the trigger', () {
      expect(CachePressureValve.bytesToFree(usageBytes: (cap * 0.94).floor(), capBytes: cap), 0);
      expect(CachePressureValve.bytesToFree(usageBytes: 0, capBytes: cap), 0);
      expect(CachePressureValve.bytesToFree(usageBytes: 10, capBytes: 0), 0);
    });

    test('at or over the trigger, free down to the target', () {
      expect(CachePressureValve.bytesToFree(usageBytes: cap, capBytes: cap), cap - (cap * 0.85).floor());
      expect(CachePressureValve.bytesToFree(usageBytes: cap + 5 * 1048576, capBytes: cap),
          cap + 5 * 1048576 - (cap * 0.85).floor());
    });

    test('picks the oldest captures until the need is covered, no more', () {
      final cands = [
        (id: 'a', bytes: 100), (id: 'b', bytes: 100), (id: 'c', bytes: 100), (id: 'd', bytes: 100),
      ];
      expect(CachePressureValve.pickToDrop(oldestFirst: cands, bytesNeeded: 250), ['a', 'b', 'c']);
      expect(CachePressureValve.pickToDrop(oldestFirst: cands, bytesNeeded: 300), ['a', 'b', 'c']);
      expect(CachePressureValve.pickToDrop(oldestFirst: cands, bytesNeeded: 0), isEmpty);
      expect(CachePressureValve.pickToDrop(oldestFirst: cands, bytesNeeded: 10000), ['a', 'b', 'c', 'd']);
    });

    test('zero-byte (already missing) files do not satisfy the need by themselves', () {
      final cands = [(id: 'ghost', bytes: 0), (id: 'real', bytes: 500)];
      expect(CachePressureValve.pickToDrop(oldestFirst: cands, bytesNeeded: 400), ['ghost', 'real']);
    });
  });
}
