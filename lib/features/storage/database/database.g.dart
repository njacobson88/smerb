// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'database.dart';

// ignore_for_file: type=lint
class $EventsTable extends Events with TableInfo<$EventsTable, Event> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $EventsTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
      'id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _sessionIdMeta =
      const VerificationMeta('sessionId');
  @override
  late final GeneratedColumn<String> sessionId = GeneratedColumn<String>(
      'session_id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _participantIdMeta =
      const VerificationMeta('participantId');
  @override
  late final GeneratedColumn<String> participantId = GeneratedColumn<String>(
      'participant_id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _eventTypeMeta =
      const VerificationMeta('eventType');
  @override
  late final GeneratedColumn<String> eventType = GeneratedColumn<String>(
      'event_type', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _timestampMeta =
      const VerificationMeta('timestamp');
  @override
  late final GeneratedColumn<DateTime> timestamp = GeneratedColumn<DateTime>(
      'timestamp', aliasedName, false,
      type: DriftSqlType.dateTime, requiredDuringInsert: true);
  static const VerificationMeta _platformMeta =
      const VerificationMeta('platform');
  @override
  late final GeneratedColumn<String> platform = GeneratedColumn<String>(
      'platform', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _urlMeta = const VerificationMeta('url');
  @override
  late final GeneratedColumn<String> url = GeneratedColumn<String>(
      'url', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  static const VerificationMeta _dataMeta = const VerificationMeta('data');
  @override
  late final GeneratedColumn<String> data = GeneratedColumn<String>(
      'data', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _syncedMeta = const VerificationMeta('synced');
  @override
  late final GeneratedColumn<bool> synced = GeneratedColumn<bool>(
      'synced', aliasedName, false,
      type: DriftSqlType.bool,
      requiredDuringInsert: false,
      defaultConstraints:
          GeneratedColumn.constraintIsAlways('CHECK ("synced" IN (0, 1))'),
      defaultValue: const Constant(false));
  static const VerificationMeta _createdAtMeta =
      const VerificationMeta('createdAt');
  @override
  late final GeneratedColumn<DateTime> createdAt = GeneratedColumn<DateTime>(
      'created_at', aliasedName, false,
      type: DriftSqlType.dateTime,
      requiredDuringInsert: false,
      defaultValue: currentDateAndTime);
  @override
  List<GeneratedColumn> get $columns => [
        id,
        sessionId,
        participantId,
        eventType,
        timestamp,
        platform,
        url,
        data,
        synced,
        createdAt
      ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'events';
  @override
  VerificationContext validateIntegrity(Insertable<Event> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('session_id')) {
      context.handle(_sessionIdMeta,
          sessionId.isAcceptableOrUnknown(data['session_id']!, _sessionIdMeta));
    } else if (isInserting) {
      context.missing(_sessionIdMeta);
    }
    if (data.containsKey('participant_id')) {
      context.handle(
          _participantIdMeta,
          participantId.isAcceptableOrUnknown(
              data['participant_id']!, _participantIdMeta));
    } else if (isInserting) {
      context.missing(_participantIdMeta);
    }
    if (data.containsKey('event_type')) {
      context.handle(_eventTypeMeta,
          eventType.isAcceptableOrUnknown(data['event_type']!, _eventTypeMeta));
    } else if (isInserting) {
      context.missing(_eventTypeMeta);
    }
    if (data.containsKey('timestamp')) {
      context.handle(_timestampMeta,
          timestamp.isAcceptableOrUnknown(data['timestamp']!, _timestampMeta));
    } else if (isInserting) {
      context.missing(_timestampMeta);
    }
    if (data.containsKey('platform')) {
      context.handle(_platformMeta,
          platform.isAcceptableOrUnknown(data['platform']!, _platformMeta));
    } else if (isInserting) {
      context.missing(_platformMeta);
    }
    if (data.containsKey('url')) {
      context.handle(
          _urlMeta, url.isAcceptableOrUnknown(data['url']!, _urlMeta));
    }
    if (data.containsKey('data')) {
      context.handle(
          _dataMeta, this.data.isAcceptableOrUnknown(data['data']!, _dataMeta));
    } else if (isInserting) {
      context.missing(_dataMeta);
    }
    if (data.containsKey('synced')) {
      context.handle(_syncedMeta,
          synced.isAcceptableOrUnknown(data['synced']!, _syncedMeta));
    }
    if (data.containsKey('created_at')) {
      context.handle(_createdAtMeta,
          createdAt.isAcceptableOrUnknown(data['created_at']!, _createdAtMeta));
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  Event map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return Event(
      id: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}id'])!,
      sessionId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}session_id'])!,
      participantId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}participant_id'])!,
      eventType: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}event_type'])!,
      timestamp: attachedDatabase.typeMapping
          .read(DriftSqlType.dateTime, data['${effectivePrefix}timestamp'])!,
      platform: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}platform'])!,
      url: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}url']),
      data: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}data'])!,
      synced: attachedDatabase.typeMapping
          .read(DriftSqlType.bool, data['${effectivePrefix}synced'])!,
      createdAt: attachedDatabase.typeMapping
          .read(DriftSqlType.dateTime, data['${effectivePrefix}created_at'])!,
    );
  }

  @override
  $EventsTable createAlias(String alias) {
    return $EventsTable(attachedDatabase, alias);
  }
}

class Event extends DataClass implements Insertable<Event> {
  final String id;
  final String sessionId;
  final String participantId;
  final String eventType;
  final DateTime timestamp;
  final String platform;
  final String? url;
  final String data;
  final bool synced;
  final DateTime createdAt;
  const Event(
      {required this.id,
      required this.sessionId,
      required this.participantId,
      required this.eventType,
      required this.timestamp,
      required this.platform,
      this.url,
      required this.data,
      required this.synced,
      required this.createdAt});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['session_id'] = Variable<String>(sessionId);
    map['participant_id'] = Variable<String>(participantId);
    map['event_type'] = Variable<String>(eventType);
    map['timestamp'] = Variable<DateTime>(timestamp);
    map['platform'] = Variable<String>(platform);
    if (!nullToAbsent || url != null) {
      map['url'] = Variable<String>(url);
    }
    map['data'] = Variable<String>(data);
    map['synced'] = Variable<bool>(synced);
    map['created_at'] = Variable<DateTime>(createdAt);
    return map;
  }

  EventsCompanion toCompanion(bool nullToAbsent) {
    return EventsCompanion(
      id: Value(id),
      sessionId: Value(sessionId),
      participantId: Value(participantId),
      eventType: Value(eventType),
      timestamp: Value(timestamp),
      platform: Value(platform),
      url: url == null && nullToAbsent ? const Value.absent() : Value(url),
      data: Value(data),
      synced: Value(synced),
      createdAt: Value(createdAt),
    );
  }

  factory Event.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return Event(
      id: serializer.fromJson<String>(json['id']),
      sessionId: serializer.fromJson<String>(json['sessionId']),
      participantId: serializer.fromJson<String>(json['participantId']),
      eventType: serializer.fromJson<String>(json['eventType']),
      timestamp: serializer.fromJson<DateTime>(json['timestamp']),
      platform: serializer.fromJson<String>(json['platform']),
      url: serializer.fromJson<String?>(json['url']),
      data: serializer.fromJson<String>(json['data']),
      synced: serializer.fromJson<bool>(json['synced']),
      createdAt: serializer.fromJson<DateTime>(json['createdAt']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'sessionId': serializer.toJson<String>(sessionId),
      'participantId': serializer.toJson<String>(participantId),
      'eventType': serializer.toJson<String>(eventType),
      'timestamp': serializer.toJson<DateTime>(timestamp),
      'platform': serializer.toJson<String>(platform),
      'url': serializer.toJson<String?>(url),
      'data': serializer.toJson<String>(data),
      'synced': serializer.toJson<bool>(synced),
      'createdAt': serializer.toJson<DateTime>(createdAt),
    };
  }

  Event copyWith(
          {String? id,
          String? sessionId,
          String? participantId,
          String? eventType,
          DateTime? timestamp,
          String? platform,
          Value<String?> url = const Value.absent(),
          String? data,
          bool? synced,
          DateTime? createdAt}) =>
      Event(
        id: id ?? this.id,
        sessionId: sessionId ?? this.sessionId,
        participantId: participantId ?? this.participantId,
        eventType: eventType ?? this.eventType,
        timestamp: timestamp ?? this.timestamp,
        platform: platform ?? this.platform,
        url: url.present ? url.value : this.url,
        data: data ?? this.data,
        synced: synced ?? this.synced,
        createdAt: createdAt ?? this.createdAt,
      );
  @override
  String toString() {
    return (StringBuffer('Event(')
          ..write('id: $id, ')
          ..write('sessionId: $sessionId, ')
          ..write('participantId: $participantId, ')
          ..write('eventType: $eventType, ')
          ..write('timestamp: $timestamp, ')
          ..write('platform: $platform, ')
          ..write('url: $url, ')
          ..write('data: $data, ')
          ..write('synced: $synced, ')
          ..write('createdAt: $createdAt')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(id, sessionId, participantId, eventType,
      timestamp, platform, url, data, synced, createdAt);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is Event &&
          other.id == this.id &&
          other.sessionId == this.sessionId &&
          other.participantId == this.participantId &&
          other.eventType == this.eventType &&
          other.timestamp == this.timestamp &&
          other.platform == this.platform &&
          other.url == this.url &&
          other.data == this.data &&
          other.synced == this.synced &&
          other.createdAt == this.createdAt);
}

class EventsCompanion extends UpdateCompanion<Event> {
  final Value<String> id;
  final Value<String> sessionId;
  final Value<String> participantId;
  final Value<String> eventType;
  final Value<DateTime> timestamp;
  final Value<String> platform;
  final Value<String?> url;
  final Value<String> data;
  final Value<bool> synced;
  final Value<DateTime> createdAt;
  final Value<int> rowid;
  const EventsCompanion({
    this.id = const Value.absent(),
    this.sessionId = const Value.absent(),
    this.participantId = const Value.absent(),
    this.eventType = const Value.absent(),
    this.timestamp = const Value.absent(),
    this.platform = const Value.absent(),
    this.url = const Value.absent(),
    this.data = const Value.absent(),
    this.synced = const Value.absent(),
    this.createdAt = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  EventsCompanion.insert({
    required String id,
    required String sessionId,
    required String participantId,
    required String eventType,
    required DateTime timestamp,
    required String platform,
    this.url = const Value.absent(),
    required String data,
    this.synced = const Value.absent(),
    this.createdAt = const Value.absent(),
    this.rowid = const Value.absent(),
  })  : id = Value(id),
        sessionId = Value(sessionId),
        participantId = Value(participantId),
        eventType = Value(eventType),
        timestamp = Value(timestamp),
        platform = Value(platform),
        data = Value(data);
  static Insertable<Event> custom({
    Expression<String>? id,
    Expression<String>? sessionId,
    Expression<String>? participantId,
    Expression<String>? eventType,
    Expression<DateTime>? timestamp,
    Expression<String>? platform,
    Expression<String>? url,
    Expression<String>? data,
    Expression<bool>? synced,
    Expression<DateTime>? createdAt,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (sessionId != null) 'session_id': sessionId,
      if (participantId != null) 'participant_id': participantId,
      if (eventType != null) 'event_type': eventType,
      if (timestamp != null) 'timestamp': timestamp,
      if (platform != null) 'platform': platform,
      if (url != null) 'url': url,
      if (data != null) 'data': data,
      if (synced != null) 'synced': synced,
      if (createdAt != null) 'created_at': createdAt,
      if (rowid != null) 'rowid': rowid,
    });
  }

  EventsCompanion copyWith(
      {Value<String>? id,
      Value<String>? sessionId,
      Value<String>? participantId,
      Value<String>? eventType,
      Value<DateTime>? timestamp,
      Value<String>? platform,
      Value<String?>? url,
      Value<String>? data,
      Value<bool>? synced,
      Value<DateTime>? createdAt,
      Value<int>? rowid}) {
    return EventsCompanion(
      id: id ?? this.id,
      sessionId: sessionId ?? this.sessionId,
      participantId: participantId ?? this.participantId,
      eventType: eventType ?? this.eventType,
      timestamp: timestamp ?? this.timestamp,
      platform: platform ?? this.platform,
      url: url ?? this.url,
      data: data ?? this.data,
      synced: synced ?? this.synced,
      createdAt: createdAt ?? this.createdAt,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (sessionId.present) {
      map['session_id'] = Variable<String>(sessionId.value);
    }
    if (participantId.present) {
      map['participant_id'] = Variable<String>(participantId.value);
    }
    if (eventType.present) {
      map['event_type'] = Variable<String>(eventType.value);
    }
    if (timestamp.present) {
      map['timestamp'] = Variable<DateTime>(timestamp.value);
    }
    if (platform.present) {
      map['platform'] = Variable<String>(platform.value);
    }
    if (url.present) {
      map['url'] = Variable<String>(url.value);
    }
    if (data.present) {
      map['data'] = Variable<String>(data.value);
    }
    if (synced.present) {
      map['synced'] = Variable<bool>(synced.value);
    }
    if (createdAt.present) {
      map['created_at'] = Variable<DateTime>(createdAt.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('EventsCompanion(')
          ..write('id: $id, ')
          ..write('sessionId: $sessionId, ')
          ..write('participantId: $participantId, ')
          ..write('eventType: $eventType, ')
          ..write('timestamp: $timestamp, ')
          ..write('platform: $platform, ')
          ..write('url: $url, ')
          ..write('data: $data, ')
          ..write('synced: $synced, ')
          ..write('createdAt: $createdAt, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $SessionsTable extends Sessions with TableInfo<$SessionsTable, Session> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $SessionsTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
      'id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _participantIdMeta =
      const VerificationMeta('participantId');
  @override
  late final GeneratedColumn<String> participantId = GeneratedColumn<String>(
      'participant_id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _startedAtMeta =
      const VerificationMeta('startedAt');
  @override
  late final GeneratedColumn<DateTime> startedAt = GeneratedColumn<DateTime>(
      'started_at', aliasedName, false,
      type: DriftSqlType.dateTime, requiredDuringInsert: true);
  static const VerificationMeta _endedAtMeta =
      const VerificationMeta('endedAt');
  @override
  late final GeneratedColumn<DateTime> endedAt = GeneratedColumn<DateTime>(
      'ended_at', aliasedName, true,
      type: DriftSqlType.dateTime, requiredDuringInsert: false);
  static const VerificationMeta _eventCountMeta =
      const VerificationMeta('eventCount');
  @override
  late final GeneratedColumn<int> eventCount = GeneratedColumn<int>(
      'event_count', aliasedName, false,
      type: DriftSqlType.int,
      requiredDuringInsert: false,
      defaultValue: const Constant(0));
  static const VerificationMeta _deviceInfoMeta =
      const VerificationMeta('deviceInfo');
  @override
  late final GeneratedColumn<String> deviceInfo = GeneratedColumn<String>(
      'device_info', aliasedName, true,
      type: DriftSqlType.string, requiredDuringInsert: false);
  @override
  List<GeneratedColumn> get $columns =>
      [id, participantId, startedAt, endedAt, eventCount, deviceInfo];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'sessions';
  @override
  VerificationContext validateIntegrity(Insertable<Session> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('participant_id')) {
      context.handle(
          _participantIdMeta,
          participantId.isAcceptableOrUnknown(
              data['participant_id']!, _participantIdMeta));
    } else if (isInserting) {
      context.missing(_participantIdMeta);
    }
    if (data.containsKey('started_at')) {
      context.handle(_startedAtMeta,
          startedAt.isAcceptableOrUnknown(data['started_at']!, _startedAtMeta));
    } else if (isInserting) {
      context.missing(_startedAtMeta);
    }
    if (data.containsKey('ended_at')) {
      context.handle(_endedAtMeta,
          endedAt.isAcceptableOrUnknown(data['ended_at']!, _endedAtMeta));
    }
    if (data.containsKey('event_count')) {
      context.handle(
          _eventCountMeta,
          eventCount.isAcceptableOrUnknown(
              data['event_count']!, _eventCountMeta));
    }
    if (data.containsKey('device_info')) {
      context.handle(
          _deviceInfoMeta,
          deviceInfo.isAcceptableOrUnknown(
              data['device_info']!, _deviceInfoMeta));
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  Session map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return Session(
      id: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}id'])!,
      participantId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}participant_id'])!,
      startedAt: attachedDatabase.typeMapping
          .read(DriftSqlType.dateTime, data['${effectivePrefix}started_at'])!,
      endedAt: attachedDatabase.typeMapping
          .read(DriftSqlType.dateTime, data['${effectivePrefix}ended_at']),
      eventCount: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}event_count'])!,
      deviceInfo: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}device_info']),
    );
  }

  @override
  $SessionsTable createAlias(String alias) {
    return $SessionsTable(attachedDatabase, alias);
  }
}

class Session extends DataClass implements Insertable<Session> {
  final String id;
  final String participantId;
  final DateTime startedAt;
  final DateTime? endedAt;
  final int eventCount;
  final String? deviceInfo;
  const Session(
      {required this.id,
      required this.participantId,
      required this.startedAt,
      this.endedAt,
      required this.eventCount,
      this.deviceInfo});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['participant_id'] = Variable<String>(participantId);
    map['started_at'] = Variable<DateTime>(startedAt);
    if (!nullToAbsent || endedAt != null) {
      map['ended_at'] = Variable<DateTime>(endedAt);
    }
    map['event_count'] = Variable<int>(eventCount);
    if (!nullToAbsent || deviceInfo != null) {
      map['device_info'] = Variable<String>(deviceInfo);
    }
    return map;
  }

  SessionsCompanion toCompanion(bool nullToAbsent) {
    return SessionsCompanion(
      id: Value(id),
      participantId: Value(participantId),
      startedAt: Value(startedAt),
      endedAt: endedAt == null && nullToAbsent
          ? const Value.absent()
          : Value(endedAt),
      eventCount: Value(eventCount),
      deviceInfo: deviceInfo == null && nullToAbsent
          ? const Value.absent()
          : Value(deviceInfo),
    );
  }

  factory Session.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return Session(
      id: serializer.fromJson<String>(json['id']),
      participantId: serializer.fromJson<String>(json['participantId']),
      startedAt: serializer.fromJson<DateTime>(json['startedAt']),
      endedAt: serializer.fromJson<DateTime?>(json['endedAt']),
      eventCount: serializer.fromJson<int>(json['eventCount']),
      deviceInfo: serializer.fromJson<String?>(json['deviceInfo']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'participantId': serializer.toJson<String>(participantId),
      'startedAt': serializer.toJson<DateTime>(startedAt),
      'endedAt': serializer.toJson<DateTime?>(endedAt),
      'eventCount': serializer.toJson<int>(eventCount),
      'deviceInfo': serializer.toJson<String?>(deviceInfo),
    };
  }

  Session copyWith(
          {String? id,
          String? participantId,
          DateTime? startedAt,
          Value<DateTime?> endedAt = const Value.absent(),
          int? eventCount,
          Value<String?> deviceInfo = const Value.absent()}) =>
      Session(
        id: id ?? this.id,
        participantId: participantId ?? this.participantId,
        startedAt: startedAt ?? this.startedAt,
        endedAt: endedAt.present ? endedAt.value : this.endedAt,
        eventCount: eventCount ?? this.eventCount,
        deviceInfo: deviceInfo.present ? deviceInfo.value : this.deviceInfo,
      );
  @override
  String toString() {
    return (StringBuffer('Session(')
          ..write('id: $id, ')
          ..write('participantId: $participantId, ')
          ..write('startedAt: $startedAt, ')
          ..write('endedAt: $endedAt, ')
          ..write('eventCount: $eventCount, ')
          ..write('deviceInfo: $deviceInfo')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(
      id, participantId, startedAt, endedAt, eventCount, deviceInfo);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is Session &&
          other.id == this.id &&
          other.participantId == this.participantId &&
          other.startedAt == this.startedAt &&
          other.endedAt == this.endedAt &&
          other.eventCount == this.eventCount &&
          other.deviceInfo == this.deviceInfo);
}

class SessionsCompanion extends UpdateCompanion<Session> {
  final Value<String> id;
  final Value<String> participantId;
  final Value<DateTime> startedAt;
  final Value<DateTime?> endedAt;
  final Value<int> eventCount;
  final Value<String?> deviceInfo;
  final Value<int> rowid;
  const SessionsCompanion({
    this.id = const Value.absent(),
    this.participantId = const Value.absent(),
    this.startedAt = const Value.absent(),
    this.endedAt = const Value.absent(),
    this.eventCount = const Value.absent(),
    this.deviceInfo = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  SessionsCompanion.insert({
    required String id,
    required String participantId,
    required DateTime startedAt,
    this.endedAt = const Value.absent(),
    this.eventCount = const Value.absent(),
    this.deviceInfo = const Value.absent(),
    this.rowid = const Value.absent(),
  })  : id = Value(id),
        participantId = Value(participantId),
        startedAt = Value(startedAt);
  static Insertable<Session> custom({
    Expression<String>? id,
    Expression<String>? participantId,
    Expression<DateTime>? startedAt,
    Expression<DateTime>? endedAt,
    Expression<int>? eventCount,
    Expression<String>? deviceInfo,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (participantId != null) 'participant_id': participantId,
      if (startedAt != null) 'started_at': startedAt,
      if (endedAt != null) 'ended_at': endedAt,
      if (eventCount != null) 'event_count': eventCount,
      if (deviceInfo != null) 'device_info': deviceInfo,
      if (rowid != null) 'rowid': rowid,
    });
  }

  SessionsCompanion copyWith(
      {Value<String>? id,
      Value<String>? participantId,
      Value<DateTime>? startedAt,
      Value<DateTime?>? endedAt,
      Value<int>? eventCount,
      Value<String?>? deviceInfo,
      Value<int>? rowid}) {
    return SessionsCompanion(
      id: id ?? this.id,
      participantId: participantId ?? this.participantId,
      startedAt: startedAt ?? this.startedAt,
      endedAt: endedAt ?? this.endedAt,
      eventCount: eventCount ?? this.eventCount,
      deviceInfo: deviceInfo ?? this.deviceInfo,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (participantId.present) {
      map['participant_id'] = Variable<String>(participantId.value);
    }
    if (startedAt.present) {
      map['started_at'] = Variable<DateTime>(startedAt.value);
    }
    if (endedAt.present) {
      map['ended_at'] = Variable<DateTime>(endedAt.value);
    }
    if (eventCount.present) {
      map['event_count'] = Variable<int>(eventCount.value);
    }
    if (deviceInfo.present) {
      map['device_info'] = Variable<String>(deviceInfo.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('SessionsCompanion(')
          ..write('id: $id, ')
          ..write('participantId: $participantId, ')
          ..write('startedAt: $startedAt, ')
          ..write('endedAt: $endedAt, ')
          ..write('eventCount: $eventCount, ')
          ..write('deviceInfo: $deviceInfo, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

class $OcrResultsTable extends OcrResults
    with TableInfo<$OcrResultsTable, OcrResult> {
  @override
  final GeneratedDatabase attachedDatabase;
  final String? _alias;
  $OcrResultsTable(this.attachedDatabase, [this._alias]);
  static const VerificationMeta _idMeta = const VerificationMeta('id');
  @override
  late final GeneratedColumn<String> id = GeneratedColumn<String>(
      'id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _eventIdMeta =
      const VerificationMeta('eventId');
  @override
  late final GeneratedColumn<String> eventId = GeneratedColumn<String>(
      'event_id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _participantIdMeta =
      const VerificationMeta('participantId');
  @override
  late final GeneratedColumn<String> participantId = GeneratedColumn<String>(
      'participant_id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _sessionIdMeta =
      const VerificationMeta('sessionId');
  @override
  late final GeneratedColumn<String> sessionId = GeneratedColumn<String>(
      'session_id', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _extractedTextMeta =
      const VerificationMeta('extractedText');
  @override
  late final GeneratedColumn<String> extractedText = GeneratedColumn<String>(
      'extracted_text', aliasedName, false,
      type: DriftSqlType.string, requiredDuringInsert: true);
  static const VerificationMeta _wordCountMeta =
      const VerificationMeta('wordCount');
  @override
  late final GeneratedColumn<int> wordCount = GeneratedColumn<int>(
      'word_count', aliasedName, false,
      type: DriftSqlType.int,
      requiredDuringInsert: false,
      defaultValue: const Constant(0));
  static const VerificationMeta _processingTimeMsMeta =
      const VerificationMeta('processingTimeMs');
  @override
  late final GeneratedColumn<int> processingTimeMs = GeneratedColumn<int>(
      'processing_time_ms', aliasedName, true,
      type: DriftSqlType.int, requiredDuringInsert: false);
  static const VerificationMeta _capturedAtMeta =
      const VerificationMeta('capturedAt');
  @override
  late final GeneratedColumn<DateTime> capturedAt = GeneratedColumn<DateTime>(
      'captured_at', aliasedName, false,
      type: DriftSqlType.dateTime, requiredDuringInsert: true);
  static const VerificationMeta _processedAtMeta =
      const VerificationMeta('processedAt');
  @override
  late final GeneratedColumn<DateTime> processedAt = GeneratedColumn<DateTime>(
      'processed_at', aliasedName, false,
      type: DriftSqlType.dateTime,
      requiredDuringInsert: false,
      defaultValue: currentDateAndTime);
  static const VerificationMeta _syncedMeta = const VerificationMeta('synced');
  @override
  late final GeneratedColumn<bool> synced = GeneratedColumn<bool>(
      'synced', aliasedName, false,
      type: DriftSqlType.bool,
      requiredDuringInsert: false,
      defaultConstraints:
          GeneratedColumn.constraintIsAlways('CHECK ("synced" IN (0, 1))'),
      defaultValue: const Constant(false));
  @override
  List<GeneratedColumn> get $columns => [
        id,
        eventId,
        participantId,
        sessionId,
        extractedText,
        wordCount,
        processingTimeMs,
        capturedAt,
        processedAt,
        synced
      ];
  @override
  String get aliasedName => _alias ?? actualTableName;
  @override
  String get actualTableName => $name;
  static const String $name = 'ocr_results';
  @override
  VerificationContext validateIntegrity(Insertable<OcrResult> instance,
      {bool isInserting = false}) {
    final context = VerificationContext();
    final data = instance.toColumns(true);
    if (data.containsKey('id')) {
      context.handle(_idMeta, id.isAcceptableOrUnknown(data['id']!, _idMeta));
    } else if (isInserting) {
      context.missing(_idMeta);
    }
    if (data.containsKey('event_id')) {
      context.handle(_eventIdMeta,
          eventId.isAcceptableOrUnknown(data['event_id']!, _eventIdMeta));
    } else if (isInserting) {
      context.missing(_eventIdMeta);
    }
    if (data.containsKey('participant_id')) {
      context.handle(
          _participantIdMeta,
          participantId.isAcceptableOrUnknown(
              data['participant_id']!, _participantIdMeta));
    } else if (isInserting) {
      context.missing(_participantIdMeta);
    }
    if (data.containsKey('session_id')) {
      context.handle(_sessionIdMeta,
          sessionId.isAcceptableOrUnknown(data['session_id']!, _sessionIdMeta));
    } else if (isInserting) {
      context.missing(_sessionIdMeta);
    }
    if (data.containsKey('extracted_text')) {
      context.handle(
          _extractedTextMeta,
          extractedText.isAcceptableOrUnknown(
              data['extracted_text']!, _extractedTextMeta));
    } else if (isInserting) {
      context.missing(_extractedTextMeta);
    }
    if (data.containsKey('word_count')) {
      context.handle(_wordCountMeta,
          wordCount.isAcceptableOrUnknown(data['word_count']!, _wordCountMeta));
    }
    if (data.containsKey('processing_time_ms')) {
      context.handle(
          _processingTimeMsMeta,
          processingTimeMs.isAcceptableOrUnknown(
              data['processing_time_ms']!, _processingTimeMsMeta));
    }
    if (data.containsKey('captured_at')) {
      context.handle(
          _capturedAtMeta,
          capturedAt.isAcceptableOrUnknown(
              data['captured_at']!, _capturedAtMeta));
    } else if (isInserting) {
      context.missing(_capturedAtMeta);
    }
    if (data.containsKey('processed_at')) {
      context.handle(
          _processedAtMeta,
          processedAt.isAcceptableOrUnknown(
              data['processed_at']!, _processedAtMeta));
    }
    if (data.containsKey('synced')) {
      context.handle(_syncedMeta,
          synced.isAcceptableOrUnknown(data['synced']!, _syncedMeta));
    }
    return context;
  }

  @override
  Set<GeneratedColumn> get $primaryKey => {id};
  @override
  OcrResult map(Map<String, dynamic> data, {String? tablePrefix}) {
    final effectivePrefix = tablePrefix != null ? '$tablePrefix.' : '';
    return OcrResult(
      id: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}id'])!,
      eventId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}event_id'])!,
      participantId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}participant_id'])!,
      sessionId: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}session_id'])!,
      extractedText: attachedDatabase.typeMapping
          .read(DriftSqlType.string, data['${effectivePrefix}extracted_text'])!,
      wordCount: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}word_count'])!,
      processingTimeMs: attachedDatabase.typeMapping
          .read(DriftSqlType.int, data['${effectivePrefix}processing_time_ms']),
      capturedAt: attachedDatabase.typeMapping
          .read(DriftSqlType.dateTime, data['${effectivePrefix}captured_at'])!,
      processedAt: attachedDatabase.typeMapping
          .read(DriftSqlType.dateTime, data['${effectivePrefix}processed_at'])!,
      synced: attachedDatabase.typeMapping
          .read(DriftSqlType.bool, data['${effectivePrefix}synced'])!,
    );
  }

  @override
  $OcrResultsTable createAlias(String alias) {
    return $OcrResultsTable(attachedDatabase, alias);
  }
}

class OcrResult extends DataClass implements Insertable<OcrResult> {
  final String id;
  final String eventId;
  final String participantId;
  final String sessionId;
  final String extractedText;
  final int wordCount;
  final int? processingTimeMs;
  final DateTime capturedAt;
  final DateTime processedAt;
  final bool synced;
  const OcrResult(
      {required this.id,
      required this.eventId,
      required this.participantId,
      required this.sessionId,
      required this.extractedText,
      required this.wordCount,
      this.processingTimeMs,
      required this.capturedAt,
      required this.processedAt,
      required this.synced});
  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    map['id'] = Variable<String>(id);
    map['event_id'] = Variable<String>(eventId);
    map['participant_id'] = Variable<String>(participantId);
    map['session_id'] = Variable<String>(sessionId);
    map['extracted_text'] = Variable<String>(extractedText);
    map['word_count'] = Variable<int>(wordCount);
    if (!nullToAbsent || processingTimeMs != null) {
      map['processing_time_ms'] = Variable<int>(processingTimeMs);
    }
    map['captured_at'] = Variable<DateTime>(capturedAt);
    map['processed_at'] = Variable<DateTime>(processedAt);
    map['synced'] = Variable<bool>(synced);
    return map;
  }

  OcrResultsCompanion toCompanion(bool nullToAbsent) {
    return OcrResultsCompanion(
      id: Value(id),
      eventId: Value(eventId),
      participantId: Value(participantId),
      sessionId: Value(sessionId),
      extractedText: Value(extractedText),
      wordCount: Value(wordCount),
      processingTimeMs: processingTimeMs == null && nullToAbsent
          ? const Value.absent()
          : Value(processingTimeMs),
      capturedAt: Value(capturedAt),
      processedAt: Value(processedAt),
      synced: Value(synced),
    );
  }

  factory OcrResult.fromJson(Map<String, dynamic> json,
      {ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return OcrResult(
      id: serializer.fromJson<String>(json['id']),
      eventId: serializer.fromJson<String>(json['eventId']),
      participantId: serializer.fromJson<String>(json['participantId']),
      sessionId: serializer.fromJson<String>(json['sessionId']),
      extractedText: serializer.fromJson<String>(json['extractedText']),
      wordCount: serializer.fromJson<int>(json['wordCount']),
      processingTimeMs: serializer.fromJson<int?>(json['processingTimeMs']),
      capturedAt: serializer.fromJson<DateTime>(json['capturedAt']),
      processedAt: serializer.fromJson<DateTime>(json['processedAt']),
      synced: serializer.fromJson<bool>(json['synced']),
    );
  }
  @override
  Map<String, dynamic> toJson({ValueSerializer? serializer}) {
    serializer ??= driftRuntimeOptions.defaultSerializer;
    return <String, dynamic>{
      'id': serializer.toJson<String>(id),
      'eventId': serializer.toJson<String>(eventId),
      'participantId': serializer.toJson<String>(participantId),
      'sessionId': serializer.toJson<String>(sessionId),
      'extractedText': serializer.toJson<String>(extractedText),
      'wordCount': serializer.toJson<int>(wordCount),
      'processingTimeMs': serializer.toJson<int?>(processingTimeMs),
      'capturedAt': serializer.toJson<DateTime>(capturedAt),
      'processedAt': serializer.toJson<DateTime>(processedAt),
      'synced': serializer.toJson<bool>(synced),
    };
  }

  OcrResult copyWith(
          {String? id,
          String? eventId,
          String? participantId,
          String? sessionId,
          String? extractedText,
          int? wordCount,
          Value<int?> processingTimeMs = const Value.absent(),
          DateTime? capturedAt,
          DateTime? processedAt,
          bool? synced}) =>
      OcrResult(
        id: id ?? this.id,
        eventId: eventId ?? this.eventId,
        participantId: participantId ?? this.participantId,
        sessionId: sessionId ?? this.sessionId,
        extractedText: extractedText ?? this.extractedText,
        wordCount: wordCount ?? this.wordCount,
        processingTimeMs: processingTimeMs.present
            ? processingTimeMs.value
            : this.processingTimeMs,
        capturedAt: capturedAt ?? this.capturedAt,
        processedAt: processedAt ?? this.processedAt,
        synced: synced ?? this.synced,
      );
  @override
  String toString() {
    return (StringBuffer('OcrResult(')
          ..write('id: $id, ')
          ..write('eventId: $eventId, ')
          ..write('participantId: $participantId, ')
          ..write('sessionId: $sessionId, ')
          ..write('extractedText: $extractedText, ')
          ..write('wordCount: $wordCount, ')
          ..write('processingTimeMs: $processingTimeMs, ')
          ..write('capturedAt: $capturedAt, ')
          ..write('processedAt: $processedAt, ')
          ..write('synced: $synced')
          ..write(')'))
        .toString();
  }

  @override
  int get hashCode => Object.hash(
      id,
      eventId,
      participantId,
      sessionId,
      extractedText,
      wordCount,
      processingTimeMs,
      capturedAt,
      processedAt,
      synced);
  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      (other is OcrResult &&
          other.id == this.id &&
          other.eventId == this.eventId &&
          other.participantId == this.participantId &&
          other.sessionId == this.sessionId &&
          other.extractedText == this.extractedText &&
          other.wordCount == this.wordCount &&
          other.processingTimeMs == this.processingTimeMs &&
          other.capturedAt == this.capturedAt &&
          other.processedAt == this.processedAt &&
          other.synced == this.synced);
}

class OcrResultsCompanion extends UpdateCompanion<OcrResult> {
  final Value<String> id;
  final Value<String> eventId;
  final Value<String> participantId;
  final Value<String> sessionId;
  final Value<String> extractedText;
  final Value<int> wordCount;
  final Value<int?> processingTimeMs;
  final Value<DateTime> capturedAt;
  final Value<DateTime> processedAt;
  final Value<bool> synced;
  final Value<int> rowid;
  const OcrResultsCompanion({
    this.id = const Value.absent(),
    this.eventId = const Value.absent(),
    this.participantId = const Value.absent(),
    this.sessionId = const Value.absent(),
    this.extractedText = const Value.absent(),
    this.wordCount = const Value.absent(),
    this.processingTimeMs = const Value.absent(),
    this.capturedAt = const Value.absent(),
    this.processedAt = const Value.absent(),
    this.synced = const Value.absent(),
    this.rowid = const Value.absent(),
  });
  OcrResultsCompanion.insert({
    required String id,
    required String eventId,
    required String participantId,
    required String sessionId,
    required String extractedText,
    this.wordCount = const Value.absent(),
    this.processingTimeMs = const Value.absent(),
    required DateTime capturedAt,
    this.processedAt = const Value.absent(),
    this.synced = const Value.absent(),
    this.rowid = const Value.absent(),
  })  : id = Value(id),
        eventId = Value(eventId),
        participantId = Value(participantId),
        sessionId = Value(sessionId),
        extractedText = Value(extractedText),
        capturedAt = Value(capturedAt);
  static Insertable<OcrResult> custom({
    Expression<String>? id,
    Expression<String>? eventId,
    Expression<String>? participantId,
    Expression<String>? sessionId,
    Expression<String>? extractedText,
    Expression<int>? wordCount,
    Expression<int>? processingTimeMs,
    Expression<DateTime>? capturedAt,
    Expression<DateTime>? processedAt,
    Expression<bool>? synced,
    Expression<int>? rowid,
  }) {
    return RawValuesInsertable({
      if (id != null) 'id': id,
      if (eventId != null) 'event_id': eventId,
      if (participantId != null) 'participant_id': participantId,
      if (sessionId != null) 'session_id': sessionId,
      if (extractedText != null) 'extracted_text': extractedText,
      if (wordCount != null) 'word_count': wordCount,
      if (processingTimeMs != null) 'processing_time_ms': processingTimeMs,
      if (capturedAt != null) 'captured_at': capturedAt,
      if (processedAt != null) 'processed_at': processedAt,
      if (synced != null) 'synced': synced,
      if (rowid != null) 'rowid': rowid,
    });
  }

  OcrResultsCompanion copyWith(
      {Value<String>? id,
      Value<String>? eventId,
      Value<String>? participantId,
      Value<String>? sessionId,
      Value<String>? extractedText,
      Value<int>? wordCount,
      Value<int?>? processingTimeMs,
      Value<DateTime>? capturedAt,
      Value<DateTime>? processedAt,
      Value<bool>? synced,
      Value<int>? rowid}) {
    return OcrResultsCompanion(
      id: id ?? this.id,
      eventId: eventId ?? this.eventId,
      participantId: participantId ?? this.participantId,
      sessionId: sessionId ?? this.sessionId,
      extractedText: extractedText ?? this.extractedText,
      wordCount: wordCount ?? this.wordCount,
      processingTimeMs: processingTimeMs ?? this.processingTimeMs,
      capturedAt: capturedAt ?? this.capturedAt,
      processedAt: processedAt ?? this.processedAt,
      synced: synced ?? this.synced,
      rowid: rowid ?? this.rowid,
    );
  }

  @override
  Map<String, Expression> toColumns(bool nullToAbsent) {
    final map = <String, Expression>{};
    if (id.present) {
      map['id'] = Variable<String>(id.value);
    }
    if (eventId.present) {
      map['event_id'] = Variable<String>(eventId.value);
    }
    if (participantId.present) {
      map['participant_id'] = Variable<String>(participantId.value);
    }
    if (sessionId.present) {
      map['session_id'] = Variable<String>(sessionId.value);
    }
    if (extractedText.present) {
      map['extracted_text'] = Variable<String>(extractedText.value);
    }
    if (wordCount.present) {
      map['word_count'] = Variable<int>(wordCount.value);
    }
    if (processingTimeMs.present) {
      map['processing_time_ms'] = Variable<int>(processingTimeMs.value);
    }
    if (capturedAt.present) {
      map['captured_at'] = Variable<DateTime>(capturedAt.value);
    }
    if (processedAt.present) {
      map['processed_at'] = Variable<DateTime>(processedAt.value);
    }
    if (synced.present) {
      map['synced'] = Variable<bool>(synced.value);
    }
    if (rowid.present) {
      map['rowid'] = Variable<int>(rowid.value);
    }
    return map;
  }

  @override
  String toString() {
    return (StringBuffer('OcrResultsCompanion(')
          ..write('id: $id, ')
          ..write('eventId: $eventId, ')
          ..write('participantId: $participantId, ')
          ..write('sessionId: $sessionId, ')
          ..write('extractedText: $extractedText, ')
          ..write('wordCount: $wordCount, ')
          ..write('processingTimeMs: $processingTimeMs, ')
          ..write('capturedAt: $capturedAt, ')
          ..write('processedAt: $processedAt, ')
          ..write('synced: $synced, ')
          ..write('rowid: $rowid')
          ..write(')'))
        .toString();
  }
}

abstract class _$AppDatabase extends GeneratedDatabase {
  _$AppDatabase(QueryExecutor e) : super(e);
  late final $EventsTable events = $EventsTable(this);
  late final $SessionsTable sessions = $SessionsTable(this);
  late final $OcrResultsTable ocrResults = $OcrResultsTable(this);
  @override
  Iterable<TableInfo<Table, Object?>> get allTables =>
      allSchemaEntities.whereType<TableInfo<Table, Object?>>();
  @override
  List<DatabaseSchemaEntity> get allSchemaEntities =>
      [events, sessions, ocrResults];
}
