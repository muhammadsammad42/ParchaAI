# ========================================
# Flutter Local Notifications - CRITICAL
# ========================================
# Keep all plugin classes (prevents "Missing type parameter" error)
-keep class com.dexterous.flutterlocalnotifications.** { *; }
-keepclassmembers class com.dexterous.flutterlocalnotifications.** { *; }

# Keep notification models and their fields (used by Gson serialization)
-keepclassmembers class com.dexterous.flutterlocalnotifications.models.** { *; }
-keep class com.dexterous.flutterlocalnotifications.models.** { *; }

# Keep Gson serialization (CRITICAL for scheduled notifications)
-keepattributes Signature
-keepattributes *Annotation*
-keepattributes EnclosingMethod
-dontwarn sun.misc.**
-keep class com.google.gson.** { *; }
-keep class * implements com.google.gson.TypeAdapterFactory
-keep class * implements com.google.gson.JsonSerializer
-keep class * implements com.google.gson.JsonDeserializer

# Prevent R8 from stripping generic type information (fixes "Missing type parameter")
-keepattributes Signature
-keepattributes *Annotation*
-keep class kotlin.Metadata { *; }

# Keep all fields in notification-related classes (Gson needs reflection access)
-keepclassmembers class * {
    @com.google.gson.annotations.SerializedName <fields>;
}

# Keep notification receivers
-keep class * extends android.content.BroadcastReceiver { *; }

# Keep AndroidX notification classes
-keep class androidx.core.app.NotificationCompat { *; }
-keep class androidx.core.app.NotificationCompat$* { *; }
-keep class android.app.NotificationChannel { *; }
-keep class android.app.NotificationManager { *; }

# Keep timezone data (threeten-backport)
-keep class org.threeten.bp.** { *; }
-dontwarn org.threeten.bp.**

# Keep SharedPreferences (used by plugin to store scheduled notifications)
-keep class android.content.SharedPreferences { *; }
-keep class android.content.SharedPreferences$* { *; }

# Gson - Keep type adapters and reflection
-keep class * extends com.google.gson.TypeAdapter
-keep class * implements com.google.gson.TypeAdapterFactory
-keep class * implements com.google.gson.JsonSerializer
-keep class * implements com.google.gson.JsonDeserializer

# Prevent R8 optimization from breaking Gson
-keepclassmembers,allowobfuscation class * {
  @com.google.gson.annotations.SerializedName <fields>;
}
-keep,allowobfuscation @interface com.google.gson.annotations.SerializedName
