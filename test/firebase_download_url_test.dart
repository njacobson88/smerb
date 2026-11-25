import 'package:flutter_test/flutter_test.dart';
import 'package:smerb_app/features/sync/services/upload_service.dart';

/// 2026-11-25: download URLs are built on the phone from a token the app mints
/// at upload time. getDownloadURL() is a read, which a signed-out phone is not
/// allowed — 963177422 lost its session on 2026-11-12 and every screenshot
/// event failed for 13 days while the images themselves reached Storage.
void main() {
  test('matches the URL Firebase Storage serves for a tokened object', () {
    final url = firebaseDownloadUrl(
      'r01-redditx-suicide.firebasestorage.app',
      'screenshots/963177422/d3c22273-1aee-4449-96cb-9f335dfdb939/screenshot_1794346446077.jpg',
      '980cdce0-9235-40d4-a736-c6c3d0ba2362',
    );
    expect(
      url,
      'https://firebasestorage.googleapis.com/v0/b/r01-redditx-suicide.firebasestorage.app/o/'
      'screenshots%2F963177422%2Fd3c22273-1aee-4449-96cb-9f335dfdb939%2Fscreenshot_1794346446077.jpg'
      '?alt=media&token=980cdce0-9235-40d4-a736-c6c3d0ba2362',
    );
    // The token is recoverable from the URL (written to the event as screenshotToken).
    expect(Uri.parse(url).queryParameters['token'], '980cdce0-9235-40d4-a736-c6c3d0ba2362');
  });

  test('encodes every path separator and nothing else surprising', () {
    final url = firebaseDownloadUrl('b', 'html/p/s/page_1.html.gz', 't');
    expect(url, 'https://firebasestorage.googleapis.com/v0/b/b/o/html%2Fp%2Fs%2Fpage_1.html.gz?alt=media&token=t');
  });
}
