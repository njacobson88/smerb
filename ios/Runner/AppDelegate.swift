import Flutter
import UIKit
import MLKitTextRecognition
import MLKitVision
import workmanager_apple

@main
@objc class AppDelegate: FlutterAppDelegate {
  private lazy var textRecognizer = TextRecognizer.textRecognizer(options: TextRecognizerOptions())

  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    GeneratedPluginRegistrant.register(with: self)

    // Background uploads (see lib/features/sync/services/background_upload_scheduler.dart).
    // BGTaskScheduler only delivers a task to a relaunched app if its launch
    // handler was registered before didFinishLaunching returns, so register
    // both identifiers here; the Dart side submits the actual requests. The
    // headless engine that runs a task needs the other plugins (Firebase,
    // sqlite, path_provider, ...) registered on it too.
    WorkmanagerPlugin.setPluginRegistrantCallback { registry in
      GeneratedPluginRegistrant.register(with: registry)
    }
    WorkmanagerPlugin.registerPeriodicTask(
      withIdentifier: "com.dartmouth.smerb.sync.periodic",
      earliestBeginInSeconds: NSNumber(value: 15 * 60))
    WorkmanagerPlugin.registerBGProcessingTask(withIdentifier: "com.dartmouth.smerb.sync.processing")

    // Register OCR method channel
    let controller = window?.rootViewController as! FlutterViewController
    let ocrChannel = FlutterMethodChannel(name: "com.smerb/ocr", binaryMessenger: controller.binaryMessenger)

    ocrChannel.setMethodCallHandler { (call: FlutterMethodCall, result: @escaping FlutterResult) in
      if call.method == "extractText" {
        guard let args = call.arguments as? [String: Any],
              let imagePath = args["imagePath"] as? String else {
          result(FlutterError(code: "INVALID_ARGS", message: "Missing imagePath", details: nil))
          return
        }
        self.extractText(from: imagePath, result: result)
      } else {
        result(FlutterMethodNotImplemented)
      }
    }

    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  private func extractText(from imagePath: String, result: @escaping FlutterResult) {
    DispatchQueue.global(qos: .userInitiated).async {
      guard let image = UIImage(contentsOfFile: imagePath) else {
        DispatchQueue.main.async {
          result(FlutterError(code: "IMAGE_ERROR", message: "Could not load image at path: \(imagePath)", details: nil))
        }
        return
      }

      let visionImage = VisionImage(image: image)
      visionImage.orientation = image.imageOrientation

      self.textRecognizer.process(visionImage) { visionText, error in
        DispatchQueue.main.async {
          if let error = error {
            result(FlutterError(code: "OCR_ERROR", message: error.localizedDescription, details: nil))
            return
          }

          result(visionText?.text ?? "")
        }
      }
    }
  }
}
