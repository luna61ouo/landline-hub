package org.landlinehub.app;

import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/** UI text in English and Traditional Chinese (Taiwan), picked from the phone's language. */
final class T {
    private static final Map<String, String[]> M = new HashMap<>();
    static {
        add("app", "Landline", "市話");
        add("incoming", "Landline call", "市話來電");
        add("extension", "Extension call", "分機來電");
        add("answer", "Answer", "接聽");
        add("mute", "Silence", "靜音");
        add("close", "Close", "關閉畫面");
        add("hangup", "Hang up", "掛斷");
        add("speaker_on", "Speaker: on", "擴音：開");
        add("speaker_off", "Speaker: off", "擴音：關");
        add("keypad", "Keypad", "按鍵");
        add("connecting", "Connecting…", "接通中…");
        add("dialing", "Dialling…", "撥號中…");
        add("in_call", "In call  %02d:%02d", "通話中　%02d:%02d");
        add("ended", "Call ended", "通話結束");
        add("remote_hung_up", "The other side hung up", "對方掛斷了");
        add("failed", "Failed: %s", "失敗：%s");
        add("ring_n", "Ring %d", "響第 %d 聲");
        add("ringing", "Ringing", "來電中");
        add("muted", "  (silenced)", "　（已靜音）");
        add("no_number", "Unknown number", "未顯示號碼");
        add("missed", "Missed landline call: %s", "未接市話：%s");
        add("status", "Status: %s", "狀態：%s");
        add("st_idle", "Standing by", "待命中");
        add("st_unpaired", "Not paired yet", "尚未配對");
        add("st_connecting", "Connecting…", "連線中…");
        add("st_retry", "Disconnected, retrying in %d s (%s)", "連線中斷，%d 秒後重連（%s）");
        add("pair_title", "Pair with your hub", "與市話主機配對");
        add("pair_url", "Hub address, e.g. http://192.168.1.10:8910", "主機網址，例如 http://192.168.1.10:8910");
        add("pair_code", "Pairing code (landline-hub pair --name …)", "配對碼（landline-hub pair --name …）");
        add("pair_go", "Pair", "配對");
        add("pair_ok", "Paired as %s", "已配對：%s");
        add("dial_hint", "Number to call", "要撥的號碼");
        add("dial_go", "Call via landline", "用市話撥出");
        add("history", "Recent calls", "最近通話");
        add("nothing", "No calls yet", "還沒有通話紀錄");
        add("perm", "Check permissions", "檢查權限");
        add("w_notif", "⚠ Notifications are off\n", "⚠ 沒有通知權限\n");
        add("w_full", "⚠ No full-screen call permission (nothing pops up when locked)\n", "⚠ 沒有全螢幕來電權限（鎖屏時不會跳畫面）\n");
        add("w_batt", "⚠ Battery optimisation may stop the background connection\n", "⚠ 受省電限制，背景可能被關掉\n");
        add("w_mic", "⚠ No microphone permission\n", "⚠ 沒有麥克風權限\n");
        add("r_in", "Incoming", "來電");
        add("r_out", "Outgoing", "撥出");
        add("r_missed", "missed", "未接");
        add("unpair", "Unpair", "解除配對");
    }
    private static void add(String k, String en, String zh) { M.put(k, new String[]{en, zh}); }
    private static boolean zh() { return Locale.getDefault().getLanguage().equals("zh"); }
    static String s(String k) { String[] v = M.get(k); return v == null ? k : v[zh() ? 1 : 0]; }
    static String f(String k, Object... a) { return String.format(Locale.US, s(k), a); }
    private T() {}
}
