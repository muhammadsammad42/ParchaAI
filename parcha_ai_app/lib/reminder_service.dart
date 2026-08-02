import 'package:flutter/material.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:timezone/timezone.dart' as tz;
import 'package:timezone/data/latest_all.dart' as tz;
import 'package:shared_preferences/shared_preferences.dart';

import 'models.dart';

/// Service for scheduling medicine reminder notifications
class ReminderService {
  static final ReminderService _instance = ReminderService._internal();
  factory ReminderService() => _instance;
  ReminderService._internal();

  final FlutterLocalNotificationsPlugin _notificationsPlugin =
      FlutterLocalNotificationsPlugin();

  bool _initialized = false;

  /// Initialize the notification service
  Future<void> initialize() async {
    if (_initialized) return;

    // Initialize timezone data
    tz.initializeTimeZones();
    
    // Find user's local timezone
    final String timeZoneName = DateTime.now().timeZoneName;
    try {
      tz.setLocalLocation(tz.getLocation(timeZoneName));
    } catch (e) {
      // Fallback to UTC if timezone not found
      tz.setLocalLocation(tz.getLocation('UTC'));
    }

    const androidSettings = AndroidInitializationSettings('@mipmap/ic_launcher');
    const iosSettings = DarwinInitializationSettings(
      requestAlertPermission: false,
      requestBadgePermission: false,
      requestSoundPermission: false,
    );

    const settings = InitializationSettings(
      android: androidSettings,
      iOS: iosSettings,
    );

    await _notificationsPlugin.initialize(settings);
    _initialized = true;
  }

  /// Request notification permissions (Android 13+)
  Future<bool> requestPermissions() async {
    if (!_initialized) await initialize();

    final androidPlugin =
        _notificationsPlugin.resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>();

    if (androidPlugin != null) {
      // Request notification permission (Android 13+)
      final granted = await androidPlugin.requestNotificationsPermission();
      if (granted != true) return false;

      // Request exact alarm permission (Android 12+)
      final exactAlarmGranted = await androidPlugin.requestExactAlarmsPermission();

    }

    return true;
  }

  /// Check if PRN/as-needed medicine (should NOT schedule automatic reminders)
  bool _isPrnMedicine(String frequency) {
    final freq = frequency.toLowerCase();
    const prnKeywords = ['sos', 'prn', 'as needed', 'when needed', 'ضرورت'];
    return prnKeywords.any((keyword) => freq.contains(keyword));
  }

  /// Parse frequency string into list of reminder times
  /// Returns null if frequency is PRN or unparseable
  List<TimeOfDay>? parseFrequencyToTimes(String frequency) {
    if (frequency == 'unread' || frequency.trim().isEmpty) {
      return null;
    }

    // Check for PRN/as-needed patterns first
    if (_isPrnMedicine(frequency)) {
      return null; // Don't schedule automatic reminders for PRN medicines
    }

    final freq = frequency.toLowerCase();
    
    // Four times daily patterns (check FIRST - most specific)
    if (freq.contains('four times daily') ||
        freq.contains('1-1-1-1') ||
        freq == 'qid') {
      return [
        const TimeOfDay(hour: 8, minute: 0), // Breakfast
        const TimeOfDay(hour: 13, minute: 0), // Lunch
        const TimeOfDay(hour: 18, minute: 0), // Dinner
        const TimeOfDay(hour: 22, minute: 0), // Bedtime
      ];
    }

    // Three times daily patterns (check SECOND)
    if (freq.contains('three times daily') ||
        freq.contains('1-1-1') ||
        freq == 'tid' ||
        freq == 'tds' ||
        freq.contains('تین بار')) {
      return [
        const TimeOfDay(hour: 9, minute: 0), // Morning
        const TimeOfDay(hour: 14, minute: 0), // Afternoon
        const TimeOfDay(hour: 21, minute: 0), // Night
      ];
    }

    // Twice daily patterns (check THIRD)
    if (freq.contains('twice daily') ||
        freq.contains('1-0-1') ||
        freq == 'bd' ||
        freq == 'bid' ||
        freq.contains('دو بار')) {
      return [
        const TimeOfDay(hour: 9, minute: 0), // Morning
        const TimeOfDay(hour: 21, minute: 0), // Night
      ];
    }

    // Once daily patterns (check LAST - most general)
    if (freq.contains('once daily') ||
        freq.contains('1-0-0') ||
        freq == 'od' ||
        freq == 'qd' ||
        freq.contains('ایک بار')) {
      return [const TimeOfDay(hour: 9, minute: 0)];
    }

    // Unparseable - return null to skip scheduling
    return null;
  }

  /// Parse duration string into number of days
  /// Returns default of 7 days if unparseable
  int parseDurationToDays(String duration) {
    if (duration == 'unread' || duration.trim().isEmpty) {
      return 7; // Default cap
    }

    final durationLower = duration.toLowerCase();

    // Try to extract number and unit
    final dayPattern = RegExp(r'(\d+)\s*(day|days|روز)');
    final weekPattern = RegExp(r'(\d+)\s*(week|weeks|ہفتہ)');

    final dayMatch = dayPattern.firstMatch(durationLower);
    if (dayMatch != null) {
      return int.tryParse(dayMatch.group(1)!) ?? 7;
    }

    final weekMatch = weekPattern.firstMatch(durationLower);
    if (weekMatch != null) {
      final weeks = int.tryParse(weekMatch.group(1)!) ?? 1;
      return weeks * 7;
    }

    // Unparseable - use default cap
    return 7;
  }

  /// Schedule reminders for a medicine
  /// Returns true if scheduled successfully, false otherwise
  Future<bool> scheduleMedicineReminders({
    required String prescriptionId,
    required MedicineDetail medicine,
    required int medicineIndex,
  }) async {
    if (!_initialized) await initialize();

    // Parse frequency
    final times = parseFrequencyToTimes(medicine.frequency);
    if (times == null || times.isEmpty) {
      debugPrint('Skipping reminders for ${medicine.medicineName}: '
          'frequency is PRN or unparseable (${medicine.frequency})');
      return false;
    }

    // Parse duration
    final durationDays = parseDurationToDays(medicine.duration);

    // Generate notification ID base (unique per medicine)
    final idBase = prescriptionId.hashCode + medicineIndex * 1000;

    // Get current time
    final now = tz.TZDateTime.now(tz.local);

    // Schedule for each time slot
    int scheduledCount = 0;
    for (int timeIndex = 0; timeIndex < times.length; timeIndex++) {
      final time = times[timeIndex];

      // Schedule for each day in the duration
      for (int dayOffset = 0; dayOffset < durationDays; dayOffset++) {
        final scheduledDate = tz.TZDateTime(
          tz.local,
          now.year,
          now.month,
          now.day + dayOffset,
          time.hour,
          time.minute,
        );

        // Only schedule if the time is in the future
        if (scheduledDate.isAfter(now)) {
          final notificationId = idBase + timeIndex * 100 + dayOffset;

          await _notificationsPlugin.zonedSchedule(
            notificationId,
            'وقت ہو گیا ہے', 
            '${medicine.medicineName} لینے کا', 
            scheduledDate,
            NotificationDetails(
              android: AndroidNotificationDetails(
                'medicine_reminders',
                'Medicine Reminders',
                channelDescription: 'Reminders to take prescribed medicines',
                importance: Importance.high,
                priority: Priority.high,
                icon: '@mipmap/ic_launcher',
              ),
              iOS: const DarwinNotificationDetails(
                presentAlert: true,
                presentBadge: true,
                presentSound: true,
              ),
            ),
            androidScheduleMode: AndroidScheduleMode.exactAllowWhileIdle,
            uiLocalNotificationDateInterpretation:
                UILocalNotificationDateInterpretation.absoluteTime,
          );

          scheduledCount++;
        }
      }
    }

    // Save reminder state
    await _saveReminderState(prescriptionId, medicineIndex, true);

    debugPrint('Scheduled $scheduledCount reminders for ${medicine.medicineName}');
    return scheduledCount > 0;
  }

  /// Cancel all reminders for a specific medicine
  Future<void> cancelMedicineReminders({
    required String prescriptionId,
    required int medicineIndex,
  }) async {
    final idBase = prescriptionId.hashCode + medicineIndex * 1000;

    // Cancel all possible notification IDs for this medicine
    // (up to 4 times/day × 30 days max = 120 notifications)
    for (int i = 0; i < 500; i++) {
      await _notificationsPlugin.cancel(idBase + i);
    }

    // Clear reminder state
    await _saveReminderState(prescriptionId, medicineIndex, false);

    debugPrint('Cancelled reminders for prescription $prescriptionId, medicine $medicineIndex');
  }

  /// Check if reminders are set for a medicine
  Future<bool> hasReminders(String prescriptionId, int medicineIndex) async {
    final prefs = await SharedPreferences.getInstance();
    final key = 'reminder_${prescriptionId}_$medicineIndex';
    return prefs.getBool(key) ?? false;
  }

  /// Save reminder state
  Future<void> _saveReminderState(
      String prescriptionId, int medicineIndex, bool enabled) async {
    final prefs = await SharedPreferences.getInstance();
    final key = 'reminder_${prescriptionId}_$medicineIndex';
    await prefs.setBool(key, enabled);
  }

  /// Cancel all reminders for a prescription
  Future<void> cancelPrescriptionReminders(String prescriptionId) async {
    // Cancel up to 10 medicines per prescription
    for (int medicineIndex = 0; medicineIndex < 10; medicineIndex++) {
      await cancelMedicineReminders(
        prescriptionId: prescriptionId,
        medicineIndex: medicineIndex,
      );
    }
  }
}
