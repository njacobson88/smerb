package com.dartmouth.smerb

import android.net.Uri
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import java.io.File

class MainActivity : FlutterActivity() {
    private val CHANNEL = "com.smerb/ocr"

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL).setMethodCallHandler { call, result ->
            if (call.method == "extractText") {
                val imagePath = call.argument<String>("imagePath")
                if (imagePath == null) {
                    result.error("INVALID_ARGS", "Missing imagePath", null)
                    return@setMethodCallHandler
                }
                extractText(imagePath, result)
            } else {
                result.notImplemented()
            }
        }
    }

    private fun extractText(imagePath: String, result: MethodChannel.Result) {
        try {
            val file = File(imagePath)
            if (!file.exists()) {
                result.error("IMAGE_ERROR", "Image file not found: $imagePath", null)
                return
            }

            val image = InputImage.fromFilePath(this, Uri.fromFile(file))
            val recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)

            recognizer.process(image)
                .addOnSuccessListener { visionText ->
                    result.success(visionText.text)
                }
                .addOnFailureListener { e ->
                    result.error("OCR_ERROR", e.message, null)
                }
        } catch (e: Exception) {
            result.error("OCR_ERROR", e.message, null)
        }
    }
}
