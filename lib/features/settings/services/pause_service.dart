import 'dart:async';
import 'package:shared_preferences/shared_preferences.dart';

/// Global pause state for data collection (screenshots + sync).
/// Uses a 5-minute timer that auto-expires.
class PauseService {
  static final PauseService _instance = PauseService._();
  factory PauseService() => _instance;
  PauseService._();

  static const String _prefKey = 'data_collection_pause_until';
  static const Duration pauseDuration = Duration(minutes: 5);

  Timer? _expiryTimer;
  DateTime? _pauseUntil;

  // Callbacks to notify services when pause state changes
  final List<void Function(bool paused)> _listeners = [];

  void addListener(void Function(bool paused) listener) {
    _listeners.add(listener);
  }

  bool get isPaused {
    if (_pauseUntil == null) return false;
    if (DateTime.now().isAfter(_pauseUntil!)) {
      _pauseUntil = null;
      return false;
    }
    return true;
  }

  Duration get remainingTime {
    if (_pauseUntil == null) return Duration.zero;
    final remaining = _pauseUntil!.difference(DateTime.now());
    return remaining.isNegative ? Duration.zero : remaining;
  }

  /// Initialize from persisted state (call on app start).
  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    final pauseMs = prefs.getInt(_prefKey);
    if (pauseMs != null) {
      final until = DateTime.fromMillisecondsSinceEpoch(pauseMs);
      if (until.isAfter(DateTime.now())) {
        _pauseUntil = until;
        _startExpiryTimer();
        _notifyListeners(true);
      } else {
        await prefs.remove(_prefKey);
      }
    }
  }

  /// Start a 5-minute pause.
  Future<void> pause() async {
    _pauseUntil = DateTime.now().add(pauseDuration);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_prefKey, _pauseUntil!.millisecondsSinceEpoch);
    _startExpiryTimer();
    _notifyListeners(true);
  }

  /// Cancel the pause early.
  Future<void> resume() async {
    _pauseUntil = null;
    _expiryTimer?.cancel();
    _expiryTimer = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_prefKey);
    _notifyListeners(false);
  }

  void _startExpiryTimer() {
    _expiryTimer?.cancel();
    final remaining = remainingTime;
    if (remaining.inSeconds > 0) {
      _expiryTimer = Timer(remaining, () {
        _pauseUntil = null;
        _notifyListeners(false);
      });
    }
  }

  void _notifyListeners(bool paused) {
    for (final listener in _listeners) {
      listener(paused);
    }
  }
}
