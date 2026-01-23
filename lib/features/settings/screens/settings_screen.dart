import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../../checkin/services/checkin_service.dart';

class SettingsScreen extends StatefulWidget {
  final CheckinService checkinService;

  const SettingsScreen({super.key, required this.checkinService});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  TimeOfDay _wakeUpTime = const TimeOfDay(hour: 8, minute: 0);
  bool _notificationsEnabled = true;
  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    final wakeStr = prefs.getString('wake_up_time') ?? '08:00';
    final parts = wakeStr.split(':');
    final notifs = prefs.getBool('checkin_notifications_enabled') ?? true;

    setState(() {
      _wakeUpTime = TimeOfDay(
        hour: int.parse(parts[0]),
        minute: int.parse(parts[1]),
      );
      _notificationsEnabled = notifs;
      _loaded = true;
    });
  }

  Future<void> _saveWakeUpTime(TimeOfDay time) async {
    final prefs = await SharedPreferences.getInstance();
    final timeStr =
        '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';
    await prefs.setString('wake_up_time', timeStr);

    // Update the checkin service - first window is wake + 4hrs
    final firstWindowHour = time.hour + 4;
    final firstWindowStr =
        '${firstWindowHour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';
    await widget.checkinService.setFirstWindowTime(firstWindowStr);

    setState(() => _wakeUpTime = time);
  }

  Future<void> _toggleNotifications(bool enabled) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('checkin_notifications_enabled', enabled);

    if (enabled) {
      await widget.checkinService.scheduleNotifications();
    } else {
      await widget.checkinService.cancelNotifications();
    }

    setState(() => _notificationsEnabled = enabled);
  }

  void _showTimePicker() async {
    final picked = await showTimePicker(
      context: context,
      initialTime: _wakeUpTime,
      helpText: 'Select your usual wake-up time',
    );
    if (picked != null) {
      await _saveWakeUpTime(picked);
    }
  }

  List<TimeOfDay> _getCheckinTimes() {
    return [
      TimeOfDay(hour: (_wakeUpTime.hour + 4) % 24, minute: _wakeUpTime.minute),
      TimeOfDay(hour: (_wakeUpTime.hour + 8) % 24, minute: _wakeUpTime.minute),
      TimeOfDay(hour: (_wakeUpTime.hour + 12) % 24, minute: _wakeUpTime.minute),
    ];
  }

  String _formatTime(TimeOfDay time) {
    final hour = time.hourOfPeriod == 0 ? 12 : time.hourOfPeriod;
    final minute = time.minute.toString().padLeft(2, '0');
    final period = time.period == DayPeriod.am ? 'AM' : 'PM';
    return '$hour:$minute $period';
  }

  @override
  Widget build(BuildContext context) {
    if (!_loaded) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    final checkinTimes = _getCheckinTimes();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Settings'),
      ),
      body: ListView(
        children: [
          const SizedBox(height: 16),
          // Wake-up time section
          _buildSectionHeader('CHECK-IN SCHEDULE'),
          ListTile(
            leading: Icon(Icons.alarm, color: const Color(0xFF6B8AFF)),
            title: const Text('Wake-up Time'),
            subtitle: Text(_formatTime(_wakeUpTime)),
            trailing: const Icon(Icons.chevron_right),
            onTap: _showTimePicker,
          ),
          const Divider(indent: 72),
          // Show computed check-in times
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Card(
              color: Colors.grey[50],
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Your check-in windows:',
                      style: TextStyle(
                        fontWeight: FontWeight.w600,
                        color: Colors.grey[700],
                      ),
                    ),
                    const SizedBox(height: 12),
                    ...checkinTimes.asMap().entries.map((entry) {
                      final idx = entry.key;
                      final time = entry.value;
                      final hoursAfterWake = (idx + 1) * 4;
                      return Padding(
                        padding: const EdgeInsets.symmetric(vertical: 4),
                        child: Row(
                          children: [
                            Container(
                              width: 28,
                              height: 28,
                              decoration: BoxDecoration(
                                color: const Color(0xFF4A6CF7),
                                borderRadius: BorderRadius.circular(14),
                              ),
                              alignment: Alignment.center,
                              child: Text(
                                '${idx + 1}',
                                style: const TextStyle(
                                  color: Colors.white,
                                  fontWeight: FontWeight.bold,
                                  fontSize: 14,
                                ),
                              ),
                            ),
                            const SizedBox(width: 12),
                            Text(
                              _formatTime(time),
                              style: const TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.w500,
                              ),
                            ),
                            const SizedBox(width: 8),
                            Text(
                              '(${hoursAfterWake}hrs after wake)',
                              style: TextStyle(
                                fontSize: 13,
                                color: Colors.grey[600],
                              ),
                            ),
                          ],
                        ),
                      );
                    }),
                    const SizedBox(height: 8),
                    Text(
                      'Each window is 1 hour long.',
                      style: TextStyle(
                        fontSize: 12,
                        color: Colors.grey[500],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
          const SizedBox(height: 8),
          // Notifications section
          _buildSectionHeader('NOTIFICATIONS'),
          SwitchListTile(
            secondary: Icon(Icons.notifications_outlined,
                color: const Color(0xFF6B8AFF)),
            title: const Text('Check-in Reminders'),
            subtitle: const Text('Get notified when a check-in window opens'),
            value: _notificationsEnabled,
            activeColor: const Color(0xFF4A6CF7),
            onChanged: _toggleNotifications,
          ),
        ],
      ),
    );
  }

  Widget _buildSectionHeader(String title) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Text(
        title,
        style: TextStyle(
          fontSize: 13,
          fontWeight: FontWeight.w600,
          color: Colors.grey[600],
          letterSpacing: 0.5,
        ),
      ),
    );
  }
}
