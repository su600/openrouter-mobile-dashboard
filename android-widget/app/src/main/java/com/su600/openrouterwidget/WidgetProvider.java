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

import java.util.Locale;
import java.util.concurrent.TimeUnit;

public class WidgetProvider extends AppWidgetProvider {
    static final String ACTION_REFRESH = "com.su600.openrouterwidget.ACTION_REFRESH";
    private static final String PERIODIC_WORK = "openrouter-widget-periodic-refresh";
    private static final String MANUAL_WORK = "openrouter-widget-manual-refresh";
    private static final String TOP_UP_URL = "https://openrouter.ai/settings/credits";

    @Override public void onUpdate(Context context, AppWidgetManager manager, int[] ids) {
        for (int id : ids) showLoading(context, manager, id, "正在更新…");
        schedulePeriodicRefresh(context);
        enqueueRefresh(context);
    }

    @Override public void onReceive(Context context, Intent intent) {
        if (intent != null && (ACTION_REFRESH.equals(intent.getAction())
                || AppWidgetManager.ACTION_APPWIDGET_UPDATE.equals(intent.getAction()))) {
            AppWidgetManager manager = AppWidgetManager.getInstance(context);
            int[] ids = intent.getIntArrayExtra(AppWidgetManager.EXTRA_APPWIDGET_IDS);
            if (ids == null || ids.length == 0) {
                ids = manager.getAppWidgetIds(new ComponentName(context, WidgetProvider.class));
            }
            for (int id : ids) showLoading(context, manager, id, "正在更新…");
            schedulePeriodicRefresh(context);
            enqueueRefresh(context);
            return;
        }
        super.onReceive(context, intent);
    }

    static void refreshAll(Context context) {
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        int[] ids = manager.getAppWidgetIds(new ComponentName(context, WidgetProvider.class));
        if (ids.length == 0) return;
        for (int id : ids) showLoading(context, manager, id, "正在更新…");
        schedulePeriodicRefresh(context);
        enqueueRefresh(context);
    }

    private static void enqueueRefresh(Context context) {
        Constraints network = new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build();
        OneTimeWorkRequest request = new OneTimeWorkRequest.Builder(WidgetRefreshWorker.class)
                .setConstraints(network)
                .build();
        WorkManager.getInstance(context).enqueueUniqueWork(
                MANUAL_WORK, ExistingWorkPolicy.APPEND_OR_REPLACE, request);
    }

    private static void schedulePeriodicRefresh(Context context) {
        Constraints network = new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build();
        PeriodicWorkRequest request = new PeriodicWorkRequest.Builder(
                WidgetRefreshWorker.class, 30, TimeUnit.MINUTES)
                .setConstraints(network)
                .build();
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                PERIODIC_WORK, ExistingPeriodicWorkPolicy.UPDATE, request);
    }

    private static void showLoading(Context context, AppWidgetManager manager, int id, String message) {
        RemoteViews views = baseViews(context);
        views.setViewVisibility(R.id.widget_fee_note, View.GONE);
        setActions(context, views, id);
        manager.updateAppWidget(id, views);
    }

    static void updateAll(Context context, AppWidgetManager manager, int[] ids,
                          WidgetApi.Summary summary, String error) {
        for (int id : ids) {
            RemoteViews views = baseViews(context);
            setActions(context, views, id);
            if (summary != null) {
                views.setTextViewText(R.id.widget_account_name, summary.accountName);
                views.setViewVisibility(R.id.widget_fee_note, View.GONE);
                views.setTextViewText(R.id.widget_remaining,
                        formatCny(summary.remaining, summary.usdToCny, 2));
                views.setTextViewText(R.id.widget_total_usage,
                        formatCny(summary.totalUsage, summary.usdToCny, 2));
                views.setTextViewText(R.id.widget_month,
                        formatCny(summary.month, summary.usdToCny, 2));
                views.setTextViewText(R.id.widget_today,
                        formatCny(summary.today, summary.usdToCny, 4));
            } else {
                views.setTextViewText(R.id.widget_account_name, "未连接");
                views.setTextViewText(R.id.widget_fee_note,
                        error == null ? "连接失败：请打开 App 检查设置" : compact(error));
                views.setTextColor(R.id.widget_fee_note, 0xffff6b6b);
                views.setViewVisibility(R.id.widget_fee_note, View.VISIBLE);
                views.setTextViewText(R.id.widget_remaining, "—");
                views.setTextViewText(R.id.widget_total_usage, "—");
                views.setTextViewText(R.id.widget_month, "—");
                views.setTextViewText(R.id.widget_today, "—");
            }
            manager.updateAppWidget(id, views);
        }
    }

    private static String compact(String text) {
        String value = text.replace('\n', ' ').trim();
        return value.length() > 34 ? value.substring(0, 33) + "…" : value;
    }

    private static String formatCny(double usd, double rate, int decimals) {
        if (Double.isNaN(usd) || Double.isInfinite(usd)) return "—";
        return String.format(Locale.US, "¥%,." + decimals + "f", usd * rate);
    }

    private static RemoteViews baseViews(Context context) {
        RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_account);
        Intent open = new Intent(context, SettingsActivity.class);
        PendingIntent openPending = PendingIntent.getActivity(context, 20, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        views.setOnClickPendingIntent(R.id.widget_root, openPending);
        return views;
    }

    private static void setActions(Context context, RemoteViews views, int id) {
        Intent refresh = new Intent(context, WidgetProvider.class).setAction(ACTION_REFRESH);
        refresh.setData(Uri.parse("widget://refresh/" + id));
        PendingIntent refreshPending = PendingIntent.getBroadcast(context, id, refresh,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        views.setOnClickPendingIntent(R.id.widget_refresh, refreshPending);

        Intent topUp = new Intent(Intent.ACTION_VIEW, Uri.parse(TOP_UP_URL));
        PendingIntent topUpPending = PendingIntent.getActivity(context, 1000 + id, topUp,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        views.setOnClickPendingIntent(R.id.widget_topup, topUpPending);
    }
}
