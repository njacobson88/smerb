import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:url_launcher/url_launcher.dart';
import '../../../core/config/environment_config.dart';

/// Checks for app updates via Firestore-stored version info.
/// On launch, compares the local build number against the latest
/// version stored in Firestore. If a newer version is available,
/// shows a dialog prompting the user to update via Firebase App Distribution.
class AppUpdateService {
  /// The build number actually installed, read from the package at runtime.
  ///
  /// This used to be a hardcoded `1` that nobody remembered to bump, so the
  /// comparison below was effectively "is the published build newer than 1" —
  /// true for every release forever. Publishing a version would have nagged
  /// participants who were ALREADY up to date, on every launch.
  static Future<int> installedBuildNumber() async {
    try {
      return int.tryParse((await PackageInfo.fromPlatform()).buildNumber) ?? 0;
    } catch (e) {
      print('[AppUpdate] Could not read build number: $e');
      return 0;
    }
  }

  /// Check for updates on app launch.
  static Future<void> checkForUpdate(BuildContext context) async {
    try {
      final currentBuildNumber = await installedBuildNumber();
      // Unknown build: stay silent rather than nag on a bad read.
      if (currentBuildNumber == 0) return;

      final doc = await FirebaseFirestore.instance
          .collection(EnvConfig.col('app_config'))
          .doc('latest_version')
          .get();

      if (!doc.exists) return;

      final data = doc.data();
      if (data == null) return;

      final latestBuildNumber = data['buildNumber'] as int? ?? 0;
      final latestVersion = data['version'] as String? ?? '';
      final updateUrl = data['updateUrl'] as String? ?? '';
      final forceUpdate = data['forceUpdate'] as bool? ?? false;
      final releaseNotes = data['releaseNotes'] as String? ?? '';

      if (latestBuildNumber > currentBuildNumber && context.mounted) {
        _showUpdateDialog(
          context,
          latestVersion: latestVersion,
          releaseNotes: releaseNotes,
          updateUrl: updateUrl,
          forceUpdate: forceUpdate,
        );
      }
    } catch (e) {
      print('[AppUpdate] Error checking for updates: $e');
    }
  }

  static void _showUpdateDialog(
    BuildContext context, {
    required String latestVersion,
    required String releaseNotes,
    required String updateUrl,
    required bool forceUpdate,
  }) {
    showDialog(
      context: context,
      barrierDismissible: !forceUpdate,
      builder: (dialogContext) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Row(
          children: [
            Icon(Icons.system_update, color: Colors.blue[700], size: 28),
            const SizedBox(width: 10),
            const Expanded(
              child: Text('Update Available', style: TextStyle(fontSize: 18)),
            ),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'A new version of SocialScope ($latestVersion) is available.',
              style: const TextStyle(fontSize: 14, height: 1.4),
            ),
            if (releaseNotes.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                "What's new:",
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: Colors.grey[800],
                ),
              ),
              const SizedBox(height: 4),
              Text(
                releaseNotes,
                style: TextStyle(fontSize: 13, color: Colors.grey[600], height: 1.4),
              ),
            ],
            if (forceUpdate) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: Colors.amber[50],
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.amber[200]!),
                ),
                child: Text(
                  'This update is required to continue using the app.',
                  style: TextStyle(fontSize: 12, color: Colors.amber[800]),
                ),
              ),
            ],
          ],
        ),
        actions: [
          if (!forceUpdate)
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(),
              child: Text('Later', style: TextStyle(color: Colors.grey[500])),
            ),
          ElevatedButton(
            onPressed: () {
              Navigator.of(dialogContext).pop();
              if (updateUrl.isNotEmpty) {
                _launchUpdateUrl(updateUrl);
              }
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF4A6CF7),
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(8),
              ),
            ),
            child: const Text('Update Now'),
          ),
        ],
      ),
    );
  }

  static Future<void> _launchUpdateUrl(String url) async {
    try {
      final uri = Uri.parse(url);
      if (await canLaunchUrl(uri)) {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
      }
    } catch (e) {
      print('[AppUpdate] Failed to launch update URL: $e');
    }
  }
}
