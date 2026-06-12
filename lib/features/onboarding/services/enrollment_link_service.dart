import 'dart:convert';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:http/http.dart' as http;
import 'package:uuid/uuid.dart';
import 'participant_service.dart';

/// Handles the per-participant enrollment deep link (smerb://enroll?pid=&s=).
///
/// Flow: exchange the high-entropy secret for a Firebase custom token at the
/// backend, signInWithCustomToken (so request.auth.uid == participantId for the
/// scoped rules), then enroll the participant locally — exactly the state the
/// manual type-the-ID flow reaches, plus the auth session.
///
/// Additive and non-fatal: any failure returns false and leaves the app on the
/// normal (manual) enrollment screen. It never throws into app startup.
class EnrollmentLinkService {
  EnrollmentLinkService({required this.participantService, http.Client? client})
      : _client = client ?? http.Client();

  final ParticipantService participantService;
  final http.Client _client;

  // The dashboard backend (Cloud Run). Same host the landing page points the
  // app's token exchange at.
  static const String _backendBase =
      'https://socialscope-dashboard-api-436153481478.us-central1.run.app';

  /// True if the URI is a SocialScope enrollment link.
  static bool isEnrollUri(Uri uri) =>
      uri.scheme == 'smerb' && (uri.host == 'enroll' || uri.path == 'enroll');

  /// Returns the enrolled participantId on success, or null on any failure.
  Future<String?> processUri(Uri uri) async {
    if (!isEnrollUri(uri)) return null;
    final pid = uri.queryParameters['pid']?.trim();
    final secret = uri.queryParameters['s'];
    if (pid == null || pid.isEmpty || secret == null || secret.isEmpty) {
      print('[EnrollLink] Missing pid/secret in $uri');
      return null;
    }

    try {
      // 1. Exchange the secret for a Firebase custom token.
      final resp = await _client
          .post(
            Uri.parse('$_backendBase/api/auth/enrollment-token'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'participantId': pid, 'secret': secret}),
          )
          .timeout(const Duration(seconds: 20));
      if (resp.statusCode != 200) {
        print('[EnrollLink] Token exchange failed: ${resp.statusCode} ${resp.body}');
        return null;
      }
      final token = (jsonDecode(resp.body) as Map<String, dynamic>)['token'] as String?;
      if (token == null || token.isEmpty) {
        print('[EnrollLink] No token in response');
        return null;
      }

      // 2. Sign in with the custom token (uid == participantId).
      await FirebaseAuth.instance.signInWithCustomToken(token);

      // 3. Enroll locally (mirrors the manual flow's end state).
      final visitorId = const Uuid().v4();
      try {
        await participantService.registerDeviceEnrollment(
          participantId: pid,
          visitorId: visitorId,
          deviceInfo: const {'platform': 'enroll_link'},
        );
      } catch (e) {
        // Device-registration is best-effort (e.g. re-install with reusable
        // link) — the local enroll + auth are what matter.
        print('[EnrollLink] registerDeviceEnrollment non-fatal: $e');
      }
      await participantService.enroll(participantId: pid, visitorId: visitorId);

      print('[EnrollLink] Enrolled $pid via sign-in link');
      return pid;
    } catch (e) {
      print('[EnrollLink] Enrollment via link failed: $e');
      return null;
    }
  }
}
