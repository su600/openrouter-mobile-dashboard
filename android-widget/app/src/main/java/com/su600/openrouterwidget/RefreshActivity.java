package com.su600.openrouterwidget;

import android.app.Activity;
import android.os.Bundle;

/** Small transparent trampoline so launcher taps reliably enqueue the manual refresh. */
public class RefreshActivity extends Activity {
    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        WidgetProvider.refreshAll(getApplicationContext(), true);
        finish();
    }
}
