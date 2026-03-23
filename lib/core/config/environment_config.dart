import 'package:cloud_firestore/cloud_firestore.dart';

/// Centralized environment configuration for the SocialScope app.
///
/// Controls whether the app reads/writes to production or dev Firestore
/// collections. Dev mode prefixes all top-level collections with "dev_".
///
/// Usage:
///   flutter run --dart-define=ENVIRONMENT=dev    # Dev mode
///   flutter run --dart-define=ENVIRONMENT=prod   # Prod mode (default)
///   flutter run                                   # Prod mode (default)
///
/// In code:
///   FirebaseFirestore.instance.collection(EnvConfig.col('participants'))
///
class EnvConfig {
  EnvConfig._();

  /// Read from --dart-define=ENVIRONMENT=dev (defaults to "prod")
  static const String environment =
      String.fromEnvironment('ENVIRONMENT', defaultValue: 'prod');

  static bool get isDev => environment == 'dev';
  static bool get isProd => environment == 'prod';

  /// Prefix for top-level Firestore collections
  static String get prefix => isDev ? 'dev_' : '';

  /// Returns the environment-appropriate collection name.
  /// Example: col('participants') returns 'dev_participants' in dev, 'participants' in prod.
  static String col(String name) => '$prefix$name';

  /// Convenience: get a Firestore collection reference with the correct prefix.
  static CollectionReference<Map<String, dynamic>> colRef(String name) =>
      FirebaseFirestore.instance.collection(col(name));

  /// Display name for UI banners
  static String get label => isDev ? 'DEV' : 'PROD';
}
