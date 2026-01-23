import 'dart:convert';
import 'package:flutter/services.dart';

/// Represents a single EMA question
class EmaQuestion {
  final String id;
  final String text;
  final String type; // 'yes_no', 'slider', 'likert'
  final bool required;
  final bool hidden; // Only shown based on skip logic
  final double? min;
  final double? max;
  final String? minLabel;
  final String? maxLabel;
  final List<LikertOption>? options;
  final Map<String, dynamic>? skipLogic;
  final Map<String, dynamic>? safetyTrigger;

  EmaQuestion({
    required this.id,
    required this.text,
    required this.type,
    this.required = true,
    this.hidden = false,
    this.min,
    this.max,
    this.minLabel,
    this.maxLabel,
    this.options,
    this.skipLogic,
    this.safetyTrigger,
  });

  factory EmaQuestion.fromJson(Map<String, dynamic> json) {
    return EmaQuestion(
      id: json['id'],
      text: json['text'],
      type: json['type'],
      required: json['required'] ?? true,
      hidden: json['hidden'] ?? false,
      min: (json['min'] as num?)?.toDouble(),
      max: (json['max'] as num?)?.toDouble(),
      minLabel: json['min_label'],
      maxLabel: json['max_label'],
      options: (json['options'] as List<dynamic>?)
          ?.map((o) => LikertOption.fromJson(o))
          .toList(),
      skipLogic: json['skip_logic'],
      safetyTrigger: json['safety_trigger'],
    );
  }
}

class LikertOption {
  final int value;
  final String label;

  LikertOption({required this.value, required this.label});

  factory LikertOption.fromJson(Map<String, dynamic> json) {
    return LikertOption(
      value: json['value'],
      label: json['label'],
    );
  }
}

class SafetyAlert {
  final List<String> triggerQuestions;
  final int threshold;
  final String questionText;
  final List<CrisisResource> resources;

  SafetyAlert({
    required this.triggerQuestions,
    required this.threshold,
    required this.questionText,
    required this.resources,
  });

  factory SafetyAlert.fromJson(Map<String, dynamic> json) {
    return SafetyAlert(
      triggerQuestions: List<String>.from(json['trigger_questions']),
      threshold: json['threshold'],
      questionText: json['question_text'],
      resources: (json['crisis_resources'] as List<dynamic>)
          .map((r) => CrisisResource.fromJson(r))
          .toList(),
    );
  }
}

class CrisisResource {
  final String name;
  final String action; // 'call' or 'text'
  final String value;
  final String? message;

  CrisisResource({
    required this.name,
    required this.action,
    required this.value,
    this.message,
  });

  factory CrisisResource.fromJson(Map<String, dynamic> json) {
    return CrisisResource(
      name: json['name'],
      action: json['action'],
      value: json['value'],
      message: json['message'],
    );
  }
}

/// Full EMA configuration loaded from JSON
class EmaConfig {
  final int version;
  final String title;
  final List<EmaQuestion> questions; // Flattened list from all sections
  final SafetyAlert safetyAlert;

  EmaConfig({
    required this.version,
    required this.title,
    required this.questions,
    required this.safetyAlert,
  });

  static Future<EmaConfig> load() async {
    final jsonStr = await rootBundle.loadString('assets/ema_questions.json');
    final json = jsonDecode(jsonStr) as Map<String, dynamic>;
    return EmaConfig.fromJson(json);
  }

  factory EmaConfig.fromJson(Map<String, dynamic> json) {
    final sections = json['sections'] as List<dynamic>;
    final allQuestions = <EmaQuestion>[];
    for (final section in sections) {
      final questions = (section['questions'] as List<dynamic>)
          .map((q) => EmaQuestion.fromJson(q))
          .toList();
      allQuestions.addAll(questions);
    }

    return EmaConfig(
      version: json['version'],
      title: json['title'],
      questions: allQuestions,
      safetyAlert: SafetyAlert.fromJson(json['safety_alert']),
    );
  }
}
