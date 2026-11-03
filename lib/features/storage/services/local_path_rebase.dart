/// Rebase stored media paths onto the app's CURRENT documents directory.
///
/// Why (2026-11-03): the app stores absolute paths for every screenshot and
/// HTML file it saves. On iOS the app's data container is renamed on every
/// update/reinstall (`/var/mobile/Containers/Data/Application/<UUID>/…`), so
/// after an update every stored path points into a folder that no longer
/// exists while the files themselves sit, intact, under the new one.
/// Observed on participant 865960135: seven different container UUIDs in
/// 30 days, one per install. Consequences before this fix:
///   * every HTML page not yet uploaded at update time could never be found
///     (17,094 pages retired as "file missing" in one go on 2026-11-03);
///   * the launch sweep saw those files as orphans and deleted them;
///   * screenshots still awaiting upload or OCR at update time were lost the
///     same way (rare — screenshots upload within seconds — but possible).
///
/// The stored path keeps its tail from the media sub-directory on
/// (`screenshots/…` or `html/<session>/…`); only the prefix is replaced.
/// Pure logic, unit-tested; the database applies it in `rebaseStoredPaths`.
library;

class LocalPathRebase {
  LocalPathRebase._();

  /// The sub-directories under the documents folder that hold media.
  static const List<String> mediaDirs = ['screenshots', 'html'];

  /// `stored` rewritten so it lives under `docsDir`, or null when it is
  /// already there or has no recognisable media sub-directory in it.
  static String? rebase(String stored, String docsDir) {
    final root = docsDir.endsWith('/') ? docsDir.substring(0, docsDir.length - 1) : docsDir;
    if (stored.startsWith('$root/')) return null;
    for (final dir in mediaDirs) {
      final marker = '/$dir/';
      final i = stored.indexOf(marker);
      if (i >= 0) return '$root${stored.substring(i)}';
    }
    return null;
  }

  /// The container prefix of a stored path (everything before the media
  /// sub-directory), for logging which old install the rows came from.
  static String? prefixOf(String stored) {
    for (final dir in mediaDirs) {
      final i = stored.indexOf('/$dir/');
      if (i >= 0) return stored.substring(0, i);
    }
    return null;
  }
}
