package org.landlinehub.app;

import android.Manifest;
import android.app.Activity;
import android.app.NotificationManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.text.InputType;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** Main screen: pairing (first run), status, warnings, dial out, recent calls.
 *  Pairing can also be done with adb:  am start -n org.landlinehub.app/.MainActivity --es url URL --es code CODE */
public class MainActivity extends Activity {
    private static MainActivity shown;
    private static final Handler main = new Handler(Looper.getMainLooper());
    private LinearLayout root, list;
    private TextView status, warn;

    static void refreshLater() { main.post(() -> { if (shown != null) shown.refresh(); }); }

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        build();
        takeIntent(getIntent());
        if (Config.paired(this)) ListenService.start(this);
        askPerms(false);
    }

    @Override protected void onNewIntent(Intent i) { super.onNewIntent(i); takeIntent(i); }

    private void takeIntent(Intent i) {
        if (i != null && i.hasExtra("url") && i.hasExtra("code")) pair(i.getStringExtra("url"), i.getStringExtra("code"));
    }

    private void build() {
        ScrollView sv = new ScrollView(this);
        sv.setBackgroundColor(Color.parseColor("#F4F7F5"));
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(40, 90, 40, 40);
        sv.addView(root);
        setContentView(sv);
        render();
    }

    private void render() {
        root.removeAllViews();
        TextView title = new TextView(this);
        title.setText(T.s("app")); title.setTextSize(26); title.setTextColor(Color.parseColor("#1E3A2F"));
        root.addView(title);
        if (!Config.paired(this)) { renderPairing(); return; }
        status = new TextView(this); status.setTextSize(16); status.setPadding(0, 16, 0, 8);
        root.addView(status);
        warn = new TextView(this); warn.setTextSize(15); warn.setTextColor(Color.parseColor("#B23B3B"));
        root.addView(warn);

        EditText num = new EditText(this);
        num.setHint(T.s("dial_hint"));
        num.setInputType(InputType.TYPE_CLASS_PHONE);
        root.addView(num);
        Button call = button(T.s("dial_go"));
        call.setOnClickListener(v -> {
            String n = num.getText().toString().trim();
            if (!n.isEmpty()) startActivity(new Intent(this, InCallActivity.class).putExtra("dial", n));
        });
        root.addView(call);
        Button perms = button(T.s("perm"));
        perms.setOnClickListener(v -> askPerms(true));
        root.addView(perms);

        TextView h = new TextView(this);
        h.setText(T.s("history")); h.setTextSize(20); h.setTextColor(Color.parseColor("#1E3A2F")); h.setPadding(0, 40, 0, 12);
        root.addView(h);
        list = new LinearLayout(this); list.setOrientation(LinearLayout.VERTICAL);
        root.addView(list);
        Button unpair = button(T.s("unpair"));
        unpair.setOnClickListener(v -> { Config.clear(this); stopService(new Intent(this, ListenService.class)); render(); });
        root.addView(unpair);
        refresh();
    }

    private void renderPairing() {
        TextView t = new TextView(this); t.setText(T.s("pair_title")); t.setTextSize(18); t.setPadding(0, 30, 0, 10);
        root.addView(t);
        EditText url = new EditText(this); url.setHint(T.s("pair_url")); url.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        EditText code = new EditText(this); code.setHint(T.s("pair_code"));
        root.addView(url); root.addView(code);
        Button go = button(T.s("pair_go"));
        go.setOnClickListener(v -> pair(url.getText().toString().trim(), code.getText().toString().trim()));
        root.addView(go);
    }

    private void pair(String url, String code) {
        new Thread(() -> {
            try {
                Config.save(this, url, "", "");
                JSONObject r = new JSONObject(Http.post(this, "/v1/pair", new JSONObject().put("code", code).toString()));
                if (!r.has("token")) throw new Exception(r.optString("error"));
                Config.save(this, url, r.getString("token"), r.optString("client_id"));
                main.post(() -> {
                    render();
                    ListenService.restart(this);
                    status.setText(T.f("pair_ok", Config.name(this)));
                });
            } catch (Exception e) {
                Config.clear(this);
                main.post(() -> { render(); root.addView(textRow(T.f("failed", e.getMessage()))); });
            }
        }).start();
    }

    private Button button(String s) {
        Button btn = new Button(this);
        btn.setText(s); btn.setAllCaps(false); btn.setTextColor(Color.WHITE); btn.setTextSize(16);
        GradientDrawable bg = new GradientDrawable(); bg.setColor(Color.parseColor("#2E7D5B")); bg.setCornerRadius(40);
        btn.setBackground(bg);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 140);
        lp.topMargin = 24; btn.setLayoutParams(lp);
        return btn;
    }

    private void askPerms(boolean openSettings) {
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS, Manifest.permission.RECORD_AUDIO}, 1);
            return;
        }
        if (!openSettings) return;
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= 34 && !nm.canUseFullScreenIntent()) {
            startActivity(new Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.parse("package:" + getPackageName())));
            return;
        }
        PowerManager pm = getSystemService(PowerManager.class);
        if (!pm.isIgnoringBatteryOptimizations(getPackageName()))
            startActivity(new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:" + getPackageName())));
    }

    private String warnings() {
        StringBuilder w = new StringBuilder();
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            w.append(T.s("w_notif"));
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) w.append(T.s("w_mic"));
        if (Build.VERSION.SDK_INT >= 34 && !getSystemService(NotificationManager.class).canUseFullScreenIntent()) w.append(T.s("w_full"));
        if (!getSystemService(PowerManager.class).isIgnoringBatteryOptimizations(getPackageName())) w.append(T.s("w_batt"));
        return w.toString();
    }

    @Override protected void onResume() { super.onResume(); shown = this; refresh(); }
    @Override protected void onPause() { super.onPause(); shown = null; }

    private void refresh() {
        if (status == null || !Config.paired(this)) return;
        status.setText(T.f("status", ListenService.status));
        warn.setText(warnings());
        new Thread(() -> {
            try {
                JSONArray arr = new JSONArray(Http.get(this, "/v1/history"));
                main.post(() -> renderHistory(arr));
            } catch (Exception e) {
                main.post(() -> { if (list != null) { list.removeAllViews(); list.addView(textRow(T.f("failed", e.getMessage()))); } });
            }
        }).start();
    }

    private void renderHistory(JSONArray arr) {
        if (list == null) return;
        list.removeAllViews();
        if (arr.length() == 0) { list.addView(textRow(T.s("nothing"))); return; }
        SimpleDateFormat f = new SimpleDateFormat("M/d HH:mm", Locale.getDefault());
        for (int i = 0; i < arr.length(); i++) {
            JSONObject e = arr.optJSONObject(i);
            String when = f.format(new Date((long) (e.optDouble("started") * 1000)));
            boolean in = "inbound".equals(e.optString("direction"));
            String res = e.optString("result");
            boolean missed = in && (res.equals("missed") || res.equals("caller_gave_up") || res.equals("unanswered"));
            list.addView(row(Config.pretty(e.optString("number", "")),
                    when + "  " + (in ? T.s("r_in") : T.s("r_out")) + (missed ? "  " + T.s("r_missed") : "")));
        }
    }

    private TextView textRow(String s) {
        TextView t = new TextView(this); t.setText(s); t.setTextSize(15); t.setPadding(8, 12, 8, 12);
        return t;
    }

    private LinearLayout row(String a, String b) {
        LinearLayout r = new LinearLayout(this); r.setOrientation(LinearLayout.VERTICAL); r.setPadding(24, 20, 24, 20);
        GradientDrawable bg = new GradientDrawable(); bg.setColor(Color.WHITE); bg.setCornerRadius(24); r.setBackground(bg);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.bottomMargin = 14; r.setLayoutParams(lp);
        TextView t1 = new TextView(this); t1.setText(a); t1.setTextSize(19); t1.setTextColor(Color.parseColor("#1E3A2F"));
        TextView t2 = new TextView(this); t2.setText(b); t2.setTextSize(14); t2.setTextColor(Color.GRAY);
        r.addView(t1); r.addView(t2);
        return r;
    }
}
