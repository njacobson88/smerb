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
  final bool isAlreadyInUse;

  ValidationResult({
    required this.isValid,
    this.errorMessage,
    this.isAlreadyInUse = false,
  });

  factory ValidationResult.valid() => ValidationResult(isValid: true);

  factory ValidationResult.invalid(String message) => ValidationResult(
    isValid: false,
    errorMessage: message,
  );

  factory ValidationResult.inUse() => ValidationResult(
    isValid: false,
    errorMessage: 'This participant ID is already enrolled on another device',
    isAlreadyInUse: true,
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

  /// Validate a participant ID against Firebase
  /// Returns ValidationResult indicating if the ID is valid and available
  Future<ValidationResult> validateParticipantId(String participantId) async {
    // Normalize the ID (trim whitespace, ensure proper format)
    final normalizedId = participantId.trim();

    // Basic format validation: must be exactly 9 digits
    if (normalizedId.length != 9) {
      return ValidationResult.invalid('Participant ID must be exactly 9 digits');
    }
    if (!RegExp(r'^\d{9}$').hasMatch(normalizedId)) {
      return ValidationResult.invalid('Participant ID must contain only numbers');
    }

    try {
      // Check if the ID exists in the valid_participants collection
      final doc = await _firestore
          .collection(_validParticipantsCollection)
          .doc(normalizedId)
          .get();

      if (!doc.exists) {
        return ValidationResult.invalid('Invalid participant ID. Please check your ID and try again.');
      }

      // Check if already in use
      final data = doc.data();
      if (data != null && data['inUse'] == true) {
        return ValidationResult.inUse();
      }

      return ValidationResult.valid();
    } catch (e) {
      print('[ParticipantService] Error validating participant ID: $e');
      return ValidationResult.invalid('Unable to verify participant ID. Please check your internet connection.');
    }
  }

  /// Mark a participant ID as in-use in Firebase
  Future<bool> markParticipantIdAsInUse({
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
        'enrolledAt': FieldValue.serverTimestamp(),
        'enrolledByVisitorId': visitorId,
        'enrolledByDeviceInfo': deviceInfo,
      });
      print('[ParticipantService] Marked participant ID as in-use: $participantId');
      return true;
    } catch (e) {
      print('[ParticipantService] Error marking participant ID as in-use: $e');
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
      enrolledAt: DateTime.now().toUtc(),
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
      redditLoginAt: loggedIn ? DateTime.now().toUtc() : null,
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
      twitterLoginAt: loggedIn ? DateTime.now().toUtc() : null,
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
