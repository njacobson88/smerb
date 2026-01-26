import 'package:json_annotation/json_annotation.dart';

part 'base_event.g.dart';

/// Base class for all captured events
@JsonSerializable()
class BaseEvent {
  /// Unique event identifier (UUID v4)
  final String id;

  /// Session ID this event belongs to
  final String sessionId;

  /// Participant identifier
  final String participantId;

  /// When the event occurred (UTC)
  final DateTime timestamp;

  /// Platform where event occurred ('reddit', 'twitter', 'other')
  final String platform;

  /// Current page URL
  final String url;

  /// Event type ('page_view', 'scroll', 'content_exposure', 'interaction')
  final String eventType;

  /// Platform-specific event data
  final Map<String, dynamic> data;

  BaseEvent({
    required this.id,
    required this.sessionId,
    required this.participantId,
    required this.timestamp,
    required this.platform,
    required this.url,
    required this.eventType,
    required this.data,
  });

  factory BaseEvent.fromJson(Map<String, dynamic> json) =>
      _$BaseEventFromJson(json);

  Map<String, dynamic> toJson() => _$BaseEventToJson(this);
}
