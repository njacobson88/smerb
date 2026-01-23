import Cocoa
import FlutterMacOS
import Vision

@main
class AppDelegate: FlutterAppDelegate {
  override func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
    return true
  }

  override func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool {
    return true
  }

  override func applicationDidFinishLaunching(_ notification: Notification) {
    let controller = mainFlutterWindow?.contentViewController as! FlutterViewController
    let ocrChannel = FlutterMethodChannel(name: "com.smerb/ocr", binaryMessenger: controller.engine.binaryMessenger)

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

    super.applicationDidFinishLaunching(notification)
  }

  private func extractText(from imagePath: String, result: @escaping FlutterResult) {
    DispatchQueue.global(qos: .userInitiated).async {
      guard let image = NSImage(contentsOfFile: imagePath),
            let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        DispatchQueue.main.async {
          result(FlutterError(code: "IMAGE_ERROR", message: "Could not load image at path: \(imagePath)", details: nil))
        }
        return
      }

      let request = VNRecognizeTextRequest { (request, error) in
        if let error = error {
          DispatchQueue.main.async {
            result(FlutterError(code: "OCR_ERROR", message: error.localizedDescription, details: nil))
          }
          return
        }

        guard let observations = request.results as? [VNRecognizedTextObservation] else {
          DispatchQueue.main.async {
            result("")
          }
          return
        }

        let recognizedText = observations.compactMap { observation in
          observation.topCandidates(1).first?.string
        }.joined(separator: "\n")

        DispatchQueue.main.async {
          result(recognizedText)
        }
      }

      request.recognitionLevel = .accurate
      request.usesLanguageCorrection = true

      let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
      do {
        try handler.perform([request])
      } catch {
        DispatchQueue.main.async {
          result(FlutterError(code: "OCR_ERROR", message: error.localizedDescription, details: nil))
        }
      }
    }
  }
}
