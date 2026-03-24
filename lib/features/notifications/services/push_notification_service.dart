import 'dart:convert';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import '../../../core/config/environment_config.dart';

/// Handles Firebase Cloud Messaging (FCM) push notifications.
/// - Requests permission on iOS
/// - Registers the FCM token in Firestore for the participant
/// - Shows local notifications when the app is in the foreground
/// - Stores received notifications for display in the app
class PushNotificationService {
  final String participantId;
  final FirebaseMessaging _messaging = FirebaseMessaging.instance;
  final FlutterLocalNotificationsPlugin _localNotifications =
      FlutterLocalNotificationsPlugin();

  String? _fcmToken;

  PushNotificationService({required this.participantId});

  String? get fcmToken => _fcmToken;

  /// Initialize push notifications — call once after enrollment
  Future<void> initialize() async {
    // Request permission (required on iOS)
    final settings = await _messaging.requestPermission(
      alert: true,
      badge: true,
      sound: true,
      provisional: false,
    );

    print('[Push] Permission status: ${settings.authorizationStatus}');

    if (settings.authorizationStatus == AuthorizationStatus.authorized ||
        settings.authorizationStatus == AuthorizationStatus.provisional) {
      // Get and register FCM token
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
    }
  }

  Future<void> _registerToken() async {
    try {
      _fcmToken = await _messaging.getToken();
      if (_fcmToken != null) {
        await _saveTokenToFirestore(_fcmToken!);
        print('[Push] FCM token registered: ${_fcmToken!.substring(0, 20)}...');
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
    } catch (e) {
      print('[Push] Failed to save FCM token: $e');
    }
  }

  Future<void> _initLocalNotifications() async {
    const androidSettings =
        AndroidInitializationSettings('@mipmap/ic_launcher');
    const iosSettings = DarwinInitializationSettings(
      requestAlertPermission: false, // Already requested via FCM
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
        // Navigation handled by the screen that reads stored notifications
      },
    );
  }

  /// Handle messages received while app is in the foreground
  void _handleForegroundMessage(RemoteMessage message) {
    print('[Push] Foreground message: ${message.notification?.title}');

    // Store the notification
    _storeNotification(message);

    // Show as a local notification (FCM doesn't auto-show in foreground)
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

  /// Handle notification tap (app was in background or terminated)
  void _handleNotificationTap(RemoteMessage message) {
    print('[Push] Notification tapped: ${message.notification?.title}');
    _storeNotification(message, tapped: true);
  }

  /// Store received notification in Firestore for display in the app
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

  /// Get unread notification count
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

  /// Mark a notification as read
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

  /// Mark all notifications as read
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
