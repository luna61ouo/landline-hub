package org.landlinehub.app;

import android.Manifest;
import android.app.Activity;
import android.app.NotificationManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.text.InputType;
import android.view.Gravity;
import android.view.HapticFeedbackConstants;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** Main screen, laid out like a phone's dialler: the keypad comes first, with
 *  Recents / Keypad / Settings tabs along the bottom.  First run shows pairing.
 *  Pairing can also be done with adb:  am start -n org.landlinehub.app/.MainActivity --es url URL --es code CODE */
public class MainActivity extends Activity {
    private static MainActivity shown;
    private static final Handler main = new Handler(Looper.getMainLooper());
    private static final String INK = "#1C1C1E", GREY = "#8E8E93", KEY = "#E5E5EA", BG = "#FFFFFF",
            GREEN = "#34C759", RED = "#D9423B", ACCENT = "#2E7D5B";
    private static final int RECENTS = 0, KEYPAD = 1, SETTINGS = 2;

    private FrameLayout content;
    private LinearLayout tabBar, list;
    private TextView status, warn, banner, numberView;
    private View deleteKey;
    private final StringBuilder number = new StringBuilder();
    private int tab = KEYPAD;
    private JSONArray history = new JSONArray();

    static void refreshLater() { main.post(() -> { if (shown != null) shown.refresh(); }); }

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().setStatusBarColor(Color.parseColor(BG));
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR);
        render();
        takeIntent(getIntent());
        if (Config.paired(this)) ListenService.start(this);
        askPerms(false);
    }

    @Override protected void onNewIntent(Intent i) { super.onNewIntent(i); takeIntent(i); }

    private void takeIntent(Intent i) {
        if (i != null && i.hasExtra("url") && i.hasExtra("code")) pair(i.getStringExtra("url"), i.getStringExtra("code"));
    }

    // ------------------------------------------------------------------ shell

    private void render() {
        if (!Config.paired(this)) { renderPairing(); return; }
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor(BG));
        content = new FrameLayout(this);
        root.addView(content, new LinearLayout.LayoutParams(-1, 0, 1f));
        View line = new View(this);
        line.setBackgroundColor(Color.parseColor("#D1D1D6"));
        root.addView(line, new LinearLayout.LayoutParams(-1, 2));
        tabBar = new LinearLayout(this);
        tabBar.setBackgroundColor(Color.parseColor("#F7F7F7"));
        tabBar.setPadding(0, 14, 0, 14);
        root.addView(tabBar, new LinearLayout.LayoutParams(-1, -2));
        setContentView(root);
        UI.fitSystemBars(root);
        showTab(tab);
    }

    private void showTab(int t) {
        tab = t;
        content.removeAllViews();
        list = null; status = null; warn = null; banner = null; numberView = null; deleteKey = null;
        content.addView(t == RECENTS ? recentsView() : t == SETTINGS ? settingsView() : keypadView());
        tabBar.removeAllViews();
        String[][] tabs = {{"◷", T.s("tab_recents")}, {"⌗", T.s("tab_keypad")}, {"⚙", T.s("tab_settings")}};
        for (int i = 0; i < tabs.length; i++) {
            final int idx = i;
            LinearLayout b = new LinearLayout(this);
            b.setOrientation(LinearLayout.VERTICAL);
            b.setGravity(Gravity.CENTER);
            String c = i == t ? ACCENT : GREY;
            TextView icon = label(tabs[i][0], 24, c); icon.setGravity(Gravity.CENTER);
            TextView name = label(tabs[i][1], 12, c); name.setGravity(Gravity.CENTER);
            b.addView(icon); b.addView(name);
            b.setOnClickListener(v -> showTab(idx));
            tabBar.addView(b, new LinearLayout.LayoutParams(0, -2, 1f));
        }
        refresh();
    }

    // ------------------------------------------------------------------ keypad

    private View keypadView() {
        LinearLayout v = new LinearLayout(this);
        v.setOrientation(LinearLayout.VERTICAL);
        v.setGravity(Gravity.CENTER_HORIZONTAL);
        v.setPadding(0, 30, 0, 30);

        banner = label("", 14, "#FFFFFF");
        banner.setPadding(30, 18, 30, 18);
        banner.setGravity(Gravity.CENTER);
        banner.setBackground(round(RED, 30));
        banner.setVisibility(View.GONE);
        banner.setOnClickListener(x -> showTab(SETTINGS));
        LinearLayout.LayoutParams bl = new LinearLayout.LayoutParams(-2, -2);
        bl.bottomMargin = 10;
        v.addView(banner, bl);

        numberView = label("", 38, INK);
        numberView.setGravity(Gravity.CENTER);
        numberView.setSingleLine(true);
        numberView.setTypeface(Typeface.create("sans-serif-light", Typeface.NORMAL));
        v.addView(numberView, new LinearLayout.LayoutParams(-1, 150));
        v.addView(new View(this), new LinearLayout.LayoutParams(1, 0, 1f));

        String[][] keys = {{"1", ""}, {"2", "ABC"}, {"3", "DEF"}, {"4", "GHI"}, {"5", "JKL"}, {"6", "MNO"},
                {"7", "PQRS"}, {"8", "TUV"}, {"9", "WXYZ"}, {"*", ""}, {"0", "+"}, {"#", ""}};
        int size = dp(76), gap = dp(24);
        for (int r = 0; r < 4; r++) {
            LinearLayout row = new LinearLayout(this);
            row.setGravity(Gravity.CENTER);
            for (int c = 0; c < 3; c++) {
                String[] k = keys[r * 3 + c];
                View key = digitKey(k[0], k[1], size);
                LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(size, size);
                lp.leftMargin = lp.rightMargin = gap / 2;
                row.addView(key, lp);
            }
            LinearLayout.LayoutParams rl = new LinearLayout.LayoutParams(-2, -2);
            rl.bottomMargin = dp(14);
            v.addView(row, rl);
        }

        // bottom row: (spacer) [call] [delete]
        LinearLayout bottom = new LinearLayout(this);
        bottom.setGravity(Gravity.CENTER);
        View spacer = new View(this);
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(size, size);
        sp.leftMargin = sp.rightMargin = gap / 2;
        bottom.addView(spacer, sp);
        TextView call = label("✆", 34, "#FFFFFF");
        call.setGravity(Gravity.CENTER);
        call.setBackground(oval(GREEN));
        call.setContentDescription(T.s("dial_go"));
        call.setOnClickListener(x -> dial());
        LinearLayout.LayoutParams cp = new LinearLayout.LayoutParams(size, size);
        cp.leftMargin = cp.rightMargin = gap / 2;
        bottom.addView(call, cp);
        TextView del = label("⌫", 28, GREY);
        del.setGravity(Gravity.CENTER);
        del.setContentDescription(T.s("delete"));
        del.setOnClickListener(x -> { if (number.length() > 0) { number.setLength(number.length() - 1); showNumber(); } });
        del.setOnLongClickListener(x -> { number.setLength(0); showNumber(); return true; });
        deleteKey = del;
        bottom.addView(del, sp);
        v.addView(bottom);
        showNumber();
        return v;
    }

    private View digitKey(String digit, String letters, int size) {
        LinearLayout k = new LinearLayout(this);
        k.setOrientation(LinearLayout.VERTICAL);
        k.setGravity(Gravity.CENTER);
        k.setBackground(oval(KEY));
        TextView d = label(digit, 34, INK); d.setGravity(Gravity.CENTER);
        k.addView(d);
        if (!letters.isEmpty()) {
            TextView l = label(letters, 10, INK); l.setGravity(Gravity.CENTER); l.setLetterSpacing(0.15f);
            k.addView(l);
        }
        k.setOnClickListener(x -> { x.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP); type(digit); });
        if (digit.equals("0")) k.setOnLongClickListener(x -> { type("+"); return true; });
        return k;
    }

    private void type(String s) {
        if (number.length() < 20) number.append(s);
        showNumber();
    }

    private void showNumber() {
        if (numberView == null) return;
        String n = number.toString();
        numberView.setText(n.isEmpty() ? "" : Config.pretty(n));
        if (deleteKey != null) deleteKey.setVisibility(n.isEmpty() ? View.INVISIBLE : View.VISIBLE);
    }

    private void dial() {
        String n = number.toString().trim();
        if (n.isEmpty()) {                       // like a phone: an empty call key recalls the last number dialled
            for (int i = 0; i < history.length(); i++) {
                JSONObject e = history.optJSONObject(i);
                if (e != null && "outbound".equals(e.optString("direction")) && !e.optString("number").isEmpty()) {
                    number.append(e.optString("number")); showNumber(); return;
                }
            }
            return;
        }
        startActivity(new Intent(this, InCallActivity.class).putExtra("dial", n));
    }

    // ------------------------------------------------------------------ recents

    private View recentsView() {
        ScrollView sv = new ScrollView(this);
        LinearLayout v = new LinearLayout(this);
        v.setOrientation(LinearLayout.VERTICAL);
        v.setPadding(40, 40, 40, 40);
        TextView h = label(T.s("history"), 30, INK);
        h.setTypeface(Typeface.DEFAULT_BOLD);
        h.setPadding(0, 0, 0, 24);
        v.addView(h);
        list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        v.addView(list);
        sv.addView(v);
        renderHistory();
        return sv;
    }

    private void renderHistory() {
        if (list == null) return;
        list.removeAllViews();
        if (history.length() == 0) { list.addView(label(T.s("nothing"), 16, GREY)); return; }
        SimpleDateFormat f = new SimpleDateFormat("M/d HH:mm", Locale.getDefault());
        for (int i = 0; i < history.length(); i++) {
            JSONObject e = history.optJSONObject(i);
            if (e == null) continue;
            String raw = e.optString("number", "");
            String when = f.format(new Date((long) (e.optDouble("started") * 1000)));
            boolean in = "inbound".equals(e.optString("direction"));
            String res = e.optString("result");
            boolean missed = in && (res.equals("missed") || res.equals("caller_gave_up") || res.equals("unanswered"));

            LinearLayout r = new LinearLayout(this);
            r.setGravity(Gravity.CENTER_VERTICAL);
            r.setPadding(0, 26, 0, 26);
            LinearLayout left = new LinearLayout(this);
            left.setOrientation(LinearLayout.VERTICAL);
            TextView n = label(raw.isEmpty() ? T.s("no_number") : Config.pretty(raw), 19, missed ? RED : INK);
            TextView kind = label((in ? T.s("r_in") : T.s("r_out")) + (missed ? " · " + T.s("r_missed") : ""), 14, GREY);
            left.addView(n); left.addView(kind);
            r.addView(left, new LinearLayout.LayoutParams(0, -2, 1f));
            r.addView(label(when, 14, GREY));
            if (!raw.isEmpty()) r.setOnClickListener(x -> {   // tap: put the number on the keypad, one more tap calls
                number.setLength(0); number.append(raw); showTab(KEYPAD);
            });
            list.addView(r);
            View sep = new View(this);
            sep.setBackgroundColor(Color.parseColor("#E5E5EA"));
            list.addView(sep, new LinearLayout.LayoutParams(-1, 2));
        }
    }

    // ------------------------------------------------------------------ settings

    private View settingsView() {
        ScrollView sv = new ScrollView(this);
        LinearLayout v = new LinearLayout(this);
        v.setOrientation(LinearLayout.VERTICAL);
        v.setPadding(40, 40, 40, 40);
        TextView h = label(T.s("tab_settings"), 30, INK);
        h.setTypeface(Typeface.DEFAULT_BOLD);
        v.addView(h);
        status = label("", 16, INK); status.setPadding(0, 24, 0, 8);
        v.addView(status);
        v.addView(label(Config.name(this).isEmpty() ? "" : T.f("pair_ok", Config.name(this)), 14, GREY));
        warn = label("", 15, RED); warn.setPadding(0, 16, 0, 0);
        v.addView(warn);
        Button perms = button(T.s("perm"), ACCENT);
        perms.setOnClickListener(x -> askPerms(true));
        v.addView(perms);
        Button unpair = button(T.s("unpair"), "#8E8E93");
        unpair.setOnClickListener(x -> { Config.clear(this); stopService(new Intent(this, ListenService.class)); render(); });
        v.addView(unpair);
        sv.addView(v);
        return sv;
    }

    // ------------------------------------------------------------------ pairing (first run)

    private void renderPairing() {
        ScrollView sv = new ScrollView(this);
        sv.setBackgroundColor(Color.parseColor("#F4F7F5"));
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(40, 40, 40, 40);
        sv.addView(root);
        TextView title = label(T.s("app"), 26, "#1E3A2F");
        root.addView(title);
        TextView t = label(T.s("pair_title"), 18, INK); t.setPadding(0, 30, 0, 10);
        root.addView(t);
        EditText url = new EditText(this); url.setHint(T.s("pair_url")); url.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        EditText code = new EditText(this); code.setHint(T.s("pair_code"));
        root.addView(url); root.addView(code);
        Button go = button(T.s("pair_go"), ACCENT);
        go.setOnClickListener(x -> pair(url.getText().toString().trim(), code.getText().toString().trim()));
        root.addView(go);
        setContentView(sv);
        UI.fitSystemBars(sv);
        content = null;
        pairingRoot = root;
    }

    private LinearLayout pairingRoot;

    private void pair(String url, String code) {
        new Thread(() -> {
            try {
                Config.save(this, url, "", "");
                JSONObject r = new JSONObject(Http.post(this, "/v1/pair", new JSONObject().put("code", code).toString()));
                if (!r.has("token")) throw new Exception(r.optString("error"));
                Config.save(this, url, r.getString("token"), r.optString("client_id"));
                main.post(() -> {
                    tab = KEYPAD;
                    render();
                    ListenService.restart(this);
                });
            } catch (Exception e) {
                Config.clear(this);
                main.post(() -> {
                    render();
                    if (pairingRoot != null) pairingRoot.addView(label(T.f("failed", e.getMessage()), 15, RED));
                });
            }
        }).start();
    }

    // ------------------------------------------------------------------ permissions / status

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
        return w.toString().trim();
    }

    @Override protected void onResume() { super.onResume(); shown = this; refresh(); }
    @Override protected void onPause() { super.onPause(); shown = null; }

    private void refresh() {
        if (content == null || !Config.paired(this)) return;
        String w = warnings();
        if (status != null) status.setText(T.f("status", ListenService.status));
        if (warn != null) warn.setText(w);
        if (banner != null) {
            boolean bad = !w.isEmpty() || !ListenService.status.equals(T.s("st_idle"));
            banner.setText(!w.isEmpty() ? T.s("banner_perm") : T.f("status", ListenService.status));
            banner.setVisibility(bad ? View.VISIBLE : View.GONE);
        }
        new Thread(() -> {
            try {
                JSONArray arr = new JSONArray(Http.get(this, "/v1/history"));
                main.post(() -> { history = arr; renderHistory(); });
            } catch (Exception e) {
                main.post(() -> { if (list != null) { list.removeAllViews(); list.addView(label(T.f("failed", e.getMessage()), 15, RED)); } });
            }
        }).start();
    }

    // ------------------------------------------------------------------ helpers

    private TextView label(String s, int sp, String color) {
        TextView t = new TextView(this);
        t.setText(s); t.setTextSize(sp); t.setTextColor(Color.parseColor(color));
        return t;
    }

    private Button button(String s, String color) {
        Button btn = new Button(this);
        btn.setText(s); btn.setAllCaps(false); btn.setTextColor(Color.WHITE); btn.setTextSize(16);
        btn.setBackground(round(color, 40));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 140);
        lp.topMargin = 24; btn.setLayoutParams(lp);
        return btn;
    }

    private static GradientDrawable round(String color, int radius) {
        GradientDrawable bg = new GradientDrawable(); bg.setColor(Color.parseColor(color)); bg.setCornerRadius(radius);
        return bg;
    }

    private static GradientDrawable oval(String color) {
        GradientDrawable bg = new GradientDrawable(); bg.setShape(GradientDrawable.OVAL); bg.setColor(Color.parseColor(color));
        return bg;
    }

    private int dp(int v) { return Math.round(v * getResources().getDisplayMetrics().density); }
}
