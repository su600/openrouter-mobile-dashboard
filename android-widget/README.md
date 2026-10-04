# OpenRouter Android app and home-screen widget

The Android app opens the existing responsive dashboard in a WebView and bundles two native home-screen widgets. The app icon and widgets use the same logo. The 4×2 account widget follows the dashboard's dark palette (`#0f1117` / `#1a1d29`) and green accent (`#4ade80`), showing account metrics plus Codex / Claude / Pi logos and 30-day usage sorted by spend. App names are bold and usage amounts use bold 18sp type with added spacing from the account metrics. The 4×1 news widget uses a minimal static RemoteViews layout (standard text and image views only) to show up to two lines of recent vendor/model/date entries, a vendor logo, and a NEW badge for models released within seven days. It avoids dynamic child inflation, marquee methods, and launcher auto-advance bindings; the project owner confirmed it can be added on Samsung One UI 8.5. The dashboard uses a locally served Chart.js bundle, avoiding a blocking CDN fetch at startup.

**Prebuilt APK v1.0.33:** [Download](releases/openrouter-account-widget-v1.0.33.apk). This debug-signed APK is for direct installation, not Google Play distribution. The account widget supports choosing CNY or USD in app settings, and now follows the dashboard's locally customized exchange rate. The default dashboard address is `https://account.su600.cn`; saved legacy `:8080` dashboard URLs are migrated to the HTTPS domain when settings are opened. The Pi app-usage icon uses the updated Pi Coding Agent logo.

## Setup

1. Install the APK and open **OpenRouter 账户看板**.
2. On first launch, enter the dashboard base URL and access password, then tap **连接并读取账户**.
3. Select an account and the account widget's display currency (**人民币 CNY** or **美元 USD**), then save. CNY values use the server's configured rate unless you customize the rate in the dashboard WebView, in which case the widget follows that local rate too; USD values show the original amount. The currency and custom rate are shared by all account widgets on this device. The app then opens the full dashboard; saved credentials are restored automatically next time.
4. Add **OpenRouter 账户小组件** (4×2) and/or **OpenRouter 新品快讯** (4×1) from Android's home-screen widget picker. Tap a widget to return to the app. When updating from v1.0.28, remove and re-add the news widget once so the launcher refreshes its layout.
5. Tap **刷新** to force a fresh account and app-usage query (bypassing the server's 60-second summary cache). The button starts a dedicated refresh activity and WorkManager job; periodic work is requested every 30 minutes, though Android may defer it.

The dashboard password and read-only token are encrypted at rest with Android Keystore. A restricted JavaScript bridge supplies the in-memory dashboard token to the trusted WebView; it is not stored in WebView localStorage, so background resume keeps the page state. The APK contains no embedded dashboard/OpenRouter credentials. Use HTTPS or a trusted VPN when setting up remotely; avoid sending the dashboard password over public HTTP.

## Build

Requires JDK 17 and Android SDK Platform 35 / Build Tools 35.0.0.

```bash
./gradlew assembleDebug
```

The debug APK is written to `app/build/outputs/apk/debug/app-debug.apk`.
