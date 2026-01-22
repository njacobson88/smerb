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
  final _participantService = ParticipantService();

  bool _isLoading = false;
  String? _errorMessage;

  @override
  void dispose() {
    _participantIdController.dispose();
    super.dispose();
  }

  Future<void> _enroll() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final participantId = _participantIdController.text.trim().toUpperCase();

      // Generate a unique visitor ID for this device
      final visitorId = const Uuid().v4();

      // Enroll the participant locally
      final participant = await _participantService.enroll(
        participantId: participantId,
        visitorId: visitorId,
      );

      // Sync enrollment to Firebase (if uploadService provided)
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
      });
    }
  }

  @override
  Widget build(BuildContext context) {
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
                Icon(
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
                            Icon(Icons.info_outline, color: Colors.blue),
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
                  'This ID was provided to you by the research team.',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Colors.grey[600],
                  ),
                ),
                const SizedBox(height: 12),

                TextFormField(
                  controller: _participantIdController,
                  decoration: InputDecoration(
                    hintText: 'e.g., SMERB-001',
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(8),
                    ),
                    prefixIcon: const Icon(Icons.badge_outlined),
                  ),
                  textCapitalization: TextCapitalization.characters,
                  validator: (value) {
                    if (value == null || value.trim().isEmpty) {
                      return 'Please enter your Participant ID';
                    }
                    if (value.trim().length < 3) {
                      return 'Participant ID must be at least 3 characters';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: 24),

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
                        Icon(Icons.error_outline, color: Colors.red),
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
                  onPressed: _isLoading ? null : _enroll,
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
