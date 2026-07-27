
/// Complete medicine detail with all 11 fields from MedicineDetail schema
class MedicineDetail {
  
  final String medicineName;
  final String dosage;
  final String frequency;
  final String duration;
  final String purpose;
  
  // Enriched fields (from database/API lookups)
  final String composition;
  final String uses;
  final String sideEffects;
  final String precautions;
  final String manufacturer;
  
  // Computed field
  final double confidence;
  final double extractionConfidence;
  
  // Status tracking flags
  final bool foundInLocalDb;
  final bool foundInOpenfda;
  final bool lowConfidence;
  final bool requiresHumanReview;

  MedicineDetail({
    required this.medicineName,
    required this.dosage,
    required this.frequency,
    required this.duration,
    required this.purpose,
    required this.composition,
    required this.uses,
    required this.sideEffects,
    required this.precautions,
    required this.manufacturer,
    required this.confidence,
    required this.extractionConfidence,
    required this.foundInLocalDb,
    required this.foundInOpenfda,
    required this.lowConfidence,
    required this.requiresHumanReview,
  });

  factory MedicineDetail.fromJson(Map<String, dynamic> json) {
    return MedicineDetail(
      medicineName: json['medicine_name'] as String? ?? 'Unknown',
      dosage: json['dosage'] as String? ?? 'unread',
      frequency: json['frequency'] as String? ?? 'unread',
      duration: json['duration'] as String? ?? 'unread',
      purpose: json['purpose'] as String? ?? 'unread',
      composition: json['composition'] as String? ?? 'unread',
      uses: json['uses'] as String? ?? 'unread',
      sideEffects: json['side_effects'] as String? ?? 'unread',
      precautions: json['precautions'] as String? ?? 'unread',
      manufacturer: json['manufacturer'] as String? ?? 'unread',
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
      extractionConfidence: (json['extraction_confidence'] as num?)?.toDouble() ?? 0.5,
      foundInLocalDb: json['found_in_local_db'] as bool? ?? false,
      foundInOpenfda: json['found_in_openfda'] as bool? ?? false,
      lowConfidence: json['low_confidence'] as bool? ?? false,
      requiresHumanReview: json['requires_human_review'] as bool? ?? false,
    );
  }
  
  /// Check if a field value is unread/missing
  bool isFieldUnread(String value) {
    return value == 'unread' || value.trim().isEmpty;
  }
  
  /// Get confidence level as a readable string
  String get confidenceLevel {
    if (confidence >= 0.9) return 'Very High';
    if (confidence >= 0.85) return 'High';
    if (confidence >= 0.7) return 'Medium';
    if (confidence >= 0.5) return 'Low';
    return 'Very Low';
  }
  
  /// Get confidence color for UI
  ConfidenceLevel get confidenceCategory {
    if (requiresHumanReview) return ConfidenceLevel.critical;
    if (confidence >= 0.85) return ConfidenceLevel.high;
    if (confidence >= 0.7) return ConfidenceLevel.medium;
    return ConfidenceLevel.low;
  }
}

/// Confidence level categories for UI display
enum ConfidenceLevel {
  high,
  medium,
  low,
  critical,
}

/// Medicine with Urdu audio result
class MedicineAudioResult {
  final String medicineName;
  final String urduText;
  final String? audioUrl;
  final bool audioGenerated;

  MedicineAudioResult({
    required this.medicineName,
    required this.urduText,
    required this.audioUrl,
    required this.audioGenerated,
  });

  factory MedicineAudioResult.fromJson(Map<String, dynamic> json) {
    return MedicineAudioResult(
      medicineName: json['medicine_name'] as String? ?? 'Unknown',
      urduText: json['urdu_text'] as String? ?? '',
      audioUrl: json['audio_url'] as String?,
      audioGenerated: json['audio_generated'] as bool? ?? false,
    );
  }
}

/// Complete prescription result with extraction details
class PrescriptionResult {
  final String prescriptionId;
  final List<MedicineAudioResult> medicines;
  final String? combinedAudioUrl;
  
  // Timing information
  final double? urduGenerationTimeSeconds;
  final double? audioGenerationTimeSeconds;
  final double? totalTimeSeconds;
  
  // Nested extraction response with full medicine details
  final ExtractionResponse? extractionResponse;

  PrescriptionResult({
    required this.prescriptionId,
    required this.medicines,
    required this.combinedAudioUrl,
    this.urduGenerationTimeSeconds,
    this.audioGenerationTimeSeconds,
    this.totalTimeSeconds,
    this.extractionResponse,
  });

  factory PrescriptionResult.fromJson(Map<String, dynamic> json) {
    final medicinesJson = (json['medicines'] as List<dynamic>? ?? []);
    return PrescriptionResult(
      prescriptionId: json['prescription_id'] as String? ?? '',
      medicines: medicinesJson
          .map((m) => MedicineAudioResult.fromJson(m as Map<String, dynamic>))
          .toList(),
      combinedAudioUrl: json['combined_audio_url'] as String?,
      urduGenerationTimeSeconds: (json['urdu_generation_time_seconds'] as num?)?.toDouble(),
      audioGenerationTimeSeconds: (json['audio_generation_time_seconds'] as num?)?.toDouble(),
      totalTimeSeconds: (json['total_time_seconds'] as num?)?.toDouble(),
      extractionResponse: json['extraction_response'] != null
          ? ExtractionResponse.fromJson(json['extraction_response'] as Map<String, dynamic>)
          : null,
    );
  }
}

/// Extraction response containing full medicine details
class ExtractionResponse {
  final String prescriptionId;
  final List<MedicineDetail> extractedMedicines;
  final String? imagePath;
  final double? extractionTimeSeconds;

  ExtractionResponse({
    required this.prescriptionId,
    required this.extractedMedicines,
    this.imagePath,
    this.extractionTimeSeconds,
  });

  factory ExtractionResponse.fromJson(Map<String, dynamic> json) {
    final medicinesJson = (json['extracted_medicines'] as List<dynamic>? ?? []);
    return ExtractionResponse(
      prescriptionId: json['prescription_id'] as String? ?? '',
      extractedMedicines: medicinesJson
          .map((m) => MedicineDetail.fromJson(m as Map<String, dynamic>))
          .toList(),
      imagePath: json['image_path'] as String?,
      extractionTimeSeconds: (json['extraction_time_seconds'] as num?)?.toDouble(),
    );
  }
}

/// Lifecycle status returned by GET /status/{id}.
enum PrescriptionStatus { pending, processing, done, failed, unknown }

PrescriptionStatus statusFromString(String? value) {
  switch (value) {
    case 'pending':
      return PrescriptionStatus.pending;
    case 'processing':
      return PrescriptionStatus.processing;
    case 'done':
      return PrescriptionStatus.done;
    case 'failed':
      return PrescriptionStatus.failed;
    default:
      return PrescriptionStatus.unknown;
  }
}
