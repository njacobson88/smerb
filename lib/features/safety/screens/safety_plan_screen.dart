import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:url_launcher/url_launcher.dart';
import '../../../core/config/environment_config.dart';

/// Displays the participant's personalized crisis safety plan.
/// Data is loaded from Firestore (populated during onboarding from REDCap).
class SafetyPlanScreen extends StatefulWidget {
  final String participantId;

  const SafetyPlanScreen({
    super.key,
    required this.participantId,
  });

  @override
  State<SafetyPlanScreen> createState() => _SafetyPlanScreenState();
}

class _SafetyPlanScreenState extends State<SafetyPlanScreen> {
  Map<String, dynamic>? _safetyPlan;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadSafetyPlan();
  }

  Future<void> _loadSafetyPlan() async {
    try {
      final doc = await FirebaseFirestore.instance
          .collection(EnvConfig.col('participants'))
          .doc(widget.participantId)
          .collection('safety_plan')
          .doc('current')
          .get();

      if (doc.exists) {
        setState(() {
          _safetyPlan = doc.data();
          _loading = false;
        });
      } else {
        setState(() {
          _safetyPlan = null;
          _loading = false;
        });
      }
    } catch (e) {
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text(
          'My Safety Plan',
          style: TextStyle(fontWeight: FontWeight.w600),
        ),
        flexibleSpace: Container(
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              colors: [Color(0xFF39A0EC), Color(0xFF587AE0), Color(0xFF7050E0)],
              begin: Alignment.centerLeft,
              end: Alignment.centerRight,
            ),
          ),
        ),
        foregroundColor: Colors.white,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(child: Text('Error loading safety plan: $_error'))
              : _safetyPlan == null
                  ? _buildDefaultPlan()
                  : _buildPersonalizedPlan(),
    );
  }

  Widget _buildDefaultPlan() {
    // Show default crisis resources when no personalized plan is available
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildCrisisHeader(),
          const SizedBox(height: 24),
          _buildSection(
            'Crisis Resources',
            Icons.emergency,
            Colors.red,
            [
              _buildResourceTile(
                '988 Suicide & Crisis Lifeline',
                'Call or text 988',
                Icons.phone,
                () => _launchUrl('tel:988'),
              ),
              _buildResourceTile(
                'Crisis Text Line',
                'Text HOME to 741741',
                Icons.message,
                () => _launchUrl('sms:741741?body=HOME'),
              ),
              _buildResourceTile(
                '911 Emergency',
                'Call for immediate help',
                Icons.local_hospital,
                () => _launchUrl('tel:911'),
              ),
            ],
          ),
          const SizedBox(height: 20),
          _buildSection(
            'Coping Strategies',
            Icons.psychology,
            Colors.blue,
            [
              _buildInfoTile('Take slow, deep breaths'),
              _buildInfoTile('Go for a walk or change your environment'),
              _buildInfoTile('Listen to music or a calming podcast'),
              _buildInfoTile('Call a friend or family member'),
              _buildInfoTile('Use a mindfulness or meditation app'),
            ],
          ),
          const SizedBox(height: 20),
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.blue.shade50,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: Colors.blue.shade200),
            ),
            child: const Text(
              'Your personalized safety plan will appear here once it has been '
              'completed with the study team during your onboarding visit.',
              style: TextStyle(color: Colors.blueGrey, height: 1.4),
              textAlign: TextAlign.center,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPersonalizedPlan() {
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildCrisisHeader(),
          const SizedBox(height: 24),

          // Step 1: Warning Signs
          if (_safetyPlan!['warningSignal'] != null)
            _buildSection(
              'Step 1: My Warning Signs',
              Icons.warning_amber,
              Colors.orange,
              [_buildInfoTile(_safetyPlan!['warningSignal'])],
            ),

          const SizedBox(height: 16),

          // Step 2: Coping Strategies
          if (_safetyPlan!['copingStrategies'] != null)
            _buildSection(
              'Step 2: My Coping Strategies',
              Icons.psychology,
              Colors.blue,
              (_safetyPlan!['copingStrategies'] is List)
                  ? (_safetyPlan!['copingStrategies'] as List)
                      .map<Widget>((s) => _buildInfoTile(s.toString()))
                      .toList()
                  : [_buildInfoTile(_safetyPlan!['copingStrategies'].toString())],
            ),

          const SizedBox(height: 16),

          // Step 3: People & Places for Distraction
          if (_safetyPlan!['distractionContacts'] != null)
            _buildSection(
              'Step 3: People & Places for Distraction',
              Icons.people,
              Colors.green,
              _buildContactList(_safetyPlan!['distractionContacts']),
            ),

          const SizedBox(height: 16),

          // Step 4: Support Network
          if (_safetyPlan!['supportContacts'] != null)
            _buildSection(
              'Step 4: People I Can Ask for Help',
              Icons.support_agent,
              Colors.teal,
              _buildContactList(_safetyPlan!['supportContacts']),
            ),

          const SizedBox(height: 16),

          // Step 5: Crisis Resources
          _buildSection(
            'Step 5: Crisis Resources',
            Icons.emergency,
            Colors.red,
            [
              _buildResourceTile(
                '988 Suicide & Crisis Lifeline',
                'Call or text 988',
                Icons.phone,
                () => _launchUrl('tel:988'),
              ),
              _buildResourceTile(
                'Crisis Text Line',
                'Text HOME to 741741',
                Icons.message,
                () => _launchUrl('sms:741741?body=HOME'),
              ),
              if (_safetyPlan!['clinicianName'] != null)
                _buildResourceTile(
                  _safetyPlan!['clinicianName'],
                  _safetyPlan!['clinicianPhone'] ?? 'Clinician',
                  Icons.medical_services,
                  _safetyPlan!['clinicianPhone'] != null
                      ? () => _launchUrl('tel:${_safetyPlan!['clinicianPhone']}')
                      : null,
                ),
              _buildResourceTile(
                '911 Emergency',
                'Call for immediate help',
                Icons.local_hospital,
                () => _launchUrl('tel:911'),
              ),
            ],
          ),

          const SizedBox(height: 16),

          // Step 6: Making the Environment Safe
          if (_safetyPlan!['environmentSafety'] != null)
            _buildSection(
              'Step 6: Making My Environment Safe',
              Icons.shield,
              Colors.purple,
              [_buildInfoTile(_safetyPlan!['environmentSafety'].toString())],
            ),

          const SizedBox(height: 16),

          // Reasons to Live
          if (_safetyPlan!['reasonsToLive'] != null)
            _buildSection(
              'My Reasons to Live',
              Icons.favorite,
              Colors.pink,
              (_safetyPlan!['reasonsToLive'] is List)
                  ? (_safetyPlan!['reasonsToLive'] as List)
                      .map<Widget>((r) => _buildInfoTile(r.toString()))
                      .toList()
                  : [_buildInfoTile(_safetyPlan!['reasonsToLive'].toString())],
            ),

          const SizedBox(height: 32),
        ],
      ),
    );
  }

  Widget _buildCrisisHeader() {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [Color(0xFFFFEBEE), Color(0xFFFFF3E0)],
        ),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.red.shade200),
      ),
      child: Row(
        children: [
          Icon(Icons.health_and_safety, color: Colors.red.shade700, size: 32),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'If you are in immediate danger',
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: Colors.red.shade900,
                    fontSize: 16,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  'Call 988 or 911, or go to your nearest emergency room.',
                  style: TextStyle(color: Colors.red.shade800, height: 1.3),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSection(String title, IconData icon, Color color, List<Widget> children) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, color: color, size: 22),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                title,
                style: TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.bold,
                  color: color.withAlpha(200),
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        ...children,
      ],
    );
  }

  Widget _buildInfoTile(String text) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.grey.shade50,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: Colors.grey.shade200),
        ),
        child: Text(text, style: const TextStyle(height: 1.4)),
      ),
    );
  }

  Widget _buildResourceTile(String name, String subtitle, IconData icon, VoidCallback? onTap) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Material(
        color: Colors.transparent,
        child: ListTile(
          leading: Icon(icon, color: Colors.red.shade600),
          title: Text(name, style: const TextStyle(fontWeight: FontWeight.w600)),
          subtitle: Text(subtitle),
          trailing: onTap != null
              ? Icon(Icons.arrow_forward_ios, size: 16, color: Colors.grey.shade400)
              : null,
          onTap: onTap,
          tileColor: Colors.red.shade50,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        ),
      ),
    );
  }

  List<Widget> _buildContactList(dynamic contacts) {
    if (contacts is List) {
      return contacts.map<Widget>((c) {
        if (c is Map) {
          final name = c['name']?.toString() ?? '';
          final phone = c['phone']?.toString();
          return _buildResourceTile(
            name,
            phone ?? 'No phone listed',
            Icons.person,
            phone != null ? () => _launchUrl('tel:$phone') : null,
          );
        }
        return _buildInfoTile(c.toString());
      }).toList();
    }
    return [_buildInfoTile(contacts.toString())];
  }

  Future<void> _launchUrl(String url) async {
    final uri = Uri.parse(url);
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri);
    } else if (mounted) {
      // Fallback: show the number so they can dial manually
      final number = url.replaceAll(RegExp(r'[^0-9+]'), '');
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Unable to open. Please call or text $number directly.'),
          duration: const Duration(seconds: 8),
        ),
      );
    }
  }
}
