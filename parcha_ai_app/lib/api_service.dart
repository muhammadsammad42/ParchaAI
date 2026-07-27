
import 'dart:convert';
import 'dart:io';
import 'dart:async';

import 'package:http/http.dart' as http;

import 'models.dart';

class ApiException implements Exception {
  final int statusCode;
  final String message;
  ApiException(this.statusCode, this.message);

  @override
  String toString() => 'ApiException($statusCode): $message';
  
  String get userMessage {
    if (statusCode == 409) {
      return 'Prescription is still being processed. Please wait a moment.';
    } else if (statusCode == 404) {
      return 'Prescription not found. It may have been deleted.';
    } else if (statusCode == 400) {
      return message.contains('extension')
          ? 'Please upload a valid image file (JPG, JPEG, or PNG).'
          : message.contains('size')
              ? 'Image file is too large. Please use an image under 10 MB.'
              : 'Invalid upload: $message';
    } else if (statusCode == 500) {
      return 'Server error: $message';
    } else if (statusCode >= 500) {
      return 'Server is experiencing issues. Please try again later.';
    } else {
      return message;
    }
  }
}

class ApiService {

  static const String baseUrl = "http://192.168.100.8:8000";
  
  static const Duration requestTimeout = Duration(seconds: 30);

  /// Checks if the backend server is healthy and reachable
  Future<bool> checkHealth() async {
    try {
      final uri = Uri.parse('$baseUrl/health');
      final response = await http.get(uri).timeout(
        const Duration(seconds: 5),
        onTimeout: () => http.Response('Timeout', 408),
      );
      
      if (response.statusCode == 200) {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        return body['status'] == 'ok';
      }
      return false;
    } catch (e) {
      return false;
    }
  }

  /// Uploads a prescription image file. Returns the new prescription_id.
  Future<String> uploadPrescription(File imageFile) async {
    try {
      final uri = Uri.parse('$baseUrl/upload');
      final request = http.MultipartRequest('POST', uri);
      request.files.add(await http.MultipartFile.fromPath('file', imageFile.path));

      final streamedResponse = await request.send().timeout(requestTimeout);
      final response = await http.Response.fromStream(streamedResponse);

      if (response.statusCode != 200) {
        throw ApiException(response.statusCode, _extractDetail(response.body));
      }

      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return body['prescription_id'] as String;
    } on SocketException {
      throw ApiException(
        0,
        'Cannot connect to server. Please check:\n'
        '1. Backend is running (uvicorn, Redis, Celery worker)\n'
        '2. Phone and laptop are on same Wi-Fi\n'
        '3. Base URL is set to laptop\'s LAN IP',
      );
    } on TimeoutException {
      throw ApiException(408, 'Upload timed out. Please check your internet connection.');
    } catch (e) {
      if (e is ApiException) rethrow;
      throw ApiException(0, 'Upload failed: $e');
    }
  }

  Future<PrescriptionStatus> getStatus(String prescriptionId) async {
    try {
      final uri = Uri.parse('$baseUrl/status/$prescriptionId');
      final response = await http.get(uri).timeout(requestTimeout);

      if (response.statusCode != 200) {
        throw ApiException(response.statusCode, _extractDetail(response.body));
      }

      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return statusFromString(body['status'] as String?);
    } on SocketException {
      throw ApiException(0, 'Lost connection to server');
    } on TimeoutException {
      throw ApiException(408, 'Status check timed out');
    } catch (e) {
      if (e is ApiException) rethrow;
      throw ApiException(0, 'Status check failed: $e');
    }
  }

  Future<PrescriptionResult> getResult(String prescriptionId) async {
    try {
      final uri = Uri.parse('$baseUrl/result/$prescriptionId');
      final response = await http.get(uri).timeout(requestTimeout);

      if (response.statusCode == 409) {
        throw ApiException(
          409,
          'Prescription is still being processed. This is a client bug - '
          'getResult() should only be called after status is "done".',
        );
      }

      if (response.statusCode != 200) {
        throw ApiException(response.statusCode, _extractDetail(response.body));
      }

      final body = jsonDecode(response.body) as Map<String, dynamic>;
      return PrescriptionResult.fromJson(body);
    } on SocketException {
      throw ApiException(0, 'Lost connection to server');
    } on TimeoutException {
      throw ApiException(408, 'Result fetch timed out');
    } catch (e) {
      if (e is ApiException) rethrow;
      throw ApiException(0, 'Failed to fetch result: $e');
    }
  }

  Future<PrescriptionResult> uploadAndWaitForResult(
    File imageFile, {
    Duration interval = const Duration(seconds: 2),
    Duration timeout = const Duration(minutes: 3),
    void Function(PrescriptionStatus status)? onStatusUpdate,
  }) async {
    final id = await uploadPrescription(imageFile);
    final deadline = DateTime.now().add(timeout);

    while (DateTime.now().isBefore(deadline)) {
      final status = await getStatus(id);
      onStatusUpdate?.call(status);

      if (status == PrescriptionStatus.done) {
        return getResult(id);
      }
      if (status == PrescriptionStatus.failed) {
        try {
          await getResult(id);
        } catch (e) {
          if (e is ApiException && e.statusCode == 500) {
            throw ApiException(
              500,
              'Processing failed on the server. The prescription image may be '
              'unreadable or the backend encountered an error: ${e.message}',
            );
          }
        }
        throw ApiException(
          500,
          'Processing failed on the server for prescription $id. '
          'Please try again with a clearer image.',
        );
      }
      await Future.delayed(interval);
    }

    throw ApiException(
      408,
      'Processing timed out after ${timeout.inMinutes} minutes. '
      'This usually means the prescription is very complex or the backend is overloaded.',
    );
  }

  String _extractDetail(String responseBody) {
    try {
      final decoded = jsonDecode(responseBody);
      if (decoded is Map && decoded.containsKey('detail')) {
        return decoded['detail'].toString();
      }
    } catch (_) {
    }
    return responseBody;
  }
}
