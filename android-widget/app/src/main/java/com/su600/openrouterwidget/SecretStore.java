package com.su600.openrouterwidget;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Encrypts local credentials with a non-exportable Android Keystore key. */
final class SecretStore {
    private static final String PREFS = "widget_secrets";
    private static final String KEY_ALIAS = "openrouter-widget-readonly-v1";
    // Keep the original keys so existing installs retain their saved widget token.
    private static final String WIDGET_IV_KEY = "token_iv";
    private static final String WIDGET_DATA_KEY = "token_data";
    private static final String DASHBOARD_IV_KEY = "dashboard_token_iv";
    private static final String DASHBOARD_DATA_KEY = "dashboard_token_data";

    private SecretStore() {}

    static void saveToken(Context context, String token) throws Exception {
        saveSecret(context, WIDGET_IV_KEY, WIDGET_DATA_KEY, token);
    }

    static String readToken(Context context) throws Exception {
        return readSecret(context, WIDGET_IV_KEY, WIDGET_DATA_KEY);
    }

    static void saveDashboardToken(Context context, String token) throws Exception {
        saveSecret(context, DASHBOARD_IV_KEY, DASHBOARD_DATA_KEY, token);
    }

    static String readDashboardToken(Context context) throws Exception {
        return readSecret(context, DASHBOARD_IV_KEY, DASHBOARD_DATA_KEY);
    }

    static void clearDashboardToken(Context context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .remove(DASHBOARD_IV_KEY)
                .remove(DASHBOARD_DATA_KEY)
                .commit();
    }

    private static void saveSecret(Context context, String ivKey, String dataKey, String value) throws Exception {
        if (value == null || value.isEmpty()) return;
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey());
        byte[] encrypted = cipher.doFinal(value.getBytes(StandardCharsets.UTF_8));
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        boolean saved = prefs.edit()
                .putString(ivKey, Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP))
                .putString(dataKey, Base64.encodeToString(encrypted, Base64.NO_WRAP))
                .commit();
        if (!saved) throw new IllegalStateException("无法保存加密凭证");
    }

    private static String readSecret(Context context, String ivKey, String dataKey) throws Exception {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String ivText = prefs.getString(ivKey, null);
        String dataText = prefs.getString(dataKey, null);
        if (ivText == null || dataText == null) return null;
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(),
                new GCMParameterSpec(128, Base64.decode(ivText, Base64.NO_WRAP)));
        byte[] clear = cipher.doFinal(Base64.decode(dataText, Base64.NO_WRAP));
        return new String(clear, StandardCharsets.UTF_8);
    }

    static void clear(Context context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().clear().apply();
        try {
            KeyStore store = KeyStore.getInstance("AndroidKeyStore");
            store.load(null);
            if (store.containsAlias(KEY_ALIAS)) store.deleteEntry(KEY_ALIAS);
        } catch (Exception ignored) {}
    }

    private static SecretKey getOrCreateKey() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (store.containsAlias(KEY_ALIAS)) {
            return (SecretKey) store.getKey(KEY_ALIAS, null);
        }
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build());
        return generator.generateKey();
    }
}
