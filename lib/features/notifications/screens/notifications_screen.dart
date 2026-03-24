import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import '../../../core/config/environment_config.dart';
import '../services/push_notification_service.dart';

/// Displays received push notifications with a clean, modern UI.
/// Shows notification history, unread badges, and allows marking as read.
class NotificationsScreen extends StatefulWidget {
  final String participantId;
  final PushNotificationService pushService;

  const NotificationsScreen({
    super.key,
    required this.participantId,
    required this.pushService,
  });

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  List<Map<String, dynamic>> _notifications = [];
  bool _loading = true;
  String? _expandedId;

  @override
  void initState() {
    super.initState();
    _loadNotifications();
  }

  Future<void> _loadNotifications() async {
    try {
      final query = await FirebaseFirestore.instance
          .collection(EnvConfig.col('participants'))
          .doc(widget.participantId)
          .collection('received_notifications')
          .orderBy('receivedAt', descending: true)
          .limit(50)
          .get();

      setState(() {
        _notifications = query.docs.map((doc) {
          final data = doc.data();
          return {
            'id': doc.id,
            'title': data['title'] ?? 'Notification',
            'body': data['body'] ?? '',
            'read': data['read'] ?? false,
            'tapped': data['tapped'] ?? false,
            'receivedAt': data['receivedAt'],
            'data': data['data'] ?? {},
          };
        }).toList();
        _loading = false;
      });
    } catch (e) {
      print('[Notifications] Error loading: $e');
      setState(() => _loading = false);
    }
  }

  Future<void> _markAsRead(String notificationId) async {
    await widget.pushService.markAsRead(notificationId);
    setState(() {
      final idx = _notifications.indexWhere((n) => n['id'] == notificationId);
      if (idx >= 0) _notifications[idx]['read'] = true;
    });
  }

  Future<void> _markAllAsRead() async {
    await widget.pushService.markAllAsRead();
    setState(() {
      for (final n in _notifications) {
        n['read'] = true;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final unreadCount = _notifications.where((n) => !n['read']).length;

    return Scaffold(
      appBar: AppBar(
        title: const Text(
          'Notifications',
          style: TextStyle(fontWeight: FontWeight.w600),
        ),
        flexibleSpace: Container(
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              colors: [Color(0xFF39A0EC), Color(0xFF587AE0), Color(0xFF7050E0)],
              begin: Alignment.centerLeft,
              end: Alignment.centerRight,
            ),
          ),
        ),
        foregroundColor: Colors.white,
        actions: [
          if (unreadCount > 0)
            TextButton(
              onPressed: _markAllAsRead,
              child: const Text(
                'Mark all read',
                style: TextStyle(color: Colors.white70, fontSize: 13),
              ),
            ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _notifications.isEmpty
              ? _buildEmptyState()
              : _buildNotificationList(),
    );
  }

  Widget _buildEmptyState() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.notifications_none, size: 64, color: Colors.grey[300]),
          const SizedBox(height: 16),
          Text(
            'No notifications yet',
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w500,
              color: Colors.grey[500],
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'You\'ll see messages from the study team here',
            style: TextStyle(fontSize: 14, color: Colors.grey[400]),
          ),
        ],
      ),
    );
  }

  Widget _buildNotificationList() {
    return RefreshIndicator(
      onRefresh: _loadNotifications,
      child: ListView.builder(
        padding: const EdgeInsets.symmetric(vertical: 8),
        itemCount: _notifications.length,
        itemBuilder: (context, index) {
          final notif = _notifications[index];
          final isRead = notif['read'] as bool;
          final isExpanded = _expandedId == notif['id'];
          final receivedAt = notif['receivedAt'];

          String timeStr = '';
          if (receivedAt != null && receivedAt is Timestamp) {
            final dt = receivedAt.toDate();
            final now = DateTime.now();
            final diff = now.difference(dt);
            if (diff.inMinutes < 60) {
              timeStr = '${diff.inMinutes}m ago';
            } else if (diff.inHours < 24) {
              timeStr = '${diff.inHours}h ago';
            } else if (diff.inDays < 7) {
              timeStr = '${diff.inDays}d ago';
            } else {
              timeStr = '${dt.month}/${dt.day}';
            }
          }

          // Determine notification type for icon/color
          final title = notif['title'] as String;
          IconData icon;
          Color iconColor;
          if (title.toLowerCase().contains('compliance') ||
              title.toLowerCase().contains('check-in')) {
            icon = Icons.assignment;
            iconColor = const Color(0xFF4A6CF7);
          } else if (title.toLowerCase().contains('weekly') ||
                     title.toLowerCase().contains('report')) {
            icon = Icons.bar_chart;
            iconColor = Colors.green;
          } else if (title.toLowerCase().contains('safety') ||
                     title.toLowerCase().contains('alert')) {
            icon = Icons.health_and_safety;
            iconColor = Colors.red;
          } else {
            icon = Icons.notifications;
            iconColor = Colors.purple;
          }

          return GestureDetector(
            onTap: () {
              if (!isRead) _markAsRead(notif['id']);
              setState(() {
                _expandedId = isExpanded ? null : notif['id'];
              });
            },
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              decoration: BoxDecoration(
                color: isRead ? Colors.white : const Color(0xFFF0F4FF),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: isRead
                      ? Colors.grey.shade200
                      : const Color(0xFF4A6CF7).withAlpha(80),
                  width: isRead ? 1 : 1.5,
                ),
                boxShadow: [
                  if (!isRead)
                    BoxShadow(
                      color: const Color(0xFF4A6CF7).withAlpha(20),
                      blurRadius: 8,
                      offset: const Offset(0, 2),
                    ),
                ],
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Header row: icon + title + time + unread dot
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.center,
                      children: [
                        Container(
                          width: 36,
                          height: 36,
                          decoration: BoxDecoration(
                            color: iconColor.withAlpha(25),
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: Icon(icon, color: iconColor, size: 20),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            title,
                            style: TextStyle(
                              fontSize: 15,
                              fontWeight: isRead ? FontWeight.w500 : FontWeight.w700,
                              color: const Color(0xFF1A1A2E),
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          timeStr,
                          style: TextStyle(fontSize: 11, color: Colors.grey[400]),
                        ),
                        if (!isRead) ...[
                          const SizedBox(width: 6),
                          Container(
                            width: 8, height: 8,
                            decoration: const BoxDecoration(
                              color: Color(0xFF4A6CF7),
                              shape: BoxShape.circle,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                  // Body text — full width, no truncation when expanded
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
                    child: Text(
                      isExpanded
                          ? (notif['body'] as String)
                          : _truncate(notif['body'] as String, 100),
                      style: TextStyle(
                        fontSize: 13,
                        color: Colors.grey[600],
                        height: 1.5,
                      ),
                    ),
                  ),
                  // Mark as read button when expanded
                  if (isExpanded && !isRead) ...[
                    const Divider(height: 1),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                      child: TextButton.icon(
                        onPressed: () => _markAsRead(notif['id']),
                        icon: const Icon(Icons.check, size: 16),
                        label: const Text('Mark as read'),
                        style: TextButton.styleFrom(
                          foregroundColor: const Color(0xFF4A6CF7),
                          textStyle: const TextStyle(fontSize: 12),
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          );
        },
      ),
    );
  }

  String _truncate(String text, int maxLength) {
    if (text.length <= maxLength) return text;
    return '${text.substring(0, maxLength)}...';
  }
}
