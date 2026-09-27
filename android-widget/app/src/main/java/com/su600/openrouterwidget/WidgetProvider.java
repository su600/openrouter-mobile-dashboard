package com.su600.openrouterwidget;

import android.app.PendingIntent;
import android.appwidget.AppWidgetManager;
import android.appwidget.AppWidgetProvider;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.widget.RemoteViews;

import androidx.work.Constraints;
import androidx.work.Data;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;

import java.util.ArrayList;
import java.util.List;
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
        enqueueRefresh(context, false);
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
            enqueueRefresh(context, ACTION_REFRESH.equals(intent.getAction()));
            return;
        }
        super.onReceive(context, intent);
    }

    static void refreshAll(Context context) {
        refreshAll(context, false);
    }

    static void refreshAll(Context context, boolean force) {
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        int[] ids = manager.getAppWidgetIds(new ComponentName(context, WidgetProvider.class));
        if (ids.length == 0) return;
        for (int id : ids) showLoading(context, manager, id, "正在更新…");
        schedulePeriodicRefresh(context);
        enqueueRefresh(context, force);
    }

    private static void enqueueRefresh(Context context, boolean force) {
        Constraints network = new Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build();
        OneTimeWorkRequest request = new OneTimeWorkRequest.Builder(WidgetRefreshWorker.class)
                .setConstraints(network)
                .setInputData(new Data.Builder().putBoolean("force_refresh", force).build())
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
        views.setTextViewText(R.id.widget_refresh, "…");
        setActions(context, views, id);
        manager.updateAppWidget(id, views);
    }

    static void updateAll(Context context, AppWidgetManager manager, int[] ids,
                          WidgetApi.Summary summary, String error) {
        for (int id : ids) {
            RemoteViews views = baseViews(context);
            setActions(context, views, id);
            if (summary != null) {
                views.setTextViewText(R.id.widget_title, context.getString(R.string.widget_overview_title));
                views.setTextViewText(R.id.widget_account_name, summary.accountName);
                views.setTextViewText(R.id.widget_remaining,
                        formatCny(summary.remaining, summary.usdToCny, 2));
                views.setTextViewText(R.id.widget_total_usage,
                        formatCny(summary.totalUsage, summary.usdToCny, 2));
                views.setTextViewText(R.id.widget_month,
                        formatCny(summary.month, summary.usdToCny, 2));
                views.setTextViewText(R.id.widget_today,
                        formatCny(summary.today, summary.usdToCny, 4));
                setAppsUsage(views, summary.appsLast30Days, summary.usdToCny);
            } else {
                views.setTextViewText(R.id.widget_title, errorTitle(error));
                views.setTextViewText(R.id.widget_account_name, "点卡片检查设置");
                views.setTextViewText(R.id.widget_remaining, "—");
                views.setTextViewText(R.id.widget_total_usage, "—");
                views.setTextViewText(R.id.widget_month, "—");
                views.setTextViewText(R.id.widget_today, "—");
                setAppsUsage(views, null, Double.NaN);
            }
            manager.updateAppWidget(id, views);
        }
    }

    private static void setAppsUsage(RemoteViews views, List<WidgetApi.AppUsage> apps, double rate) {
        List<WidgetApi.AppUsage> sorted = apps == null ? new ArrayList<>() : new ArrayList<>(apps);
        if (sorted.isEmpty()) {
            sorted.add(new WidgetApi.AppUsage("Codex", Double.NaN));
            sorted.add(new WidgetApi.AppUsage("Claude", Double.NaN));
            sorted.add(new WidgetApi.AppUsage("Pi", Double.NaN));
        }
        sorted.sort((left, right) -> Double.compare(appUsage(right.usage), appUsage(left.usage)));

        int[] iconIds = {R.id.widget_app_icon_0, R.id.widget_app_icon_1, R.id.widget_app_icon_2};
        int[] nameIds = {R.id.widget_app_name_0, R.id.widget_app_name_1, R.id.widget_app_name_2};
        int[] valueIds = {R.id.widget_app_value_0, R.id.widget_app_value_1, R.id.widget_app_value_2};
        String[] defaults = {"Codex", "Claude", "Pi"};
        for (int i = 0; i < iconIds.length; i++) {
            WidgetApi.AppUsage app = i < sorted.size() ? sorted.get(i)
                    : new WidgetApi.AppUsage(defaults[i], Double.NaN);
            views.setImageViewResource(iconIds[i], appIcon(app.name));
            views.setTextViewText(nameIds[i], app.name);
            views.setTextViewText(valueIds[i], formatCny(app.usage, rate, 1));
        }
    }

    private static int appIcon(String name) {
        if ("codex".equalsIgnoreCase(name)) return R.drawable.app_codex;
        if ("claude".equalsIgnoreCase(name)) return R.drawable.app_claude_code;
        if ("pi".equalsIgnoreCase(name)) return R.drawable.app_pi;
        return R.drawable.app_icon;
    }

    private static double appUsage(double value) {
        return Double.isNaN(value) || Double.isInfinite(value) ? Double.NEGATIVE_INFINITY : value;
    }

    private static String errorTitle(String error) {
        if (error == null || error.isEmpty()) return "连接失败";
        if (error.contains("HTTPS") || error.contains("SSL")) return "协议错误";
        if (error.contains("域名") || error.contains("DNS")) return "域名错误";
        if (error.contains("超时")) return "连接超时";
        if (error.contains("拒绝")) return "连接被拒";
        if (error.contains("凭证") || error.contains("认证")) return "认证失败";
        return "刷新失败";
    }

    private static String formatCny(double usd, double rate, int decimals) {
        if (Double.isNaN(usd) || Double.isInfinite(usd)) return "—";
        return String.format(Locale.US, "¥%,." + decimals + "f", usd * rate);
    }

    private static RemoteViews baseViews(Context context) {
        RemoteViews views = new RemoteViews(context.getPackageName(), R.layout.widget_account);
        Intent open = new Intent(context, MainActivity.class);
        PendingIntent openPending = PendingIntent.getActivity(context, 20, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        views.setOnClickPendingIntent(R.id.widget_title, openPending);
        views.setOnClickPendingIntent(R.id.widget_data, openPending);
        return views;
    }

    private static void setActions(Context context, RemoteViews views, int id) {
        Intent refresh = new Intent(context, RefreshActivity.class);
        refresh.setData(Uri.parse("widget://refresh/" + id));
        PendingIntent refreshPending = PendingIntent.getActivity(context, id, refresh,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        views.setOnClickPendingIntent(R.id.widget_refresh, refreshPending);

        Intent topUp = new Intent(Intent.ACTION_VIEW, Uri.parse(TOP_UP_URL));
        PendingIntent topUpPending = PendingIntent.getActivity(context, 1000 + id, topUp,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        views.setOnClickPendingIntent(R.id.widget_topup, topUpPending);
    }
}
