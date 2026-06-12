import 'package:flutter/material.dart';
import 'package:uuid/uuid.dart';
import '../services/participant_service.dart';
import '../../sync/services/upload_service.dart';

class EnrollmentScreen extends StatefulWidget {
  final VoidCallback onEnrolled;
  final UploadService? uploadService;

  const EnrollmentScreen({
    super.key,
    required this.onEnrolled,
    this.uploadService,
  });

  @override
  State<EnrollmentScreen> createState() => _EnrollmentScreenState();
}

class _EnrollmentScreenState extends State<EnrollmentScreen> {
  final _formKey = GlobalKey<FormState>();
  final _participantIdController = TextEditingController();
  final _confirmIdController = TextEditingController();
  final _participantService = ParticipantService();

  bool _isLoading = false;
  String? _errorMessage;

  // Retry and rate limiting
  static const int _maxRetries = 5;
  int _failedAttempts = 0;
  DateTime? _lastAttemptTime;
  static const Duration _rateLimitDuration = Duration(minutes: 1);

  @override
  void dispose() {
    _participantIdController.dispose();
    _confirmIdController.dispose();
    super.dispose();
  }

  bool get _isRateLimited {
    if (_failedAttempts < _maxRetries) return false;
    if (_lastAttemptTime == null) return false;

    final elapsed = DateTime.now().difference(_lastAttemptTime!);
    return elapsed < _rateLimitDuration;
  }

  Duration get _remainingRateLimitTime {
    if (_lastAttemptTime == null) return Duration.zero;
    final elapsed = DateTime.now().difference(_lastAttemptTime!);
    final remaining = _rateLimitDuration - elapsed;
    return remaining.isNegative ? Duration.zero : remaining;
  }

  Future<void> _enroll() async {
    // Check rate limiting
    if (_isRateLimited) {
      final remaining = _remainingRateLimitTime;
      setState(() {
        _errorMessage = 'Too many attempts. Please wait ${remaining.inSeconds} seconds before trying again.';
      });
      return;
    }

    if (!_formKey.currentState!.validate()) return;

    // Check if IDs match (case-insensitive for test users)
    final participantId = _participantIdController.text.trim();
    final confirmId = _confirmIdController.text.trim();
    final normalizedId = ParticipantService.isTestUserId(participantId)
        ? participantId.toLowerCase()
        : participantId;
    final normalizedConfirmId = ParticipantService.isTestUserId(confirmId)
        ? confirmId.toLowerCase()
        : confirmId;

    if (normalizedId != normalizedConfirmId) {
      setState(() {
        _errorMessage = 'Participant IDs do not match. Please re-enter.';
        _failedAttempts++;
        _lastAttemptTime = DateTime.now();
      });
      return;
    }

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      // Validate against Firebase
      final validationResult = await _participantService.validateParticipantId(normalizedId);

      if (!validationResult.isValid) {
        setState(() {
          _errorMessage = validationResult.errorMessage;
          _isLoading = false;
          _failedAttempts++;
          _lastAttemptTime = DateTime.now();
        });
        return;
      }

      // Generate a unique visitor ID for this device
      final visitorId = const Uuid().v4();

      // Register this device enrollment in Firebase
      final marked = await _participantService.registerDeviceEnrollment(
        participantId: normalizedId,
        visitorId: visitorId,
        deviceInfo: {'platform': Theme.of(context).platform.name},
      );

      if (!marked) {
        setState(() {
          _errorMessage = 'Failed to register. Please try again.';
          _isLoading = false;
          _failedAttempts++;
          _lastAttemptTime = DateTime.now();
        });
        return;
      }

      // Enroll the participant locally
      final participant = await _participantService.enroll(
        participantId: normalizedId,
        visitorId: visitorId,
      );

      // Sync enrollment to Firebase participants collection (if uploadService provided)
      if (widget.uploadService != null) {
        try {
          await widget.uploadService!.registerParticipant(
            participantId: participant.id,
            visitorId: participant.visitorId,
            enrolledAt: participant.enrolledAt,
          );
        } catch (e) {
          print('[EnrollmentScreen] Firebase registration failed, continuing locally: $e');
          // Continue anyway - we have local enrollment
        }
      }

      // Notify parent that enrollment is complete
      widget.onEnrolled();
    } catch (e) {
      setState(() {
        _errorMessage = 'Enrollment failed: $e';
        _isLoading = false;
        _failedAttempts++;
        _lastAttemptTime = DateTime.now();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final retriesRemaining = _maxRetries - _failedAttempts;
    final showRetriesWarning = _failedAttempts > 0 && retriesRemaining > 0;

    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const SizedBox(height: 48),

                // Logo/Title
                const Icon(
                  Icons.analytics_outlined,
                  size: 80,
                  color: Color(0xFF4A6CF7),
                ),
                const SizedBox(height: 24),

                Text(
                  'SocialScope',
                  style: Theme.of(context).textTheme.headlineLarge?.copyWith(
                    fontWeight: FontWeight.bold,
                    color: const Color(0xFF1A1A2E),
                  ),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 8),

                Text(
                  'Social Media Research Platform',
                  style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                    color: Colors.grey[600],
                  ),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 48),

                // Study Info Card
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(Icons.info_outline, color: Colors.blue),
                            const SizedBox(width: 8),
                            Text(
                              'Study Information',
                              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        Text(
                          'This app is part of an IRB-approved research study examining social media content exposure. '
                          'By participating, you agree to have your Reddit and X/Twitter browsing activity recorded for research purposes.',
                          style: Theme.of(context).textTheme.bodyMedium,
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 24),

                // Sign in via the secure link (no manual ID entry).
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      children: [
                        const Icon(Icons.link, size: 40, color: Color(0xFF4A6CF7)),
                        const SizedBox(height: 12),
                        Text(
                          'Sign in with your link',
                          style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.bold,
                          ),
                          textAlign: TextAlign.center,
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'The research team sent you a secure sign-in link by text and '
                          'email. Open that link on this phone to sign in — there is '
                          'nothing to type here.',
                          style: Theme.of(context).textTheme.bodyMedium,
                          textAlign: TextAlign.center,
                        ),
                        const SizedBox(height: 12),
                        Text(
                          'If you didn\'t receive a link, or it isn\'t working, contact '
                          'the research team and we\'ll resend it.',
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: Colors.grey[600],
                          ),
                          textAlign: TextAlign.center,
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),

                // Retries warning
                if (showRetriesWarning) ...[
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.orange[50],
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: Colors.orange[200]!),
                    ),
                    child: Row(
                      children: [
                        Icon(Icons.warning_amber, color: Colors.orange[700]),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            '$retriesRemaining attempt${retriesRemaining == 1 ? '' : 's'} remaining',
                            style: TextStyle(color: Colors.orange[700]),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                ],

                // Error message
                if (_errorMessage != null) ...[
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.red[50],
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: Colors.red[200]!),
                    ),
                    child: Row(
                      children: [
                        Icon(Icons.error_outline, color: Colors.red[700]),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            _errorMessage!,
                            style: TextStyle(color: Colors.red[700]),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                ],

                // Waiting for the participant to open their sign-in link.
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    const SizedBox(
                      height: 16,
                      width: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                    const SizedBox(width: 12),
                    Text(
                      'Waiting for your sign-in link…',
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: Colors.grey[600],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 24),

                // Privacy Note
                Text(
                  'Your data is encrypted and stored securely. '
                  'You can withdraw from the study at any time by contacting the research team.',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Colors.grey[600],
                  ),
                  textAlign: TextAlign.center,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
