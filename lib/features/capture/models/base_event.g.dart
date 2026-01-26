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
