package com.su600.openrouterwidget;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
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
import java.util.concurrent.TimeUnit;

public class NewsWidgetProvider extends AppWidgetProvider {
    private static final String PERIODIC_WORK = "openrouter-news-widget-periodic-refresh";
    private static final String MANUAL_WORK = "openrouter-news-widget-refresh";

    @Override public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        refreshAll(context);
    }

    static void refreshAll(Context context) {
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        int[] ids = manager.getAppWidgetIds(new ComponentName(context, NewsWidgetProvider.class));
        if (ids.length == 0) return;
        showMessage(context, manager, ids, context.getString(R.string.news_widget_loading));
        schedulePeriodic(context);
        enqueueRefresh(context);
    }

    static void showNews(Context context, AppWidgetManager manager, int[] ids,
                         List<WidgetApi.NewsItem> news, String error) {
        for (int id : ids) {
            RemoteViews widget = baseViews(context, id);
            ViewFlipperData.fill(context, widget, news, error);
            manager.updateAppWidget(id, widget);
        }
    }

    private static void showMessage(Context context, AppWidgetManager manager,
                                    int[] ids, String message) {
        for (int id : ids) {
            RemoteViews widget = baseViews(context, id);
            widget.setViewVisibility(R.id.news_flipper, View.GONE);
            widget.setViewVisibility(R.id.news_placeholder, View.VISIBLE);
            widget.setTextViewText(R.id.news_empty, message);
            manager.updateAppWidget(id, widget);
        }
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
                MANUAL_WORK, ExistingWorkPolicy.KEEP, request);
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

    private static final class ViewFlipperData {
        static void fill(Context context, RemoteViews widget, List<WidgetApi.NewsItem> news,
                         String error) {
            if (news == null || news.isEmpty()) {
                widget.setViewVisibility(R.id.news_flipper, View.GONE);
                widget.setViewVisibility(R.id.news_placeholder, View.VISIBLE);
                widget.setTextViewText(R.id.news_empty,
                        error == null ? context.getString(R.string.news_widget_empty) : error);
                return;
            }

            widget.removeAllViews(R.id.news_flipper);
            long now = System.currentTimeMillis();
            for (WidgetApi.NewsItem item : news) {
                RemoteViews row = new RemoteViews(context.getPackageName(), R.layout.widget_news_item);
                row.setImageViewResource(R.id.news_logo, logoForVendor(item.vendor));
                row.setTextViewText(R.id.news_vendor, item.vendor);
                row.setTextViewText(R.id.news_model, stripVendorPrefix(item.modelName, item.vendor));
                row.setTextViewText(R.id.news_date, item.date);
                long age = now - item.created * 1000L;
                boolean isNew = item.created > 0 && age >= 0 && age <= 7L * 24 * 60 * 60 * 1000;
                row.setViewVisibility(R.id.news_new_badge, isNew ? View.VISIBLE : View.GONE);
                widget.addView(R.id.news_flipper, row);
            }
            widget.setInt(R.id.news_flipper, "setFlipInterval", 4500);
            widget.setBoolean(R.id.news_flipper, "setAutoStart", true);
            widget.setDisplayedChild(R.id.news_flipper, 0);
            widget.setViewVisibility(R.id.news_placeholder, View.GONE);
            widget.setViewVisibility(R.id.news_flipper, View.VISIBLE);
        }

        private static int logoForVendor(String vendor) {
            if (vendor == null) return R.drawable.news_openai;
            switch (vendor.toLowerCase(java.util.Locale.ROOT)) {
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
    }
}
