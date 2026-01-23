import 'dart:async';
import 'dart:convert';
import 'package:flutter/services.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:timezone/timezone.dart' as tz;
import 'package:timezone/data/latest_all.dart' as tz;
import '../../storage/database/database.dart';

/// Manages check-in windows, notifications, and scheduling.
/// Based on Mood Triggers' CheckinController pattern:
/// - 3 windows per day, 4 hours apart, 1 hour each
/// - Notifications at window start
/// - Tracks which windows have been completed
class CheckinService {
  final AppDatabase database;
  final FlutterLocalNotificationsPlugin _notifications =
      FlutterLocalNotificationsPlugin();

  // Configuration (from ema_questions.json schedule section)
  int windowsPerDay = 3;
  int windowDurationMinutes = 60;
  int betweenWindowsMinutes = 240;
  String defaultFirstWindow = '09:00';
  bool alwaysAvailable = true;

  // State
  bool _initialized = false;
  Timer? _windowCheckTimer;
  final List<CheckinWindow> _todayWindows = [];
  bool _checkinAvailable = false;
  int? _currentWindowIndex;

  // Callback for UI updates
  void Function(bool available)? onAvailabilityChanged;

  CheckinService({required this.database});

  bool get isInitialized => _initialized;
  bool get checkinAvailable => _checkinAvailable || alwaysAvailable;
  int? get currentWindowIndex => _currentWindowIndex;
  List<CheckinWindow> get todayWindows => List.unmodifiable(_todayWindows);

  Future<void> initialize() async {
    if (_initialized) return;

    // Load schedule config
    await _loadConfig();

    // Initialize timezone
    tz.initializeTimeZones();

    // Initialize notifications
    await _initializeNotifications();

    // Generate today's windows
    _generateWindows();

    // Start periodic window check
    _windowCheckTimer = Timer.periodic(
      const Duration(seconds: 30),
      (_) => _checkWindows(),
    );

    // Initial check
    _checkWindows();

    _initialized = true;
    print('[CheckIn] Service initialized. Windows: ${_todayWindows.length}, '
        'always_available: $alwaysAvailable');
  }

  Future<void> _loadConfig() async {
    try {
      final jsonStr = await rootBundle.loadString('assets/ema_questions.json');
      final json = jsonDecode(jsonStr) as Map<String, dynamic>;
      final schedule = json['schedule'] as Map<String, dynamic>;

      windowsPerDay = schedule['windows_per_day'] ?? 3;
      windowDurationMinutes = schedule['window_duration_minutes'] ?? 60;
      betweenWindowsMinutes = schedule['between_windows_minutes'] ?? 240;
      defaultFirstWindow = schedule['default_first_window'] ?? '12:00';
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

    // Request permissions on iOS
    await _notifications
        .resolvePlatformSpecificImplementation<
            IOSFlutterLocalNotificationsPlugin>()
        ?.requestPermissions(alert: true, badge: true, sound: true);
  }

  void _onNotificationTap(NotificationResponse response) {
    print('[CheckIn] Notification tapped: ${response.payload}');
    // The app will handle opening the check-in screen when notified
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
      if (!_checkinAvailable) {
        _checkinAvailable = true;
        onAvailabilityChanged?.call(true);
      }
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

    if (inWindow != _checkinAvailable || windowIndex != _currentWindowIndex) {
      _checkinAvailable = inWindow;
      _currentWindowIndex = windowIndex;
      onAvailabilityChanged?.call(_checkinAvailable);
    }
  }

  /// Schedule notifications for today's remaining windows
  Future<void> scheduleNotifications() async {
    // Cancel existing notifications
    await _notifications.cancelAll();

    final now = DateTime.now();

    for (final window in _todayWindows) {
      if (window.start.isAfter(now) && !window.completed) {
        await _notifications.zonedSchedule(
          window.index,
          'Time for a SocialScope check-in!',
          'Tap to complete your check-in.',
          tz.TZDateTime.from(window.start, tz.local),
          const NotificationDetails(
            iOS: DarwinNotificationDetails(
              presentAlert: true,
              presentBadge: true,
              presentSound: true,
            ),
            android: AndroidNotificationDetails(
              'checkin_channel',
              'Check-in Reminders',
              channelDescription: 'Notifications for EMA check-in windows',
              importance: Importance.high,
              priority: Priority.high,
            ),
          ),
          androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
          uiLocalNotificationDateInterpretation:
              UILocalNotificationDateInterpretation.absoluteTime,
          payload: jsonEncode({'window': window.index}),
        );
        print('[CheckIn] Scheduled notification for window ${window.index} '
            'at ${window.start}');
      }
    }
  }

  /// Mark current window as completed
  void markWindowComplete(int windowIndex) {
    if (windowIndex < _todayWindows.length) {
      _todayWindows[windowIndex].completed = true;
      _checkWindows();
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
