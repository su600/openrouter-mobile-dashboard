package com.su600.openrouterwidget;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

final class WidgetApi {
    private WidgetApi() {}

    static final class Account {
        final String id;
        final String name;

        Account(String id, String name) {
            this.id = id;
            this.name = name;
        }

        @Override public String toString() { return name; }
    }

    static final class AppUsage {
        final String name;
        final double usage;

        AppUsage(String name, double usage) {
            this.name = name;
            this.usage = usage;
        }
    }

    static final class NewsItem {
        final String vendor;
        final String modelId;
        final String modelName;
        final long created;
        final String date;

        NewsItem(String vendor, String modelId, String modelName, long created, String date) {
            this.vendor = vendor;
            this.modelId = modelId;
            this.modelName = modelName;
            this.created = created;
            this.date = date;
        }
    }

    static final class Summary {
        String accountName;
        final List<AppUsage> appsLast30Days = new ArrayList<>();
        double remaining = Double.NaN;
        double totalUsage = Double.NaN;
        double today = Double.NaN;
        double month = Double.NaN;
        double usdToCny = 7.1;
        long generatedAt;
    }

    static String exchangeDashboardToken(String baseUrl, String dashboardToken) throws Exception {
        JSONObject json = request(baseUrl, "/api/widget/session", "POST", dashboardToken, "{}");
        String token = json.optString("widget_token", "");
        if (token.isEmpty()) throw new IllegalStateException("服务端没有返回只读凭证");
        return token;
    }

    static List<Account> accounts(String baseUrl, String widgetToken) throws Exception {
        JSONObject json = request(baseUrl, "/api/widget/accounts", "GET", widgetToken, null);
        JSONArray rows = json.optJSONArray("accounts");
        List<Account> result = new ArrayList<>();
        if (rows == null) return result;
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.optJSONObject(i);
            if (row == null) continue;
            result.add(new Account(row.optString("id", ""), row.optString("name", "账户")));
        }
        return result;
    }

    static List<NewsItem> latestNews(String baseUrl, String widgetToken) throws Exception {
        JSONObject json = request(baseUrl, "/api/widget/news", "GET", widgetToken, null);
        JSONArray rows = json.optJSONArray("news");
        List<NewsItem> result = new ArrayList<>();
        if (rows == null) return result;
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.optJSONObject(i);
            if (row == null) continue;
            result.add(new NewsItem(
                    row.optString("vendor", ""),
                    row.optString("model_id", ""),
                    row.optString("model_name", ""),
                    row.optLong("created", 0L),
                    row.optString("date", "")));
        }
        return result;
    }

    static Summary summary(String baseUrl, String widgetToken, String accountId, boolean force) throws Exception {
        String encoded = URLEncoder.encode(accountId, StandardCharsets.UTF_8.name());
        String path = "/api/widget/summary?account=" + encoded + (force ? "&refresh=1" : "");
        JSONObject json = request(baseUrl, path, "GET", widgetToken, null);
        Summary result = new Summary();
        result.accountName = json.optString("account_name", "账户");
        result.generatedAt = json.optLong("generated_at", 0L);
        JSONObject account = json.optJSONObject("account");
        if (account != null) {
            result.remaining = number(account, "remaining");
            result.totalUsage = number(account, "total_usage");
            result.today = number(account, "today_usage");
            result.month = number(account, "month_usage");
        }
        JSONObject rate = json.optJSONObject("exchange_rate");
        if (rate != null) result.usdToCny = rate.optDouble("usd_to_cny", 7.1);
        JSONArray apps = json.optJSONArray("apps_last_30_days");
        if (apps != null) {
            for (int i = 0; i < apps.length(); i++) {
                JSONObject app = apps.optJSONObject(i);
                if (app != null) result.appsLast30Days.add(
                        new AppUsage(app.optString("name", ""), number(app, "usage")));
            }
        }
        return result;
    }

    private static double number(JSONObject object, String key) {
        Object value = object.opt(key);
        if (value == null || value == JSONObject.NULL) return Double.NaN;
        try { return Double.parseDouble(String.valueOf(value)); }
        catch (NumberFormatException ignored) { return Double.NaN; }
    }

    private static JSONObject request(String baseUrl, String path,
                                      String method, String bearerToken, String body) throws Exception {
        String root = baseUrl.trim().replaceAll("/+$", "");
        if (!(root.startsWith("https://") || root.startsWith("http://"))) {
            throw new IllegalArgumentException("看板地址请以 https:// 或 http:// 开头");
        }
        HttpURLConnection connection = (HttpURLConnection) new URL(root + path).openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(9000);
        connection.setReadTimeout(12000);
        connection.setUseCaches(false);
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("Authorization", "Bearer " + bearerToken);
        if (body != null) {
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            try (OutputStream output = connection.getOutputStream()) { output.write(bytes); }
        }
        int status = connection.getResponseCode();
        InputStream stream = status >= 200 && status < 300
                ? connection.getInputStream() : connection.getErrorStream();
        String response = stream == null ? "" : readAll(stream);
        connection.disconnect();
        if (status < 200 || status >= 300) {
            if (status == 401) throw new IllegalStateException("口令无效或只读凭证已失效（HTTP 401）");
            throw new IllegalStateException("看板返回 HTTP " + status + (response.isEmpty() ? "" : ": " + safeError(response)));
        }
        return new JSONObject(response);
    }

    private static String safeError(String body) {
        try { return new JSONObject(body).optString("error", ""); }
        catch (Exception ignored) { return ""; }
    }

    private static String readAll(InputStream stream) throws Exception {
        try (InputStream input = stream; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096];
            int count;
            while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
            return output.toString(StandardCharsets.UTF_8.name());
        }
    }
}
