#include "ocr_handler.h"

#include <flutter/encodable_value.h>

#include <thread>
#include <string>
#include <locale>
#include <codecvt>

#include <winrt/Windows.Foundation.h>
#include <winrt/Windows.Graphics.Imaging.h>
#include <winrt/Windows.Media.Ocr.h>
#include <winrt/Windows.Storage.h>
#include <winrt/Windows.Storage.Streams.h>

using namespace winrt;
using namespace Windows::Foundation;
using namespace Windows::Graphics::Imaging;
using namespace Windows::Media::Ocr;
using namespace Windows::Storage;
using namespace Windows::Storage::Streams;

namespace {

std::wstring Utf8ToWide(const std::string& str) {
  if (str.empty()) return L"";
  int size = MultiByteToWideChar(CP_UTF8, 0, str.c_str(), -1, nullptr, 0);
  std::wstring result(size - 1, 0);
  MultiByteToWideChar(CP_UTF8, 0, str.c_str(), -1, result.data(), size);
  return result;
}

std::string WideToUtf8(const std::wstring& str) {
  if (str.empty()) return "";
  int size = WideCharToMultiByte(CP_UTF8, 0, str.c_str(), -1, nullptr, 0, nullptr, nullptr);
  std::string result(size - 1, 0);
  WideCharToMultiByte(CP_UTF8, 0, str.c_str(), -1, result.data(), size, nullptr, nullptr);
  return result;
}

}  // namespace

void OcrHandler::Register(flutter::FlutterEngine* engine) {
  auto channel = std::make_unique<flutter::MethodChannel<flutter::EncodableValue>>(
      engine->messenger(), "com.smerb/ocr",
      &flutter::StandardMethodCodec::GetInstance());

  channel->SetMethodCallHandler(
      [](const flutter::MethodCall<flutter::EncodableValue>& call,
         std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result) {
        HandleMethodCall(call, std::move(result));
      });
}

void OcrHandler::HandleMethodCall(
    const flutter::MethodCall<flutter::EncodableValue>& method_call,
    std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result) {
  if (method_call.method_name() == "extractText") {
    const auto* arguments = std::get_if<flutter::EncodableMap>(method_call.arguments());
    if (!arguments) {
      result->Error("INVALID_ARGS", "Missing arguments");
      return;
    }

    auto it = arguments->find(flutter::EncodableValue("imagePath"));
    if (it == arguments->end() || !std::holds_alternative<std::string>(it->second)) {
      result->Error("INVALID_ARGS", "Missing imagePath");
      return;
    }

    std::string image_path = std::get<std::string>(it->second);
    ExtractText(image_path, std::move(result));
  } else {
    result->NotImplemented();
  }
}

void OcrHandler::ExtractText(
    const std::string& image_path,
    std::unique_ptr<flutter::MethodResult<flutter::EncodableValue>> result) {
  // Move result to shared_ptr for use in async lambda
  auto shared_result = std::shared_ptr<flutter::MethodResult<flutter::EncodableValue>>(
      std::move(result));

  std::thread([image_path, shared_result]() {
    try {
      winrt::init_apartment();

      // Convert path to wide string
      std::wstring wide_path = Utf8ToWide(image_path);

      // Replace forward slashes with backslashes for Windows
      for (auto& c : wide_path) {
        if (c == L'/') c = L'\\';
      }

      // Open the image file
      auto file = StorageFile::GetFileFromPathAsync(wide_path).get();
      auto stream = file.OpenAsync(FileAccessMode::Read).get();

      // Decode the image
      auto decoder = BitmapDecoder::CreateAsync(stream).get();
      auto bitmap = decoder.GetSoftwareBitmapAsync().get();

      // Create OCR engine from user profile languages
      auto engine = OcrEngine::TryCreateFromUserProfileLanguages();
      if (!engine) {
        shared_result->Error("OCR_ERROR", "Could not create OCR engine. Ensure a language pack is installed.");
        winrt::uninit_apartment();
        return;
      }

      // Ensure bitmap is in the correct format for OCR (BGRA8, Premultiplied)
      auto convertedBitmap = SoftwareBitmap::Convert(bitmap, BitmapPixelFormat::Bgra8, BitmapAlphaMode::Premultiplied);

      // Run OCR
      auto ocrResult = engine.RecognizeAsync(convertedBitmap).get();
      std::string text = WideToUtf8(std::wstring(ocrResult.Text()));

      shared_result->Success(flutter::EncodableValue(text));

      winrt::uninit_apartment();
    } catch (const winrt::hresult_error& ex) {
      std::string error_msg = WideToUtf8(std::wstring(ex.message()));
      shared_result->Error("OCR_ERROR", error_msg);
    } catch (const std::exception& ex) {
      shared_result->Error("OCR_ERROR", ex.what());
    }
  }).detach();
}
