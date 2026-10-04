package com.su600.openrouterwidget;

import android.content.Context;
import android.content.SharedPreferences;

final class WidgetStore {
    private static final String PREFS = "widget_config";
    private static final String URL = "base_url";
    private static final String ACCOUNT = "account_id";
    private static final String CURRENCY = "currency";
    static final String CURRENCY_CNY = "CNY";
    static final String CURRENCY_USD = "USD";
    static final String DEFAULT_URL = "https://account.su600.cn";

    private WidgetStore() {}

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static String baseUrl(Context context) {
        SharedPreferences preferences = prefs(context);
        String saved = preferences.getString(URL, "");
        if (saved == null || saved.trim().isEmpty()) return DEFAULT_URL;
        saved = saved.trim().replaceAll("/+$", "");
        if (saved.matches("(?i)^https?://[^/]+:8080(?:/.*)?$")) {
            preferences.edit().putString(URL, DEFAULT_URL).apply();
            return DEFAULT_URL;
        }
        return saved;
    }
    static String accountId(Context context) { return prefs(context).getString(ACCOUNT, ""); }

    static String currency(Context context) {
        String saved = prefs(context).getString(CURRENCY, CURRENCY_CNY);
        return CURRENCY_USD.equals(saved) ? CURRENCY_USD : CURRENCY_CNY;
    }

    static void save(Context context, String baseUrl, String accountId) {
        save(context, baseUrl, accountId, currency(context));
    }

    static void save(Context context, String baseUrl, String accountId, String currency) {
        String resolvedCurrency = CURRENCY_USD.equals(currency) ? CURRENCY_USD : CURRENCY_CNY;
        prefs(context).edit().putString(URL, baseUrl.trim().replaceAll("/+$", ""))
                .putString(ACCOUNT, accountId).putString(CURRENCY, resolvedCurrency).apply();
    }
}
