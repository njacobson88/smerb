import 'dart:convert';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Model for participant data
class Participant {
  final String id;
  final String visitorId;
  final DateTime enrolledAt;
  final bool redditLoggedIn;
  final bool twitterLoggedIn;
  final DateTime? redditLoginAt;
  final DateTime? twitterLoginAt;
  final String? redditUsername;
  final String? twitterUsername;

  Participant({
    required this.id,
    required this.visitorId,
    required this.enrolledAt,
    this.redditLoggedIn = false,
    this.twitterLoggedIn = false,
    this.redditLoginAt,
    this.twitterLoginAt,
    this.redditUsername,
    this.twitterUsername,
  });

  Map<String, dynamic> toJson() => {
    'id': id,
    'visitorId': visitorId,
    'enrolledAt': enrolledAt.toIso8601String(),
    'redditLoggedIn': redditLoggedIn,
    'twitterLoggedIn': twitterLoggedIn,
    'redditLoginAt': redditLoginAt?.toIso8601String(),
    'twitterLoginAt': twitterLoginAt?.toIso8601String(),
    'redditUsername': redditUsername,
    'twitterUsername': twitterUsername,
  };

  factory Participant.fromJson(Map<String, dynamic> json) => Participant(
    id: json['id'] as String,
    visitorId: json['visitorId'] as String,
    enrolledAt: DateTime.parse(json['enrolledAt'] as String),
    redditLoggedIn: json['redditLoggedIn'] as bool? ?? false,
    twitterLoggedIn: json['twitterLoggedIn'] as bool? ?? false,
    redditLoginAt: json['redditLoginAt'] != null
        ? DateTime.parse(json['redditLoginAt'] as String)
        : null,
    twitterLoginAt: json['twitterLoginAt'] != null
        ? DateTime.parse(json['twitterLoginAt'] as String)
        : null,
    redditUsername: json['redditUsername'] as String?,
    twitterUsername: json['twitterUsername'] as String?,
  );

  Participant copyWith({
    String? id,
    String? visitorId,
    DateTime? enrolledAt,
    bool? redditLoggedIn,
    bool? twitterLoggedIn,
    DateTime? redditLoginAt,
    DateTime? twitterLoginAt,
    String? redditUsername,
    String? twitterUsername,
  }) => Participant(
    id: id ?? this.id,
    visitorId: visitorId ?? this.visitorId,
    enrolledAt: enrolledAt ?? this.enrolledAt,
    redditLoggedIn: redditLoggedIn ?? this.redditLoggedIn,
    twitterLoggedIn: twitterLoggedIn ?? this.twitterLoggedIn,
    redditLoginAt: redditLoginAt ?? this.redditLoginAt,
    twitterLoginAt: twitterLoginAt ?? this.twitterLoginAt,
    redditUsername: redditUsername ?? this.redditUsername,
    twitterUsername: twitterUsername ?? this.twitterUsername,
  );
}

/// Result of participant ID validation
class ValidationResult {
  final bool isValid;
  final String? errorMessage;

  ValidationResult({
    required this.isValid,
    this.errorMessage,
  });

  factory ValidationResult.valid() => ValidationResult(isValid: true);

  factory ValidationResult.invalid(String message) => ValidationResult(
    isValid: false,
    errorMessage: message,
  );
}

/// Service for managing participant data
class ParticipantService {
  static const String _participantKey = 'smerb_participant';
  static const String _validParticipantsCollection = 'valid_participants';

  SharedPreferences? _prefs;
  final FirebaseFirestore _firestore;

  ParticipantService({FirebaseFirestore? firestore})
      : _firestore = firestore ?? FirebaseFirestore.instance;

  Future<SharedPreferences> get _preferences async {
    _prefs ??= await SharedPreferences.getInstance();
    return _prefs!;
  }

  /// Check if a participant is enrolled
  Future<bool> isEnrolled() async {
    final prefs = await _preferences;
    return prefs.containsKey(_participantKey);
  }

  /// Check if an ID matches the test user format (test1-test1000)
  static bool isTestUserId(String id) {
    final testMatch = RegExp(r'^test(\d+)$').firstMatch(id.toLowerCase());
    if (testMatch == null) return false;
    final num = int.tryParse(testMatch.group(1)!) ?? 0;
    return num >= 1 && num <= 1000;
  }

  /// Check if an ID matches the production format (9 digits)
  static bool isProductionId(String id) {
    return RegExp(r'^\d{9}$').hasMatch(id);
  }

  /// Validate participant ID format (local validation before Firebase check)
  static String? validateIdFormat(String? value) {
    if (value == null || value.trim().isEmpty) {
      return 'Please enter your Participant ID';
    }
    final trimmed = value.trim();

    // Accept test user format (test1-test1000) or 9-digit numeric
    if (isTestUserId(trimmed) || isProductionId(trimmed)) {
      return null; // Valid format
    }

    return 'Invalid format. Enter a 9-digit ID or test ID (test1-test1000)';
  }

  /// Validate a participant ID against Firebase
  /// Returns ValidationResult indicating if the ID is valid and available
  Future<ValidationResult> validateParticipantId(String participantId) async {
    // Normalize the ID (trim whitespace)
    final normalizedId = participantId.trim().toLowerCase();

    // Basic format validation: must be test user or 9-digit numeric
    if (!isTestUserId(normalizedId) && !isProductionId(participantId.trim())) {
      return ValidationResult.invalid('Invalid format. Enter a 9-digit ID or test ID (test1-test1000)');
    }

    // Use the appropriate ID format for lookup
    final lookupId = isTestUserId(normalizedId) ? normalizedId : participantId.trim();

    try {
      // Check if the ID exists in the valid_participants collection
      final doc = await _firestore
          .collection(_validParticipantsCollection)
          .doc(lookupId)
          .get();

      if (!doc.exists) {
        return ValidationResult.invalid('Invalid participant ID. Please check your ID and try again.');
      }

      return ValidationResult.valid();
    } catch (e) {
      print('[ParticipantService] Error validating participant ID: $e');
      return ValidationResult.invalid('Unable to verify participant ID. Please check your internet connection.');
    }
  }

  /// Register a device enrollment for this participant ID in Firebase
  Future<bool> registerDeviceEnrollment({
    required String participantId,
    required String visitorId,
    Map<String, dynamic>? deviceInfo,
  }) async {
    try {
      await _firestore
          .collection(_validParticipantsCollection)
          .doc(participantId)
          .update({
        'inUse': true,
        'lastEnrolledAt': FieldValue.serverTimestamp(),
        'devices': FieldValue.arrayUnion([
          {
            'visitorId': visitorId,
            'enrolledAt': DateTime.now().toIso8601String(),  // Local time
            ...?deviceInfo,
          }
        ]),
      });
      print('[ParticipantService] Registered device for participant: $participantId');
      return true;
    } catch (e) {
      print('[ParticipantService] Error registering device enrollment: $e');
      return false;
    }
  }

  /// Get the current participant
  Future<Participant?> getParticipant() async {
    final prefs = await _preferences;
    final json = prefs.getString(_participantKey);
    if (json == null) return null;

    try {
      return Participant.fromJson(jsonDecode(json) as Map<String, dynamic>);
    } catch (e) {
      print('[ParticipantService] Error parsing participant: $e');
      return null;
    }
  }

  /// Enroll a new participant
  Future<Participant> enroll({
    required String participantId,
    required String visitorId,
  }) async {
    final participant = Participant(
      id: participantId,
      visitorId: visitorId,
      enrolledAt: DateTime.now(),  // Local time for participant
    );

    await _saveParticipant(participant);
    print('[ParticipantService] Enrolled participant: $participantId');
    return participant;
  }

  /// Update Reddit login status
  Future<Participant?> updateRedditLogin({
    required bool loggedIn,
    String? username,
  }) async {
    final participant = await getParticipant();
    if (participant == null) return null;

    final updated = participant.copyWith(
      redditLoggedIn: loggedIn,
      redditLoginAt: loggedIn ? DateTime.now() : null,  // Local time
      redditUsername: username,
    );

    await _saveParticipant(updated);
    print('[ParticipantService] Updated Reddit login: $loggedIn, user: $username');
    return updated;
  }

  /// Update Twitter login status
  Future<Participant?> updateTwitterLogin({
    required bool loggedIn,
    String? username,
  }) async {
    final participant = await getParticipant();
    if (participant == null) return null;

    final updated = participant.copyWith(
      twitterLoggedIn: loggedIn,
      twitterLoginAt: loggedIn ? DateTime.now() : null,  // Local time
      twitterUsername: username,
    );

    await _saveParticipant(updated);
    print('[ParticipantService] Updated Twitter login: $loggedIn, user: $username');
    return updated;
  }

  /// Save participant to storage
  Future<void> _saveParticipant(Participant participant) async {
    final prefs = await _preferences;
    await prefs.setString(_participantKey, jsonEncode(participant.toJson()));
  }

  /// Clear participant data (for testing/logout)
  Future<void> clearParticipant() async {
    final prefs = await _preferences;
    await prefs.remove(_participantKey);
    print('[ParticipantService] Cleared participant data');
  }

  /// Get participant ID (convenience method)
  Future<String?> getParticipantId() async {
    final participant = await getParticipant();
    return participant?.id;
  }
}
