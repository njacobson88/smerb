import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:card_swiper/card_swiper.dart';
import 'package:uuid/uuid.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import '../models/ema_config.dart';
import '../../storage/database/database.dart';
import 'package:drift/drift.dart' as drift;

class CheckinScreen extends StatefulWidget {
  final AppDatabase database;
  final String participantId;
  final String sessionId;
  final bool selfInitiated;

  const CheckinScreen({
    super.key,
    required this.database,
    required this.participantId,
    required this.sessionId,
    this.selfInitiated = true,
  });

  @override
  State<CheckinScreen> createState() => _CheckinScreenState();
}

class _CheckinScreenState extends State<CheckinScreen>
    with SingleTickerProviderStateMixin {
  EmaConfig? _config;
  final SwiperController _swiperController = SwiperController();
  final Map<String, dynamic> _responses = {};
  int _currentIndex = 0;
  List<EmaQuestion> _visibleQuestions = [];
  bool _completed = false;
  bool _showPostResources = false;
  DateTime? _startedAt;

  // Crisis button state
  bool _crisisTriggered = false;
  late AnimationController _crisisFlashController;
  late Animation<double> _crisisFlashAnimation;

  // Safety confirmation tracking
  bool _safetyConfirmationShowing = false;
  String? _currentTriggerQuestionId;
  int _confirmationCount = 0; // How many confirmations shown so far
  final Set<String> _confirmedNoQuestions = {}; // Questions where they said "No"
  bool _confirmedYes = false; // True if they ever said "Yes, I am in immediate danger"

  @override
  void initState() {
    super.initState();
    _startedAt = DateTime.now();

    _crisisFlashController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    );
    _crisisFlashAnimation = Tween<double>(begin: 0.3, end: 1.0).animate(
      CurvedAnimation(parent: _crisisFlashController, curve: Curves.easeInOut),
    );

    _loadConfig();
  }

  Future<void> _loadConfig() async {
    final config = await EmaConfig.load();
    setState(() {
      _config = config;
      _updateVisibleQuestions();
    });
  }

  void _updateVisibleQuestions() {
    if (_config == null) return;

    final visible = <EmaQuestion>[];
    for (final q in _config!.questions) {
      if (!q.hidden) {
        visible.add(q);
      } else if (_shouldShowHiddenQuestion(q)) {
        visible.add(q);
      }
    }
    _visibleQuestions = visible;
  }

  bool _shouldShowHiddenQuestion(EmaQuestion question) {
    for (final q in _config!.questions) {
      if (q.skipLogic != null) {
        final showIfYes = q.skipLogic!['show_if_yes'] as List<dynamic>?;
        if (showIfYes != null && showIfYes.contains(question.id)) {
          return _responses[q.id] == true;
        }
      }
    }
    return false;
  }

  /// Check if a specific question's response exceeds the safety threshold.
  bool _isQuestionAboveThreshold(EmaQuestion question) {
    if (question.safetyTrigger == null) return false;
    final response = _responses[question.id];
    if (response == null || response is! double) return false;

    final threshold = (question.safetyTrigger!['threshold'] as num).toDouble();
    final inverted = question.safetyTrigger!['inverted'] == true;

    if (inverted) {
      return response < threshold; // e.g., ability_safe < 30 = dangerous
    } else {
      return response > threshold; // e.g., desire_intensity > 30 = dangerous
    }
  }

  /// Check if any trigger question has been answered above threshold.
  bool _anyTriggerExceeded() {
    if (_config == null) return false;
    for (final q in _config!.questions) {
      if (_isQuestionAboveThreshold(q)) return true;
    }
    return false;
  }

  void _onResponseChanged(String questionId, dynamic value) {
    setState(() {
      _responses[questionId] = value;
      _updateVisibleQuestions();
    });
  }

  void _advanceToNext() {
    // Check if the current question is a safety trigger that needs confirmation
    if (!_confirmedYes && !_safetyConfirmationShowing) {
      final currentQ = _visibleQuestions[_currentIndex];
      if (_isQuestionAboveThreshold(currentQ) &&
          !_confirmedNoQuestions.contains(currentQ.id)) {
        // Show safety confirmation for this question
        setState(() {
          _safetyConfirmationShowing = true;
          _currentTriggerQuestionId = currentQ.id;
        });
        return;
      }
    }

    if (_currentIndex < _visibleQuestions.length - 1) {
      _swiperController.next();
    } else {
      _submitCheckin();
    }
  }

  void _onSafetyConfirmationYes() {
    setState(() {
      _confirmedYes = true;
      _crisisTriggered = true;
      _safetyConfirmationShowing = false;
      _responses['safety_confirmed_danger'] = true;
      _responses['safety_confirmed_at_question'] = _currentTriggerQuestionId;
      _responses['safety_confirmation_number'] = _confirmationCount + 1;
    });

    _crisisFlashController.repeat(reverse: true);

    // NOW send the alert — only on confirmed "Yes"
    _sendSafetyAlert();

    // Show crisis resources dialog
    _showCrisisDialog();
  }

  void _onSafetyConfirmationNo() {
    setState(() {
      _confirmedNoQuestions.add(_currentTriggerQuestionId!);
      _confirmationCount++;
      _safetyConfirmationShowing = false;
      _currentTriggerQuestionId = null;

      // Track the crisis state for post-resources screen (but don't alert)
      if (_anyTriggerExceeded()) {
        _crisisTriggered = true;
        _crisisFlashController.repeat(reverse: true);
      }
    });

    // Continue to next question
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (_currentIndex < _visibleQuestions.length - 1) {
        _swiperController.next();
      } else {
        _submitCheckin();
      }
    });
  }

  Future<void> _sendSafetyAlert() async {
    try {
      final alertId = const Uuid().v4();
      await FirebaseFirestore.instance
          .collection('participants')
          .doc(widget.participantId)
          .collection('safety_alerts')
          .doc(alertId)
          .set({
        'participantId': widget.participantId,
        'sessionId': widget.sessionId,
        'responses': _responses.map((k, v) => MapEntry(k, v?.toString())),
        'triggeredAt': FieldValue.serverTimestamp(),
        'confirmedDanger': true,
        'confirmationNumber': _confirmationCount + 1,
        'triggerQuestion': _currentTriggerQuestionId,
        // Recipients managed via alert_recipients Firestore collection
        'handled': false,
      });
      print('[CheckIn] Safety alert written to Firestore: $alertId');
    } catch (e) {
      print('[CheckIn] Error sending safety alert: $e');
    }
  }

  Future<void> _submitCheckin() async {
    final now = DateTime.now();
    final checkinId = const Uuid().v4();

    final companion = EmaResponsesCompanion(
      id: drift.Value(checkinId),
      participantId: drift.Value(widget.participantId),
      sessionId: drift.Value(widget.sessionId),
      responses: drift.Value(jsonEncode(_responses)),
      startedAt: drift.Value(_startedAt!),
      completedAt: drift.Value(now),
      selfInitiated: drift.Value(widget.selfInitiated),
    );

    await widget.database.insertEmaResponse(companion);
    print('[CheckIn] Saved EMA response: $checkinId (${_responses.length} answers)');

    if (_crisisTriggered) {
      setState(() => _showPostResources = true);
    } else {
      setState(() => _completed = true);
      await Future.delayed(const Duration(seconds: 2));
      if (mounted) Navigator.of(context).pop(true);
    }
  }

  @override
  void dispose() {
    _crisisFlashController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_config == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    if (_completed) {
      return _buildCompletionScreen();
    }

    if (_showPostResources) {
      return _buildPostResourcesScreen();
    }

    if (_safetyConfirmationShowing) {
      return _buildSafetyConfirmationScreen();
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(
          _config!.title,
          style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 18),
        ),
        flexibleSpace: Container(
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              colors: [Color(0xFF39A0EC), Color(0xFF587AE0), Color(0xFF7050E0)],
              stops: [0.0, 0.5, 1.0],
              begin: Alignment.centerLeft,
              end: Alignment.centerRight,
            ),
          ),
        ),
        foregroundColor: Colors.white,
        elevation: 2,
        leading: IconButton(
          icon: const Icon(Icons.close),
          onPressed: _showExitConfirmation,
        ),
        actions: [
          _buildCrisisButton(),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            LinearProgressIndicator(
              value: _visibleQuestions.isEmpty
                  ? 0
                  : (_currentIndex + 1) / _visibleQuestions.length,
              backgroundColor: Colors.grey[200],
              color: const Color(0xFF4A6CF7),
              minHeight: 4,
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 6),
              child: Text(
                '${_currentIndex + 1} of ${_visibleQuestions.length}',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Colors.grey[600],
                    ),
              ),
            ),
            Expanded(
              child: Swiper(
                controller: _swiperController,
                index: _currentIndex,
                itemCount: _visibleQuestions.length,
                viewportFraction: 0.88,
                scale: 0.92,
                loop: false,
                onIndexChanged: (index) {
                  setState(() => _currentIndex = index);
                },
                itemBuilder: (context, index) {
                  return _buildQuestionCard(_visibleQuestions[index]);
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildCrisisButton() {
    if (!_crisisTriggered) {
      return IconButton(
        icon: const Icon(Icons.health_and_safety_outlined),
        onPressed: _showCrisisResources,
        tooltip: 'Crisis Resources',
      );
    }

    return AnimatedBuilder(
      animation: _crisisFlashAnimation,
      builder: (context, child) {
        return Container(
          margin: const EdgeInsets.only(right: 8),
          child: ElevatedButton.icon(
            onPressed: _showCrisisResources,
            icon: const Icon(Icons.warning, size: 18),
            label: const Text('Help', style: TextStyle(fontWeight: FontWeight.bold)),
            style: ElevatedButton.styleFrom(
              backgroundColor: Color.lerp(
                Colors.red[300],
                Colors.red[900],
                _crisisFlashAnimation.value,
              ),
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              minimumSize: Size.zero,
            ),
          ),
        );
      },
    );
  }

  Widget _buildQuestionCard(EmaQuestion question) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 12.0, horizontal: 4.0),
      child: Card(
        elevation: 4,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: BorderSide(color: const Color(0xFF4A6CF7).withOpacity(0.3), width: 2),
        ),
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Flexible(
                flex: 2,
                child: Center(
                  child: Text(
                    question.text,
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(
                          fontSize: question.text.length > 100 ? 16 : 18,
                          height: 1.4,
                        ),
                  ),
                ),
              ),
              const SizedBox(height: 24),
              Flexible(
                flex: 3,
                child: _buildQuestionInterface(question),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildQuestionInterface(EmaQuestion question) {
    switch (question.type) {
      case 'yes_no':
        return _buildYesNo(question);
      case 'slider':
        return _buildSlider(question);
      case 'likert':
        return _buildLikert(question);
      default:
        return Text('Unknown question type: ${question.type}');
    }
  }

  Widget _buildYesNo(EmaQuestion question) {
    final response = _responses[question.id] as bool?;

    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceEvenly,
          children: [
            _buildChoiceButton('Yes', response == true, () {
              _onResponseChanged(question.id, true);
              Future.delayed(const Duration(milliseconds: 300), _advanceToNext);
            }),
            _buildChoiceButton('No', response == false, () {
              _onResponseChanged(question.id, false);
              Future.delayed(const Duration(milliseconds: 300), _advanceToNext);
            }),
          ],
        ),
      ],
    );
  }

  Widget _buildChoiceButton(String label, bool selected, VoidCallback onTap) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        width: 120,
        height: 60,
        decoration: BoxDecoration(
          color: selected ? const Color(0xFF4A6CF7) : Colors.grey[100],
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: selected ? const Color(0xFF4A6CF7) : Colors.grey[300]!,
            width: 2,
          ),
        ),
        alignment: Alignment.center,
        child: Text(
          label,
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w600,
            color: selected ? Colors.white : Colors.black87,
          ),
        ),
      ),
    );
  }

  Widget _buildSlider(EmaQuestion question) {
    final response = _responses[question.id] as double?;
    final hasInteracted = response != null;

    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        SliderTheme(
          data: SliderTheme.of(context).copyWith(
            activeTrackColor:
                hasInteracted ? const Color(0xFF4A6CF7) : Colors.grey[300],
            inactiveTrackColor: Colors.grey[300],
            thumbColor: hasInteracted ? const Color(0xFF4A6CF7) : Colors.grey[400],
            overlayColor: const Color(0xFF4A6CF7).withOpacity(0.2),
            trackHeight: 6,
          ),
          child: Slider(
            value: response ?? ((question.min! + question.max!) / 2),
            min: question.min!,
            max: question.max!,
            onChangeStart: (_) {
              if (!hasInteracted) {
                _onResponseChanged(
                    question.id, (question.min! + question.max!) / 2);
              }
            },
            onChanged: (value) {
              _onResponseChanged(question.id, value);
            },
            onChangeEnd: (value) {
              _onResponseChanged(question.id, value);
              Future.delayed(const Duration(milliseconds: 400), _advanceToNext);
            },
          ),
        ),
        const SizedBox(height: 8),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Flexible(
              child: Text(
                question.minLabel ?? '${question.min!.toInt()}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
            if (hasInteracted)
              Text(
                response!.round().toString(),
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      color: const Color(0xFF4A6CF7),
                      fontWeight: FontWeight.bold,
                    ),
              ),
            Flexible(
              child: Text(
                question.maxLabel ?? '${question.max!.toInt()}',
                style: Theme.of(context).textTheme.bodySmall,
                textAlign: TextAlign.right,
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildLikert(EmaQuestion question) {
    final response = _responses[question.id] as int?;

    return SingleChildScrollView(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: question.options!.map((option) {
          final selected = response == option.value;
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 4.0),
            child: Material(
              color: Colors.transparent,
              child: InkWell(
                borderRadius: BorderRadius.circular(8),
                onTap: () {
                  _onResponseChanged(question.id, option.value);
                  Future.delayed(
                      const Duration(milliseconds: 300), _advanceToNext);
                },
                child: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.symmetric(
                      horizontal: 16, vertical: 14),
                  decoration: BoxDecoration(
                    color: selected
                        ? const Color(0xFF4A6CF7).withOpacity(0.1)
                        : Colors.grey[50],
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(
                      color: selected ? const Color(0xFF4A6CF7) : Colors.grey[300]!,
                      width: selected ? 2 : 1,
                    ),
                  ),
                  child: Text(
                    option.label,
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight:
                          selected ? FontWeight.w600 : FontWeight.normal,
                      color: selected ? const Color(0xFF4A6CF7) : Colors.black87,
                    ),
                  ),
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  // --- Safety Confirmation Screen ---
  Widget _buildSafetyConfirmationScreen() {
    final alert = _config!.safetyAlert;
    final promptText = alert.getConfirmationPrompt(_confirmationCount);

    return Scaffold(
      appBar: AppBar(
        backgroundColor: Colors.red[700],
        foregroundColor: Colors.white,
        title: const Text('Safety Check'),
        automaticallyImplyLeading: false,
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.warning_amber_rounded, size: 64, color: Colors.red[700]),
              const SizedBox(height: 24),
              Text(
                promptText,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleMedium?.copyWith(
                      height: 1.5,
                      fontSize: 17,
                    ),
              ),
              const SizedBox(height: 40),

              // "Yes" button — Red, prominent, deliberate
              SizedBox(
                width: double.infinity,
                height: 56,
                child: ElevatedButton(
                  onPressed: _onSafetyConfirmationYes,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.red[700],
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    elevation: 3,
                  ),
                  child: const Text(
                    'Yes, I am in immediate danger\nof harming myself',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      height: 1.3,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 16),

              // "No" button — Blue outline, deliberate
              SizedBox(
                width: double.infinity,
                height: 56,
                child: OutlinedButton(
                  onPressed: _onSafetyConfirmationNo,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: const Color(0xFF1565C0),
                    side: const BorderSide(color: Color(0xFF1565C0), width: 2),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                  child: const Text(
                    'No, I am not in immediate danger\nof harming myself',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      height: 1.3,
                    ),
                  ),
                ),
              ),

              const SizedBox(height: 32),
              const Divider(),
              const SizedBox(height: 16),
              Text(
                'If you are in a crisis, please report to your nearest Emergency Room, call 988, or text the Crisis Text Line.',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: Colors.grey[700],
                      height: 1.4,
                    ),
              ),
              const SizedBox(height: 12),
              ..._buildResourceButtons(alert.resources),
            ],
          ),
        ),
      ),
    );
  }

  void _showCrisisDialog() {
    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => AlertDialog(
        title: Row(
          children: [
            Icon(Icons.emergency, color: Colors.red[700]),
            const SizedBox(width: 8),
            const Text('Crisis Resources'),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'The study team has been notified and will follow up with you. '
              'If you are in immediate danger, please contact one of these resources now.',
              style: TextStyle(height: 1.4),
            ),
            const SizedBox(height: 16),
            ..._config!.safetyAlert.resources.map((r) => _buildEmergencyResourceButton(
                  r.name,
                  r.action == 'call' ? Icons.phone : Icons.message,
                  Colors.red[600]!,
                  () => _launchResource(r),
                )),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.of(dialogContext).pop();
              // Continue to next question after crisis dialog
              WidgetsBinding.instance.addPostFrameCallback((_) {
                if (!mounted) return;
                if (_currentIndex < _visibleQuestions.length - 1) {
                  _swiperController.next();
                } else {
                  _submitCheckin();
                }
              });
            },
            child: const Text('Continue check-in'),
          ),
        ],
      ),
    );
  }

  Widget _buildEmergencyResourceButton(
      String label, IconData icon, Color color, VoidCallback onTap) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4.0),
      child: ElevatedButton.icon(
        onPressed: onTap,
        icon: Icon(icon),
        label: Text(label),
        style: ElevatedButton.styleFrom(
          backgroundColor: color,
          foregroundColor: Colors.white,
          minimumSize: const Size(double.infinity, 48),
        ),
      ),
    );
  }

  // --- Post Check-in Resources Screen ---
  Widget _buildPostResourcesScreen() {
    return Scaffold(
      appBar: AppBar(
        title: const Text(
          'Check-in Complete',
          style: TextStyle(fontWeight: FontWeight.w600, fontSize: 18),
        ),
        flexibleSpace: Container(
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              colors: [Color(0xFF39A0EC), Color(0xFF587AE0), Color(0xFF7050E0)],
              stops: [0.0, 0.5, 1.0],
              begin: Alignment.centerLeft,
              end: Alignment.centerRight,
            ),
          ),
        ),
        foregroundColor: Colors.white,
        elevation: 2,
        automaticallyImplyLeading: false,
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            children: [
              const SizedBox(height: 16),
              Icon(Icons.check_circle, size: 60, color: Colors.green[600]),
              const SizedBox(height: 16),
              Text(
                'Thank you for completing your check-in.',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 24),
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.red[50],
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: Colors.red[200]!),
                ),
                child: Column(
                  children: [
                    Row(
                      children: [
                        Icon(Icons.info_outline, color: Colors.red[700]),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'Based on your responses, we want to make sure you have access to support resources.',
                            style: TextStyle(
                              color: Colors.red[900],
                              fontWeight: FontWeight.w500,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'If you are in a crisis, please report to your nearest Emergency Room, call 988 (Suicide & Crisis Lifeline), or text the Crisis Text Line.',
                      style: TextStyle(
                        color: Colors.red[800],
                        height: 1.4,
                      ),
                    ),
                    const SizedBox(height: 16),
                    ..._config!.safetyAlert.resources.map((r) =>
                        _buildEmergencyResourceButton(
                          r.name,
                          r.action == 'call' ? Icons.phone : Icons.message,
                          Colors.red[600]!,
                          () => _launchResource(r),
                        )),
                  ],
                ),
              ),
              const Spacer(),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: () {
                    Navigator.of(context).pop(true);
                  },
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF4A6CF7),
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 16),
                  ),
                  child: const Text('Done', style: TextStyle(fontSize: 16)),
                ),
              ),
              const SizedBox(height: 16),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildCompletionScreen() {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.check_circle, size: 80, color: Colors.green[600]),
            const SizedBox(height: 16),
            Text(
              'Check-in complete!',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            const SizedBox(height: 8),
            Text(
              'Thank you for your responses.',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
          ],
        ),
      ),
    );
  }

  // --- Crisis Resources ---
  void _showCrisisResources() {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) => Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                Icon(Icons.health_and_safety, color: Colors.red[700], size: 28),
                const SizedBox(width: 8),
                Text(
                  'Crisis Resources',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
              ],
            ),
            const SizedBox(height: 16),
            const Text(
              'If you are in a crisis, please report to your nearest Emergency Room, call 988 (Suicide & Crisis Lifeline), or text the Crisis Text Line.',
              style: TextStyle(height: 1.4),
            ),
            const SizedBox(height: 16),
            ...(_config?.safetyAlert.resources ?? []).map((r) =>
                _buildEmergencyResourceButton(
                  r.name,
                  r.action == 'call' ? Icons.phone : Icons.message,
                  Colors.red[600]!,
                  () => _launchResource(r),
                )),
            const SizedBox(height: 16),
          ],
        ),
      ),
    );
  }

  List<Widget> _buildResourceButtons(List<CrisisResource> resources) {
    return resources
        .map((resource) => Padding(
              padding: const EdgeInsets.symmetric(vertical: 4.0),
              child: OutlinedButton.icon(
                onPressed: () => _launchResource(resource),
                icon: Icon(
                  resource.action == 'call' ? Icons.phone : Icons.message,
                ),
                label: Text(resource.name),
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size(double.infinity, 48),
                ),
              ),
            ))
        .toList();
  }

  Future<void> _launchResource(CrisisResource resource) async {
    Uri uri;
    if (resource.action == 'call') {
      uri = Uri(scheme: 'tel', path: resource.value);
    } else {
      uri = Uri(scheme: 'sms', path: resource.value, queryParameters: {
        if (resource.message != null) 'body': resource.message!,
      });
    }
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri);
    }
  }

  /// Check if any responses so far exceed safety thresholds
  bool _hasHighRiskResponses() {
    if (_config == null) return false;
    for (final q in _config!.questions) {
      if (_isQuestionAboveThreshold(q)) return true;
    }
    return false;
  }

  /// Send a fallback safety alert when check-in is abandoned with high-risk responses.
  /// This catches cases where the participant exits before reaching the confirmation.
  Future<void> _sendFallbackAlert() async {
    try {
      final alertId = const Uuid().v4();

      // Identify which questions triggered
      final triggerQuestions = <String>[];
      for (final q in _config!.questions) {
        if (_isQuestionAboveThreshold(q)) {
          triggerQuestions.add(q.id);
        }
      }

      await FirebaseFirestore.instance
          .collection('participants')
          .doc(widget.participantId)
          .collection('safety_alerts')
          .doc(alertId)
          .set({
        'participantId': widget.participantId,
        'sessionId': widget.sessionId,
        'responses': _responses.map((k, v) => MapEntry(k, v?.toString())),
        'triggeredAt': FieldValue.serverTimestamp(),
        'alertType': 'incomplete_checkin_fallback',
        'triggerQuestions': triggerQuestions,
        'completedQuestionCount': _currentIndex + 1,
        'totalQuestionCount': _visibleQuestions.length,
        'confirmedDanger': null, // Never reached confirmation
        'handled': false,
        // Recipients managed via alert_recipients Firestore collection
      });
      print('[CheckIn] Fallback safety alert sent for abandoned check-in: $alertId');
    } catch (e) {
      print('[CheckIn] Error sending fallback safety alert: $e');
    }
  }

  /// Save partial check-in responses even when exiting early
  Future<void> _savePartialCheckin() async {
    if (_responses.isEmpty) return;

    final now = DateTime.now();
    final checkinId = const Uuid().v4();

    final companion = EmaResponsesCompanion(
      id: drift.Value(checkinId),
      participantId: drift.Value(widget.participantId),
      sessionId: drift.Value(widget.sessionId),
      responses: drift.Value(jsonEncode({
        ..._responses,
        '_partial': true,
        '_exitedAtQuestion': _currentIndex,
        '_totalQuestions': _visibleQuestions.length,
      })),
      startedAt: drift.Value(_startedAt!),
      completedAt: drift.Value(now),
      selfInitiated: drift.Value(widget.selfInitiated),
    );

    await widget.database.insertEmaResponse(companion);
    print('[CheckIn] Saved partial EMA response: $checkinId (${_responses.length} answers, exited at ${_currentIndex + 1}/${_visibleQuestions.length})');
  }

  void _showExitConfirmation() {
    final hasRisk = _hasHighRiskResponses();

    showDialog(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Exit check-in?'),
        content: Text(
          hasRisk
            ? 'Based on some of your responses, we want to make sure you\'re safe. '
              'If you exit now, your responses will be saved and the study team may follow up.'
            : 'Your responses will not be saved.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Continue check-in'),
          ),
          TextButton(
            onPressed: () async {
              Navigator.of(dialogContext).pop();

              // If high-risk responses were given, save partial data and alert
              if (hasRisk) {
                await _savePartialCheckin();
                await _sendFallbackAlert();
              }

              if (mounted) {
                Navigator.of(this.context).pop(false);
              }
            },
            child: Text(
              'Exit',
              style: TextStyle(color: hasRisk ? Colors.red : null),
            ),
          ),
        ],
      ),
    );
  }
}
