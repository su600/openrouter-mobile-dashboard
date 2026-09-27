# OpenRouter Android home-screen widget

A lightweight native AppWidget for the OpenRouter account dashboard. It follows the dashboard's dark palette (`#0f1117` / `#1a1d29`) and green accent (`#4ade80`), with an approximately 5×2 layout: an account header and recharge/refresh actions above a 2×2 grid for remaining balance, cumulative spend, monthly spend, and UTC today's spend. Static fee guidance is omitted; a connection diagnostic appears only when refresh fails.

**Prebuilt APK v1.0.5:** [Download](releases/openrouter-account-widget-v1.0.5.apk). This debug-signed APK is for direct installation, not Google Play distribution.

## Setup

1. Install the APK and open **OpenRouter 小组件**.
2. Enter the dashboard base URL (for example `https://dashboard.example.com`) and the same access password used by the dashboard.
3. Tap **连接并读取账户**. The app exchanges the dashboard credential once for a dedicated read-only token; it does not persist the dashboard credential.
4. Select an account and save. Add the widget from Android's home-screen widget picker.
5. Tap **刷新** for an immediate refresh. Manual and periodic updates run through WorkManager rather than the short-lived widget broadcast; periodic work is requested every 30 minutes, though Android may defer it.

The read-only token is encrypted at rest with Android Keystore. The APK contains no dashboard/OpenRouter credentials. Use HTTPS or a trusted VPN when setting up remotely; avoid sending the dashboard password over public HTTP.

## Build

Requires JDK 17 and Android SDK Platform 35 / Build Tools 35.0.0.

```bash
./gradlew assembleDebug
```

The debug APK is written to `app/build/outputs/apk/debug/app-debug.apk`.
