import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:firebase_core/firebase_core.dart';
import 'firebase_options.dart';
import 'features/browser/screens/browser_screen.dart';
import 'features/debug/screens/debug_screen.dart';
import 'features/storage/database/database.dart';
import 'features/capture/services/capture_service.dart';
import 'features/sync/services/upload_service.dart';
import 'features/sync/services/background_sync_service.dart';
import 'features/ocr/services/ocr_service.dart';
import 'features/onboarding/services/participant_service.dart';
import 'features/onboarding/screens/enrollment_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp(
    options: DefaultFirebaseOptions.currentPlatform,
  );
  runApp(const ProviderScope(child: SmerbApp()));
}

class SmerbApp extends StatelessWidget {
  const SmerbApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'SocialScope',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF4A6CF7),
          primary: const Color(0xFF4A6CF7),
          secondary: const Color(0xFF7B61FF),
          brightness: Brightness.light,
        ),
        appBarTheme: const AppBarTheme(
          backgroundColor: Colors.white,
          foregroundColor: Color(0xFF1A1A2E),
          elevation: 0.5,
          surfaceTintColor: Colors.transparent,
        ),
        elevatedButtonTheme: ElevatedButtonThemeData(
          style: ElevatedButton.styleFrom(
            backgroundColor: const Color(0xFF4A6CF7),
            foregroundColor: Colors.white,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
            ),
          ),
        ),
      ),
      home: const AppInitializer(),
    );
  }
}

/// Initializes services and shows main screen or enrollment
class AppInitializer extends StatefulWidget {
  const AppInitializer({super.key});

  @override
  State<AppInitializer> createState() => _AppInitializerState();
}

class _AppInitializerState extends State<AppInitializer> with WidgetsBindingObserver {
  late final AppDatabase _database;
  late final ParticipantService _participantService;
  CaptureService? _captureService;
  UploadService? _uploadService;
  OcrService? _ocrService;
  BackgroundSyncService? _backgroundSyncService;

  bool _initialized = false;
  bool _enrolled = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _initialize();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    super.didChangeAppLifecycleState(state);

    // Handle app lifecycle changes for background sync
    if (state == AppLifecycleState.paused || state == AppLifecycleState.inactive) {
      // App going to background - trigger immediate sync
      print('[App] App pausing - triggering sync');
      _backgroundSyncService?.syncNow();
    } else if (state == AppLifecycleState.resumed) {
      // App coming back to foreground - ensure sync is running
      print('[App] App resumed');
      if (_backgroundSyncService != null && !_backgroundSyncService!.isRunning) {
        _backgroundSyncService!.start();
      }
    }
  }

  Future<void> _initialize() async {
    // Initialize database
    _database = AppDatabase();

    // Initialize participant service
    _participantService = ParticipantService();

    // Check enrollment status
    final isEnrolled = await _participantService.isEnrolled();

    if (isEnrolled) {
      await _initializeServices();
    }

    setState(() {
      _initialized = true;
      _enrolled = isEnrolled;
    });
  }

  Future<void> _initializeServices() async {
    // Get participant ID from service
    final participantId = await _participantService.getParticipantId();
    if (participantId == null) {
      print('[App] Error: No participant ID found');
      return;
    }

    // Initialize capture service with real participant ID
    _captureService = CaptureService(
      database: _database,
      participantId: participantId,
    );

    // Initialize upload service
    _uploadService = UploadService(database: _database);

    // Initialize OCR service
    _ocrService = OcrService(database: _database);

    // Initialize and start background sync service
    _backgroundSyncService = BackgroundSyncService(
      database: _database,
      uploadService: _uploadService!,
      ocrService: _ocrService!,
    );

    // Listen for sync status changes (optional - for UI updates)
    _backgroundSyncService!.onSyncStatusChanged = (status) {
      print('[App] Sync status: ${status.state.name} - '
          'pending: ${status.pendingEvents} events, ${status.pendingOcr} OCR');
    };

    // Start background sync
    _backgroundSyncService!.start();

    // Start a session
    await _captureService!.startSession(
      deviceInfo: {
        'platform': 'ios',
        'app_version': '1.0.0',
      },
    );

    print('[App] Services initialized for participant: $participantId');
    print('[App] Background sync started (30s interval)');
  }

  Future<void> _onEnrolled() async {
    // Re-initialize services after enrollment
    await _initializeServices();
    setState(() => _enrolled = true);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _backgroundSyncService?.dispose();
    _captureService?.endSession();
    _database.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_initialized) {
      return const Scaffold(
        body: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              CircularProgressIndicator(),
              SizedBox(height: 16),
              Text('Initializing SocialScope...'),
            ],
          ),
        ),
      );
    }

    // Show enrollment screen if not enrolled
    if (!_enrolled) {
      return EnrollmentScreen(onEnrolled: _onEnrolled);
    }

    // Show main app
    return _ServicesProvider(
      database: _database,
      captureService: _captureService!,
      uploadService: _uploadService!,
      ocrService: _ocrService!,
      backgroundSyncService: _backgroundSyncService!,
      participantService: _participantService,
      child: Builder(
        builder: (context) => Navigator(
          onGenerateRoute: (settings) {
            if (settings.name == '/debug') {
              final services = _ServicesProvider.of(context);
              return MaterialPageRoute(
                builder: (_) => DebugScreen(
                  captureService: services.captureService,
                  database: services.database,
                  uploadService: services.uploadService,
                ),
              );
            }
            return MaterialPageRoute(
              builder: (_) => BrowserScreen(
                captureService: _captureService!,
                database: _database,
                uploadService: _uploadService!,
                participantService: _participantService,
              ),
            );
          },
        ),
      ),
    );
  }
}

/// Provides services to child widgets
class _ServicesProvider extends InheritedWidget {
  final AppDatabase database;
  final CaptureService captureService;
  final UploadService uploadService;
  final OcrService ocrService;
  final BackgroundSyncService backgroundSyncService;
  final ParticipantService participantService;

  const _ServicesProvider({
    required this.database,
    required this.captureService,
    required this.uploadService,
    required this.ocrService,
    required this.backgroundSyncService,
    required this.participantService,
    required super.child,
  });

  static _ServicesProvider of(BuildContext context) {
    final provider =
        context.dependOnInheritedWidgetOfExactType<_ServicesProvider>();
    assert(provider != null, 'No _ServicesProvider found in context');
    return provider!;
  }

  @override
  bool updateShouldNotify(_ServicesProvider oldWidget) => false;
}
