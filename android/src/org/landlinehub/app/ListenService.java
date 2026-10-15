package org.landlinehub.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

/** Foreground service: one SSE connection to the hub, events go to Ringer.
 *  Reconnects with backoff; on reconnect the hub replays calls that are still ringing. */
public class ListenService extends Service {
    static final String CH_STATUS = "status_v1";
    static final int NOTIF_STATUS = 1;
    static volatile String status = T.s("st_connecting");
    private volatile boolean running;
    private Thread worker;

    static void start(Context c) {
        Intent i = new Intent(c, ListenService.class);
        if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i); else c.startService(i);
    }

    static void restart(Context c) {
        c.stopService(new Intent(c, ListenService.class));
        start(c);
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        NotificationChannel ch = new NotificationChannel(CH_STATUS, "Connection", NotificationManager.IMPORTANCE_MIN);
        ch.setShowBadge(false);
        nm.createNotificationChannel(ch);
        Ringer.channels(this);
        Notification n = statusNotif(T.s("st_connecting"));
        if (Build.VERSION.SDK_INT >= 34) startForeground(NOTIF_STATUS, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(NOTIF_STATUS, n);
        if (worker == null || !worker.isAlive()) {
            running = true;
            worker = new Thread(this::loop, "hub-sse");
            worker.start();
        }
        return START_STICKY;
    }

    private Notification statusNotif(String text) {
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CH_STATUS)
                .setSmallIcon(R.drawable.ic_launcher)
                .setContentTitle(T.s("app"))
                .setContentText(text)
                .setContentIntent(open)
                .setOngoing(true)
                .build();
    }

    private void setStatus(String s) {
        status = s;
        getSystemService(NotificationManager.class).notify(NOTIF_STATUS, statusNotif(s));
        MainActivity.refreshLater();
    }

    private void loop() {
        int backoff = 2;
        while (running) {
            HttpURLConnection conn = null;
            try {
                if (!Config.paired(this)) { setStatus(T.s("st_unpaired")); Thread.sleep(10_000); continue; }
                conn = (HttpURLConnection) new URL(Config.url(this) + "/v1/events").openConnection();
                conn.setRequestProperty("Authorization", "Bearer " + Config.token(this));
                conn.setRequestProperty("Accept", "text/event-stream");
                conn.setConnectTimeout(10_000);
                conn.setReadTimeout(60_000);          // the hub pings every 15 s
                int code = conn.getResponseCode();
                if (code != 200) throw new Exception("HTTP " + code);
                setStatus(T.s("st_idle"));
                backoff = 2;
                Ringer.resync(this);
                BufferedReader r = new BufferedReader(new InputStreamReader(conn.getInputStream(), "UTF-8"));
                String line;
                StringBuilder data = new StringBuilder();
                while (running && (line = r.readLine()) != null) {
                    if (line.startsWith("data:")) data.append(line.substring(5).trim());
                    else if (line.isEmpty() && data.length() > 0) {
                        Ringer.onEvent(this, new JSONObject(data.toString()));
                        data.setLength(0);
                    }
                }
                throw new Exception("connection closed");
            } catch (Exception e) {
                setStatus(T.f("st_retry", backoff, e.getMessage()));
                try { Thread.sleep(backoff * 1000L); } catch (InterruptedException ignored) {}
                backoff = Math.min(backoff * 2, 30);
            } finally {
                if (conn != null) conn.disconnect();
            }
        }
    }

    @Override public void onDestroy() { running = false; if (worker != null) worker.interrupt(); super.onDestroy(); }
    @Override public IBinder onBind(Intent intent) { return null; }
}
