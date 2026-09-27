# OpenRouter Android app and home-screen widget

The Android app opens the existing responsive dashboard in a WebView and bundles its native home-screen widget. The app icon and widget use the same logo. The widget follows the dashboard's dark palette (`#0f1117` / `#1a1d29`) and green accent (`#4ade80`), with an initial 4-column × 2-row target on launchers that support cell sizing (dp fallback elsewhere); horizontal resizing is allowed while the height stays at 2 rows. It shows the four account metrics plus a row with Codex / Claude / Pi logos and their latest-30-day usage, sorted by spend. Static fee guidance is omitted; a connection diagnostic appears only when refresh fails. The dashboard uses a locally served Chart.js bundle, avoiding a blocking CDN fetch at startup.

**Prebuilt APK v1.0.21:** [Download](releases/openrouter-account-widget-v1.0.21.apk). This debug-signed APK is for direct installation, not Google Play distribution.

## Setup

1. Install the APK and open **OpenRouter 账户看板**.
2. On first launch, enter the dashboard base URL and access password, then tap **连接并读取账户**.
3. Select an account and save. The app then opens the full dashboard; saved credentials are restored automatically next time.
4. Add **OpenRouter 账户小组件** from Android's home-screen widget picker. Tap the card data or title to return to the app.
5. Tap **刷新** to force a fresh account and app-usage query (bypassing the server's 60-second summary cache). The button starts a dedicated refresh activity and WorkManager job; periodic work is requested every 30 minutes, though Android may defer it.

The dashboard password and read-only token are encrypted at rest with Android Keystore. A restricted JavaScript bridge supplies the in-memory dashboard token to the trusted WebView; it is not stored in WebView localStorage, so background resume keeps the page state. The APK contains no embedded dashboard/OpenRouter credentials. Use HTTPS or a trusted VPN when setting up remotely; avoid sending the dashboard password over public HTTP.

## Build

Requires JDK 17 and Android SDK Platform 35 / Build Tools 35.0.0.

```bash
./gradlew assembleDebug
```

The debug APK is written to `app/build/outputs/apk/debug/app-debug.apk`.
