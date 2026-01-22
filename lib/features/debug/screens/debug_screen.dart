import 'dart:convert';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart';
import '../../../features/capture/services/capture_service.dart';
import '../../../features/storage/database/database.dart';

class DebugScreen extends StatefulWidget {
  final CaptureService captureService;
  final AppDatabase database;

  const DebugScreen({
    super.key,
    required this.captureService,
    required this.database,
  });

  @override
  State<DebugScreen> createState() => _DebugScreenState();
}

class _DebugScreenState extends State<DebugScreen> {
  List<Event> _events = [];
  Map<String, int> _eventCounts = {};
  int _totalEvents = 0;
  String? _selectedEventType;
  bool _isLoading = true;

  final DateFormat _dateFormat = DateFormat('HH:mm:ss');

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    setState(() => _isLoading = true);

    try {
      final events = _selectedEventType != null
          ? await widget.database.getEventsByType(_selectedEventType!)
          : await widget.database.getAllEvents();

      final counts = await widget.database.getEventCountByType();
      final total = await widget.database.getEventCount();

      setState(() {
        _events = events.reversed.toList(); // Most recent first
        _eventCounts = counts;
        _totalEvents = total;
        _isLoading = false;
      });
    } catch (e) {
      print('[Debug] Error loading data: $e');
      setState(() => _isLoading = false);
    }
  }

  Future<void> _clearAllData() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Clear All Data?'),
        content: const Text(
          'This will delete all captured events. This action cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            style: TextButton.styleFrom(foregroundColor: Colors.red),
            child: const Text('Delete'),
          ),
        ],
      ),
    );

    if (confirmed == true) {
      await widget.captureService.clearAllData();
      _loadData();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('All data cleared')),
        );
      }
    }
  }

  Future<void> _exportToJson() async {
    final events = await widget.database.getAllEvents();

    final exportData = {
      'exported_at': DateTime.now().toIso8601String(),
      'total_events': events.length,
      'events': events.map((e) {
        return {
          'id': e.id,
          'session_id': e.sessionId,
          'participant_id': e.participantId,
          'event_type': e.eventType,
          'timestamp': e.timestamp.toIso8601String(),
          'platform': e.platform,
          'url': e.url,
          'data': jsonDecode(e.data),
        };
      }).toList(),
    };

    final jsonString = const JsonEncoder.withIndent('  ').convert(exportData);

    await Clipboard.setData(ClipboardData(text: jsonString));

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Exported to clipboard')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Debug Console'),
        backgroundColor: Colors.deepOrange,
        foregroundColor: Colors.white,
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadData,
            tooltip: 'Refresh',
          ),
          PopupMenuButton<String>(
            onSelected: (value) {
              if (value == 'export') {
                _exportToJson();
              } else if (value == 'clear') {
                _clearAllData();
              }
            },
            itemBuilder: (context) => [
              const PopupMenuItem(
                value: 'export',
                child: Row(
                  children: [
                    Icon(Icons.download),
                    SizedBox(width: 8),
                    Text('Export to JSON'),
                  ],
                ),
              ),
              const PopupMenuItem(
                value: 'clear',
                child: Row(
                  children: [
                    Icon(Icons.delete, color: Colors.red),
                    SizedBox(width: 8),
                    Text('Clear All Data'),
                  ],
                ),
              ),
            ],
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                // Statistics
                _buildStatistics(),

                // Event type filter
                _buildEventTypeFilter(),

                const Divider(height: 1),

                // Event list
                Expanded(
                  child: _events.isEmpty
                      ? const Center(
                          child: Text('No events captured yet'),
                        )
                      : ListView.builder(
                          itemCount: _events.length,
                          itemBuilder: (context, index) {
                            return _buildEventCard(_events[index]);
                          },
                        ),
                ),
              ],
            ),
    );
  }

  Widget _buildStatistics() {
    return Container(
      padding: const EdgeInsets.all(16),
      color: Colors.grey[100],
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Total Events: $_totalEvents',
            style: const TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: _eventCounts.entries.map((entry) {
              return Chip(
                label: Text('${entry.key}: ${entry.value}'),
                backgroundColor: _getEventTypeColor(entry.key),
              );
            }).toList(),
          ),
        ],
      ),
    );
  }

  Widget _buildEventTypeFilter() {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
      child: Row(
        children: [
          ChoiceChip(
            label: const Text('All'),
            selected: _selectedEventType == null,
            onSelected: (selected) {
              setState(() => _selectedEventType = null);
              _loadData();
            },
          ),
          const SizedBox(width: 8),
          ..._eventCounts.keys.map((type) {
            return Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(
                label: Text(type),
                selected: _selectedEventType == type,
                onSelected: (selected) {
                  setState(() => _selectedEventType = selected ? type : null);
                  _loadData();
                },
                backgroundColor: _getEventTypeColor(type).withOpacity(0.3),
              ),
            );
          }),
        ],
      ),
    );
  }

  Widget _buildEventCard(Event event) {
    final data = jsonDecode(event.data) as Map<String, dynamic>;

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      child: ExpansionTile(
        leading: CircleAvatar(
          backgroundColor: _getEventTypeColor(event.eventType),
          child: Text(
            event.eventType[0].toUpperCase(),
            style: const TextStyle(color: Colors.white),
          ),
        ),
        title: Text(
          event.eventType,
          style: const TextStyle(fontWeight: FontWeight.bold),
        ),
        subtitle: Text(
          '${_dateFormat.format(event.timestamp)} • ${event.platform}',
          style: const TextStyle(fontSize: 12),
        ),
        children: [
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            color: Colors.grey[50],
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Show screenshot thumbnail if this is a screenshot event
                if (event.eventType == 'screenshot' && data['filePath'] != null) ...[
                  _buildScreenshotThumbnail(data['filePath'] as String),
                  const SizedBox(height: 12),
                ],
                if (event.url != null) ...[
                  _buildInfoRow('URL', event.url!),
                  const SizedBox(height: 8),
                ],
                _buildInfoRow('Session', event.sessionId),
                const SizedBox(height: 8),
                const Text(
                  'Data:',
                  style: TextStyle(fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 4),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: Colors.black87,
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    const JsonEncoder.withIndent('  ').convert(data),
                    style: const TextStyle(
                      fontFamily: 'Courier',
                      fontSize: 12,
                      color: Colors.greenAccent,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildScreenshotThumbnail(String filePath) {
    final file = File(filePath);

    if (!file.existsSync()) {
      return Container(
        height: 150,
        decoration: BoxDecoration(
          color: Colors.grey[300],
          borderRadius: BorderRadius.circular(8),
        ),
        child: const Center(
          child: Text('Screenshot file not found'),
        ),
      );
    }

    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.grey[400]!),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(8),
        child: Image.file(
          file,
          height: 200,
          fit: BoxFit.contain,
        ),
      ),
    );
  }

  Widget _buildInfoRow(String label, String value) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 80,
          child: Text(
            '$label:',
            style: const TextStyle(fontWeight: FontWeight.bold),
          ),
        ),
        Expanded(
          child: Text(
            value,
            style: const TextStyle(fontSize: 12),
          ),
        ),
      ],
    );
  }

  Color _getEventTypeColor(String eventType) {
    switch (eventType) {
      case 'page_view':
        return Colors.blue;
      case 'scroll':
        return Colors.green;
      case 'content_exposure':
        return Colors.orange;
      case 'interaction':
        return Colors.purple;
      default:
        return Colors.grey;
    }
  }
}
