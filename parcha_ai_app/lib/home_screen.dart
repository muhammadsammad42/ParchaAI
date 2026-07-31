
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import 'api_service.dart';
import 'models.dart';
import 'theme.dart';

enum _ScreenState { idle, checkingHealth, uploading, polling, done, error }

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final ApiService _api = ApiService();
  final ImagePicker _picker = ImagePicker();
  final AudioPlayer _audioPlayer = AudioPlayer();

  File? _selectedImage;
  _ScreenState _state = _ScreenState.idle;
  String _statusMessage = '';
  PrescriptionResult? _result;
  String? _currentlyPlayingUrl;

  @override
  void dispose() {
    _audioPlayer.dispose();
    super.dispose();
  }

  Future<void> _pickImage(ImageSource source) async {
    final picked = await _picker.pickImage(source: source, imageQuality: 90);
    if (picked == null) return;

    setState(() {
      _selectedImage = File(picked.path);
      _state = _ScreenState.idle;
      _result = null;
      _statusMessage = '';
    });
  }

  Future<void> _uploadAndProcess() async {
    if (_selectedImage == null) return;

    // First, check if backend is healthy
    setState(() {
      _state = _ScreenState.checkingHealth;
      _statusMessage = 'Checking connection to server...';
    });

    final isHealthy = await _api.checkHealth();
    if (!isHealthy) {
      if (!mounted) return;
      setState(() {
        _state = _ScreenState.error;
        _statusMessage = 
            'Cannot connect to backend server.\n\n'
            'Please verify:\n'
            '• Backend is running (uvicorn + Redis + Celery worker)\n'
            '• Phone and laptop are on the same Wi-Fi network\n'
            '• Base URL in api_service.dart is set to your laptop\'s LAN IP';
      });
      return;
    }

    setState(() {
      _state = _ScreenState.uploading;
      _statusMessage = 'Uploading prescription...';
    });

    try {
      final result = await _api.uploadAndWaitForResult(
        _selectedImage!,
        onStatusUpdate: (status) {
          if (!mounted) return;
          setState(() {
            _state = _ScreenState.polling;
            _statusMessage = switch (status) {
              PrescriptionStatus.pending => 'Waiting in queue...',
              PrescriptionStatus.processing => 
                  'Reading prescription...\nExtracting medicine details...\nGenerating Urdu explanations...\nCreating audio files...',
              PrescriptionStatus.done => 'Done!',
              PrescriptionStatus.failed => 'Processing failed.',
              PrescriptionStatus.unknown => 'Checking status...',
            };
          });
        },
      );

      if (!mounted) return;
      setState(() {
        _result = result;
        _state = _ScreenState.done;
        _statusMessage = '';
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _state = _ScreenState.error;
        _statusMessage = e.userMessage;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _state = _ScreenState.error;
        _statusMessage = 'Unexpected error: $e';
      });
    }
  }

  Future<void> _playAudio(String url) async {
    if (_currentlyPlayingUrl == url) {
      await _audioPlayer.stop();
      setState(() => _currentlyPlayingUrl = null);
      return;
    }
    await _audioPlayer.stop();
    await _audioPlayer.play(UrlSource(url));
    setState(() => _currentlyPlayingUrl = url);
    _audioPlayer.onPlayerComplete.first.then((_) {
      if (mounted) setState(() => _currentlyPlayingUrl = null);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            Icon(Icons.medical_services, color: AppColors.textOnPrimary),
            const SizedBox(width: AppSpacing.sm),
            const Text('ParchaAI'),
          ],
        ),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.md),
          children: [
            _buildImagePickerCard(),
            const SizedBox(height: AppSpacing.md),
            _buildUploadButton(),
            const SizedBox(height: AppSpacing.md),
            if (_state == _ScreenState.checkingHealth ||
                _state == _ScreenState.uploading || 
                _state == _ScreenState.polling)
              _buildProgress(),
            if (_state == _ScreenState.error) _buildError(),
            if (_state == _ScreenState.done && _result != null) 
              _buildResults(_result!),
          ],
        ),
      ),
    );
  }

  Widget _buildImagePickerCard() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Upload Prescription',
              style: AppTextStyles.h3,
            ),
            const SizedBox(height: AppSpacing.sm),
            Text(
              'Take a photo or select from gallery',
              style: AppTextStyles.bodySmall,
            ),
            const SizedBox(height: AppSpacing.md),
            if (_selectedImage != null)
              ClipRRect(
                borderRadius: BorderRadius.circular(AppRadius.sm),
                child: Image.file(
                  _selectedImage!,
                  height: 240,
                  width: double.infinity,
                  fit: BoxFit.cover,
                ),
              )
            else
              Container(
                height: 240,
                decoration: BoxDecoration(
                  color: AppColors.surfaceVariant,
                  borderRadius: BorderRadius.circular(AppRadius.sm),
                  border: Border.all(
                    color: AppColors.borderLight,
                    width: 2,
                    strokeAlign: BorderSide.strokeAlignInside,
                  ),
                ),
                child: Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(
                        Icons.image_outlined,
                        size: 64,
                        color: AppColors.textTertiary,
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      Text(
                        'No prescription image selected',
                        style: AppTextStyles.bodySmall.copyWith(
                          color: AppColors.textTertiary,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            const SizedBox(height: AppSpacing.md),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () => _pickImage(ImageSource.camera),
                    icon: const Icon(Icons.camera_alt_outlined),
                    label: const Text('Camera'),
                  ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () => _pickImage(ImageSource.gallery),
                    icon: const Icon(Icons.photo_library_outlined),
                    label: const Text('Gallery'),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildUploadButton() {
    final busy = _state == _ScreenState.checkingHealth ||
                 _state == _ScreenState.uploading || 
                 _state == _ScreenState.polling;
    
    return SizedBox(
      width: double.infinity,
      child: ElevatedButton.icon(
        onPressed: (_selectedImage == null || busy) ? null : _uploadAndProcess,
        icon: busy
            ? const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: Colors.white,
                ),
              )
            : const Icon(Icons.upload_file, size: 24),
        label: Padding(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
          child: Text(
            busy ? 'Processing...' : 'Get Urdu Instructions',
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
          ),
        ),
      ),
    );
  }

  Widget _buildProgress() {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.info.withOpacity(0.1),
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.info.withOpacity(0.3)),
      ),
      child: Row(
        children: [
          const SizedBox(
            width: 24,
            height: 24,
            child: CircularProgressIndicator(strokeWidth: 2.5),
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Text(
              _statusMessage,
              style: AppTextStyles.bodyMedium,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildError() {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.error.withOpacity(0.1),
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.error.withOpacity(0.3)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.error_outline, color: AppColors.error, size: 24),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Error',
                  style: AppTextStyles.h3.copyWith(color: AppColors.error),
                ),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  _statusMessage,
                  style: AppTextStyles.bodyMedium.copyWith(
                    color: AppColors.error.withOpacity(0.9),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildResults(PrescriptionResult result) {
    final extractedMedicines = result.extractionResponse?.extractedMedicines ?? [];
    
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Disclaimer banner at the top
        _buildDisclaimerBanner(),
        const SizedBox(height: AppSpacing.lg),
        
        // Combined audio player
        if (result.combinedAudioUrl != null)
          _buildCombinedAudioCard(result.combinedAudioUrl!),
        
        const SizedBox(height: AppSpacing.lg),
        
        // Header with medicine count
        Row(
          children: [
            Text('Your Medicines', style: AppTextStyles.h2),
            const SizedBox(width: AppSpacing.sm),
            Container(
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.sm,
                vertical: AppSpacing.xs,
              ),
              decoration: BoxDecoration(
                color: AppColors.primary,
                borderRadius: BorderRadius.circular(AppRadius.pill),
              ),
              child: Text(
                '${extractedMedicines.length}',
                style: AppTextStyles.badge,
              ),
            ),
          ],
        ),
        
        const SizedBox(height: AppSpacing.md),
        
        // Medicine cards
        ...extractedMedicines.asMap().entries.map((entry) {
          final index = entry.key;
          final medicine = entry.value;
          final audioResult = result.medicines.length > index 
              ? result.medicines[index] 
              : null;
          return Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.md),
            child: _buildMedicineCard(medicine, audioResult),
          );
        }),
      ],
    );
  }

  Widget _buildDisclaimerBanner() {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.disclaimerBackground,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(
          color: AppColors.warning.withOpacity(0.3),
          width: 2,
        ),
      ),
      child: Row(
        children: [
          Icon(
            Icons.warning_amber_rounded,
            color: AppColors.warning,
            size: 28,
          ),
          const SizedBox(width: AppSpacing.md),
          Expanded(
            child: Text(
              'Please confirm with your pharmacist or doctor before taking this medicine',
              style: AppTextStyles.disclaimer,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildCombinedAudioCard(String audioUrl) {
    final isPlaying = _currentlyPlayingUrl == audioUrl;
    
    return Card(
      color: AppColors.primary.withOpacity(0.08),
      child: InkWell(
        onTap: () => _playAudio(audioUrl),
        borderRadius: BorderRadius.circular(AppRadius.md),
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(AppSpacing.sm),
                decoration: BoxDecoration(
                  color: AppColors.primary,
                  borderRadius: BorderRadius.circular(AppRadius.sm),
                ),
                child: Icon(
                  isPlaying ? Icons.stop : Icons.play_arrow,
                  color: AppColors.textOnPrimary,
                  size: 32,
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Play Full Prescription',
                      style: AppTextStyles.h3.copyWith(fontSize: 17),
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Text(
                      'Listen to instructions for all medicines',
                      style: AppTextStyles.bodySmall,
                    ),
                  ],
                ),
              ),
              Icon(
                isPlaying ? Icons.volume_up : Icons.volume_up_outlined,
                color: AppColors.primary,
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildMedicineCard(MedicineDetail medicine, MedicineAudioResult? audioResult) {
    return Card(
      elevation: 3,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header with medicine name and confidence badge
          _buildMedicineHeader(medicine),
          
          const Divider(height: 1),
          
          Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Dosage info row
                _buildDosageInfoRow(medicine),
                
                const SizedBox(height: AppSpacing.md),
                const Divider(),
                const SizedBox(height: AppSpacing.md),
                
                // Medicine details
                _buildMedicineDetails(medicine),
                
                // Urdu instructions
                if (audioResult != null && audioResult.urduText.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.md),
                  const Divider(),
                  const SizedBox(height: AppSpacing.md),
                  _buildUrduSection(audioResult),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMedicineHeader(MedicineDetail medicine) {
    final confidenceColor = getConfidenceColor(medicine.confidenceCategory);
    final confidenceIcon = getConfidenceIcon(medicine.confidenceCategory);
    
    return Container(
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.primary.withOpacity(0.05),
        borderRadius: const BorderRadius.only(
          topLeft: Radius.circular(AppRadius.md),
          topRight: Radius.circular(AppRadius.md),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(
                  medicine.medicineName,
                  style: AppTextStyles.medicineName,
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              _buildConfidenceBadge(
                medicine.confidenceLevel,
                confidenceColor,
                confidenceIcon,
              ),
            ],
          ),
          
          // Warning badges for human review
          if (medicine.requiresHumanReview) ...[
            const SizedBox(height: AppSpacing.sm),
            _buildWarningBadge(
              'Requires verification',
              Icons.error_outline,
              AppColors.confidenceCritical,
            ),
          ],
          
          // Database match indicators
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.xs,
            runSpacing: AppSpacing.xs,
            children: [
              if (medicine.foundInLocalDb)
                _buildInfoChip('Local DB', Icons.check_circle, AppColors.success),
              if (medicine.foundInOpenfda)
                _buildInfoChip('FDA', Icons.verified_user, AppColors.info),
              if (!medicine.foundInLocalDb && !medicine.foundInOpenfda)
                _buildInfoChip('Not verified', Icons.help_outline, AppColors.warning),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildConfidenceBadge(String level, Color color, IconData icon) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.xs,
      ),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(AppRadius.sm),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: AppColors.textOnPrimary, size: 14),
          const SizedBox(width: 4),
          Text(
            level,
            style: AppTextStyles.badge.copyWith(fontSize: 12),
          ),
        ],
      ),
    );
  }

  Widget _buildWarningBadge(String text, IconData icon, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.xs,
      ),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: BorderRadius.circular(AppRadius.sm),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: color, size: 16),
          const SizedBox(width: 4),
          Text(
            text,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: color,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildInfoChip(String label, IconData icon, Color color) {
    return Chip(
      avatar: Icon(icon, color: color, size: 16),
      label: Text(
        label,
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w600,
          color: color,
        ),
      ),
      backgroundColor: color.withOpacity(0.1),
      side: BorderSide(color: color.withOpacity(0.3)),
      padding: EdgeInsets.zero,
      labelPadding: const EdgeInsets.only(right: AppSpacing.xs),
      visualDensity: VisualDensity.compact,
    );
  }

  Widget _buildDosageInfoRow(MedicineDetail medicine) {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.sm),
      decoration: BoxDecoration(
        color: AppColors.surfaceVariant,
        borderRadius: BorderRadius.circular(AppRadius.sm),
      ),
      child: Row(
        children: [
          Expanded(child: _buildQuickInfo('Dosage', medicine.dosage, Icons.medication)),
          Container(width: 1, height: 40, color: AppColors.borderLight),
          Expanded(child: _buildQuickInfo('Frequency', medicine.frequency, Icons.schedule)),
          Container(width: 1, height: 40, color: AppColors.borderLight),
          Expanded(child: _buildQuickInfo('Duration', medicine.duration, Icons.calendar_today)),
        ],
      ),
    );
  }

  Widget _buildQuickInfo(String label, String value, IconData icon) {
    final isUnread = value == 'unread' || value.trim().isEmpty;
    
    return Column(
      children: [
        Icon(
          icon,
          color: isUnread ? AppColors.textTertiary : AppColors.primary,
          size: 20,
        ),
        const SizedBox(height: AppSpacing.xs),
        Text(
          label,
          style: AppTextStyles.fieldLabel.copyWith(fontSize: 11),
        ),
        const SizedBox(height: 2),
        Text(
          isUnread ? '—' : value,
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w600,
            color: isUnread ? AppColors.textTertiary : AppColors.textPrimary,
          ),
          textAlign: TextAlign.center,
        ),
      ],
    );
  }

  Widget _buildMedicineDetails(MedicineDetail medicine) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Side Effects (Urdu only, when present)
        if (medicine.sideEffectsUrduShort != null && medicine.sideEffectsUrduShort!.isNotEmpty)
          _buildUrduSummaryField('SIDE EFFECTS', medicine.sideEffectsUrduShort!, isWarning: true),
        
        // Precautions (Urdu only, when present)
        if (medicine.precautionsUrduShort != null && medicine.precautionsUrduShort!.isNotEmpty)
          _buildUrduSummaryField('PRECAUTIONS', medicine.precautionsUrduShort!, isWarning: true),
      ],
    );
  }

  Widget _buildDetailField(String label, String value, IconData icon, {bool isWarning = false}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                icon,
                size: 16,
                color: isWarning ? AppColors.warning : AppColors.textSecondary,
              ),
              const SizedBox(width: AppSpacing.xs),
              Text(label.toUpperCase(), style: AppTextStyles.fieldLabel),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Text(
            value,
            style: AppTextStyles.fieldValue.copyWith(
              color: isWarning ? AppColors.textPrimary : AppColors.textPrimary,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildUrduSummaryField(String label, String urduText, {bool isWarning = false}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.translate,
                size: 16,
                color: isWarning ? AppColors.warning : AppColors.textSecondary,
              ),
              const SizedBox(width: AppSpacing.xs),
              Text(label.toUpperCase(), style: AppTextStyles.fieldLabel),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(AppSpacing.sm),
            decoration: BoxDecoration(
              color: isWarning 
                  ? AppColors.warning.withOpacity(0.05)
                  : AppColors.urduBackground,
              borderRadius: BorderRadius.circular(AppRadius.sm),
              border: Border.all(
                color: isWarning 
                    ? AppColors.warning.withOpacity(0.2)
                    : Colors.amber.shade200,
              ),
            ),
            child: Directionality(
              textDirection: TextDirection.rtl,
              child: Text(
                urduText,
                style: AppTextStyles.urduText.copyWith(
                  fontSize: 15,
                  height: 1.8,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildUrduSection(MedicineAudioResult audioResult) {
    final isPlaying = _currentlyPlayingUrl == audioResult.audioUrl;
    
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(Icons.translate, size: 18, color: AppColors.textSecondary),
            const SizedBox(width: AppSpacing.xs),
            Text('URDU INSTRUCTIONS', style: AppTextStyles.fieldLabel),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        
        // Urdu text with special background
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(AppSpacing.md),
          decoration: BoxDecoration(
            color: AppColors.urduBackground,
            borderRadius: BorderRadius.circular(AppRadius.sm),
            border: Border.all(color: Colors.amber.shade200),
          ),
          child: Directionality(
            textDirection: TextDirection.rtl,
            child: Text(
              audioResult.urduText,
              style: AppTextStyles.urduText,
            ),
          ),
        ),
        
        // Audio playback button
        if (audioResult.audioGenerated && audioResult.audioUrl != null) ...[
          const SizedBox(height: AppSpacing.sm),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: () => _playAudio(audioResult.audioUrl!),
              icon: Icon(isPlaying ? Icons.stop : Icons.play_arrow),
              label: Text(isPlaying ? 'Stop Audio' : 'Play Audio'),
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
              ),
            ),
          ),
        ] else ...[
          const SizedBox(height: AppSpacing.sm),
          Text(
            'Audio unavailable for this medicine',
            style: AppTextStyles.bodySmall.copyWith(
              fontStyle: FontStyle.italic,
              color: AppColors.textTertiary,
            ),
          ),
        ],
      ],
    );
  }
}
