import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:smerb_app/features/storage/database/database.dart';
import 'package:smerb_app/features/storage/services/local_path_rebase.dart';

const oldIos = '/var/mobile/Containers/Data/Application/0524F799-DB61-4FE3-AF45-663C15228000/Documents';
const newIos = '/var/mobile/Containers/Data/Application/6F5FAC37-9570-43B5-87D7-F0DCAC147333/Documents';
const android = '/data/user/0/com.dartmouth.smerb/app_flutter';

void main() {
  group('LocalPathRebase.rebase', () {
    test('iOS container rename: prefix replaced, tail kept', () {
      expect(LocalPathRebase.rebase('$oldIos/screenshots/shot_1.jpg', newIos),
          '$newIos/screenshots/shot_1.jpg');
      expect(LocalPathRebase.rebase('$oldIos/html/sess-1/page_17.html.gz', newIos),
          '$newIos/html/sess-1/page_17.html.gz');
    });

    test('already under the current folder: untouched', () {
      expect(LocalPathRebase.rebase('$newIos/screenshots/shot_1.jpg', newIos), isNull);
      expect(LocalPathRebase.rebase('$android/html/s/p.html.gz', android), isNull);
      expect(LocalPathRebase.rebase('$android/html/s/p.html.gz', '$android/'), isNull);
    });

    test('no media sub-directory: left alone', () {
      expect(LocalPathRebase.rebase('/somewhere/else/file.bin', newIos), isNull);
    });

    test('prefixOf names the old install', () {
      expect(LocalPathRebase.prefixOf('$oldIos/html/s/p.html.gz'), oldIos);
      expect(LocalPathRebase.prefixOf('/x/y.bin'), isNull);
    });
  });

  group('AppDatabase.rebaseStoredPaths', () {
    late AppDatabase db;
    setUp(() => db = AppDatabase.forTesting(NativeDatabase.memory()));
    tearDown(() => db.close());

    test('rewrites stale screenshot JSON paths and HTML rows, leaves current ones', () async {
      await db.insertEvent(EventsCompanion(
        id: const Value('e-old'), sessionId: const Value('s'), participantId: const Value('p'),
        eventType: const Value('screenshot'), timestamp: Value(DateTime(2026, 11, 1)),
        platform: const Value('reddit'),
        data: const Value('{"filePath": "$oldIos/screenshots/a.jpg", "fileSize": 10, "dedup": false}'),
      ));
      await db.insertEvent(EventsCompanion(
        id: const Value('e-new'), sessionId: const Value('s'), participantId: const Value('p'),
        eventType: const Value('screenshot'), timestamp: Value(DateTime(2026, 11, 2)),
        platform: const Value('reddit'),
        data: const Value('{"filePath": "$newIos/screenshots/b.jpg", "fileSize": 10}'),
      ));
      await db.insertEvent(EventsCompanion(
        id: const Value('e-other'), sessionId: const Value('s'), participantId: const Value('p'),
        eventType: const Value('page_view'), timestamp: Value(DateTime(2026, 11, 2)),
        platform: const Value('reddit'), data: const Value('{"url": "https://x"}'),
      ));
      await db.into(db.htmlCaptures).insert(HtmlCapturesCompanion(
        id: const Value('h-old'), eventId: const Value('e-old'), participantId: const Value('p'),
        sessionId: const Value('s'), htmlHash: const Value('h'),
        filePath: const Value('$oldIos/html/s/page_1.html.gz'), platform: const Value('reddit'),
        capturedAt: Value(DateTime(2026, 11, 1)),
      ));
      await db.into(db.htmlCaptures).insert(HtmlCapturesCompanion(
        id: const Value('h-new'), eventId: const Value('e-new'), participantId: const Value('p'),
        sessionId: const Value('s'), htmlHash: const Value('h'),
        filePath: const Value('$newIos/html/s/page_2.html.gz'), platform: const Value('reddit'),
        capturedAt: Value(DateTime(2026, 11, 2)),
      ));

      final r = await db.rebaseStoredPaths(newIos);
      expect(r.screenshotRows, 1);
      expect(r.htmlRows, 1);
      expect(r.oldPrefixes, {oldIos});

      final refs = await db.getReferencedScreenshotFiles();
      expect(refs.keys.toSet(), {'$newIos/screenshots/a.jpg', '$newIos/screenshots/b.jpg'});
      final html = await db.getReferencedHtmlFiles();
      expect(html, {'$newIos/html/s/page_1.html.gz', '$newIos/html/s/page_2.html.gz'});

      // Other JSON fields survive the rewrite.
      final ev = await (db.select(db.events)..where((e) => e.id.equals('e-old'))).getSingle();
      expect(ev.data, contains('"fileSize":10'));
      expect(ev.data, contains('"dedup":false'));

      // Second run is a no-op.
      final again = await db.rebaseStoredPaths(newIos);
      expect(again.screenshotRows + again.htmlRows, 0);
    });

    test('rows from several old installs all land under the current folder', () async {
      for (var i = 0; i < 3; i++) {
        await db.into(db.htmlCaptures).insert(HtmlCapturesCompanion(
          id: Value('h$i'), eventId: Value('e$i'), participantId: const Value('p'),
          sessionId: const Value('s'), htmlHash: const Value('h'),
          filePath: Value('/var/mobile/Containers/Data/Application/UUID-$i/Documents/html/s/p$i.html.gz'),
          platform: const Value('reddit'), capturedAt: Value(DateTime(2026, 11, 1, i)),
        ));
      }
      final r = await db.rebaseStoredPaths(newIos);
      expect(r.htmlRows, 3);
      expect(r.oldPrefixes.length, 3);
      expect(await db.getReferencedHtmlFiles(),
          {for (var i = 0; i < 3; i++) '$newIos/html/s/p$i.html.gz'});
    });
  });
}
