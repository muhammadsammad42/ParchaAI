# Flutter App - Quick Start Checklist

## ✅ 5-Minute Setup for Demo

### 1. Install Dependencies (30 seconds)
```bash
cd parcha_ai_app
flutter pub get
```

### 2. Find Your Laptop's IP (30 seconds)
```bash
# Windows
ipconfig

# Mac/Linux  
ifconfig
```
Note down the IPv4 address (e.g., `192.168.1.42`)

### 3. Update Base URL (1 minute)
Open `lib/api_service.dart`, line 52:
```dart
static const String baseUrl = "http://192.168.1.42:8000";  // Your IP here
```

### 4. Start Backend (1 minute)
Three terminals:
```bash
# Terminal 1
redis-server

# Terminal 2
celery -A parcha_ai.celery_app worker --loglevel=info --concurrency=2

# Terminal 3
uvicorn parcha_ai.api:app --host 0.0.0.0 --port 8000
```

### 5. Connect Phone (1 minute)
- Enable USB debugging (Android) or trust computer (iOS)
- Connect via USB
- Verify: `flutter devices` should show your phone

### 6. Run App (1 minute)
```bash
flutter run
```

### 7. Test (1 minute)
- Tap "Camera" → grant permission
- Take photo of prescription
- Tap "Get Urdu Instructions"
- Wait 10-30 seconds
- View results!

---

## 🔧 If Something Goes Wrong

**"Cannot connect to server"**
→ Phone's browser: `http://192.168.1.42:8000/health` (use your IP)
→ Should show `{"status":"ok"}`

**"No devices detected"**
→ Android: Enable USB debugging in Developer Options
→ iOS: Trust computer when prompted

**"Camera permission denied"**
→ Settings → ParchaAI → Enable Camera & Photos
→ Restart app

---

## 📚 Full Documentation

- **`FLUTTER_SETUP.md`** - Complete setup and testing guide
- **`CONFIGURE_BASE_URL.md`** - Base URL configuration help
- **`WEEK4_FLUTTER_COMPLETE.md`** - Full implementation details

---

## 🎯 What to Look For When Testing

1. **Disclaimer Banner** - Orange warning at top of results
2. **Confidence Badges** - Green (High), Orange (Medium), Red (Low/Critical)
3. **Medicine Cards** - Show dosage, frequency, duration, composition, uses, precautions, manufacturer (purpose & side effects hidden to reduce clutter)
4. **Urdu Instructions** - Right-to-left text in amber background
5. **Audio Playback** - Combined + individual buttons work
6. **Database Indicators** - Chips showing "Local DB", "FDA", or "Not verified"
7. **Warning Flags** - "Requires verification" for low-confidence medicines

---

## 🚀 Ready to Demo!

Once you see results with all the above features, your Week 4 Flutter app is fully functional!
