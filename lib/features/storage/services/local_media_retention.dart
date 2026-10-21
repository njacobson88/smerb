/// Local media retention — pure decision logic (no I/O), unit-tested.
///
/// Why this exists (2026-10-21): a heavy iOS user hit the 2 GB local cache cap
/// and capture paused for good. Every screenshot had uploaded, but the local
/// file is only deleted once BOTH upload and on-device OCR have happened, and
/// OCR covered ~27% of their screenshots. Then the 30-day prune dropped the
/// un-OCR'd event ROWS while leaving their FILES behind — ~1.5 GB of orphans
/// nothing could ever free. Capture does not resume by itself from that state.
///
/// Rules:
///   * A file is kept only while something still needs it: the event is not
///     yet uploaded, or OCR is still expected AND the file is younger than
///     [ocrGraceDays]. OCR text is nice-to-have; a cache so full that capture
///     stops is data loss.
///   * A file that no event row references at all is an orphan: delete it.
///   * Files are never deleted before their event has been uploaded.
library;

class LocalMediaRetention {
  LocalMediaRetention._();

  /// Keep a synced screenshot without OCR only this long (OCR runs in the
  /// background sync cycle; if it has not happened in a week it is not going
  /// to help). Unsynced files are never subject to this.
  static const int ocrGraceDays = 7;

  /// Should a screenshot file still be kept on disk?
  ///
  /// [referenced]   an event row still points at this file.
  /// [synced]       that event has been uploaded (file is safe in Storage).
  /// [ocrDone]      an OCR result exists for that event (or its dedup original).
  /// [ageDays]      age of the file on disk.
  static bool shouldKeep({
    required bool referenced,
    required bool synced,
    required bool ocrDone,
    required double ageDays,
    int graceDays = ocrGraceDays,
  }) {
    if (!referenced) return false;        // orphan: nothing can ever use it
    if (!synced) return true;             // not uploaded yet: never delete
    if (ocrDone) return false;            // uploaded + text extracted: done
    return ageDays < graceDays;           // uploaded, OCR pending: wait a while
  }

  /// Split the files found on disk into keep / delete, given what the local
  /// database knows about them. [filesOnDisk] maps path -> age in days;
  /// [referencedFiles] maps path -> (synced, ocrDone) for every path an event
  /// row still references (a path may be shared by deduped events — it counts
  /// as synced/ocrDone only if EVERY referencing event is).
  static List<String> filesToDelete({
    required Map<String, double> filesOnDisk,
    required Map<String, ({bool synced, bool ocrDone})> referencedFiles,
    int graceDays = ocrGraceDays,
  }) {
    final out = <String>[];
    filesOnDisk.forEach((path, age) {
      final ref = referencedFiles[path];
      final keep = shouldKeep(
        referenced: ref != null,
        synced: ref?.synced ?? false,
        ocrDone: ref?.ocrDone ?? false,
        ageDays: age,
        graceDays: graceDays,
      );
      if (!keep) out.add(path);
    });
    return out;
  }
}
