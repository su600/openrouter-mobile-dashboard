package com.su600.openrouterwidget;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
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
        List<WidgetApi.NewsItem> cached = NewsCache.load(context);
        showNews(context, manager, ids, cached,
                cached.isEmpty() ? context.getString(R.string.news_widget_loading) : null);
        schedulePeriodic(context);
        enqueueRefresh(context);
    }

    static void showNews(Context context, AppWidgetManager manager, int[] ids,
                         List<WidgetApi.NewsItem> news, String error) {
        if (news != null && !news.isEmpty()) NewsCache.save(context, news);
        List<WidgetApi.NewsItem> display = news == null || news.isEmpty()
                ? NewsCache.load(context) : news;
        for (int id : ids) {
            RemoteViews widget = baseViews(context, id);
            if (display.isEmpty()) {
                widget.setViewVisibility(R.id.news_flipper, View.GONE);
                widget.setViewVisibility(R.id.news_placeholder, View.VISIBLE);
                widget.setTextViewText(R.id.news_empty,
                        error == null ? context.getString(R.string.news_widget_empty) : error);
            } else {
                widget.setViewVisibility(R.id.news_placeholder, View.GONE);
                widget.setViewVisibility(R.id.news_flipper, View.VISIBLE);
                widget.setDisplayedChild(R.id.news_flipper, 0);
            }
            manager.updateAppWidget(id, widget);
            manager.notifyAppWidgetViewDataChanged(id, R.id.news_flipper);
        }
    }

    private static RemoteViews baseViews(Context context, int id) {
        RemoteViews widget = new RemoteViews(context.getPackageName(), R.layout.widget_news);
        Intent open = new Intent(context, MainActivity.class);
        PendingIntent pending = PendingIntent.getActivity(context, 3000 + id, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        widget.setOnClickPendingIntent(R.id.news_widget_root, pending);
        PendingIntent itemPending = PendingIntent.getActivity(context, 4000 + id, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_MUTABLE);
        widget.setPendingIntentTemplate(R.id.news_flipper, itemPending);

        Intent service = new Intent(context, NewsRemoteViewsService.class);
        service.putExtra(AppWidgetManager.EXTRA_APPWIDGET_ID, id);
        service.setData(Uri.parse("news-widget://" + context.getPackageName() + "/" + id));
        widget.setRemoteAdapter(R.id.news_flipper, service);
        widget.setInt(R.id.news_flipper, "setFlipInterval", 4500);
        widget.setBoolean(R.id.news_flipper, "setAutoStart", true);
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
