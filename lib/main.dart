import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:firebase_core/firebase_core.dart';
import 'firebase_options.dart';
import 'features/browser/screens/browser_screen.dart';
import 'features/debug/screens/debug_screen.dart';
import 'features/storage/database/database.dart';
import 'features/capture/services/capture_service.dart';
import 'features/sync/services/upload_service.dart';

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
      routes: {
        '/debug': (context) {
          final services = _ServicesProvider.of(context);
          return DebugScreen(
            captureService: services.captureService,
            database: services.database,
            uploadService: services.uploadService,
          );
        },
      },
    );
  }
}

/// Initializes services and shows main screen
class AppInitializer extends StatefulWidget {
  const AppInitializer({super.key});

  @override
  State<AppInitializer> createState() => _AppInitializerState();
}

class _AppInitializerState extends State<AppInitializer> {
  late final AppDatabase _database;
  late final CaptureService _captureService;
  late final UploadService _uploadService;
  bool _initialized = false;

  @override
  void initState() {
    super.initState();
    _initialize();
  }

  Future<void> _initialize() async {
    // Initialize database
    _database = AppDatabase();

    // For MVP, use a hardcoded participant ID
    // In production, this would come from enrollment/authentication
    const participantId = 'mvp_test_participant';

    // Initialize capture service
    _captureService = CaptureService(
      database: _database,
      participantId: participantId,
    );

    // Initialize upload service
    _uploadService = UploadService(database: _database);

    // Start a session
    await _captureService.startSession(
      deviceInfo: {
        'platform': 'ios',
        'app_version': '1.0.0',
      },
    );

    setState(() => _initialized = true);
  }

  @override
  void dispose() {
    _captureService.endSession();
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

    return _ServicesProvider(
      database: _database,
      captureService: _captureService,
      uploadService: _uploadService,
      child: BrowserScreen(
        captureService: _captureService,
        database: _database,
        uploadService: _uploadService,
      ),
    );
  }
}

/// Provides services to child widgets
class _ServicesProvider extends InheritedWidget {
  final AppDatabase database;
  final CaptureService captureService;
  final UploadService uploadService;

  const _ServicesProvider({
    required this.database,
    required this.captureService,
    required this.uploadService,
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
