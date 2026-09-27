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
import javax.net.ssl.SSLException;

public class WidgetRefreshWorker extends Worker {
    public WidgetRefreshWorker(@NonNull Context context, @NonNull WorkerParameters parameters) {
        super(context, parameters);
    }

    @NonNull @Override public Result doWork() {
        Context context = getApplicationContext();
        AppWidgetManager manager = AppWidgetManager.getInstance(context);
        int[] ids = manager.getAppWidgetIds(new ComponentName(context, WidgetProvider.class));
        if (ids.length == 0) return Result.success();

        try {
            String baseUrl = WidgetStore.baseUrl(context);
            String accountId = WidgetStore.accountId(context);
            String token = SecretStore.readToken(context);
            if (baseUrl.isEmpty() || accountId.isEmpty() || token == null) {
                WidgetProvider.updateAll(context, manager, ids, null, "打开 App 完成小组件设置");
                return Result.success();
            }
            boolean forceRefresh = getInputData().getBoolean("force_refresh", false);
            WidgetApi.Summary summary = WidgetApi.summary(baseUrl, token, accountId, forceRefresh);
            WidgetProvider.updateAll(context, manager, ids, summary, null);
        } catch (Exception error) {
            WidgetProvider.updateAll(context, manager, ids, null, explain(error));
        }
        return Result.success();
    }

    private static String explain(Throwable error) {
        Throwable cause = error;
        while (cause != null) {
            if (cause instanceof SSLException) {
                return "HTTPS 握手失败：检查协议和端口（8080 是 HTTP）";
            }
            if (cause instanceof UnknownHostException) {
                return "找不到看板域名：检查地址和 DNS";
            }
            if (cause instanceof SocketTimeoutException) {
                return "连接超时：检查网络和看板服务";
            }
            if (cause instanceof ConnectException) {
                return "拒绝连接：检查看板地址、端口和防火墙";
            }
            cause = cause.getCause();
        }
        String message = error.getMessage();
        if (message == null || message.isEmpty()) return "刷新失败：打开 App 检查连接设置";
        if (message.contains("401") || message.contains("只读凭证已失效")) {
            return "只读凭证失效：打开 App 重新连接";
        }
        if (message.contains("Keystore") || message.contains("密钥")) {
            return "本机凭证读取失败：打开 App 重新连接";
        }
        return message.startsWith("刷新失败") ? message : "刷新失败：" + message;
    }
}
