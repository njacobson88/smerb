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
                  Icons.science_outlined,
                  size: 80,
                  color: Colors.deepOrange,
                ),
                const SizedBox(height: 24),

                Text(
                  'SMERB',
                  style: Theme.of(context).textTheme.headlineLarge?.copyWith(
                    fontWeight: FontWeight.bold,
                    color: Colors.deepOrange,
                  ),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 8),

                Text(
                  'Social Media Exposure Research Browser',
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

                // Participant ID Input
                Text(
                  'Enter your Participant ID',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  'This 9-digit ID was provided to you by the research team.',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Colors.grey[600],
                  ),
                ),
                const SizedBox(height: 12),

                TextFormField(
                  controller: _participantIdController,
                  decoration: InputDecoration(
                    labelText: 'Participant ID',
                    hintText: 'e.g., 123456789 or test1',
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                    prefixIcon: const Icon(Icons.badge_outlined),
                  ),
                  keyboardType: TextInputType.text,
                  validator: ParticipantService.validateIdFormat,
                ),
                const SizedBox(height: 16),

                // Confirm Participant ID Input
                TextFormField(
                  controller: _confirmIdController,
                  decoration: InputDecoration(
                    labelText: 'Confirm Participant ID',
                    hintText: 'Re-enter your ID',
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                    prefixIcon: const Icon(Icons.badge_outlined),
                  ),
                  keyboardType: TextInputType.text,
                  validator: ParticipantService.validateIdFormat,
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

                // Enroll Button
                ElevatedButton(
                  onPressed: (_isLoading || _isRateLimited) ? null : _enroll,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.deepOrange,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                  ),
                  child: _isLoading
                      ? const SizedBox(
                          height: 20,
                          width: 20,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : _isRateLimited
                          ? Text(
                              'Please wait ${_remainingRateLimitTime.inSeconds}s',
                              style: const TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.bold,
                              ),
                            )
                          : const Text(
                              'Enroll in Study',
                              style: TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
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
