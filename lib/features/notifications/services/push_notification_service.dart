import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import '../../../core/config/environment_config.dart';
import '../screens/safety_response_screen.dart';

/// Global navigator key so push handlers can present the safety-response
/// screen from anywhere (foreground, background tap, or cold start).
final GlobalKey<NavigatorState> appNavigatorKey = GlobalKey<NavigatorState>();

/// Handles Firebase Cloud Messaging (FCM) push notifications.
class PushNotificationService {
  final String participantId;
  final FirebaseMessaging _messaging = FirebaseMessaging.instance;
  final FlutterLocalNotificationsPlugin _localNotifications =
      FlutterLocalNotificationsPlugin();

  String? _fcmToken;

  // Guards against presenting the safety-response screen twice for the same
  // alert (e.g. foreground message + tap both arriving).
  String? _activeSafetyAlertId;

  PushNotificationService({required this.participantId});

  String? get fcmToken => _fcmToken;

  /// Initialize push notifications — call once after enrollment
  Future<void> initialize() async {
    try {
      print('[Push] Initializing for participant: $participantId');

      // Request permission (required on iOS)
      NotificationSettings settings;
      try {
        // Request FULL (non-provisional) authorization. Provisional auth
        // delivers everything quietly (no banner/sound), which is wrong for a
        // study where safety self-confirmation + check-in pushes must be seen.
        settings = await _messaging.requestPermission(
          alert: true,
          badge: true,
          sound: true,
        );
        print('[Push] Permission status: ${settings.authorizationStatus}');
      } catch (e) {
        print('[Push] Permission request failed: $e');
        // Still try to get token — Android doesn't need explicit permission
        settings = await _messaging.getNotificationSettings();
        print('[Push] Current settings: ${settings.authorizationStatus}');
      }

      // Always try to get the FCM token regardless of permission status
      // On Android, no permission needed. On iOS, provisional allows silent delivery.
      await _registerToken();

      // Listen for token refreshes
      _messaging.onTokenRefresh.listen((newToken) {
        _fcmToken = newToken;
        _saveTokenToFirestore(newToken);
        print('[Push] Token refreshed');
      });

      // Initialize local notifications for foreground display
      await _initLocalNotifications();

      // Handle foreground messages
      FirebaseMessaging.onMessage.listen(_handleForegroundMessage);

      // Handle notification taps (app was in background)
      FirebaseMessaging.onMessageOpenedApp.listen(_handleNotificationTap);

      // Check if app was opened from a notification (app was terminated)
      final initialMessage = await _messaging.getInitialMessage();
      if (initialMessage != null) {
        _handleNotificationTap(initialMessage);
      }

      print('[Push] Initialization complete. Token: ${_fcmToken != null ? "registered" : "FAILED"}');
    } catch (e) {
      print('[Push] INITIALIZATION ERROR: $e');
      // Don't rethrow — push failure shouldn't crash the app
    }
  }

  Future<void> _registerToken() async {
    try {
      // On iOS, you may need the APNS token first
      final apnsToken = await _messaging.getAPNSToken();
      print('[Push] APNS token: ${apnsToken != null ? "${apnsToken.substring(0, 20)}..." : "null (expected on simulator/macOS)"}');

      _fcmToken = await _messaging.getToken();
      if (_fcmToken != null) {
        await _saveTokenToFirestore(_fcmToken!);
        print('[Push] FCM token registered: ${_fcmToken!.substring(0, 20)}...');
      } else {
        print('[Push] FCM token is null — push notifications will not work');
      }
    } catch (e) {
      print('[Push] Failed to get FCM token: $e');
    }
  }

  Future<void> _saveTokenToFirestore(String token) async {
    try {
      await FirebaseFirestore.instance
          .collection(EnvConfig.col('participants'))
          .doc(participantId)
          .set({
        'fcmToken': token,
        'fcmTokenUpdatedAt': FieldValue.serverTimestamp(),
      }, SetOptions(merge: true));
      print('[Push] Token saved to Firestore');
    } catch (e) {
      print('[Push] Failed to save FCM token to Firestore: $e');
    }
  }

  Future<void> _initLocalNotifications() async {
    const androidSettings =
        AndroidInitializationSettings('@mipmap/ic_launcher');
    const iosSettings = DarwinInitializationSettings(
      requestAlertPermission: false,
      requestBadgePermission: false,
      requestSoundPermission: false,
    );
    const initSettings = InitializationSettings(
      android: androidSettings,
      iOS: iosSettings,
    );

    await _localNotifications.initialize(
      initSettings,
      onDidReceiveNotificationResponse: (response) {
        print('[Push] Local notification tapped: ${response.payload}');
      },
    );
  }

  void _handleForegroundMessage(RemoteMessage message) {
    print('[Push] Foreground message: ${message.notification?.title}');

    _storeNotification(message);

    // Safety self-confirmation prompt — present the interactive screen instead
    // of a passive banner so the participant can confirm or mark it an error.
    if (message.data['type'] == 'safety_self_confirm') {
      _presentSafetyResponse(message.data['alertId'] as String?);
      return;
    }

    final notification = message.notification;
    if (notification != null) {
      _localNotifications.show(
        message.hashCode,
        notification.title ?? 'SocialScope',
        notification.body ?? '',
        const NotificationDetails(
          android: AndroidNotificationDetails(
            'push_notifications',
            'Push Notifications',
            channelDescription: 'Notifications from the study team',
            importance: Importance.high,
            priority: Priority.high,
            icon: '@mipmap/ic_launcher',
          ),
          iOS: DarwinNotificationDetails(
            presentAlert: true,
            presentBadge: true,
            presentSound: true,
          ),
        ),
        payload: jsonEncode(message.data),
      );
    }
  }

  void _handleNotificationTap(RemoteMessage message) {
    print('[Push] Notification tapped: ${message.notification?.title}');
    _storeNotification(message, tapped: true);

    if (message.data['type'] == 'safety_self_confirm') {
      _presentSafetyResponse(message.data['alertId'] as String?);
    }
  }

  /// Present the full-screen safety-response prompt for a given alert.
  /// On a COLD START (app was terminated, participant tapped the push), this is
  /// called from getInitialMessage() before the MaterialApp navigator exists,
  /// so we wait for the navigator to mount instead of dropping the prompt.
  void _presentSafetyResponse(String? alertId, {int attempt = 0}) {
    if (alertId == null || alertId.isEmpty) {
      print('[Push] safety_self_confirm push missing alertId — ignoring');
      return;
    }
    if (_activeSafetyAlertId == alertId) return; // already showing this alert

    final navigator = appNavigatorKey.currentState;
    if (navigator == null) {
      // Navigator not mounted yet (cold start). Retry for up to ~15s rather
      // than silently losing the in-app self-resolution channel.
      if (attempt >= 30) {
        print('[Push] Navigator never became available — cannot show safety response');
        return;
      }
      Future.delayed(const Duration(milliseconds: 500),
          () => _presentSafetyResponse(alertId, attempt: attempt + 1));
      return;
    }

    _activeSafetyAlertId = alertId;
    navigator
        .push(MaterialPageRoute(
          fullscreenDialog: true,
          builder: (_) => SafetyResponseScreen(
            alertId: alertId,
            pushService: this,
          ),
        ))
        .then((_) => _activeSafetyAlertId = null);
  }

  /// Record the participant's response to a safety self-confirmation prompt.
  /// Writes to participants/{id}/safety_responses/{alertId}; a Cloud Function
  /// reacts — an "error" response stops the escalation process, a "confirmed"
  /// response is logged and lets escalation continue. Returns true on success.
  Future<bool> submitSafetyResponse({
    required String alertId,
    required String response, // 'confirmed' | 'error'
  }) async {
    for (var attempt = 1; attempt <= 3; attempt++) {
      try {
        await FirebaseFirestore.instance
            .collection(EnvConfig.col('participants'))
            .doc(participantId)
            .collection('safety_responses')
            .doc(alertId)
            .set({
          'participantId': participantId,
          'alertId': alertId,
          'response': response,
          'respondedAt': FieldValue.serverTimestamp(),
          'source': 'app_push',
        }).timeout(const Duration(seconds: 10));
        print('[Push] Safety response recorded: $response for $alertId');
        return true;
      } catch (e) {
        print('[Push] Safety response write failed (attempt $attempt/3): $e');
        if (attempt < 3) {
          await Future.delayed(Duration(seconds: 1 << (attempt - 1)));
        }
      }
    }
    return false;
  }

  Future<void> _storeNotification(RemoteMessage message, {bool tapped = false}) async {
    try {
      await FirebaseFirestore.instance
          .collection(EnvConfig.col('participants'))
          .doc(participantId)
          .collection('received_notifications')
          .doc(message.messageId ?? DateTime.now().millisecondsSinceEpoch.toString())
          .set({
        'title': message.notification?.title,
        'body': message.notification?.body,
        'data': message.data,
        'receivedAt': FieldValue.serverTimestamp(),
        'tapped': tapped,
        'read': false,
      });
    } catch (e) {
      print('[Push] Failed to store notification: $e');
    }
  }

  Future<int> getUnreadCount() async {
    try {
      final query = await FirebaseFirestore.instance
          .collection(EnvConfig.col('participants'))
          .doc(participantId)
          .collection('received_notifications')
          .where('read', isEqualTo: false)
          .get();
      return query.size;
    } catch (e) {
      return 0;
    }
  }

  Future<void> markAsRead(String notificationId) async {
    try {
      await FirebaseFirestore.instance
          .collection(EnvConfig.col('participants'))
          .doc(participantId)
          .collection('received_notifications')
          .doc(notificationId)
          .update({'read': true});
    } catch (e) {
      print('[Push] Failed to mark notification as read: $e');
    }
  }

  Future<void> markAllAsRead() async {
    try {
      final unread = await FirebaseFirestore.instance
          .collection(EnvConfig.col('participants'))
          .doc(participantId)
          .collection('received_notifications')
          .where('read', isEqualTo: false)
          .get();

      final batch = FirebaseFirestore.instance.batch();
      for (final doc in unread.docs) {
        batch.update(doc.reference, {'read': true});
      }
      await batch.commit();
    } catch (e) {
      print('[Push] Failed to mark all as read: $e');
    }
  }
}
