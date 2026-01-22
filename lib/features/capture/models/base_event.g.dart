// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'base_event.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

BaseEvent _$BaseEventFromJson(Map<String, dynamic> json) => BaseEvent(
      id: json['id'] as String,
      sessionId: json['sessionId'] as String,
      participantId: json['participantId'] as String,
      timestamp: DateTime.parse(json['timestamp'] as String),
      platform: json['platform'] as String,
      url: json['url'] as String,
      eventType: json['eventType'] as String,
      data: json['data'] as Map<String, dynamic>,
    );

Map<String, dynamic> _$BaseEventToJson(BaseEvent instance) => <String, dynamic>{
      'id': instance.id,
      'sessionId': instance.sessionId,
      'participantId': instance.participantId,
      'timestamp': instance.timestamp.toIso8601String(),
      'platform': instance.platform,
      'url': instance.url,
      'eventType': instance.eventType,
      'data': instance.data,
    };

PageViewEvent _$PageViewEventFromJson(Map<String, dynamic> json) =>
    PageViewEvent(
      pageType: json['pageType'] as String,
      referrerUrl: json['referrerUrl'] as String?,
      loadTimeMs: (json['loadTimeMs'] as num).toInt(),
      pageTitle: json['pageTitle'] as String?,
    );

Map<String, dynamic> _$PageViewEventToJson(PageViewEvent instance) =>
    <String, dynamic>{
      'pageType': instance.pageType,
      'referrerUrl': instance.referrerUrl,
      'loadTimeMs': instance.loadTimeMs,
      'pageTitle': instance.pageTitle,
    };

ContentExposureEvent _$ContentExposureEventFromJson(
        Map<String, dynamic> json) =>
    ContentExposureEvent(
      contentId: json['contentId'] as String,
      contentType: json['contentType'] as String,
      exposureDurationMs: (json['exposureDurationMs'] as num).toInt(),
      scrollDepth: (json['scrollDepth'] as num).toDouble(),
      wasExpanded: json['wasExpanded'] as bool,
      content:
          ContentSnapshot.fromJson(json['content'] as Map<String, dynamic>),
    );

Map<String, dynamic> _$ContentExposureEventToJson(
        ContentExposureEvent instance) =>
    <String, dynamic>{
      'contentId': instance.contentId,
      'contentType': instance.contentType,
      'exposureDurationMs': instance.exposureDurationMs,
      'scrollDepth': instance.scrollDepth,
      'wasExpanded': instance.wasExpanded,
      'content': instance.content,
    };

ContentSnapshot _$ContentSnapshotFromJson(Map<String, dynamic> json) =>
    ContentSnapshot(
      authorUsername: json['authorUsername'] as String?,
      authorId: json['authorId'] as String?,
      textContent: json['textContent'] as String?,
      mediaUrls: (json['mediaUrls'] as List<dynamic>?)
          ?.map((e) => e as String)
          .toList(),
      upvotes: (json['upvotes'] as num?)?.toInt(),
      comments: (json['comments'] as num?)?.toInt(),
      subreddit: json['subreddit'] as String?,
      contentTimestamp: json['contentTimestamp'] == null
          ? null
          : DateTime.parse(json['contentTimestamp'] as String),
    );

Map<String, dynamic> _$ContentSnapshotToJson(ContentSnapshot instance) =>
    <String, dynamic>{
      'authorUsername': instance.authorUsername,
      'authorId': instance.authorId,
      'textContent': instance.textContent,
      'mediaUrls': instance.mediaUrls,
      'upvotes': instance.upvotes,
      'comments': instance.comments,
      'subreddit': instance.subreddit,
      'contentTimestamp': instance.contentTimestamp?.toIso8601String(),
    };

InteractionEvent _$InteractionEventFromJson(Map<String, dynamic> json) =>
    InteractionEvent(
      interactionType: json['interactionType'] as String,
      targetContentId: json['targetContentId'] as String,
      targetContentType: json['targetContentType'] as String,
      interactionData: json['interactionData'] as Map<String, dynamic>?,
    );

Map<String, dynamic> _$InteractionEventToJson(InteractionEvent instance) =>
    <String, dynamic>{
      'interactionType': instance.interactionType,
      'targetContentId': instance.targetContentId,
      'targetContentType': instance.targetContentType,
      'interactionData': instance.interactionData,
    };

ScrollEvent _$ScrollEventFromJson(Map<String, dynamic> json) => ScrollEvent(
      scrollPosition: (json['scrollPosition'] as num).toDouble(),
      viewportHeight: (json['viewportHeight'] as num).toDouble(),
      contentHeight: (json['contentHeight'] as num).toDouble(),
      scrollVelocity: (json['scrollVelocity'] as num).toDouble(),
      scrollDirection: json['scrollDirection'] as String,
    );

Map<String, dynamic> _$ScrollEventToJson(ScrollEvent instance) =>
    <String, dynamic>{
      'scrollPosition': instance.scrollPosition,
      'viewportHeight': instance.viewportHeight,
      'contentHeight': instance.contentHeight,
      'scrollVelocity': instance.scrollVelocity,
      'scrollDirection': instance.scrollDirection,
    };
