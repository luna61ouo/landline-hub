package org.landlinehub.app;

import android.content.Context;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Shared look for the call screens (code-built views, no layout XML). */
final class UI {
    static final String BG = "#14251E";

    static TextView text(Context c, String s, int sp, String color) {
        TextView t = new TextView(c);
        t.setText(s); t.setTextSize(sp); t.setTextColor(Color.parseColor(color)); t.setGravity(Gravity.CENTER);
        return t;
    }

    static Button button(Context c, String s, String color, int height) {
        Button btn = new Button(c);
        btn.setText(s); btn.setTextSize(20); btn.setTextColor(Color.WHITE); btn.setAllCaps(false);
        GradientDrawable bg = new GradientDrawable(); bg.setColor(Color.parseColor(color)); bg.setCornerRadius(60);
        btn.setBackground(bg);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, height);
        lp.topMargin = 30;
        btn.setLayoutParams(lp);
        return btn;
    }
    private UI() {}
}
