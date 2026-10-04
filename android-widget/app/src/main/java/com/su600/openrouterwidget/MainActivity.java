package com.su600.openrouterwidget;

import android.app.Activity;
import android.annotation.SuppressLint;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.SslErrorHandler;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;

public class MainActivity extends Activity {
    private static final int REQUEST_SETTINGS = 710;
    private static final int PAGE_BG = Color.rgb(15, 17, 23);
    private static final int ACCENT = Color.rgb(74, 222, 128);

    private FrameLayout root;
    private WebView webView;
    private ProgressBar progressBar;
    private TextView loadingStatus;
    private boolean loadTimedOut;
    private final Handler uiHandler = new Handler(Looper.getMainLooper());
    private final Runnable loadTimeout = () -> {
        if (progressBar != null && progressBar.getVisibility() == View.VISIBLE) {
            loadTimedOut = true;
            progressBar.setVisibility(View.GONE);
            if (webView != null) webView.setAlpha(1f);
            if (loadingStatus != null) {
                loadingStatus.setText(R.string.webview_timeout_retry);
                loadingStatus.setVisibility(View.VISIBLE);
                loadingStatus.setOnClickListener(view -> loadDashboard());
            }
        }
    };
    private String dashboardUrl;
    private volatile String dashboardToken;
    private boolean settingsOpen;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (readCredentials()) {
            WidgetProvider.refreshAll(this);
            NewsWidgetProvider.refreshAll(this);
            buildWebView();
            loadDashboard();
        } else {
            showSetupPrompt();
            openSettings();
        }
    }

    private boolean readCredentials() {
        try {
            dashboardUrl = WidgetStore.baseUrl(this);
            dashboardToken = SecretStore.readDashboardToken(this);
            return dashboardUrl != null && !dashboardUrl.isEmpty()
                    && dashboardToken != null && !dashboardToken.isEmpty();
        } catch (Exception error) {
            return false;
        }
    }

    private void showSetupPrompt() {
        FrameLayout screen = new FrameLayout(this);
        screen.setBackgroundColor(PAGE_BG);
        TextView text = new TextView(this);
        text.setText("首次使用，请完成看板连接设置…");
        text.setTextColor(Color.rgb(139, 143, 163));
        text.setTextSize(14);
        text.setGravity(Gravity.CENTER);
        screen.addView(text, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(screen);
    }

    // The dashboard requires JS for charts, API calls, and its existing login flow.
    @SuppressLint("SetJavaScriptEnabled")
    private void buildWebView() {
        root = new FrameLayout(this);
        root.setBackgroundColor(PAGE_BG);

        webView = new WebView(this);
        webView.setBackgroundColor(PAGE_BG);
        webView.setAlpha(0f);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        webView.addJavascriptInterface(new NativeDashboardBridge(), "AndroidDashboard");
        root.addView(webView, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));

        progressBar = new ProgressBar(this);
        FrameLayout.LayoutParams progressLp = new FrameLayout.LayoutParams(dp(42), dp(42), Gravity.CENTER);
        root.addView(progressBar, progressLp);

        loadingStatus = new TextView(this);
        loadingStatus.setTextColor(Color.rgb(139, 143, 163));
        loadingStatus.setTextSize(13);
        loadingStatus.setGravity(Gravity.CENTER);
        loadingStatus.setVisibility(View.GONE);
        FrameLayout.LayoutParams statusLp = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.WRAP_CONTENT,
                Gravity.CENTER);
        statusLp.setMargins(dp(24), dp(58), dp(24), 0);
        root.addView(loadingStatus, statusLp);

        TextView settingsButton = new TextView(this);
        settingsButton.setText("⚙");
        settingsButton.setTextSize(21);
        settingsButton.setTextColor(ACCENT);
        settingsButton.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        settingsButton.setGravity(Gravity.CENTER);
        settingsButton.setContentDescription("看板设置");
        settingsButton.setBackground(roundButton());
        settingsButton.setElevation(dp(6));
        settingsButton.setOnClickListener(view -> openSettings());
        FrameLayout.LayoutParams settingsLp = new FrameLayout.LayoutParams(dp(48), dp(48),
                Gravity.BOTTOM | Gravity.END);
        settingsLp.setMargins(0, 0, dp(16), dp(16));
        root.addView(settingsButton, settingsLp);

        ViewCompat.setOnApplyWindowInsetsListener(root, (view, insets) -> {
            Insets bars = insets.getInsets(WindowInsetsCompat.Type.systemBars());
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return insets;
        });
        ViewCompat.requestApplyInsets(root);

        webView.setWebChromeClient(new WebChromeClient() {
            @Override public void onProgressChanged(WebView view, int progress) {
                if (progress < 100 && !loadTimedOut) progressBar.setVisibility(View.VISIBLE);
                else if (progress >= 100) revealDashboard();
            }
        });
        webView.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return routeUrl(request.getUrl());
            }

            @Override public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                // Reveal regardless of origin match: a strict host/port check here previously
                // left the WebView stuck behind the loading spinner (alpha=0) whenever the
                // final URL didn't exactly match dashboardUrl (redirects, trailing slash, etc.)
                // and onProgressChanged never separately reached 100.
                if (isDashboardOrigin(Uri.parse(url))) {
                    view.evaluateJavascript("localStorage.removeItem('or_dashboard_token');", null);
                    syncExchangeRateBridge(view);
                }
                revealDashboard();
            }

            @Override public void onPageCommitVisible(WebView view, String url) {
                super.onPageCommitVisible(view, url);
                // Fires as soon as the page is visually ready; a second safety net in case
                // progress/onPageFinished callbacks are delayed or skipped by the WebView.
                revealDashboard();
            }

            @Override public void onReceivedError(WebView view, WebResourceRequest request,
                                                  android.webkit.WebResourceError error) {
                if (request.isForMainFrame()) {
                    showLoadError("网络错误：" + error.getDescription());
                }
            }

            @Override public void onReceivedHttpError(WebView view, WebResourceRequest request,
                                                       android.webkit.WebResourceResponse response) {
                if (request.isForMainFrame() && response.getStatusCode() >= 400) {
                    showLoadError("服务器返回 HTTP " + response.getStatusCode());
                }
            }

            @Override public void onReceivedSslError(WebView view, SslErrorHandler handler,
                                                     android.net.http.SslError error) {
                handler.cancel();
                showLoadError("HTTPS 证书验证失败");
            }
        });
        setContentView(root);
    }

    private boolean routeUrl(Uri uri) {
        if (isDashboardOrigin(uri)) return false;
        String scheme = uri.getScheme();
        if ("https".equalsIgnoreCase(scheme) || "http".equalsIgnoreCase(scheme)) {
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, uri));
            } catch (Exception error) {
                Toast.makeText(this, "无法打开链接", Toast.LENGTH_SHORT).show();
            }
        }
        return true;
    }

    private boolean isDashboardOrigin(Uri uri) {
        if (dashboardUrl == null || uri == null) return false;
        Uri base = Uri.parse(dashboardUrl);
        if (base.getHost() == null || uri.getHost() == null
                || !base.getHost().equalsIgnoreCase(uri.getHost())) return false;
        return effectivePort(base) == effectivePort(uri);
    }

    private int effectivePort(Uri uri) {
        if (uri.getPort() >= 0) return uri.getPort();
        return "https".equalsIgnoreCase(uri.getScheme()) ? 443 : 80;
    }

    private void loadDashboard() {
        if (!readCredentials()) {
            openSettings();
            return;
        }
        uiHandler.removeCallbacks(loadTimeout);
        loadTimedOut = false;
        webView.animate().cancel();
        webView.setAlpha(0f);
        progressBar.setVisibility(View.VISIBLE);
        loadingStatus.setText(R.string.webview_loading);
        loadingStatus.setVisibility(View.VISIBLE);
        loadingStatus.setOnClickListener(null);
        uiHandler.postDelayed(loadTimeout, 20000);
        webView.loadUrl(dashboardUrl);
    }

    private void syncExchangeRateBridge(WebView view) {
        String script = "(function(){try{"
                + "var key='or_dashboard_usd_to_cny_rate';"
                + "var sync=function(value){try{AndroidDashboard.saveExchangeRate(value==null?'':String(value));}catch(e){}};"
                + "var nativeRate=AndroidDashboard.getExchangeRate();"
                + "if(nativeRate)localStorage.setItem(key,nativeRate);else sync(localStorage.getItem(key));"
                + "var storage=Storage.prototype;"
                + "if(!storage.__orDashboardRateSync){var set=storage.setItem,remove=storage.removeItem;"
                + "storage.setItem=function(k,v){set.apply(this,arguments);if(k===key)sync(v);};"
                + "storage.removeItem=function(k){remove.apply(this,arguments);if(k===key)sync(null);};"
                + "storage.__orDashboardRateSync=true;}"
                + "}catch(e){}})();";
        view.evaluateJavascript(script, null);
    }

    private void revealDashboard() {
        uiHandler.removeCallbacks(loadTimeout);
        loadTimedOut = false;
        if (progressBar != null) progressBar.setVisibility(View.GONE);
        if (loadingStatus != null) loadingStatus.setVisibility(View.GONE);
        if (webView != null && webView.getAlpha() < 1f) {
            webView.animate().alpha(1f).setDuration(180).start();
        }
    }

    private void showLoadError(String message) {
        uiHandler.removeCallbacks(loadTimeout);
        loadTimedOut = true;
        if (progressBar != null) progressBar.setVisibility(View.GONE);
        if (webView != null) webView.setAlpha(1f);
        if (loadingStatus != null) {
            loadingStatus.setText(getString(R.string.webview_error_retry, message));
            loadingStatus.setVisibility(View.VISIBLE);
            loadingStatus.setOnClickListener(view -> loadDashboard());
        }
    }

    private void openSettings() {
        if (settingsOpen) return;
        settingsOpen = true;
        startActivityForResult(new Intent(this, SettingsActivity.class), REQUEST_SETTINGS);
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_SETTINGS) return;
        settingsOpen = false;
        if (readCredentials()) {
            if (webView == null) buildWebView();
            loadDashboard();
        } else if (webView == null) {
            finish();
        } else {
            Toast.makeText(this, "请完成看板连接设置", Toast.LENGTH_SHORT).show();
        }
    }

    @Override protected void onPause() {
        if (webView != null) webView.onPause();
        super.onPause();
    }

    @Override protected void onResume() {
        super.onResume();
        if (webView != null) webView.onResume();
    }

    @Override public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    @Override protected void onDestroy() {
        uiHandler.removeCallbacks(loadTimeout);
        if (webView != null) {
            webView.stopLoading();
            webView.destroy();
            webView = null;
        }
        super.onDestroy();
    }

    private final class NativeDashboardBridge {
        @JavascriptInterface public String getToken() {
            return dashboardToken == null ? "" : dashboardToken;
        }

        @JavascriptInterface public boolean saveToken(String token) {
            if (token == null || token.trim().isEmpty()) return false;
            String cleaned = token.trim();
            try {
                SecretStore.saveDashboardToken(MainActivity.this, cleaned);
                dashboardToken = cleaned;
                return true;
            } catch (Exception error) {
                return false;
            }
        }

        @JavascriptInterface public void clearToken() {
            SecretStore.clearDashboardToken(MainActivity.this);
            dashboardToken = "";
        }

        @JavascriptInterface public void saveExchangeRate(String rate) {
            try {
                WidgetStore.saveCustomExchangeRate(MainActivity.this, rate);
                WidgetProvider.refreshAll(MainActivity.this);
            } catch (Exception ignored) {
                // Keep the dashboard's in-page rate functional even if native sync fails.
            }
        }

        @JavascriptInterface public String getExchangeRate() {
            String customRate = WidgetStore.customExchangeRate(MainActivity.this);
            return customRate == null ? "" : customRate;
        }
    }

    private GradientDrawable roundButton() {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(Color.rgb(32, 35, 48));
        shape.setCornerRadius(dp(24));
        shape.setStroke(dp(1), Color.rgb(58, 63, 85));
        return shape;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
