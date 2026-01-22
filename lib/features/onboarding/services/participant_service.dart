import 'dart:convert';
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

/// Service for managing participant data
class ParticipantService {
  static const String _participantKey = 'smerb_participant';

  SharedPreferences? _prefs;

  Future<SharedPreferences> get _preferences async {
    _prefs ??= await SharedPreferences.getInstance();
    return _prefs!;
  }

  /// Check if a participant is enrolled
  Future<bool> isEnrolled() async {
    final prefs = await _preferences;
    return prefs.containsKey(_participantKey);
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
