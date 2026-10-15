package org.landlinehub.app;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

/** Full-screen incoming call (also over the lock screen): answer / silence / close. */
public class IncomingActivity extends Activity {
    private TextView label, number, sub;
    private Button mute;

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setBackgroundColor(Color.parseColor(UI.BG));
        root.setPadding(48, 220, 48, 120);
        label = UI.text(this, T.s("incoming"), 22, "#9FD3BC");
        number = UI.text(this, "", 40, "#FFFFFF");
        number.setPadding(0, 40, 0, 16);
        sub = UI.text(this, "", 18, "#B8C7C0");
        root.addView(label); root.addView(number); root.addView(sub);
        root.addView(new LinearLayout(this), new LinearLayout.LayoutParams(1, 0, 1f));
        Button pick = UI.button(this, T.s("answer"), "#2E9D63", 170);
        pick.setOnClickListener(v -> {
            JSONObject e = Ringer.current;
            if (e != null) startActivity(new Intent(this, InCallActivity.class).putExtra("answer", e.optString("call_id"))
                    .putExtra("title", Ringer.title(e)));
            finish();
        });
        mute = UI.button(this, T.s("mute"), "#3A5A4C", 170);
        mute.setOnClickListener(v -> Ringer.mute(this));
        Button close = UI.button(this, T.s("close"), "#5A3A3A", 170);
        close.setOnClickListener(v -> { Ringer.mute(this); finish(); });
        root.addView(pick); root.addView(mute); root.addView(close);
        setContentView(root);
    }

    @Override protected void onResume() {
        super.onResume();
        Ringer.listener = () -> runOnUiThread(this::render);
        render();
    }

    @Override protected void onPause() { super.onPause(); Ringer.listener = null; }

    private void render() {
        JSONObject e = Ringer.current;
        if (e == null) { finish(); return; }
        label.setText(e.optBoolean("extension") ? T.s("extension") : T.s("incoming"));
        number.setText(Ringer.title(e));
        int rings = e.optInt("rings", 0);
        sub.setText((rings > 0 ? T.f("ring_n", rings) : T.s("ringing")) + (Ringer.muted ? T.s("muted") : ""));
        mute.setEnabled(!Ringer.muted);
    }
}
