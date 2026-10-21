# --- flutter_local_notifications + Gson ---------------------------------------
# The plugin stores scheduled notifications as JSON via Gson and reads them
# back with `new TypeToken<ArrayList<NotificationDetails>>() {}`. R8 strips
# generic signatures by default, after which Gson throws
# "TypeToken must be created with a type argument" — on every launch after the
# first, and inside the alarm receiver that reschedules the next daily
# occurrence. Result: Android reminders worked for one day, then stopped
# (2026-10-21). Keep what Gson needs.
-keepattributes Signature
-keepattributes *Annotation*
-keepattributes EnclosingMethod
-keepattributes InnerClasses

-keep class com.google.gson.** { *; }
-keep class com.google.gson.reflect.TypeToken { *; }
-keep class * extends com.google.gson.reflect.TypeToken
-keepclassmembers,allowobfuscation class * {
  @com.google.gson.annotations.SerializedName <fields>;
}

# The plugin's own model classes are (de)serialised by field name.
-keep class com.dexterous.** { *; }
