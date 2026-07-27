# ⚠️ CRITICAL: Configure Base URL for Physical Device Testing

## Why This Matters

The Flutter app needs to know where your backend server is running. The default configuration is for Android emulator only. **Physical devices require your laptop's LAN IP address.**

---

## Quick Start (3 Steps)

### Step 1: Find Your Laptop's IP Address

**Windows:**
```bash
ipconfig
```
Look for **"IPv4 Address"** under your Wi-Fi adapter (e.g., `192.168.1.42`)

**Mac:**
```bash
ifconfig | grep "inet "
```
Look for the IP that starts with `192.168.` or `10.0.`

**Linux:**
```bash
ip addr show
```
Look for `inet` under your Wi-Fi interface

### Step 2: Update the Base URL

Open this file:
```
parcha_ai_app/lib/api_service.dart
```

Find line 52 and update it:
```dart
// BEFORE (works only for Android emulator)
static const String baseUrl = "http://10.0.2.2:8000";

// AFTER (replace with YOUR laptop's IP)
static const String baseUrl = "http://192.168.1.42:8000";
```

### Step 3: Full Rebuild

Hot reload won't work for this change. You need a full rebuild:
```bash
flutter run
```

---

## Base URL Cheat Sheet

| Testing Scenario | Base URL | Notes |
|-----------------|----------|-------|
| **Android Emulator** | `http://10.0.2.2:8000` | Default, already set |
| **iOS Simulator** | `http://127.0.0.1:8000` | Simulators share Mac's localhost |
| **Physical Device (same Wi-Fi)** | `http://192.168.x.x:8000` | **Most common for demos** |
| **Physical Device (different Wi-Fi)** | `https://xxxx.ngrok-free.app` | Need ngrok tunnel |

---

## Testing the Connection

After updating the base URL, verify it works:

### Option 1: Phone's Web Browser
Open this URL in your phone's browser:
```
http://192.168.x.x:8000/health
```
Should show: `{"status":"ok"}`

### Option 2: In the App
The app automatically checks backend health when you tap "Get Urdu Instructions". If connection fails, you'll see a detailed error message.

---

## Common Mistakes

### ❌ Using "localhost" or "127.0.0.1" on Physical Device
```dart
// THIS WILL NOT WORK on physical phone!
static const String baseUrl = "http://localhost:8000";
```
**Why:** "localhost" means the phone itself, not your laptop.

### ❌ Not Using `--host 0.0.0.0` in uvicorn
```bash
# THIS WILL NOT WORK - only binds to localhost
uvicorn parcha_ai.api:app --port 8000

# THIS WORKS - binds to all interfaces
uvicorn parcha_ai.api:app --host 0.0.0.0 --port 8000
```

### ❌ Phone and Laptop on Different Wi-Fi Networks
- Phone on cellular data, laptop on Wi-Fi → **Won't work**
- Phone on guest Wi-Fi, laptop on main Wi-Fi → **Might not work** (guest networks often isolate devices)
- Both on same home/office Wi-Fi → **Will work**

### ❌ Forgetting to Rebuild After Changing Base URL
Hot reload (`r` key) doesn't update constants. You must:
```bash
# Stop the app (q key)
flutter run  # Full rebuild
```

---

## Firewall Issues

If your phone's browser CAN'T reach `http://<IP>:8000/health`:

**Windows:**
1. Windows Security → Firewall & network protection
2. Allow an app through firewall
3. Find "Python" and check both Private and Public
4. Or temporarily disable firewall to test

**Mac:**
1. System Settings → Network → Firewall
2. Allow Python/uvicorn

**Linux:**
```bash
# Allow port 8000
sudo ufw allow 8000/tcp
```

---

## Using ngrok (If on Different Networks)

If you can't get phone and laptop on same Wi-Fi:

### Step 1: Install ngrok
Download from [ngrok.com](https://ngrok.com/)

### Step 2: Start ngrok tunnel
```bash
ngrok http 8000
```

### Step 3: Copy the URL
Look for line like:
```
Forwarding  https://abc123.ngrok-free.app -> http://localhost:8000
```

### Step 4: Update base URL
```dart
static const String baseUrl = "https://abc123.ngrok-free.app";
```

### Step 5: Rebuild
```bash
flutter run
```

---

## Verification Checklist

Before testing on physical device:

- [ ] Laptop's LAN IP identified (e.g., `192.168.1.42`)
- [ ] `lib/api_service.dart` line 52 updated to that IP
- [ ] Backend running with `--host 0.0.0.0`
- [ ] Phone connected to same Wi-Fi as laptop
- [ ] Phone's browser can reach `http://<IP>:8000/health` and shows `{"status":"ok"}`
- [ ] Flutter app fully rebuilt with `flutter run` (not hot reload)
- [ ] App granted camera and photo library permissions

---

## Quick Troubleshooting

**"Cannot connect to server" error:**
1. Check backend is running: `curl http://localhost:8000/health` should work from laptop
2. Check IP is correct: `ipconfig` / `ifconfig` again
3. Check same Wi-Fi: Look at Wi-Fi name on both devices
4. Check firewall: Try disabling temporarily
5. Check base URL in code: Must match laptop's IP exactly
6. Try phone's browser: Should be able to open `http://<IP>:8000/health`

**Still not working?**
- Try ngrok as a workaround
- Check router settings (guest network isolation, AP isolation)
- Try USB tethering (share laptop's internet to phone via USB)

---

## Need Help?

1. Check the full setup guide: `FLUTTER_SETUP.md`
2. Check the troubleshooting section in `WEEK4_FLUTTER_COMPLETE.md`
3. Verify backend is working: Test with curl or Postman from laptop first
4. Check Flutter logs: Look for actual error messages in `flutter run` output
5. Check backend logs: Look at uvicorn and celery worker output for errors
