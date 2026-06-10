import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../services/push_notification_service.dart';

/// Shown when a safety alert fires and the participant receives a push asking
/// them to confirm they are at risk or mark it an error. Saying it was an error
/// stops the escalation process (same effect as texting "1"/"ERROR" or
/// pressing 1 on the IVR call).
class SafetyResponseScreen extends StatefulWidget {
  final String alertId;
  final PushNotificationService pushService;

  const SafetyResponseScreen({
    super.key,
    required this.alertId,
    required this.pushService,
  });

  @override
  State<SafetyResponseScreen> createState() => _SafetyResponseScreenState();
}

class _SafetyResponseScreenState extends State<SafetyResponseScreen> {
  bool _submitting = false;
  String? _submitted; // 'confirmed' | 'error'

  Future<void> _submit(String response) async {
    if (_submitting) return;
    setState(() => _submitting = true);

    final ok = await widget.pushService.submitSafetyResponse(
      alertId: widget.alertId,
      response: response,
    );

    if (!mounted) return;
    if (ok) {
      setState(() => _submitted = response);
    } else {
      setState(() => _submitting = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Could not save your response. Please check your connection. '
            'If you need help now, call or text 988.',
          ),
          backgroundColor: Colors.orange,
          duration: Duration(seconds: 8),
        ),
      );
    }
  }

  Future<void> _call988() async {
    final uri = Uri.parse('tel:988');
    if (await canLaunchUrl(uri)) await launchUrl(uri);
  }

  @override
  Widget build(BuildContext context) {
    // After a response, show a confirmation state (and crisis resources if they
    // confirmed they could use support).
    if (_submitted != null) {
      return _buildAcknowledgement();
    }

    return PopScope(
      // Don't let a back-gesture dismiss without an explicit choice
      canPop: false,
      child: Scaffold(
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const SizedBox(height: 24),
                const Icon(Icons.health_and_safety,
                    size: 56, color: Color(0xFF4A6CF7)),
                const SizedBox(height: 16),
                Text(
                  'Checking in on you',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                        fontWeight: FontWeight.bold,
                      ),
                ),
                const SizedBox(height: 16),
                Text(
                  'Your recent check-in indicated you may be at risk. '
                  'We want to make sure you\'re okay. Is that right?',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodyLarge,
                ),
                const Spacer(),
                ElevatedButton(
                  onPressed: _submitting ? null : () => _submit('confirmed'),
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 18),
                    backgroundColor: const Color(0xFF4A6CF7),
                  ),
                  child: const Text(
                    'Yes, I could use support',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                  ),
                ),
                const SizedBox(height: 12),
                OutlinedButton(
                  onPressed: _submitting ? null : () => _submit('error'),
                  style: OutlinedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 18),
                  ),
                  child: const Text(
                    'No, this was an error — I\'m safe',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                  ),
                ),
                const SizedBox(height: 24),
                if (_submitting)
                  const Center(child: CircularProgressIndicator())
                else
                  TextButton.icon(
                    onPressed: _call988,
                    icon: const Icon(Icons.phone),
                    label: const Text('Call or text 988 now'),
                  ),
                const SizedBox(height: 12),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildAcknowledgement() {
    final confirmed = _submitted == 'confirmed';
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Icon(confirmed ? Icons.favorite : Icons.check_circle,
                  size: 56,
                  color: confirmed ? const Color(0xFFE0518A) : Colors.green),
              const SizedBox(height: 16),
              Text(
                confirmed ? 'Help is on the way' : 'Thank you',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                      fontWeight: FontWeight.bold,
                    ),
              ),
              const SizedBox(height: 16),
              Text(
                confirmed
                    ? 'A member of our team will be reaching out shortly. '
                      'If you are in immediate danger, please call 988 or 911 '
                      'right now — you don\'t have to wait for us.'
                    : 'We\'ve noted that this was an error and will not follow '
                      'up. If you ever need support, you can reach 988 any time.',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyLarge,
              ),
              const SizedBox(height: 32),
              if (confirmed)
                ElevatedButton.icon(
                  onPressed: _call988,
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 18),
                  ),
                  icon: const Icon(Icons.phone),
                  label: const Text('Call or text 988 now',
                      style: TextStyle(fontSize: 16)),
                ),
              const SizedBox(height: 12),
              TextButton(
                onPressed: () => Navigator.of(context).maybePop(),
                child: const Text('Close'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
