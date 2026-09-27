package com.su600.openrouterwidget;

import android.content.Intent;
import android.widget.RemoteViews;
import android.widget.RemoteViewsService;

import java.util.List;
import java.util.Locale;

/** Supplies news rows through the App Widget-supported AdapterViewFlipper collection API. */
public class NewsRemoteViewsService extends RemoteViewsService {
    @Override public RemoteViewsFactory onGetViewFactory(Intent intent) {
        return new NewsFactory(getApplicationContext());
    }

    private static final class NewsFactory implements RemoteViewsFactory {
        private final android.content.Context context;
        private List<WidgetApi.NewsItem> items;

        NewsFactory(android.content.Context context) {
            this.context = context;
        }

        @Override public void onCreate() {
            items = NewsCache.load(context);
        }

        @Override public void onDataSetChanged() {
            items = NewsCache.load(context);
        }

        @Override public void onDestroy() {
            items = null;
        }

        @Override public int getCount() {
            return items == null ? 0 : items.size();
        }

        @Override public RemoteViews getViewAt(int position) {
            if (items == null || position < 0 || position >= items.size()) return null;
            WidgetApi.NewsItem item = items.get(position);
            RemoteViews row = new RemoteViews(context.getPackageName(), R.layout.widget_news_item);
            row.setImageViewResource(R.id.news_logo, logoForVendor(item.vendor));
            row.setTextViewText(R.id.news_vendor, item.vendor);
            row.setTextViewText(R.id.news_model, stripVendorPrefix(item.modelName, item.vendor));
            row.setTextViewText(R.id.news_date, item.date);
            long age = System.currentTimeMillis() - item.created * 1000L;
            boolean isNew = item.created > 0 && age >= 0 && age <= 7L * 24 * 60 * 60 * 1000;
            row.setViewVisibility(R.id.news_new_badge, isNew ? android.view.View.VISIBLE : android.view.View.GONE);
            row.setOnClickFillInIntent(R.id.news_item_root, new Intent());
            return row;
        }

        @Override public RemoteViews getLoadingView() {
            return new RemoteViews(context.getPackageName(), R.layout.widget_news_item);
        }

        @Override public int getViewTypeCount() {
            return 1;
        }

        @Override public long getItemId(int position) {
            return position;
        }

        @Override public boolean hasStableIds() {
            return true;
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
    }
}
