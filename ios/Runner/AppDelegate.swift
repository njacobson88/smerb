import Flutter
import UIKit
import MLKitTextRecognition
import MLKitVision

@main
@objc class AppDelegate: FlutterAppDelegate {
  private lazy var textRecognizer = TextRecognizer.textRecognizer(options: TextRecognizerOptions())

  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    GeneratedPluginRegistrant.register(with: self)

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
