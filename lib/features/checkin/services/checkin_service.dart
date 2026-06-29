import 'dart:async';
import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:uuid/uuid.dart';
import 'package:timezone/timezone.dart' as tz;
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:flutter_timezone/flutter_timezone.dart';
import '../../../core/config/environment_config.dart';
import '../../storage/database/database.dart';

/// Manages check-in windows, notifications, and scheduling.
/// Based on Mood Triggers' CheckinController pattern:
/// - 3 windows per day, 4 hours apart, 1 hour each
/// - Notifications at window start
/// - Tracks which windows have been completed
class CheckinService {
  final AppDatabase database;
  String? participantId;
  final FlutterLocalNotificationsPlugin _notifications =
      FlutterLocalNotificationsPlugin();

  // Configuration (from ema_questions.json schedule section)
  int windowsPerDay = 3;
  int windowDurationMinutes = 60;
  int betweenWindowsMinutes = 240;
  String defaultFirstWindow = '11:00'; // 11 AM (→ 11:00 / 15:00 / 19:00) until wake-up set
  bool alwaysAvailable = true;

  // State
  bool _initialized = false;
  Timer? _windowCheckTimer;
  final List<CheckinWindow> _todayWindows = [];
  bool _checkinAvailable = false;
  int? _currentWindowIndex;

  CheckinService({required this.database});

  bool get isInitialized => _initialized;
  bool get checkinAvailable => _checkinAvailable || alwaysAvailable;
  int? get currentWindowIndex => _currentWindowIndex;
  List<CheckinWindow> get todayWindows => List.unmodifiable(_todayWindows);

  Future<void> initialize() async {
    if (_initialized) return;

    // Load schedule config
    await _loadConfig();

    // Initialize timezone DB and pin tz.local to the DEVICE's zone. Without this
    // tz.local defaults to UTC, which makes daily-repeating reminders
    // (matchDateTimeComponents) fire at the wrong local time.
    tzdata.initializeTimeZones();
    await _configureLocalTimeZone();

    // Initialize notifications + request OS permission (incl. Android 13+).
    await _initializeNotifications();

    // Generate today's windows (used for availability gating + reminder times).
    _generateWindows();

    // Schedule the recurring reminders. THIS is what was missing — previously
    // notifications were only ever scheduled if the participant opened Settings.
    await scheduleNotifications();

    // Start periodic window check
    _windowCheckTimer = Timer.periodic(
      const Duration(seconds: 30),
      (_) => _checkWindows(),
    );

    // Initial check
    _checkWindows();

    _initialized = true;
    print('[CheckIn] Service initialized. Windows: ${_todayWindows.length}, '
        'always_available: $alwaysAvailable, tz: ${tz.local.name}');
  }

  /// Pin tz.local to the device's IANA zone (e.g. America/New_York).
  Future<void> _configureLocalTimeZone() async {
    try {
      final String tzName = await FlutterTimezone.getLocalTimezone();
      tz.setLocalLocation(tz.getLocation(tzName));
      print('[CheckIn] Local timezone set to $tzName');
    } catch (e) {
      // Leave tz.local at its default; one-shot scheduling still works, but log
      // it because recurring reminders depend on a correct local zone.
      print('[CheckIn] Could not resolve local timezone (using ${tz.local.name}): $e');
    }
  }

  Future<void> _loadConfig() async {
    try {
      final jsonStr = await rootBundle.loadString('assets/ema_questions.json');
      final json = jsonDecode(jsonStr) as Map<String, dynamic>;
      final schedule = json['schedule'] as Map<String, dynamic>;

      windowsPerDay = schedule['windows_per_day'] ?? 3;
      windowDurationMinutes = schedule['window_duration_minutes'] ?? 60;
      betweenWindowsMinutes = schedule['between_windows_minutes'] ?? 240;
      defaultFirstWindow = schedule['default_first_window'] ?? '11:00';
      alwaysAvailable = schedule['always_available'] ?? true;

      // Load user's wake-up time and compute first window
      final prefs = await SharedPreferences.getInstance();
      final wakeStr = prefs.getString('wake_up_time');
      if (wakeStr != null) {
        final parts = wakeStr.split(':');
        final wakeHour = int.parse(parts[0]);
        final wakeMinute = int.parse(parts[1]);
        // First check-in window = wake + 4 hours
        final firstHour = (wakeHour + 4) % 24;
        defaultFirstWindow =
            '${firstHour.toString().padLeft(2, '0')}:${wakeMinute.toString().padLeft(2, '0')}';
      }
    } catch (e) {
      print('[CheckIn] Error loading config, using defaults: $e');
    }
  }

  Future<void> _initializeNotifications() async {
    const androidSettings =
        AndroidInitializationSettings('@mipmap/ic_launcher');
    const iosSettings = DarwinInitializationSettings(
      requestAlertPermission: true,
      requestBadgePermission: true,
      requestSoundPermission: true,
    );
    const initSettings = InitializationSettings(
      android: androidSettings,
      iOS: iosSettings,
    );

    await _notifications.initialize(
      initSettings,
      onDidReceiveNotificationResponse: _onNotificationTap,
    );

    // iOS: request full (non-provisional) authorization so reminders are
    // prominent (banner + sound), not delivered quietly.
    final iosImpl = _notifications.resolvePlatformSpecificImplementation<
        IOSFlutterLocalNotificationsPlugin>();
    if (iosImpl != null) {
      final granted = await iosImpl.requestPermissions(
          alert: true, badge: true, sound: true);
      print('[CheckIn] iOS notification permission granted: $granted');
    }

    // Android 13+ (API 33): notifications are blocked until POST_NOTIFICATIONS
    // is granted at runtime. This was never requested before, so Android showed
    // nothing. Also create the channel up front so its importance is set.
    final androidImpl = _notifications.resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin>();
    if (androidImpl != null) {
      await androidImpl.createNotificationChannel(const AndroidNotificationChannel(
        'checkin_channel',
        'Check-in Reminders',
        description: 'Reminders to complete your SocialScope check-in',
        importance: Importance.high,
      ));
      final granted = await androidImpl.requestNotificationsPermission();
      print('[CheckIn] Android notification permission granted: $granted');
    }
  }

  void _onNotificationTap(NotificationResponse response) {
    print('[CheckIn] Notification tapped: ${response.payload}');

    _logEmaNotificationEvent('ema_notification_tapped', {
      'payload': response.payload,
      'tappedAt': DateTime.now().toIso8601String(),
    });
  }

  /// Log an EMA notification event to Firestore
  Future<void> _logEmaNotificationEvent(String eventType, Map<String, dynamic> data) async {
    if (participantId == null) return;
    try {
      await FirebaseFirestore.instance
          .collection(EnvConfig.col('participants'))
          .doc(participantId!)
          .collection('notification_log')
          .doc(const Uuid().v4())
          .set({
        'participantId': participantId,
        'eventType': eventType,
        'data': data,
        'timestamp': FieldValue.serverTimestamp(),
        'localTime': DateTime.now().toIso8601String(),
      }).timeout(const Duration(seconds: 5));
    } catch (e) {
      print('[CheckIn] Failed to log EMA notification event: $e');
    }
  }

  void _generateWindows() {
    _todayWindows.clear();

    final now = DateTime.now();
    final parts = defaultFirstWindow.split(':');
    final firstStart = DateTime(
      now.year, now.month, now.day,
      int.parse(parts[0]), int.parse(parts[1]),
    );

    for (int i = 0; i < windowsPerDay; i++) {
      // Windows start at firstWindow, firstWindow+4hrs, firstWindow+8hrs
      final windowStart = firstStart.add(
        Duration(minutes: betweenWindowsMinutes * i),
      );
      final windowEnd = windowStart.add(
        Duration(minutes: windowDurationMinutes),
      );
      _todayWindows.add(CheckinWindow(
        index: i,
        start: windowStart,
        end: windowEnd,
      ));
    }
  }

  void _checkWindows() {
    if (alwaysAvailable) {
      _checkinAvailable = true;
      return;
    }

    final now = DateTime.now();
    bool inWindow = false;
    int? windowIndex;

    for (final window in _todayWindows) {
      if (now.isAfter(window.start) && now.isBefore(window.end) &&
          !window.completed) {
        inWindow = true;
        windowIndex = window.index;
        break;
      }
    }

    _checkinAvailable = inWindow;
    _currentWindowIndex = windowIndex;
  }

  /// (Re)schedule the daily check-in reminders. Each of the day's windows is
  /// scheduled as a DAILY-REPEATING notification at its start time, so the OS
  /// re-fires it every day without the app needing to be open. Safe to call on
  /// every launch — it cancels and rebuilds the schedule (self-healing).
  Future<void> scheduleNotifications() async {
    await _notifications.cancelAll();

    // Honor the user's toggle (default ON — reminders are core to the study).
    final prefs = await SharedPreferences.getInstance();
    final enabled = prefs.getBool('checkin_notifications_enabled') ?? true;
    if (!enabled) {
      print('[CheckIn] Reminders disabled by participant — none scheduled');
      return;
    }

    const details = NotificationDetails(
      iOS: DarwinNotificationDetails(
        presentAlert: true,
        presentBadge: true,
        presentSound: true,
        interruptionLevel: InterruptionLevel.active,
      ),
      android: AndroidNotificationDetails(
        'checkin_channel',
        'Check-in Reminders',
        channelDescription: 'Reminders to complete your SocialScope check-in',
        importance: Importance.high,
        priority: Priority.high,
        category: AndroidNotificationCategory.reminder,
      ),
    );

    for (final window in _todayWindows) {
      await _scheduleWindow(window, details);
    }
  }

  /// Schedule one window's daily-repeating reminder. Prefers EXACT delivery so it
  /// fires at the precise scheduled minute; only if the OS refuses exact alarms
  /// does it fall back to inexact — so a reminder is never silently lost.
  Future<void> _scheduleWindow(
      CheckinWindow window, NotificationDetails details) async {
    final when = _nextInstanceOfTime(window.start.hour, window.start.minute);
    final timeOfDay =
        '${window.start.hour.toString().padLeft(2, '0')}:${window.start.minute.toString().padLeft(2, '0')}';

    for (final mode in const [
      AndroidScheduleMode.exactAllowWhileIdle,
      AndroidScheduleMode.inexactAllowWhileIdle,
    ]) {
      try {
        await _notifications.zonedSchedule(
          window.index,
          'Time for a SocialScope check-in',
          'Tap to complete your check-in — it only takes a moment.',
          when,
          details,
          androidScheduleMode: mode,
          uiLocalNotificationDateInterpretation:
              UILocalNotificationDateInterpretation.absoluteTime,
          // Repeat every day at this local time.
          matchDateTimeComponents: DateTimeComponents.time,
          payload: jsonEncode({'window': window.index}),
        );

        _logEmaNotificationEvent('ema_notification_scheduled', {
          'windowIndex': window.index,
          'firstFireAt': when.toIso8601String(),
          'repeats': 'daily',
          'mode': mode.name,
          'timeOfDay': timeOfDay,
          'tz': tz.local.name,
        });
        print('[CheckIn] Scheduled ${mode.name} daily reminder for window '
            '${window.index} at $timeOfDay (next: $when)');
        return; // scheduled successfully — don't also schedule the fallback
      } catch (e) {
        print('[CheckIn] ${mode.name} schedule failed for window '
            '${window.index}: $e');
        if (mode == AndroidScheduleMode.inexactAllowWhileIdle) {
          // Both modes failed — log it so the gap is visible server-side.
          _logEmaNotificationEvent('ema_notification_schedule_failed', {
            'windowIndex': window.index,
            'error': e.toString(),
          });
        }
      }
    }
  }

  /// Next occurrence of [hour]:[minute] in the device's local zone (today if it
  /// is still ahead, otherwise tomorrow).
  tz.TZDateTime _nextInstanceOfTime(int hour, int minute) {
    final now = tz.TZDateTime.now(tz.local);
    var scheduled =
        tz.TZDateTime(tz.local, now.year, now.month, now.day, hour, minute);
    if (!scheduled.isAfter(now)) {
      scheduled = scheduled.add(const Duration(days: 1));
    }
    return scheduled;
  }

  /// Mark current window as completed
  void markWindowComplete(int windowIndex) {
    if (windowIndex < _todayWindows.length) {
      _todayWindows[windowIndex].completed = true;
      _checkWindows();

      _logEmaNotificationEvent('ema_checkin_window_completed', {
        'windowIndex': windowIndex,
        'completedAt': DateTime.now().toIso8601String(),
      });

      print('[CheckIn] Window $windowIndex marked complete');
    }
  }

  /// Get count of today's completed check-ins
  int get completedCount =>
      _todayWindows.where((w) => w.completed).length;

  /// Save the user's preferred first window time
  Future<void> setFirstWindowTime(String time) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('checkin_first_window', time);
    defaultFirstWindow = time;
    _generateWindows();
    await scheduleNotifications();
    _checkWindows();
  }

  /// Cancel all scheduled notifications
  Future<void> cancelNotifications() async {
    await _notifications.cancelAll();
    print('[CheckIn] All notifications cancelled');
  }

  void dispose() {
    _windowCheckTimer?.cancel();
    _notifications.cancelAll();
  }
}

/// Represents a single check-in window
class CheckinWindow {
  final int index;
  final DateTime start;
  final DateTime end;
  bool completed;

  CheckinWindow({
    required this.index,
    required this.start,
    required this.end,
    this.completed = false,
  });

  @override
  String toString() => 'Window $index: $start - $end (done: $completed)';
}
