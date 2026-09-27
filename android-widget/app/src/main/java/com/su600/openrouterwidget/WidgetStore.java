package com.su600.openrouterwidget;

import android.content.Context;
import android.content.SharedPreferences;

final class WidgetStore {
    private static final String PREFS = "widget_config";
    private static final String URL = "base_url";
    private static final String ACCOUNT = "account_id";

    private WidgetStore() {}

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    static String baseUrl(Context context) { return prefs(context).getString(URL, ""); }
    static String accountId(Context context) { return prefs(context).getString(ACCOUNT, ""); }

    static void save(Context context, String baseUrl, String accountId) {
        prefs(context).edit().putString(URL, baseUrl.trim().replaceAll("/+$", ""))
                .putString(ACCOUNT, accountId).apply();
    }
}
