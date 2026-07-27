# ParchaAI Flutter App - Setup & Testing Guide

## Overview

This is the patient-facing mobile app for ParchaAI. It allows users to photograph handwritten prescriptions and receive structured medicine information with Urdu audio instructions.

## Prerequisites

1. **Flutter SDK** (3.0.0 or higher)
   - [Installation guide](https://docs.flutter.dev/get-started/install)
   - Verify: `flutter doctor`

2. **Backend must be running:**
   - Redis server
   - Celery worker: `celery -A parcha_ai.celery_app worker --loglevel=info --concurrency=2`
   - FastAPI server: `uvicorn parcha_ai.api:app --host 0.0.0.0 --port 8000`

3. **For physical device testing:**
   - Phone and laptop on the **same Wi-Fi network**
   - USB debugging enabled on Android / development mode on iOS

## Initial Setup

### 1. Install Dependencies

```bash
cd parcha_ai_app
flutter pub get
```

This will install all required packages:
- `http` - API communication
- `image_picker` - Camera/gallery access
- `audioplayers` - Audio playback

### 2. Configure Base URL

**IMPORTANT:** You must update the API base URL for physical device testing.

Open `lib/api_service.dart` and update line 52:

```dart
// Find your laptop's LAN IP:
// Windows: ipconfig (look for IPv4 Address)
// Mac/Linux: ifconfig (look for inet under Wi-Fi adapter)

static const String baseUrl = "http://192.168.1.42:8000";  // Your laptop's IP
```

**URL Selection Guide:**
- **Android Emulator:** `http://10.0.2.2:8000` (default, already set)
- **iOS Simulator:** `http://127.0.0.1:8000` or `http://localhost:8000`
- **Physical Device:** `http://<YOUR_LAPTOP_LAN_IP>:8000` (e.g., `http://192.168.1.42:8000`)
- **Different Network:** Use ngrok tunnel

### 3. Platform-Specific Setup

#### Android

The required permissions are already configured in `AndroidManifest.xml`:
- Camera access
- Photo library access
- Internet access

**First-time setup:**
1. Enable USB debugging in Developer Options
2. Connect phone via USB
3. Allow USB debugging popup on phone

**If using emulator:**
- Enable virtual camera in AVD settings

#### iOS

The required permissions are already configured in `Info.plist`:
- Camera usage description
- Photo library usage description

**First-time setup:**
1. Connect iPhone via USB or enable wireless debugging
2. Trust the computer when prompted on iPhone
3. May need to sign the app with your Apple Developer account

## Running the App

### Check Connected Devices

```bash
flutter devices
```

You should see your connected phone or emulator listed.

### Run on Physical Phone

```bash
# Auto-selects device if only one is connected
flutter run

# Or specify device explicitly
flutter run -d <device_id>
```

### Run on Emulator/Simulator

```bash
# Android emulator (must be running first)
flutter run -d emulator-5554

# iOS simulator
flutter run -d "iPhone 15 Pro"
```

### Hot Reload During Development

After `flutter run` is active:
- Press `r` in terminal for hot reload (fast, preserves state)
- Press `R` for hot restart (full restart)
- Press `q` to quit

**Important:** Permission changes require full rebuild, not hot reload!

## Testing Workflow

### 1. Verify Backend Connection

When you first open the app, before uploading:
- The app will check backend health when you tap "Get Urdu Instructions"
- If connection fails, you'll see a detailed error message

**Common connection issues:**
- Backend not running → Start all 3 processes (Redis, Celery, uvicorn)
- Wrong network → Ensure phone and laptop on same Wi-Fi
- Wrong IP → Update `baseUrl` in `api_service.dart` to your actual LAN IP

### 2. Upload a Prescription

1. Tap **Camera** to take a new photo, or **Gallery** to select existing image
2. Preview the image (you can retake/reselect if needed)
3. Tap **Get Urdu Instructions**
4. Wait for processing (shows progress: uploading → queue → processing → done)

### 3. View Results

After processing completes, you'll see:

**Disclaimer Banner** (top)
- Prominent warning to confirm with pharmacist/doctor

**Combined Audio Player**
- Play all medicine instructions at once

**Medicine Cards** (one per medicine)
- **Header:** Medicine name with confidence badge (High/Medium/Low/Critical)
- **Warning badges:** "Requires verification" if `requiresHumanReview` is true
- **Database indicators:** Chips showing if found in Local DB or FDA
- **Quick info row:** Dosage, Frequency, Duration with icons
- **Details section:** Composition, Uses, Precautions, Manufacturer
  - Note: `purpose` and `side_effects` are intentionally hidden (long English DB text clutters UI)
- **Urdu section:** Instructions in Urdu (RTL text) with individual audio player
- **Audio button:** Play/stop audio for this medicine

### 4. Understanding Confidence Levels

The app displays confidence visually:
- **High (≥0.85):** Green badge with checkmark - medicine is well-recognized
- **Medium (0.7-0.85):** Orange badge with info icon - likely correct but verify
- **Low (0.5-0.7):** Red badge with warning icon - needs verification
- **Critical (<0.5 or requires review):** Deep red badge with error icon - must verify with pharmacist

### 5. Permission Prompts

**First time using camera/gallery:**
- Android: Tap "Allow" when permission popup appears
- iOS: Tap "Allow" when permission popup appears
- These are one-time prompts (stored by OS)

## Troubleshooting

### "Cannot connect to server"

**Check:**
1. Is backend running? (All 3 processes: Redis, Celery, uvicorn)
2. Is phone on same Wi-Fi as laptop?
3. Is `baseUrl` set to laptop's LAN IP (not `localhost`, not `127.0.0.1`)?
4. Try pinging laptop IP from phone's browser: `http://<IP>:8000/health`

**Solution:**
```bash
# Find your laptop's LAN IP
ipconfig  # Windows
ifconfig  # Mac/Linux

# Update lib/api_service.dart line 52
static const String baseUrl = "http://192.168.x.x:8000";

# Rebuild app (hot reload won't work)
flutter run
```

### "Camera permission denied"

**Android:**
- Settings → Apps → ParchaAI → Permissions → Enable Camera & Storage

**iOS:**
- Settings → ParchaAI → Enable Camera & Photos

### Hot reload doesn't work after permission changes

**Permissions require full rebuild:**
```bash
flutter run  # Full rebuild, not hot reload
```

### Processing stuck at "pending"

- Backend may be overloaded or Celery worker not running
- Check Celery worker logs for errors
- Verify Redis is running

### Audio doesn't play

- Check that audio URLs are reachable from phone
- Ensure backend is serving `/audio/<filename>` correctly
- Check phone volume is not muted

## Development Notes

### Project Structure

```
lib/
├── main.dart              # App entry point
├── theme.dart             # Colors, typography, Material theme
├── models.dart            # Data models (MedicineDetail, PrescriptionResult, etc.)
├── api_service.dart       # Backend API client
└── home_screen.dart       # Main UI (upload, results, audio player)
```

### Key Features Implemented

✅ Camera and gallery image picker with preview
✅ Health check before upload (connection verification)
✅ Real-time processing status updates
✅ Complete medicine cards with all 11 fields
✅ Confidence level indicators with color coding
✅ Database verification badges (Local DB, FDA)
✅ Warning flags for medicines requiring human review
✅ Urdu text rendering (RTL direction, special background)
✅ Audio playback (combined + individual per medicine)
✅ Prominent patient safety disclaimer
✅ User-friendly error messages for all failure states
✅ Professional healthcare UI (calming colors, clean typography)

### Code Quality

- Material 3 design
- Responsive layouts
- Proper error handling with user-friendly messages
- Network timeout handling
- Platform-specific documentation
- Follows Flutter best practices

## Manual Actions Required

**These cannot be automated and must be done by you:**

1. **Run `flutter pub get`** after cloning or updating dependencies
2. **Update API base URL** to your laptop's LAN IP for physical device testing
3. **Full rebuild** after permission changes (not hot reload)
4. **Tap "Allow"** on OS permission prompts (camera, photo library)
5. **Enable USB debugging** on Android device (Developer Options)
6. **Trust computer** on iOS device when first connecting
7. **Ensure same Wi-Fi network** for phone and laptop during testing

## Production Considerations (Future)

Before deploying to real users:

1. **Tighten CORS** in `parcha_ai/api.py` (currently allows all origins)
2. **Add proper error tracking** (Sentry, Firebase Crashlytics)
3. **Use production API URL** (not local IP)
4. **Add loading indicators** with more granular progress
5. **Implement caching** for prescription history
6. **Add offline mode** or better offline error messages
7. **Include proper app icons** and splash screen
8. **Test on multiple device sizes** and Android versions
9. **Add analytics** to track usage patterns
10. **Implement proper state management** (Provider, Riverpod) if app grows

## Resources

- [Flutter Documentation](https://docs.flutter.dev/)
- [Material 3 Design](https://m3.material.io/)
- [ParchaAI Backend API Reference](../QUICKSTART.md)

## Support

If you encounter issues not covered here, check:
1. Backend logs (`uvicorn` and `celery` output)
2. Flutter logs (`flutter run` output)
3. Phone logcat (Android) or console (iOS) for native errors
