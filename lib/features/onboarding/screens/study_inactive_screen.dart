import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

/// Shown instead of the app when a participant is no longer actively enrolled.
///
/// Blocks browsing, capture and check-ins — but DELIBERATELY still surfaces
/// crisis resources. This is a suicide-prevention study; a participant who was
/// just deactivated may still be at risk, and an app that hard-locks them away
/// from 988 would be unsafe. Only study participation stops here.
class StudyInactiveScreen extends StatelessWidget {
  final String? reason;

  const StudyInactiveScreen({super.key, this.reason});

  Future<void> _launch(String url) async {
    final uri = Uri.parse(url);
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 48),
              const Icon(Icons.check_circle_outline,
                  size: 72, color: Color(0xFF4A6CF7)),
              const SizedBox(height: 24),
              Text('Your participation has ended',
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                        fontWeight: FontWeight.bold,
                        color: const Color(0xFF1A1A2E),
                      ),
                  textAlign: TextAlign.center),
              const SizedBox(height: 12),
              Text(
                reason?.trim().isNotEmpty == true
                    ? reason!
                    : 'Thank you for taking part in the SocialScope study. '
                        'You do not need to complete any more check-ins, and the '
                        'app is no longer collecting data.',
                style: Theme.of(context).textTheme.bodyMedium
                    ?.copyWith(color: Colors.grey[700]),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 32),
              Card(
                color: const Color(0xFFFFF4F4),
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    children: [
                      Text('Need support right now?',
                          style: Theme.of(context).textTheme.titleMedium
                              ?.copyWith(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 8),
                      Text(
                        'These are always available to you, whether or not you '
                        'are in the study.',
                        style: Theme.of(context).textTheme.bodySmall,
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 16),
                      ElevatedButton.icon(
                        onPressed: () => _launch('tel:988'),
                        icon: const Icon(Icons.phone),
                        label: const Text('Call 988'),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFFDB4325),
                          foregroundColor: Colors.white,
                          minimumSize: const Size.fromHeight(46),
                        ),
                      ),
                      const SizedBox(height: 8),
                      OutlinedButton.icon(
                        onPressed: () => _launch('sms:741741?body=HELLO'),
                        icon: const Icon(Icons.message_outlined),
                        label: const Text('Text HELLO to 741741'),
                        style: OutlinedButton.styleFrom(
                          minimumSize: const Size.fromHeight(46),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 24),
              Text(
                'Questions about the study? Contact the research team at\n'
                'Social.Media.Wellness@dartmouth.edu',
                style: Theme.of(context).textTheme.bodySmall
                    ?.copyWith(color: Colors.grey[600]),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
