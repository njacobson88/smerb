/// Configuration for data capture behavior
class CaptureConfig {
  // ============================================================================
  // CAPTURE SETTINGS
  // ============================================================================

  /// Enable scroll event capture
  static const bool captureScrollEvents = false; // Disabled for better performance - focus on content exposure

  /// Enable content exposure tracking
  static const bool captureContentExposure = true;

  /// Enable interaction tracking (upvotes, clicks, etc.)
  static const bool captureInteractions = true;

  /// Enable page navigation tracking
  static const bool capturePageViews = true;

  // ============================================================================
  // PERFORMANCE LIMITS
  // ============================================================================

  /// Debounce scroll events (milliseconds)
  /// Prevents flooding with scroll events
  static const int scrollDebounceMs = 500; // Increased from 100ms for better performance

  /// Minimum time content must be visible to count as "exposure" (milliseconds)
  static const int minExposureDurationMs = 1000;

  /// Maximum text content length to capture (characters)
  /// Prevents excessive data storage
  static const int maxTextContentLength = 5000;

  /// Intersection threshold for content visibility (0.0 to 1.0)
  /// 0.5 means 50% of content must be visible
  static const double viewportThreshold = 0.5;

  // ============================================================================
  // PLATFORM SETTINGS
  // ============================================================================

  /// Enabled platforms for capture
  static const List<String> enabledPlatforms = [
    'old.reddit.com',
    'reddit.com',
  ];

  // ============================================================================
  // DEBUG SETTINGS
  // ============================================================================

  /// Enable console logging in JavaScript
  static const bool enableJsLogging = true;

  /// Enable verbose event logging
  static const bool verboseLogging = false;
}
