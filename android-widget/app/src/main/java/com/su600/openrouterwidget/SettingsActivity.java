package com.su600.openrouterwidget;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class SettingsActivity extends Activity {
    private static final int PAGE_BG = Color.rgb(15, 17, 23);
    private static final int CARD_BG = Color.rgb(26, 29, 41);
    private static final int BORDER = Color.rgb(38, 42, 58);
    private static final int INPUT_BORDER = Color.rgb(42, 46, 63);
    private static final int TEXT = Color.rgb(230, 232, 236);
    private static final int MUTED = Color.rgb(139, 143, 163);
    private static final int ACCENT = Color.rgb(74, 222, 128);
    private static final int DANGER = Color.rgb(255, 107, 107);
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private EditText urlField;
    private EditText passwordField;
    private Spinner accountSpinner;
    private TextView message;
    private Button saveButton;
    private List<WidgetApi.Account> accounts = new ArrayList<>();
    private String pendingWidgetToken;
    private String pendingBaseUrl;
    private String savedDashboardToken = "";

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        buildScreen();
        String savedBaseUrl = WidgetStore.baseUrl(this);
        urlField.setText(savedBaseUrl);
        saveButton.setVisibility(View.GONE);
        try {
            savedDashboardToken = SecretStore.readDashboardToken(this);
            if (savedDashboardToken != null) passwordField.setText(savedDashboardToken);
            else savedDashboardToken = "";
            if (!savedBaseUrl.isEmpty() && SecretStore.readToken(this) != null) {
                connectToServer(savedBaseUrl, savedDashboardToken);
            }
        } catch (Exception e) {
            setMessage("本机凭证读取失败，请重新连接看板。", true);
        }
    }

    private void buildScreen() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(PAGE_BG);

        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(dp(18), dp(20), dp(18), dp(24));
        scroll.addView(page);

        LinearLayout hero = new LinearLayout(this);
        hero.setOrientation(LinearLayout.VERTICAL);
        hero.setPadding(dp(20), dp(20), dp(20), dp(20));
        hero.setBackground(roundRect(CARD_BG, dp(22), BORDER));
        page.addView(hero, matchWrap());

        TextView eyebrow = text("账户小组件", 12, ACCENT, true);
        hero.addView(eyebrow);
        TextView title = text("OpenRouter", 27, Color.WHITE, true);
        LinearLayout.LayoutParams titleLp = wrap();
        titleLp.topMargin = dp(5);
        hero.addView(title, titleLp);
        TextView intro = text("把余额、消费和账户状态放到桌面", 13, MUTED, false);
        LinearLayout.LayoutParams introLp = wrap();
        introLp.topMargin = dp(5);
        hero.addView(intro, introLp);

        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(18), dp(18), dp(18), dp(18));
        card.setBackground(roundRect(CARD_BG, dp(20), BORDER));
        LinearLayout.LayoutParams cardLp = matchWrap();
        cardLp.topMargin = dp(16);
        page.addView(card, cardLp);

        card.addView(label("看板地址"));
        urlField = field("https://你的看板地址", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        LinearLayout.LayoutParams fieldLp = matchWrap();
        fieldLp.topMargin = dp(7);
        card.addView(urlField, fieldLp);

        TextView urlNote = text("填写浏览器中能打开看板的完整地址，通常以 https:// 开头。", 11, MUTED, false);
        LinearLayout.LayoutParams noteLp = wrap();
        noteLp.topMargin = dp(6);
        card.addView(urlNote, noteLp);

        TextView passLabel = label("看板访问口令");
        LinearLayout.LayoutParams passLabelLp = wrap();
        passLabelLp.topMargin = dp(17);
        card.addView(passLabel, passLabelLp);
        passwordField = field("输入后加密保存，后续自动填入", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        LinearLayout.LayoutParams passLp = matchWrap();
        passLp.topMargin = dp(7);
        card.addView(passwordField, passLp);

        Button connect = button("连接并读取账户");
        LinearLayout.LayoutParams connectLp = matchWrap();
        connectLp.topMargin = dp(16);
        card.addView(connect, connectLp);
        connect.setOnClickListener(v -> connect());

        TextView accountLabel = label("小组件显示的账户");
        LinearLayout.LayoutParams accountLabelLp = wrap();
        accountLabelLp.topMargin = dp(18);
        card.addView(accountLabel, accountLabelLp);
        accountSpinner = new Spinner(this);
        accountSpinner.setPopupBackgroundDrawable(roundRect(CARD_BG, dp(12), BORDER));
        LinearLayout.LayoutParams spinnerLp = matchWrap();
        spinnerLp.topMargin = dp(7);
        card.addView(accountSpinner, spinnerLp);

        saveButton = button("保存并刷新小组件");
        LinearLayout.LayoutParams saveLp = matchWrap();
        saveLp.topMargin = dp(12);
        card.addView(saveButton, saveLp);
        saveButton.setOnClickListener(v -> save());

        message = text("", 12, ACCENT, false);
        LinearLayout.LayoutParams msgLp = wrap();
        msgLp.topMargin = dp(12);
        card.addView(message, msgLp);

        TextView security = text("安全提示：看板口令和只读凭证均由 Android Keystore 加密保存；公网连接请使用 HTTPS 或可信 VPN。", 11, MUTED, false);
        LinearLayout.LayoutParams securityLp = wrap();
        securityLp.topMargin = dp(14);
        card.addView(security, securityLp);

        TextView instructions = text("保存后：长按桌面 → 小组件 → 选择「OpenRouter 账户」。点卡片打开此设置页，点 ↻ 手动刷新。", 12, TEXT, false);
        LinearLayout.LayoutParams instructionsLp = wrap();
        instructionsLp.topMargin = dp(16);
        page.addView(instructions, instructionsLp);
        setContentView(scroll);
        ViewCompat.setOnApplyWindowInsetsListener(scroll, (view, insets) -> {
            Insets systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars());
            view.setPadding(view.getPaddingLeft(), systemBars.top,
                    view.getPaddingRight(), systemBars.bottom);
            return insets;
        });
        ViewCompat.requestApplyInsets(scroll);
    }

    private void connect() {
        String enteredUrl = urlField.getText().toString().trim();
        String dashboardToken = passwordField.getText().toString();
        if (enteredUrl.isEmpty()) { setMessage("先填写看板地址。", true); return; }
        String baseUrl = normalizeBaseUrl(enteredUrl);
        if (!(baseUrl.startsWith("https://") || baseUrl.startsWith("http://"))) {
            setMessage("看板地址格式无效。", true); return;
        }
        urlField.setText(baseUrl);
        if (baseUrl.startsWith("http://")) {
            new AlertDialog.Builder(this)
                    .setTitle("连接未加密")
                    .setMessage("HTTP 不会加密传输首次输入的看板口令。只在可信内网或 VPN 中继续；公网请改用 HTTPS。")
                    .setNegativeButton("取消", null)
                    .setPositiveButton("在可信网络继续", (dialog, which) -> connectToServer(baseUrl, dashboardToken))
                    .show();
            return;
        }
        connectToServer(baseUrl, dashboardToken);
    }

    private String normalizeBaseUrl(String value) {
        if (value.startsWith("https://") || value.startsWith("http://") || value.contains("://")) {
            return value;
        }
        if (value.matches("(?i).+:8080(?:/.*)?$")) return "http://" + value;
        return "https://" + value;
    }

    private void connectToServer(String baseUrl, String dashboardToken) {
        setBusy(true, "正在连接看板…");
        executor.execute(() -> {
            try {
                boolean savedPassword = !dashboardToken.isEmpty()
                        && dashboardToken.equals(savedDashboardToken);
                String widgetToken = (savedPassword || dashboardToken.isEmpty())
                        ? SecretStore.readToken(this) : null;
                if (widgetToken == null) {
                    if (dashboardToken.isEmpty()) {
                        throw new IllegalStateException("首次连接需要输入看板访问口令。");
                    }
                    widgetToken = WidgetApi.exchangeDashboardToken(baseUrl, dashboardToken);
                    SecretStore.saveToken(this, widgetToken);
                    SecretStore.saveDashboardToken(this, dashboardToken);
                }
                List<WidgetApi.Account> fetched;
                try {
                    fetched = WidgetApi.accounts(baseUrl, widgetToken);
                } catch (Exception firstError) {
                    if (!savedPassword || firstError.getMessage() == null
                            || !firstError.getMessage().contains("401")) throw firstError;
                    widgetToken = WidgetApi.exchangeDashboardToken(baseUrl, dashboardToken);
                    SecretStore.saveToken(this, widgetToken);
                    fetched = WidgetApi.accounts(baseUrl, widgetToken);
                }
                if (fetched.isEmpty()) throw new IllegalStateException("看板还没有可显示的账户。");
                final String resolvedWidgetToken = widgetToken;
                final List<WidgetApi.Account> resolvedAccounts = fetched;
                runOnUiThread(() -> {
                    pendingWidgetToken = resolvedWidgetToken;
                    pendingBaseUrl = baseUrl;
                    accounts = resolvedAccounts;
                    ArrayAdapter<WidgetApi.Account> adapter = new ArrayAdapter<>(this,
                            android.R.layout.simple_spinner_item, accounts);
                    adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
                    accountSpinner.setAdapter(adapter);
                    String savedId = WidgetStore.accountId(this);
                    for (int i = 0; i < accounts.size(); i++) {
                        if (accounts.get(i).id.equals(savedId)) { accountSpinner.setSelection(i); break; }
                    }
                    if (!dashboardToken.isEmpty()) savedDashboardToken = dashboardToken;
                    saveButton.setVisibility(View.VISIBLE);
                    setBusy(false, "已连接。看板口令和只读凭证已加密保存。", false);
                });
            } catch (Exception e) {
                runOnUiThread(() -> setBusy(false, friendly(e), true));
            }
        });
    }

    private void save() {
        if (accounts.isEmpty() || pendingWidgetToken == null || pendingBaseUrl == null) {
            setMessage("请先连接并读取账户。", true); return;
        }
        WidgetApi.Account account = (WidgetApi.Account) accountSpinner.getSelectedItem();
        if (account == null) { setMessage("请选择账户。", true); return; }
        try {
            String savedPassword = SecretStore.readDashboardToken(this);
            if (savedPassword == null || savedPassword.isEmpty()) {
                setMessage("请输入看板访问口令并连接一次，之后会加密记住。", true);
                return;
            }
            SecretStore.saveToken(this, pendingWidgetToken);
            WidgetStore.save(this, pendingBaseUrl, account.id);
            WidgetProvider.refreshAll(this);
            setResult(Activity.RESULT_OK);
            Toast.makeText(this, "看板和小组件设置已保存", Toast.LENGTH_SHORT).show();
            finish();
        } catch (Exception e) {
            setMessage("保存失败：" + e.getMessage(), true);
        }
    }

    private void setBusy(boolean busy, String text) { setBusy(busy, text, false); }

    private void setBusy(boolean busy, String text, boolean error) {
        runOnUiThread(() -> {
            message.setText(text);
            message.setTextColor(error ? DANGER : ACCENT);
            if (busy) message.setTextColor(ACCENT);
        });
    }

    private void setMessage(String text, boolean error) {
        message.setText(text);
        message.setTextColor(error ? DANGER : ACCENT);
    }

    private String friendly(Exception error) {
        String message = error.getMessage();
        if (message == null || message.isEmpty()) return "连接失败，请检查地址和网络。";
        if (message.contains("Cleartext HTTP traffic") || message.contains("CLEARTEXT")) {
            return "HTTP 连接被系统拦截；请改用 HTTPS 或可信 VPN。";
        }
        if (message.contains("SSL") || message.contains("handshake") || message.contains("wrong version")) {
            return "HTTPS 握手失败：确认地址和端口；当前 8080 端口只提供 HTTP。";
        }
        return message;
    }

    private TextView label(String value) {
        return text(value, 13, TEXT, true);
    }

    private TextView text(String value, int size, int color, boolean bold) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        if (bold) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return view;
    }

    private EditText field(String hint, int inputType) {
        EditText field = new EditText(this);
        field.setSingleLine(true);
        field.setTextSize(14);
        field.setHint(hint);
        field.setInputType(inputType);
        field.setTextColor(TEXT);
        field.setHintTextColor(MUTED);
        field.setPadding(dp(13), dp(10), dp(13), dp(10));
        field.setBackground(roundRect(CARD_BG, dp(11), INPUT_BORDER));
        return field;
    }

    private Button button(String title) {
        Button button = new Button(this);
        button.setText(title);
        button.setTextSize(14);
        button.setTextColor(PAGE_BG);
        button.setAllCaps(false);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setPadding(dp(12), dp(9), dp(12), dp(9));
        button.setBackground(roundRect(ACCENT, dp(12)));
        return button;
    }

    private GradientDrawable roundRect(int color, int radiusDp) {
        return roundRect(color, radiusDp, color);
    }

    private GradientDrawable roundRect(int color, int radiusDp, int strokeColor) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(color);
        shape.setCornerRadius(dp(radiusDp));
        if (strokeColor != color) shape.setStroke(dp(1), strokeColor);
        return shape;
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private LinearLayout.LayoutParams wrap() {
        return new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    @Override protected void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }
}
