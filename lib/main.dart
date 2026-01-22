import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:firebase_core/firebase_core.dart';
import 'firebase_options.dart';
import 'features/browser/screens/browser_screen.dart';
import 'features/debug/screens/debug_screen.dart';
import 'features/storage/database/database.dart';
import 'features/capture/services/capture_service.dart';
import 'features/sync/services/upload_service.dart';
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
      title: 'SMERB',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        primarySwatch: Colors.deepOrange,
        useMaterial3: true,
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

class _AppInitializerState extends State<AppInitializer> {
  late final AppDatabase _database;
  late final ParticipantService _participantService;
  CaptureService? _captureService;
  UploadService? _uploadService;

  bool _initialized = false;
  bool _enrolled = false;

  @override
  void initState() {
    super.initState();
    _initialize();
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

    // Start a session
    await _captureService!.startSession(
      deviceInfo: {
        'platform': 'ios',
        'app_version': '1.0.0',
      },
    );

    print('[App] Services initialized for participant: $participantId');
  }

  Future<void> _onEnrolled() async {
    // Re-initialize services after enrollment
    await _initializeServices();
    setState(() => _enrolled = true);
  }

  @override
  void dispose() {
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
              Text('Initializing SMERB...'),
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
  final ParticipantService participantService;

  const _ServicesProvider({
    required this.database,
    required this.captureService,
    required this.uploadService,
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
