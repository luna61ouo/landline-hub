package org.landlinehub.app;

import android.content.Context;
import android.content.SharedPreferences;

/** Hub address and this phone's credential.  The credential comes from pairing
 *  and is stored only on the phone; the hub keeps nothing but its hash. */
final class Config {
    static SharedPreferences prefs(Context c) { return c.getSharedPreferences("hub", Context.MODE_PRIVATE); }
    static String url(Context c) { return prefs(c).getString("url", ""); }
    static String token(Context c) { return prefs(c).getString("token", ""); }
    static String name(Context c) { return prefs(c).getString("name", ""); }
    static boolean paired(Context c) { return !token(c).isEmpty() && !url(c).isEmpty(); }

    static void save(Context c, String url, String token, String name) {
        prefs(c).edit().putString("url", url.replaceAll("/+$", "")).putString("token", token).putString("name", name).apply();
    }
    static void clear(Context c) { prefs(c).edit().clear().apply(); }

    /** 0912345678 -> 0912-345-678; 0212345678 -> 02-1234-5678; otherwise unchanged. */
    static String pretty(String n) {
        if (n == null || n.isEmpty() || n.equals("null")) return T.s("no_number");
        if (n.matches("09\\d{8}")) return n.substring(0, 4) + "-" + n.substring(4, 7) + "-" + n.substring(7);
        if (n.matches("0[2-8]\\d{7,8}")) {
            int a = n.startsWith("037") || n.startsWith("049") || n.startsWith("082") || n.startsWith("089") ? 3 : 2;
            if (n.startsWith("0836") || n.startsWith("0826")) a = 4;
            String rest = n.substring(a);
            int mid = rest.length() - 4;
            return n.substring(0, a) + "-" + rest.substring(0, mid) + "-" + rest.substring(mid);
        }
        return n;
    }
    private Config() {}
}
