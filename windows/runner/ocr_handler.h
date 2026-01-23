#ifndef RUNNER_OCR_HANDLER_H_
#define RUNNER_OCR_HANDLER_H_

#include <flutter/flutter_engine.h>
#include <flutter/method_channel.h>
#include <flutter/standard_method_codec.h>

#include <memory>

class OcrHandler {
 public:
  static void Register(flutter::FlutterEngine* engine);

 private:
  static void HandleMethodCall(
      const flutter::MethodCall<flutter::EncodableValue>& method_call,
      std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result);

  static void ExtractText(
      const std::string& image_path,
      std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result);
};

#endif  // RUNNER_OCR_HANDLER_H_
