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

/// Page view event
@JsonSerializable()
class PageViewEvent {
  final String pageType; // 'feed', 'post', 'profile', 'search'
  final String? referrerUrl;
  final int loadTimeMs;
  final String? pageTitle;

  PageViewEvent({
    required this.pageType,
    this.referrerUrl,
    required this.loadTimeMs,
    this.pageTitle,
  });

  factory PageViewEvent.fromJson(Map<String, dynamic> json) =>
      _$PageViewEventFromJson(json);

  Map<String, dynamic> toJson() => _$PageViewEventToJson(this);
}

/// Content exposure event
@JsonSerializable()
class ContentExposureEvent {
  final String contentId; // Reddit post ID, Tweet ID, etc.
  final String contentType; // 'post', 'comment', 'tweet', 'ad'
  final int exposureDurationMs;
  final double scrollDepth; // 0.0 to 1.0
  final bool wasExpanded;
  final ContentSnapshot content;

  ContentExposureEvent({
    required this.contentId,
    required this.contentType,
    required this.exposureDurationMs,
    required this.scrollDepth,
    required this.wasExpanded,
    required this.content,
  });

  factory ContentExposureEvent.fromJson(Map<String, dynamic> json) =>
      _$ContentExposureEventFromJson(json);

  Map<String, dynamic> toJson() => _$ContentExposureEventToJson(this);
}

/// Snapshot of content data
@JsonSerializable()
class ContentSnapshot {
  final String? authorUsername;
  final String? authorId;
  final String? textContent;
  final List<String>? mediaUrls;
  final int? upvotes;
  final int? comments;
  final String? subreddit;
  final DateTime? contentTimestamp;

  ContentSnapshot({
    this.authorUsername,
    this.authorId,
    this.textContent,
    this.mediaUrls,
    this.upvotes,
    this.comments,
    this.subreddit,
    this.contentTimestamp,
  });

  factory ContentSnapshot.fromJson(Map<String, dynamic> json) =>
      _$ContentSnapshotFromJson(json);

  Map<String, dynamic> toJson() => _$ContentSnapshotToJson(this);
}

/// Interaction event
@JsonSerializable()
class InteractionEvent {
  final String interactionType; // 'upvote', 'downvote', 'comment', 'share'
  final String targetContentId;
  final String targetContentType;
  final Map<String, dynamic>? interactionData;

  InteractionEvent({
    required this.interactionType,
    required this.targetContentId,
    required this.targetContentType,
    this.interactionData,
  });

  factory InteractionEvent.fromJson(Map<String, dynamic> json) =>
      _$InteractionEventFromJson(json);

  Map<String, dynamic> toJson() => _$InteractionEventToJson(this);
}

/// Scroll event
@JsonSerializable()
class ScrollEvent {
  final double scrollPosition;
  final double viewportHeight;
  final double contentHeight;
  final double scrollVelocity;
  final String scrollDirection; // 'up' or 'down'

  ScrollEvent({
    required this.scrollPosition,
    required this.viewportHeight,
    required this.contentHeight,
    required this.scrollVelocity,
    required this.scrollDirection,
  });

  factory ScrollEvent.fromJson(Map<String, dynamic> json) =>
      _$ScrollEventFromJson(json);

  Map<String, dynamic> toJson() => _$ScrollEventToJson(this);
}
