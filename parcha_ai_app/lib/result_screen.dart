import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';

import 'api_service.dart';
import 'models.dart';
import 'reminder_service.dart';
import 'theme.dart';

class ResultScreen extends StatefulWidget {
  final String prescriptionId;

  const ResultScreen({
    super.key,
    required this.prescriptionId,
  });

  @override
  State<ResultScreen> createState() => _ResultScreenState();
}

class _ResultScreenState extends State<ResultScreen> {
  final ApiService _api = ApiService();
  final AudioPlayer _audioPlayer = AudioPlayer();
  final ReminderService _reminderService = ReminderService();

  bool _isLoading = true;
  String? _errorMessage;
  PrescriptionResult? _result;
  String? _currentlyPlayingUrl;
  
  // Track reminder state per medicine
  Map<int, bool> _reminderStates = {};

  @override
  void initState() {
    super.initState();
    _reminderService.initialize();
    _loadResult();
  }

  @override
  void dispose() {
    _audioPlayer.dispose();
    super.dispose();
  }

  Future<void> _loadResult() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final result = await _api.getResult(widget.prescriptionId);
      if (!mounted) return;
      
      // Load reminder states
      final reminderStates = <int, bool>{};
      final medicines = result.extractionResponse?.extractedMedicines ?? [];
      for (int i = 0; i < medicines.length; i++) {
        reminderStates[i] = await _reminderService.hasReminders(
          widget.prescriptionId,
          i,
        );
      }
      
      setState(() {
        _result = result;
        _reminderStates = reminderStates;
        _isLoading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = e.userMessage;
        _isLoading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = 'Failed to load result: $e';
        _isLoading = false;
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

  Future<void> _toggleReminders(MedicineDetail medicine, int medicineIndex) async {
    final currentlyEnabled = _reminderStates[medicineIndex] ?? false;

    if (!currentlyEnabled) {
      // Request permissions first
      final granted = await _reminderService.requestPermissions();
      if (!granted) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text(
              'Notification permission is required to set reminders. '
              'Please enable notifications in your device settings.',
            ),
            duration: Duration(seconds: 4),
          ),
        );
        return;
      }

      // Schedule reminders
      final scheduled = await _reminderService.scheduleMedicineReminders(
        prescriptionId: widget.prescriptionId,
        medicine: medicine,
        medicineIndex: medicineIndex,
      );

      if (!mounted) return;

      if (scheduled) {
        setState(() {
          _reminderStates[medicineIndex] = true;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Reminders set for ${medicine.medicineName}'),
            backgroundColor: AppColors.success,
          ),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Could not schedule reminders for ${medicine.medicineName}. '
              'Frequency may be "as needed" or unparseable.',
            ),
            backgroundColor: AppColors.warning,
            duration: const Duration(seconds: 4),
          ),
        );
      }
    } else {
      // Cancel reminders
      await _reminderService.cancelMedicineReminders(
        prescriptionId: widget.prescriptionId,
        medicineIndex: medicineIndex,
      );

      if (!mounted) return;

      setState(() {
        _reminderStates[medicineIndex] = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Reminders cancelled for ${medicine.medicineName}'),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Row(
          children: [
            Icon(Icons.medical_services, color: AppColors.textOnPrimary),
            SizedBox(width: AppSpacing.sm),
            Text('Prescription Details'),
          ],
        ),
      ),
      body: SafeArea(
        child: _buildBody(),
      ),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            CircularProgressIndicator(),
            SizedBox(height: AppSpacing.md),
            Text('Loading prescription...', style: AppTextStyles.bodyMedium),
          ],
        ),
      );
    }

    if (_errorMessage != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                Icons.error_outline,
                size: 64,
                color: AppColors.error,
              ),
              const SizedBox(height: AppSpacing.md),
              Text(
                'Error',
                style: AppTextStyles.h2.copyWith(color: AppColors.error),
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                _errorMessage!,
                style: AppTextStyles.bodyMedium,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: AppSpacing.lg),
              ElevatedButton.icon(
                onPressed: _loadResult,
                icon: const Icon(Icons.refresh),
                label: const Text('Retry'),
              ),
            ],
          ),
        ),
      );
    }

    if (_result == null) {
      return const Center(
        child: Text('No result available', style: AppTextStyles.bodyMedium),
      );
    }

    return ListView(
      padding: const EdgeInsets.all(AppSpacing.md),
      children: [
        _buildResults(_result!),
      ],
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
            child: _buildMedicineCard(medicine, audioResult, index),
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

  Widget _buildMedicineCard(MedicineDetail medicine, MedicineAudioResult? audioResult, int medicineIndex) {
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
                  _buildUrduSection(audioResult, medicine, medicineIndex),
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

  Widget _buildUrduSection(MedicineAudioResult audioResult, MedicineDetail medicine, int medicineIndex) {
    final isPlaying = _currentlyPlayingUrl == audioResult.audioUrl;
    final reminderEnabled = _reminderStates[medicineIndex] ?? false;
    
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
        
        // Medicine reminder button (NEW)
        const SizedBox(height: AppSpacing.sm),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton.icon(
            onPressed: () => _toggleReminders(medicine, medicineIndex),
            icon: Icon(reminderEnabled ? Icons.notifications_off : Icons.notifications_active),
            label: Text(reminderEnabled ? 'Cancel Reminders' : 'Set Reminders'),
            style: ElevatedButton.styleFrom(
              backgroundColor: reminderEnabled ? AppColors.textSecondary : AppColors.primary,
              foregroundColor: AppColors.textOnPrimary,
              padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
            ),
          ),
        ),
        
        // Reminder info text
        if (!reminderEnabled) ...[
          const SizedBox(height: AppSpacing.xs),
          Text(
            'Get notifications to take this medicine on time',
            style: AppTextStyles.bodySmall.copyWith(
              color: AppColors.textTertiary,
              fontStyle: FontStyle.italic,
            ),
            textAlign: TextAlign.center,
          ),
        ],
      ],
    );
  }
}
