package org.landlinehub.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.Ringtone;
import android.media.RingtoneManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.os.VibrationEffect;
import android.os.Vibrator;

import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/** Ringing, the full-screen incoming notification and missed-call notices.
 *  Knows only hub events, nothing about the gateway. */
final class Ringer {
    static final String CH_INCOMING = "incoming_v1";
    static final String CH_MISSED = "missed_v1";
    static final int NOTIF_INCOMING = 10;
    static final long SAFETY_MS = 120_000;

    interface Listener { void onChanged(); }

    static volatile JSONObject current;       // the call ringing now, or null
    static volatile boolean muted;
    static volatile Listener listener;
    private static volatile long resyncAt;
    private static Ringtone ringtone;
    private static final Handler main = new Handler(Looper.getMainLooper());
    private static final Object safety = new Object();

    static void channels(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        NotificationChannel in = new NotificationChannel(CH_INCOMING, T.s("incoming"), NotificationManager.IMPORTANCE_HIGH);
        in.setSound(null, null);              // we play the ringtone ourselves so it can loop and stop
        in.enableVibration(false);
        in.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
        nm.createNotificationChannel(in);
        nm.createNotificationChannel(new NotificationChannel(CH_MISSED, T.s("history"), NotificationManager.IMPORTANCE_DEFAULT));
    }

    static String title(JSONObject e) { return Config.pretty(e.optString("number", "")); }

    static boolean isCurrent(JSONObject e) {
        JSONObject c = current;
        return c != null && c.optString("call_id").equals(e.optString("call_id"));
    }

    static void onEvent(Context c, JSONObject e) {
        String type = e.optString("type");
        main.post(() -> {
            switch (type) {
                case "incoming":
                    if (isCurrent(e)) { current = merge(e); resyncAt = 0; notifyListener(); }
                    else start(c, e);
                    break;
                case "caller_id": case "ring":
                    if (isCurrent(e)) { current = merge(e); post(c, current); notifyListener(); }
                    break;
                case "answered": case "ring_stopped":
                    if (isCurrent(e)) stop(c);
                    break;
                case "ended":
                    if (isCurrent(e)) {
                        JSONObject was = current;
                        stop(c);
                        String r = e.optString("reason");
                        if (r.equals("missed") || r.equals("caller_gave_up") || r.equals("unanswered")) missed(c, was);
                    }
                    MainActivity.refreshLater();
                    break;
            }
        });
    }

    private static JSONObject merge(JSONObject e) {
        try {
            JSONObject m = new JSONObject(current.toString());
            for (java.util.Iterator<String> it = e.keys(); it.hasNext(); ) {
                String k = it.next();
                if (!e.isNull(k)) m.put(k, e.get(k));
            }
            return m;
        } catch (Exception x) { return e; }
    }

    /** Reconnected: the hub replays calls still ringing right away.  If ours is
     *  not among them within a few seconds, it ended while we were offline. */
    static void resync(Context c) {
        if (current == null) return;
        long at = SystemClock.uptimeMillis();
        resyncAt = at;
        main.postDelayed(() -> { if (resyncAt == at && current != null) stop(c); }, 3000);
    }

    private static void start(Context c, JSONObject e) {
        current = e;
        muted = false;
        post(c, e);
        play(c);
        main.removeCallbacksAndMessages(safety);
        main.postAtTime(() -> stop(c), safety, SystemClock.uptimeMillis() + SAFETY_MS);
        notifyListener();
    }

    private static void post(Context c, JSONObject e) {
        Intent full = new Intent(c, IncomingActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_NO_USER_ACTION);
        PendingIntent fullPi = PendingIntent.getActivity(c, 1, full, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent mutePi = PendingIntent.getBroadcast(c, 2,
                new Intent(c, BootReceiver.class).setAction(BootReceiver.ACTION_MUTE), PendingIntent.FLAG_IMMUTABLE);
        int rings = e.optInt("rings", 0);
        Notification n = new Notification.Builder(c, CH_INCOMING)
                .setSmallIcon(R.drawable.ic_launcher)
                .setContentTitle(e.optBoolean("extension") ? T.s("extension") : T.s("incoming"))
                .setContentText(title(e) + (rings > 0 ? "  " + T.f("ring_n", rings) : ""))
                .setCategory(Notification.CATEGORY_CALL)
                .setOngoing(true)
                .setFullScreenIntent(fullPi, true)
                .setContentIntent(fullPi)
                .addAction(new Notification.Action.Builder(null, T.s("mute"), mutePi).build())
                .build();
        c.getSystemService(NotificationManager.class).notify(NOTIF_INCOMING, n);
    }

    /** Like a real incoming call: normal mode rings (and vibrates if the system says so),
     *  vibrate mode only vibrates, silent mode does neither. */
    private static void play(Context c) {
        AudioManager am = c.getSystemService(AudioManager.class);
        int mode = am != null ? am.getRingerMode() : AudioManager.RINGER_MODE_NORMAL;
        if (mode == AudioManager.RINGER_MODE_SILENT) return;
        boolean vibrate = mode == AudioManager.RINGER_MODE_VIBRATE
                || android.provider.Settings.System.getInt(c.getContentResolver(), "vibrate_when_ringing", 1) == 1;
        if (mode == AudioManager.RINGER_MODE_NORMAL) try {
            if (ringtone != null) ringtone.stop();
            ringtone = RingtoneManager.getRingtone(c, RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE));
            if (ringtone != null) {
                ringtone.setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
                if (Build.VERSION.SDK_INT >= 28) ringtone.setLooping(true);
                ringtone.play();
            }
        } catch (Exception ignored) {}
        if (!vibrate) return;
        Vibrator v = c.getSystemService(Vibrator.class);
        if (v != null) v.vibrate(VibrationEffect.createWaveform(new long[]{0, 1000, 2000}, 0));
    }

    static void mute(Context c) {
        muted = true;
        if (ringtone != null) ringtone.stop();
        Vibrator v = c.getSystemService(Vibrator.class);
        if (v != null) v.cancel();
        notifyListener();
    }

    static void stop(Context c) {
        main.removeCallbacksAndMessages(safety);
        mute(c);
        muted = false;
        current = null;
        c.getSystemService(NotificationManager.class).cancel(NOTIF_INCOMING);
        notifyListener();
    }

    private static void missed(Context c, JSONObject e) {
        String when = new SimpleDateFormat("HH:mm", Locale.getDefault()).format(new Date((long) (e.optDouble("at", System.currentTimeMillis() / 1000.0) * 1000)));
        PendingIntent open = PendingIntent.getActivity(c, 3, new Intent(c, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        Notification n = new Notification.Builder(c, CH_MISSED)
                .setSmallIcon(R.drawable.ic_launcher)
                .setContentTitle(T.f("missed", title(e)))
                .setContentText(when)
                .setCategory(Notification.CATEGORY_MISSED_CALL)
                .setContentIntent(open)
                .setAutoCancel(true)
                .build();
        c.getSystemService(NotificationManager.class).notify(e.optString("call_id").hashCode(), n);
    }

    private static void notifyListener() {
        Listener l = listener;
        if (l != null) l.onChanged();
    }
    private Ringer() {}
}
