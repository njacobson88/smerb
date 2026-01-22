import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_inappwebview/flutter_inappwebview.dart';
import '../../../features/capture/services/capture_service.dart';
import '../../../features/capture/services/screenshot_service.dart';
import '../../../features/storage/database/database.dart';
import '../../../features/sync/services/upload_service.dart';
import '../../../features/debug/screens/debug_screen.dart';

class BrowserScreen extends StatefulWidget {
  final CaptureService captureService;
  final AppDatabase database;
  final UploadService uploadService;

  const BrowserScreen({
    super.key,
    required this.captureService,
    required this.database,
    required this.uploadService,
  });

  @override
  State<BrowserScreen> createState() => _BrowserScreenState();
}

class _BrowserScreenState extends State<BrowserScreen> {
  InAppWebViewController? _controller;
  bool _isLoading = true;
  String _currentUrl = 'https://www.reddit.com';
  String _currentPlatform = 'reddit'; // 'reddit' or 'twitter'

  // Shared cookie manager and settings for OAuth
  final CookieManager _cookieManager = CookieManager.instance();

  // Screenshot capture service
  ScreenshotService? _screenshotService;

  @override
  void initState() {
    super.initState();
    _initializeCookies();
  }

  @override
  void dispose() {
    _screenshotService?.dispose();
    super.dispose();
  }

  /// Prime Reddit cookies before loading
  Future<void> _initializeCookies() async {
    try {
      // Set a dummy cookie to "prime" Reddit domain for OAuth
      await _cookieManager.setCookie(
        url: WebUri('https://www.reddit.com'),
        name: 'smerb_primer',
        value: '1',
        domain: '.reddit.com',
        path: '/',
      );
      print('[Browser] Cookie priming complete for .reddit.com');
    } catch (e) {
      print('[Browser] Error priming cookies: $e');
    }
  }

  /// Inject the appropriate platform observer JavaScript
  Future<void> _injectJavaScript() async {
    if (_controller == null) return;

    try {
      // Detect platform from URL
      String? observerFile;
      String platform;

      if (_currentUrl.contains('reddit.com')) {
        observerFile = 'assets/js/reddit_observer.js';
        platform = 'reddit';
      } else if (_currentUrl.contains('twitter.com') || _currentUrl.contains('x.com')) {
        observerFile = 'assets/js/twitter_observer.js';
        platform = 'twitter';
      } else {
        print('[Browser] Unknown platform, skipping injection');
        return;
      }

      // Update current platform
      setState(() {
        _currentPlatform = platform;
      });

      // Load JavaScript from assets
      final jsCode = await rootBundle.loadString(observerFile);

      // Inject into page
      await _controller!.evaluateJavascript(source: jsCode);

      print('[Browser] Injected $platform observer');
    } catch (e) {
      print('[Browser] Error injecting JavaScript: $e');
    }
  }

  void _navigateToReddit() {
    _controller?.loadUrl(
      urlRequest: URLRequest(url: WebUri('https://www.reddit.com')),
    );
  }

  void _navigateToTwitter() {
    _controller?.loadUrl(
      urlRequest: URLRequest(url: WebUri('https://x.com')),
    );
  }

  void _reload() {
    _controller?.reload();
  }

  void _goBack() async {
    if (_controller != null && await _controller!.canGoBack()) {
      _controller!.goBack();
    }
  }

  void _goForward() async {
    if (_controller != null && await _controller!.canGoForward()) {
      _controller!.goForward();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('SMERB Browser - ${_currentPlatform.toUpperCase()}'),
        backgroundColor: Colors.deepOrange,
        foregroundColor: Colors.white,
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _reload,
            tooltip: 'Reload',
          ),
          IconButton(
            icon: const Icon(Icons.bug_report),
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (context) => DebugScreen(
                    captureService: widget.captureService,
                    database: widget.database,
                    uploadService: widget.uploadService,
                  ),
                ),
              );
            },
            tooltip: 'Debug',
          ),
        ],
      ),
      body: Column(
        children: [
          // Loading indicator
          if (_isLoading)
            const LinearProgressIndicator(
              backgroundColor: Colors.grey,
              valueColor: AlwaysStoppedAnimation<Color>(Colors.deepOrange),
            ),

          // URL bar
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            color: Colors.grey[100],
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    _currentUrl,
                    style: const TextStyle(fontSize: 12),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                const SizedBox(width: 8),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: Colors.green[100],
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: const Text(
                    'Recording',
                    style: TextStyle(
                      fontSize: 10,
                      color: Colors.green,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ),
              ],
            ),
          ),

          // WebView
          Expanded(
            child: InAppWebView(
              initialUrlRequest: URLRequest(
                url: WebUri(_currentUrl),
              ),
              initialSettings: InAppWebViewSettings(
                javaScriptEnabled: true,
                javaScriptCanOpenWindowsAutomatically: true,
                supportMultipleWindows: true, // CRITICAL for OAuth popups
                useShouldOverrideUrlLoading: false,
                mediaPlaybackRequiresUserGesture: false,
                allowsInlineMediaPlayback: true,
                userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/605.1.15 (KHTML, like Gecko) '
                    'Version/17.2 Safari/605.1.15',
              ),
              onWebViewCreated: (controller) {
                _controller = controller;

                // Add JavaScript handler for data capture
                controller.addJavaScriptHandler(
                  handlerName: 'SmerbChannel',
                  callback: (args) {
                    if (args.isNotEmpty) {
                      widget.captureService.processJavaScriptEvent(args[0]);
                    }
                  },
                );

                // Initialize and start screenshot capture
                _screenshotService = ScreenshotService(
                  database: widget.database,
                  sessionId: widget.captureService.currentSessionId ?? '',
                );
                _screenshotService?.startCapture(controller);

                print('[Browser] WebView created');
              },
              onLoadStart: (controller, url) {
                setState(() {
                  _isLoading = true;
                  _currentUrl = url?.toString() ?? _currentUrl;
                });
                print('[Browser] Page started: $url');
              },
              onLoadStop: (controller, url) async {
                setState(() {
                  _isLoading = false;
                });
                print('[Browser] Page finished: $url');

                // Debug: Check cookies
                try {
                  final cookies = await _cookieManager.getCookies(url: url!);
                  print('[Browser] Cookies for $url: ${cookies.length} cookies');
                } catch (e) {
                  print('[Browser] Could not read cookies: $e');
                }

                // Inject JavaScript observer
                await _injectJavaScript();
              },
              onCreateWindow: (controller, createWindowRequest) async {
                // CRITICAL: Create a TRUE popup WebView linked via windowId
                // This preserves window.opener so postMessage works
                print('[Browser] Popup requested: ${createWindowRequest.request.url}');

                // Show a dialog with a NEW InAppWebView linked to this request
                showDialog(
                  context: context,
                  barrierDismissible: false,
                  builder: (dialogContext) => Dialog(
                    child: SizedBox(
                      width: 600,
                      height: 800,
                      child: Column(
                        children: [
                          // Close button
                          Container(
                            color: Colors.grey[200],
                            child: Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                const Padding(
                                  padding: EdgeInsets.all(8.0),
                                  child: Text('Login', style: TextStyle(fontWeight: FontWeight.bold)),
                                ),
                                IconButton(
                                  icon: const Icon(Icons.close),
                                  onPressed: () => Navigator.of(dialogContext).pop(),
                                ),
                              ],
                            ),
                          ),
                          // Popup WebView
                          Expanded(
                            child: InAppWebView(
                              // CRITICAL: Link to parent via windowId
                              windowId: createWindowRequest.windowId,
                              initialSettings: InAppWebViewSettings(
                                javaScriptEnabled: true,
                                supportMultipleWindows: true,
                                javaScriptCanOpenWindowsAutomatically: true,
                                userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                                    'AppleWebKit/605.1.15 (KHTML, like Gecko) '
                                    'Version/17.2 Safari/605.1.15',
                              ),
                              onCloseWindow: (popupController) {
                                // Google calls window.close() after postMessage
                                print('[Browser] Popup closed by JavaScript');
                                Navigator.of(dialogContext).pop();
                              },
                              onLoadStop: (popupController, url) {
                                print('[Browser] Popup loaded: $url');
                              },
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                );

                return true;
              },
              onReceivedError: (controller, request, error) {
                print('[Browser] Error: ${error.description}');
              },
            ),
          ),

          // Navigation bar
          Container(
            decoration: BoxDecoration(
              color: Colors.white,
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withOpacity(0.1),
                  blurRadius: 4,
                  offset: const Offset(0, -2),
                ),
              ],
            ),
            child: SafeArea(
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  IconButton(
                    icon: const Icon(Icons.arrow_back),
                    onPressed: _goBack,
                    tooltip: 'Back',
                  ),
                  IconButton(
                    icon: const Icon(Icons.arrow_forward),
                    onPressed: _goForward,
                    tooltip: 'Forward',
                  ),
                  Container(
                    decoration: BoxDecoration(
                      color: _currentPlatform == 'reddit' ? Colors.deepOrange.withOpacity(0.2) : null,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: IconButton(
                      icon: const Icon(Icons.reddit),
                      onPressed: _navigateToReddit,
                      tooltip: 'Reddit',
                      color: _currentPlatform == 'reddit' ? Colors.deepOrange : null,
                    ),
                  ),
                  Container(
                    decoration: BoxDecoration(
                      color: _currentPlatform == 'twitter' ? Colors.blue.withOpacity(0.2) : null,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: IconButton(
                      icon: const Text('𝕏', style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
                      onPressed: _navigateToTwitter,
                      tooltip: 'X (Twitter)',
                      color: _currentPlatform == 'twitter' ? Colors.blue : null,
                    ),
                  ),
                  IconButton(
                    icon: const Icon(Icons.refresh),
                    onPressed: _reload,
                    tooltip: 'Reload',
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
