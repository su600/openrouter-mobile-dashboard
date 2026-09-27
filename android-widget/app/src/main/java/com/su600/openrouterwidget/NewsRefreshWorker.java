package com.su600.openrouterwidget;

import android.appwidget.AppWidgetManager;
import android.content.ComponentName;
import android.content.Context;

import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.net.UnknownHostException;
import java.util.List;
import javax.net.ssl.SSLException;

public class NewsRefreshWorker extends Worker {
    public NewsRefreshWorker(@NonNull Context context, @NonNull WorkerParameters parameters) {
        super(context, parameters);
    }

    @NonNull @Override public Result doWork() {
        Context context = getApplicationContext();
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        int[] ids = manager.getAppWidgetIds(new ComponentName(context, NewsWidgetProvider.class));
        if (ids.length == 0) return Result.success();
        try {
            String baseUrl = WidgetStore.baseUrl(context);
            String token = SecretStore.readToken(context);
            if (baseUrl.isEmpty() || token == null) {
                NewsWidgetProvider.showNews(context, manager, ids, null, "打开 App 完成连接设置");
                return Result.success();
            }
            List<WidgetApi.NewsItem> news = WidgetApi.latestNews(baseUrl, token);
            NewsWidgetProvider.showNews(context, manager, ids, news, null);
            return Result.success();
        } catch (Exception error) {
            NewsWidgetProvider.showNews(context, manager, ids, null, explain(error));
            String message = error.getMessage();
            if (message != null && message.contains("401")) return Result.success();
            return Result.retry();
        }
    }

    private static String explain(Throwable error) {
        Throwable cause = error;
        while (cause != null) {
            if (cause instanceof SSLException) return "HTTPS 协议错误";
            if (cause instanceof UnknownHostException) return "域名解析失败";
            if (cause instanceof SocketTimeoutException) return "连接超时";
            if (cause instanceof ConnectException) return "连接被拒";
            cause = cause.getCause();
        }
        String message = error.getMessage();
        if (message != null && message.contains("401")) return "只读凭证失效，请打开 App";
        return "暂时无法获取新品信息";
    }
}
