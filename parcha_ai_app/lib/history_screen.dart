import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import 'api_service.dart';
import 'models.dart';
import 'result_screen.dart';
import 'theme.dart';

class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key});

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  final ApiService _api = ApiService();
  
  bool _isLoading = true;
  String? _errorMessage;
  List<PrescriptionHistoryItem> _prescriptions = [];

  @override
  void initState() {
    super.initState();
    _loadPrescriptions();
  }

  Future<void> _loadPrescriptions() async {
    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final prescriptions = await _api.getPrescriptions();
      if (!mounted) return;
      setState(() {
        _prescriptions = prescriptions;
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
        _errorMessage = 'Failed to load prescriptions: $e';
        _isLoading = false;
      });
    }
  }

  void _navigateToResult(String prescriptionId, PrescriptionStatus status) {
    if (status == PrescriptionStatus.done) {
      Navigator.push(
        context,
        MaterialPageRoute(
          builder: (context) => ResultScreen(prescriptionId: prescriptionId),
        ),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(_getStatusMessage(status)),
          backgroundColor: _getStatusColor(status),
        ),
      );
    }
  }

  String _getStatusMessage(PrescriptionStatus status) {
    switch (status) {
      case PrescriptionStatus.pending:
        return 'This prescription is still waiting to be processed';
      case PrescriptionStatus.processing:
        return 'This prescription is currently being processed';
      case PrescriptionStatus.failed:
        return 'This prescription failed to process';
      case PrescriptionStatus.done:
        return 'Ready to view';
      case PrescriptionStatus.unknown:
        return 'Status unknown';
    }
  }

  Color _getStatusColor(PrescriptionStatus status) {
    switch (status) {
      case PrescriptionStatus.done:
        return AppColors.success;
      case PrescriptionStatus.processing:
        return AppColors.info;
      case PrescriptionStatus.pending:
        return AppColors.warning;
      case PrescriptionStatus.failed:
        return AppColors.error;
      case PrescriptionStatus.unknown:
        return AppColors.textSecondary;
    }
  }

  IconData _getStatusIcon(PrescriptionStatus status) {
    switch (status) {
      case PrescriptionStatus.done:
        return Icons.check_circle;
      case PrescriptionStatus.processing:
        return Icons.hourglass_empty;
      case PrescriptionStatus.pending:
        return Icons.schedule;
      case PrescriptionStatus.failed:
        return Icons.error;
      case PrescriptionStatus.unknown:
        return Icons.help_outline;
    }
  }

  String _getStatusLabel(PrescriptionStatus status) {
    switch (status) {
      case PrescriptionStatus.done:
        return 'Done';
      case PrescriptionStatus.processing:
        return 'Processing';
      case PrescriptionStatus.pending:
        return 'Pending';
      case PrescriptionStatus.failed:
        return 'Failed';
      case PrescriptionStatus.unknown:
        return 'Unknown';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Row(
          children: [
            Icon(Icons.history, color: AppColors.textOnPrimary),
            SizedBox(width: AppSpacing.sm),
            Text('Prescription History'),
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
            Text('Loading prescriptions...', style: AppTextStyles.bodyMedium),
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
                onPressed: _loadPrescriptions,
                icon: const Icon(Icons.refresh),
                label: const Text('Retry'),
              ),
            ],
          ),
        ),
      );
    }

    if (_prescriptions.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(
                Icons.inbox_outlined,
                size: 80,
                color: AppColors.textTertiary,
              ),
              const SizedBox(height: AppSpacing.md),
              Text(
                'No prescriptions yet',
                style: AppTextStyles.h2.copyWith(color: AppColors.textSecondary),
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                'Upload your first prescription to get started',
                style: AppTextStyles.bodyMedium.copyWith(
                  color: AppColors.textTertiary,
                ),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: _loadPrescriptions,
      child: ListView.builder(
        padding: const EdgeInsets.all(AppSpacing.md),
        itemCount: _prescriptions.length,
        itemBuilder: (context, index) {
          final prescription = _prescriptions[index];
          return Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.md),
            child: _buildPrescriptionCard(prescription),
          );
        },
      ),
    );
  }

  Widget _buildPrescriptionCard(PrescriptionHistoryItem prescription) {
    final statusColor = _getStatusColor(prescription.status);
    final statusIcon = _getStatusIcon(prescription.status);
    final statusLabel = _getStatusLabel(prescription.status);
    
    return Card(
      elevation: 2,
      child: InkWell(
        onTap: () => _navigateToResult(prescription.prescriptionId, prescription.status),
        borderRadius: BorderRadius.circular(AppRadius.md),
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Row(
            children: [
              // Status indicator circle
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  color: statusColor.withOpacity(0.1),
                  shape: BoxShape.circle,
                ),
                child: Icon(
                  statusIcon,
                  color: statusColor,
                  size: 28,
                ),
              ),
              
              const SizedBox(width: AppSpacing.md),
              
              // Prescription info
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Date and time (converted from UTC to PKT)
                    Text(
                      prescription.createdAt != null
                          ? _formatPktTime(prescription.createdAt!)
                          : 'Date unknown',
                      style: AppTextStyles.bodyMedium.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    
                    const SizedBox(height: AppSpacing.xs),
                    
                    // Status badge
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: AppSpacing.sm,
                        vertical: AppSpacing.xs,
                      ),
                      decoration: BoxDecoration(
                        color: statusColor,
                        borderRadius: BorderRadius.circular(AppRadius.sm),
                      ),
                      child: Text(
                        statusLabel,
                        style: AppTextStyles.badge.copyWith(fontSize: 11),
                      ),
                    ),
                    
                    const SizedBox(height: AppSpacing.xs),
                    
                    // Prescription ID (truncated)
                    Text(
                      'ID: ${prescription.prescriptionId.substring(0, 8)}...',
                      style: AppTextStyles.bodySmall.copyWith(
                        color: AppColors.textTertiary,
                        fontFamily: 'monospace',
                      ),
                    ),
                  ],
                ),
              ),
              
              // Arrow icon
              Icon(
                Icons.chevron_right,
                color: prescription.status == PrescriptionStatus.done
                    ? AppColors.primary
                    : AppColors.textTertiary,
              ),
            ],
          ),
        ),
      ),
    );
  }

  /// Convert UTC time to Pakistan Standard Time (PKT = UTC+5) for display
  String _formatPktTime(DateTime utcTime) {
    // Ensure the input is treated as UTC
    final DateTime utc = utcTime.isUtc ? utcTime : DateTime.utc(
      utcTime.year,
      utcTime.month,
      utcTime.day,
      utcTime.hour,
      utcTime.minute,
      utcTime.second,
    );
    
    final DateTime pktTime = utc.add(const Duration(hours: 5));
    
    // Format for display
    return DateFormat('MMM dd, yyyy • h:mm a').format(pktTime);
  }
}
