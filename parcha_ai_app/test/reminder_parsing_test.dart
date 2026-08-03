import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:parcha_ai_app/reminder_service.dart';

void main() {
  late ReminderService reminderService;

  setUp(() {
    reminderService = ReminderService();
  });

  group('Frequency Parsing Tests', () {
    test('Once daily patterns', () {
      expect(
        reminderService.parseFrequencyToTimes('once daily'),
        [const TimeOfDay(hour: 9, minute: 0)],
      );
      expect(
        reminderService.parseFrequencyToTimes('once a day'),
        [const TimeOfDay(hour: 9, minute: 0)],
      );
      expect(
        reminderService.parseFrequencyToTimes('1-0-0'),
        [const TimeOfDay(hour: 9, minute: 0)],
      );
      expect(
        reminderService.parseFrequencyToTimes('od'),
        [const TimeOfDay(hour: 9, minute: 0)],
      );
      expect(
        reminderService.parseFrequencyToTimes('ایک بار'),
        [const TimeOfDay(hour: 9, minute: 0)],
      );
      // Real-world: with context in parentheses
      expect(
        reminderService.parseFrequencyToTimes('Once daily (morning)'),
        [const TimeOfDay(hour: 9, minute: 0)],
      );
      expect(
        reminderService.parseFrequencyToTimes('Once daily (at night)'),
        [const TimeOfDay(hour: 9, minute: 0)],
      );
    });

    test('Twice daily patterns', () {
      final expected = [
        const TimeOfDay(hour: 9, minute: 0),
        const TimeOfDay(hour: 21, minute: 0),
      ];
      expect(reminderService.parseFrequencyToTimes('twice daily'), expected);
      expect(reminderService.parseFrequencyToTimes('twice a day'), expected);
      expect(reminderService.parseFrequencyToTimes('2 times daily'), expected);
      expect(reminderService.parseFrequencyToTimes('2 times a day'), expected);
      expect(reminderService.parseFrequencyToTimes('1-0-1'), expected);
      expect(reminderService.parseFrequencyToTimes('bd'), expected);
      expect(reminderService.parseFrequencyToTimes('دو بار'), expected);
      // Real-world: every 12 hours
      expect(reminderService.parseFrequencyToTimes('Every 12 hours'), expected);
      // Real-world: with context in parentheses
      expect(reminderService.parseFrequencyToTimes('Twice daily (after food)'), expected);
      expect(reminderService.parseFrequencyToTimes('Twice daily (before food)'), expected);
    });

    test('Three times daily patterns', () {
      final expected = [
        const TimeOfDay(hour: 9, minute: 0),
        const TimeOfDay(hour: 14, minute: 0),
        const TimeOfDay(hour: 21, minute: 0),
      ];
      expect(reminderService.parseFrequencyToTimes('three times daily'), expected);
      expect(reminderService.parseFrequencyToTimes('three times a day'), expected);
      expect(reminderService.parseFrequencyToTimes('3 times daily'), expected);
      expect(reminderService.parseFrequencyToTimes('3 times a day'), expected);
      expect(reminderService.parseFrequencyToTimes('1-1-1'), expected);
      expect(reminderService.parseFrequencyToTimes('tid'), expected);
      expect(reminderService.parseFrequencyToTimes('تین بار'), expected);
      // Real-world: every 8 hours
      expect(reminderService.parseFrequencyToTimes('Every 8 hours'), expected);
      // Real-world: with context
      expect(reminderService.parseFrequencyToTimes('Three times daily (with meals)'), expected);
    });

    test('Four times daily patterns', () {
      final expected = [
        const TimeOfDay(hour: 8, minute: 0),
        const TimeOfDay(hour: 13, minute: 0),
        const TimeOfDay(hour: 18, minute: 0),
        const TimeOfDay(hour: 22, minute: 0),
      ];
      expect(reminderService.parseFrequencyToTimes('four times daily'), expected);
      expect(reminderService.parseFrequencyToTimes('four times a day'), expected);
      expect(reminderService.parseFrequencyToTimes('4 times daily'), expected);
      expect(reminderService.parseFrequencyToTimes('4 times a day'), expected);
      expect(reminderService.parseFrequencyToTimes('1-1-1-1'), expected);
      expect(reminderService.parseFrequencyToTimes('qid'), expected);
      // Real-world: every 6 hours
      expect(reminderService.parseFrequencyToTimes('Every 6 hours'), expected);
    });

    test('PRN/As-needed patterns - should return null', () {
      expect(reminderService.parseFrequencyToTimes('sos'), isNull);
      expect(reminderService.parseFrequencyToTimes('SOS'), isNull);
      expect(reminderService.parseFrequencyToTimes('prn'), isNull);
      expect(reminderService.parseFrequencyToTimes('as needed'), isNull);
      expect(reminderService.parseFrequencyToTimes('when needed'), isNull);
      expect(reminderService.parseFrequencyToTimes('ضرورت'), isNull);
    });

    test('Unparseable patterns - should return null', () {
      expect(reminderService.parseFrequencyToTimes('unread'), isNull);
      expect(reminderService.parseFrequencyToTimes(''), isNull);
      expect(reminderService.parseFrequencyToTimes('random text'), isNull);
      expect(reminderService.parseFrequencyToTimes('xyz-123'), isNull);
    });

    test('Case insensitivity', () {
      expect(
        reminderService.parseFrequencyToTimes('ONCE DAILY'),
        [const TimeOfDay(hour: 9, minute: 0)],
      );
      expect(
        reminderService.parseFrequencyToTimes('Twice Daily'),
        [
          const TimeOfDay(hour: 9, minute: 0),
          const TimeOfDay(hour: 21, minute: 0),
        ],
      );
      expect(
        reminderService.parseFrequencyToTimes('THREE TIMES A DAY'),
        [
          const TimeOfDay(hour: 9, minute: 0),
          const TimeOfDay(hour: 14, minute: 0),
          const TimeOfDay(hour: 21, minute: 0),
        ],
      );
      expect(
        reminderService.parseFrequencyToTimes('EVERY 6 HOURS'),
        [
          const TimeOfDay(hour: 8, minute: 0),
          const TimeOfDay(hour: 13, minute: 0),
          const TimeOfDay(hour: 18, minute: 0),
          const TimeOfDay(hour: 22, minute: 0),
        ],
      );
    });
  });

  group('Duration Parsing Tests', () {
    test('Day patterns', () {
      expect(reminderService.parseDurationToDays('5 days'), 5);
      expect(reminderService.parseDurationToDays('7 days'), 7);
      expect(reminderService.parseDurationToDays('10 days'), 10);
      expect(reminderService.parseDurationToDays('1 day'), 1);
      expect(reminderService.parseDurationToDays('3روز'), 3); // Urdu
    });

    test('Week patterns', () {
      expect(reminderService.parseDurationToDays('1 week'), 7);
      expect(reminderService.parseDurationToDays('2 weeks'), 14);
      expect(reminderService.parseDurationToDays('3 weeks'), 21);
      expect(reminderService.parseDurationToDays('1ہفتہ'), 7); // Urdu
    });

    test('Default cap for unparseable duration', () {
      expect(reminderService.parseDurationToDays('unread'), 7);
      expect(reminderService.parseDurationToDays(''), 7);
      expect(reminderService.parseDurationToDays('ongoing'), 7);
      expect(reminderService.parseDurationToDays('xyz'), 7);
    });

    test('Spacing variations', () {
      expect(reminderService.parseDurationToDays('5days'), 5);
      expect(reminderService.parseDurationToDays('5  days'), 5);
      expect(reminderService.parseDurationToDays('2week'), 14);
    });
  });
}
