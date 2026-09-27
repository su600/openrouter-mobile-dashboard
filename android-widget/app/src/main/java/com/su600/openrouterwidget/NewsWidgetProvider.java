package com.su600.openrouterwidget;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.util.Log;
import android.view.View;
import android.widget.RemoteViews;

import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;

import java.util.List;
import java.util.Locale;
import java.util.concurrent.TimeUnit;

/** Samsung One UI-friendly news widget using only stock RemoteViews setters and simple views. */
public class NewsWidgetProvider extends AppWidgetProvider {
    private static final String TAG = "NewsWidgetProvider";
    private static final String PERIODIC_WORK = "openrouter-news-widget-periodic-refresh";
    private static final String MANUAL_WORK = "openrouter-news-widget-refresh";

    @Override public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        refreshAll(context);
    }

    static void refreshAll(Context context) {
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        int[] ids = manager.getAppWidgetIds(new ComponentName(context, NewsWidgetProvider.class));
        if (ids.length == 0) return;
        List<WidgetApi.NewsItem> cached = NewsCache.load(context);
        updateWidgets(context, manager, ids, cached,
                cached.isEmpty() ? context.getString(R.string.news_widget_loading) : null);
        try {
            schedulePeriodic(context);
            enqueueRefresh(context);
        } catch (RuntimeException error) {
            Log.w(TAG, "Unable to schedule news refresh", error);
        }
    }

    static void showNews(Context context, AppWidgetManager manager, int[] ids,
                         List<WidgetApi.NewsItem> news, String error) {
        if (news != null && !news.isEmpty()) NewsCache.save(context, news);
        List<WidgetApi.NewsItem> display = news == null || news.isEmpty()
                ? NewsCache.load(context) : news;
        updateWidgets(context, manager, ids, display, error);
    }

    private static void updateWidgets(Context context, AppWidgetManager manager, int[] ids,
                                      List<WidgetApi.NewsItem> news, String error) {
        for (int id : ids) {
            RemoteViews widget = baseViews(context, id);
            if (news == null || news.isEmpty()) {
                widget.setImageViewResource(R.id.news_logo, R.drawable.news_openai);
                widget.setTextViewText(R.id.news_vendor, context.getString(R.string.news_widget_title));
                widget.setTextViewText(R.id.news_date, context.getString(R.string.news_date_placeholder));
                widget.setTextViewText(R.id.news_ticker, error == null
                        ? context.getString(R.string.news_widget_empty) : error);
                widget.setViewVisibility(R.id.news_new_badge, View.GONE);
            } else {
                WidgetApi.NewsItem latest = news.get(0);
                widget.setImageViewResource(R.id.news_logo, logoForVendor(latest.vendor));
                widget.setTextViewText(R.id.news_vendor, safe(latest.vendor));
                widget.setTextViewText(R.id.news_date, safe(latest.date));
                widget.setTextViewText(R.id.news_ticker, buildTicker(news));
                long age = System.currentTimeMillis() - latest.created * 1000L;
                boolean isNew = latest.created > 0 && age >= 0
                        && age <= 7L * 24 * 60 * 60 * 1000;
                widget.setViewVisibility(R.id.news_new_badge,
                        isNew ? View.VISIBLE : View.GONE);
            }
            manager.updateAppWidget(id, widget);
        }
    }

    private static String buildTicker(List<WidgetApi.NewsItem> news) {
        StringBuilder ticker = new StringBuilder();
        long now = System.currentTimeMillis();
        for (WidgetApi.NewsItem item : news) {
            if (ticker.length() > 0) ticker.append("   •   ");
            ticker.append(safe(item.vendor)).append("：")
                    .append(stripVendorPrefix(item.modelName, item.vendor));
            long age = now - item.created * 1000L;
            if (item.created > 0 && age >= 0 && age <= 7L * 24 * 60 * 60 * 1000) {
                ticker.append("  NEW");
            }
            if (item.date != null && !item.date.isEmpty()) ticker.append(" · ").append(item.date);
        }
        return ticker.toString();
    }

    private static String safe(String value) {
        return value == null ? "" : value;
    }

    private static int logoForVendor(String vendor) {
        if (vendor == null) return R.drawable.news_openai;
        switch (vendor.toLowerCase(Locale.ROOT)) {
            case "anthropic": return R.drawable.news_anthropic;
            case "deepseek": return R.drawable.news_deepseek;
            case "google": return R.drawable.news_google;
            case "meta": return R.drawable.news_meta;
            case "qwen": return R.drawable.news_qwen;
            case "mistral": return R.drawable.news_mistral;
            default: return R.drawable.news_openai;
        }
    }

    private static String stripVendorPrefix(String modelName, String vendor) {
        if (modelName == null) return "";
        String prefix = (vendor == null ? "" : vendor.trim()) + ":";
        if (prefix.length() > 1 && modelName.regionMatches(true, 0, prefix, 0, prefix.length())) {
            return modelName.substring(prefix.length()).trim();
        }
        return modelName;
    }

    private static RemoteViews baseViews(Context context, int id) {
        RemoteViews widget = new RemoteViews(context.getPackageName(), R.layout.widget_news);
        Intent open = new Intent(context, MainActivity.class);
        PendingIntent pending = PendingIntent.getActivity(context, 3000 + id, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        widget.setOnClickPendingIntent(R.id.news_widget_root, pending);
        return widget;
    }

    private static void enqueueRefresh(Context context) {
        Constraints network = new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build();
        OneTimeWorkRequest request = new OneTimeWorkRequest.Builder(NewsRefreshWorker.class)
                .setConstraints(network)
                .build();
        WorkManager.getInstance(context).enqueueUniqueWork(
                MANUAL_WORK, ExistingWorkPolicy.APPEND_OR_REPLACE, request);
    }

    private static void schedulePeriodic(Context context) {
        Constraints network = new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build();
        PeriodicWorkRequest request = new PeriodicWorkRequest.Builder(
                NewsRefreshWorker.class, 6, TimeUnit.HOURS)
                .setConstraints(network)
                .build();
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                PERIODIC_WORK, ExistingPeriodicWorkPolicy.UPDATE, request);
    }
}
