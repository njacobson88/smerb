import 'dart:async';
import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';
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
class CheckinService with WidgetsBindingObserver {
  final AppDatabase database;
  String? participantId;
  final FlutterLocalNotificationsPlugin _notifications =
      FlutterLocalNotificationsPlugin();

  /// Notification IDs 0-9 are reserved for the daily check-in reminders
  /// (window.index). The safety walk-away follow-ups in checkin_screen.dart use
  /// 9001-9003 — NEVER cancelAll() here, it would silently kill those.
  static const int _reminderIdRangeEnd = 10;

  // Configuration (from ema_questions.json schedule section)
  int windowsPerDay = 3;
  int windowDurationMinutes = 60;
  int betweenWindowsMinutes = 240;
  String defaultFirstWindow = '11:00'; // 11 AM (→ 11:00 / 15:00 / 19:00) until wake-up set
  bool alwaysAvailable = true;

  // State
  bool _initialized = false;
  bool _initializing = false;
  bool _observerRegistered = false;
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
    if (_initialized || _initializing) return;
    _initializing = true;

    // Self-healing: re-verify + reschedule every time the app returns to the
    // foreground. If ANY path loses the pending schedule (OS eviction, an
    // errant cancel, app update, force-quit on Android clearing exact alarms),
    // it heals on the next app open instead of staying dead until Settings.
    //
    // Registered FIRST, before any await. It used to be registered after
    // notification setup, so when that setup stalled the observer was never
    // added at all and the app could not even observe a resume to heal itself.
    if (!_observerRegistered) {
      WidgetsBinding.instance.addObserver(this);
      _observerRegistered = true;
    }

    try {
      // Load schedule config
      await _loadConfig();

      // Initialize timezone DB and pin tz.local to the DEVICE's zone. Without this
      // tz.local defaults to UTC, which makes daily-repeating reminders
      // (matchDateTimeComponents) fire at the wrong local time.
      tzdata.initializeTimeZones();
      await _configureLocalTimeZone();

      // Initialize notifications + request OS permission (incl. Android 13+).
      // Must never abort the rest of initialization — see _initializeNotifications.
      try {
        await _initializeNotifications();
      } catch (e) {
        print('[CheckIn] Notification setup failed (continuing): $e');
        _logEmaNotificationEvent('ema_notification_init_failed', {
          'stage': 'initializeNotifications',
          'error': e.toString(),
        });
      }

      // Generate today's windows (used for availability gating + reminder times).
      _generateWindows();

      // Schedule the recurring reminders. THIS is what was missing — previously
      // notifications were only ever scheduled if the participant opened Settings.
      await scheduleNotifications();
    } catch (e) {
      // Reaching here means the service is only partly configured. Say so
      // server-side rather than failing silently, and still finish wiring up
      // the timer + mark initialized so the resume path can retry scheduling.
      print('[CheckIn] Initialization error (continuing degraded): $e');
      _logEmaNotificationEvent('ema_notification_init_failed', {
        'stage': 'initialize',
        'error': e.toString(),
      });
    }

    // Start periodic window check
    _windowCheckTimer = Timer.periodic(
      const Duration(seconds: 30),
      (_) => _checkWindows(),
    );

    // Initial check
    _checkWindows();

    _initialized = true;
    _initializing = false;
    print('[CheckIn] Service initialized. Windows: ${_todayWindows.length}, '
        'always_available: $alwaysAvailable, tz: ${tz.local.name}');
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) return;

    // A previous initialize() that never finished must not leave the service
    // dead forever: retry it. This used to be gated on `_initialized`, which is
    // set on the LAST line of initialize() — so any stall meant the self-heal
    // could never run on this or any future launch.
    if (!_initialized) {
      initialize();
      return;
    }

    // Day may have rolled over while backgrounded; rebuild windows, then
    // reschedule (idempotent — same IDs replace their pending versions).
    _generateWindows();
    _checkWindows();
    scheduleNotifications();
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
        description: 'Reminders to complete your Social Media Wellness check-in',
        importance: Importance.high,
      ));
      // NEVER await this unguarded. On Android 13+ the plugin does not always
      // complete this Future when the participant denies or dismisses the
      // system dialog — verified on an API 34 emulator, where the await never
      // returned and every line after it (including scheduleNotifications)
      // simply never ran. Five live Android participants had zero reminders
      // scheduled, and zero telemetry explaining why, because of this.
      //
      // Scheduling is still the right thing to do when permission is refused:
      // the reminders sit in the OS ready to fire, and start displaying the
      // moment the participant enables notifications in system settings.
      bool? granted;
      try {
        granted = await androidImpl
            .requestNotificationsPermission()
            .timeout(const Duration(seconds: 15));
      } on TimeoutException {
        print('[CheckIn] Notification permission request never returned '
            '(denied or dismissed) — continuing without it');
        _logEmaNotificationEvent('ema_notification_permission_stalled', {
          'platform': 'android',
          'timeoutSeconds': 15,
        });
      } catch (e) {
        print('[CheckIn] Notification permission request failed: $e');
      }
      print('[CheckIn] Android notification permission granted: $granted');
      if (granted == false) {
        // Visible server-side so the dashboard can tell "participant refused
        // notifications" apart from "scheduling is broken on this device".
        _logEmaNotificationEvent('ema_notification_permission_denied', {
          'platform': 'android',
        });
      }
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
  /// every launch AND every app-resume — it rebuilds only the reminder IDs
  /// (0-9), never touching the safety follow-up notifications (9001-9003).
  Future<void> scheduleNotifications() async {
    // Cancel ONLY the reminder ID range. cancelAll() here previously wiped the
    // pending safety walk-away follow-ups too — never reintroduce it.
    for (var id = 0; id < _reminderIdRangeEnd; id++) {
      await _notifications.cancel(id);
    }

    // Honor the user's toggle (default ON — reminders are core to the study).
    final prefs = await SharedPreferences.getInstance();
    final enabled = prefs.getBool('checkin_notifications_enabled') ?? true;
    if (!enabled) {
      // Log it. This return used to be silent, which left no way to tell a
      // participant who switched reminders off apart from a device where
      // scheduling never ran at all — the exact ambiguity that made the
      // Android stall take so long to find.
      print('[CheckIn] Reminders disabled by participant — none scheduled');
      _logEmaNotificationEvent('ema_notifications_disabled_by_participant', {
        'expectedCount': _todayWindows.length,
      });
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
        channelDescription: 'Reminders to complete your Social Media Wellness check-in',
        importance: Importance.high,
        priority: Priority.high,
        category: AndroidNotificationCategory.reminder,
      ),
    );

    for (final window in _todayWindows) {
      await _scheduleWindow(window, details);
    }

    // Verify against the OS and log the ground truth — if a device ever shows
    // zero pending reminders server-side, we know scheduling is broken there.
    try {
      final pending = await _notifications.pendingNotificationRequests();
      final reminderIds = pending
          .map((p) => p.id)
          .where((id) => id < _reminderIdRangeEnd)
          .toList()
        ..sort();
      _logEmaNotificationEvent('ema_notifications_verified', {
        'pendingReminderIds': reminderIds,
        'expectedCount': _todayWindows.length,
        'ok': reminderIds.length == _todayWindows.length,
      });
      print('[CheckIn] Pending reminders verified: $reminderIds');
    } catch (e) {
      print('[CheckIn] Could not verify pending notifications: $e');
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
          'Time for your check-in',
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

  /// Cancel the scheduled check-in reminders (participant toggled them off).
  /// Only touches the reminder ID range — safety follow-ups are never affected.
  Future<void> cancelNotifications() async {
    for (var id = 0; id < _reminderIdRangeEnd; id++) {
      await _notifications.cancel(id);
    }
    print('[CheckIn] Check-in reminders cancelled');
  }

  void dispose() {
    // Do NOT cancel notifications here. This runs whenever the owning widget
    // tree is torn down (navigation changes, re-init, etc.) and previously
    // wiped every pending notification — daily reminders AND pending safety
    // walk-away follow-ups — leaving the participant with no reminders until
    // the next cold start or Settings visit. OS-scheduled notifications must
    // outlive the UI: that is their entire purpose.
    _windowCheckTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
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
