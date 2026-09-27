package com.su600.openrouterwidget;

import android.annotation.SuppressLint;
import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** Stores the last successful public news response so the widget remains useful offline. */
final class NewsCache {
    private static final String PREFS = "news_widget_cache";
    private static final String ITEMS = "items_json";

    private NewsCache() {}

    @SuppressLint("ApplySharedPref")
    static void save(Context context, List<WidgetApi.NewsItem> items) {
        if (items == null || items.isEmpty()) return;
        JSONArray array = new JSONArray();
        try {
            for (WidgetApi.NewsItem item : items) {
                JSONObject row = new JSONObject();
                row.put("vendor", item.vendor);
                row.put("model_id", item.modelId);
                row.put("model_name", item.modelName);
                row.put("created", item.created);
                row.put("date", item.date);
                array.put(row);
            }
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                    .edit().putString(ITEMS, array.toString()).commit();
        } catch (Exception ignored) {
            // A cache write failure should not prevent the current response being displayed.
        }
    }

    static List<WidgetApi.NewsItem> load(Context context) {
        List<WidgetApi.NewsItem> items = new ArrayList<>();
        String json = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getString(ITEMS, null);
        if (json == null || json.isEmpty()) return items;
        try {
            JSONArray array = new JSONArray(json);
            for (int i = 0; i < array.length(); i++) {
                JSONObject row = array.optJSONObject(i);
                if (row == null) continue;
                items.add(new WidgetApi.NewsItem(
                        row.optString("vendor", ""),
                        row.optString("model_id", ""),
                        row.optString("model_name", ""),
                        row.optLong("created", 0L),
                        row.optString("date", "")));
            }
        } catch (Exception ignored) {
            items.clear();
        }
        return items;
    }
}
