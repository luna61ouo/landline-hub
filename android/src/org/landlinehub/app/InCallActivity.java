package org.landlinehub.app;

import android.app.Activity;
import android.graphics.Color;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.AudioTrack;
import android.media.MediaRecorder;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.GridLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

/** A call on the landline: answer an incoming one (extra "answer" = call id) or
 *  dial out (extra "dial" = number).  Audio: WebSocket, 8 kHz PCM16, 20 ms frames. */
public class InCallActivity extends Activity implements WsClient.Listener {
    static final int RATE = 8000, FRAME = 320;
    private final Handler main = new Handler(Looper.getMainLooper());
    private TextView status;
    private Button speaker;
    private GridLayout keypad;
    private volatile WsClient ws;
    private volatile boolean talking, finished;
    private AudioRecord rec;
    private AudioTrack track;
    private AudioManager am;
    private long connectedAt;
    private PowerManager.WakeLock proximity;   // screen off while the phone is at the ear (earpiece mode)

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        setShowWhenLocked(true);
        setTurnScreenOn(true);
        am = getSystemService(AudioManager.class);
        PowerManager pm = getSystemService(PowerManager.class);
        if (pm.isWakeLockLevelSupported(PowerManager.PROXIMITY_SCREEN_OFF_WAKE_LOCK))
            proximity = pm.newWakeLock(PowerManager.PROXIMITY_SCREEN_OFF_WAKE_LOCK, "landline:incall");
        Ringer.stop(this);
        String answer = getIntent().getStringExtra("answer");
        String dial = getIntent().getStringExtra("dial");
        String title = getIntent().getStringExtra("title");

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setBackgroundColor(Color.parseColor(UI.BG));
        root.setPadding(48, 160, 48, 100);
        root.addView(UI.text(this, T.s("app"), 22, "#9FD3BC"));
        TextView number = UI.text(this, title != null ? title : Config.pretty(dial), 38, "#FFFFFF");
        number.setPadding(0, 30, 0, 12);
        status = UI.text(this, dial != null ? T.s("dialing") : T.s("connecting"), 18, "#B8C7C0");
        root.addView(number);
        root.addView(status);
        keypad = keypad();
        keypad.setVisibility(View.GONE);
        root.addView(keypad);
        root.addView(new LinearLayout(this), new LinearLayout.LayoutParams(1, 0, 1f));
        Button keys = UI.button(this, T.s("keypad"), "#3A5A4C", 140);
        keys.setOnClickListener(v -> keypad.setVisibility(keypad.getVisibility() == View.GONE ? View.VISIBLE : View.GONE));
        speaker = UI.button(this, T.s("speaker_off"), "#3A5A4C", 140);
        speaker.setOnClickListener(v -> toggleSpeaker());
        Button hang = UI.button(this, T.s("hangup"), "#B23B3B", 160);
        hang.setOnClickListener(v -> hangup());
        root.addView(keys); root.addView(speaker); root.addView(hang);
        setContentView(root);

        new Thread(() -> start(answer, dial), "incall").start();
    }

    private GridLayout keypad() {
        GridLayout g = new GridLayout(this);
        g.setColumnCount(3);
        String keys = "123456789*0#";
        for (int i = 0; i < keys.length(); i++) {
            String k = String.valueOf(keys.charAt(i));
            Button b = new Button(this);
            b.setText(k); b.setTextSize(22); b.setAllCaps(false);
            b.setOnClickListener(v -> sendDtmf(k));
            GridLayout.LayoutParams lp = new GridLayout.LayoutParams();
            lp.width = 220; lp.height = 150;
            b.setLayoutParams(lp);
            g.addView(b);
        }
        return g;
    }

    private void start(String answer, String dial) {
        try {
            String callId;
            if (answer != null) {
                JSONObject r = new JSONObject(Http.post(this, "/v1/calls/" + answer + "/answer", "{}"));
                if (!r.optBoolean("ok")) { end(T.f("failed", r.optString("error"))); return; }
                callId = answer;
            } else {
                JSONObject r = new JSONObject(Http.post(this, "/v1/outbound", new JSONObject().put("number", dial).toString()));
                if (!r.optBoolean("ok")) { end(T.f("failed", r.optString("error") + " " + r.optString("detail"))); return; }
                callId = r.getString("call_id");
            }
            ws = new WsClient(Config.url(this) + "/v1/calls/" + callId + "/media", Config.token(this));
            main.post(this::startAudio);
            ws.readLoop(this);
        } catch (Exception e) {
            end(T.f("failed", e.getMessage()));
        }
    }

    @Override public void onText(String s) {
        try {
            JSONObject o = new JSONObject(s);
            if ("ended".equals(o.optString("type"))) {
                String r = o.optString("reason");
                end(r.startsWith("not_connected") ? T.f("failed", r) : "remote".equals(o.optString("by")) ? T.s("remote_hung_up") : T.s("ended"));
            }
        } catch (Exception ignored) {}
    }

    @Override public void onBinary(byte[] b) {
        AudioTrack t = track;
        if (talking && t != null) t.write(b, 0, b.length);
    }

    @Override public void onClosed(String why) { end(talking ? T.s("ended") : T.f("failed", why)); }

    private void startAudio() {
        if (finished) return;
        am.setMode(AudioManager.MODE_IN_COMMUNICATION);
        int recMin = AudioRecord.getMinBufferSize(RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        try {
            rec = new AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION, RATE, AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT, Math.max(recMin, FRAME * 8));
        } catch (SecurityException e) {
            end(T.s("w_mic").trim());
            return;
        }
        int playMin = AudioTrack.getMinBufferSize(RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT);
        track = new AudioTrack.Builder()
                .setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                .setAudioFormat(new AudioFormat.Builder().setSampleRate(RATE).setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
                .setBufferSizeInBytes(Math.max(playMin, FRAME * 10))
                .setTransferMode(AudioTrack.MODE_STREAM).build();
        track.play();
        rec.startRecording();
        talking = true;
        updateProximity();
        connectedAt = SystemClock.elapsedRealtime();
        main.post(this::tick);
        new Thread(() -> {
            byte[] buf = new byte[FRAME];
            while (talking) {
                int n = rec.read(buf, 0, FRAME);
                WsClient w = ws;
                if (n == FRAME && w != null) {
                    try { w.sendBinary(buf.clone()); } catch (Exception e) { break; }
                }
            }
        }, "mic").start();
    }

    private void sendDtmf(String k) {
        new Thread(() -> {
            WsClient w = ws;
            try { if (w != null) w.sendText(new JSONObject().put("type", "dtmf").put("digits", k).toString()); }
            catch (Exception ignored) {}
        }).start();
    }

    private void tick() {
        if (!talking) return;
        long s = (SystemClock.elapsedRealtime() - connectedAt) / 1000;
        status.setText(T.f("in_call", s / 60, s % 60));
        main.postDelayed(this::tick, 1000);
    }

    private void toggleSpeaker() {
        boolean on = !am.isSpeakerphoneOn();
        am.setSpeakerphoneOn(on);
        speaker.setText(on ? T.s("speaker_on") : T.s("speaker_off"));
        updateProximity();
    }

    /** Earpiece: the proximity sensor turns the screen off at the ear, so a cheek cannot press
     *  anything.  Speaker on: the phone is not at the ear, keep the screen usable. */
    private void updateProximity() {
        if (proximity == null) return;
        boolean want = talking && !finished && !am.isSpeakerphoneOn();
        if (want && !proximity.isHeld()) proximity.acquire(4 * 60 * 60 * 1000L);
        else if (!want && proximity.isHeld()) proximity.release(PowerManager.RELEASE_FLAG_WAIT_FOR_NO_PROXIMITY);
    }

    private void hangup() {
        new Thread(() -> {
            WsClient w = ws;
            if (w != null) { try { w.sendText("{\"type\":\"hangup\"}"); } catch (Exception ignored) {} }
            end(T.s("ended"));
        }).start();
    }

    private void end(String msg) {
        if (finished) return;
        finished = true;
        talking = false;
        main.post(this::updateProximity);
        try { if (rec != null) { rec.stop(); rec.release(); } } catch (Exception ignored) {}
        try { if (track != null) { track.stop(); track.release(); } } catch (Exception ignored) {}
        am.setSpeakerphoneOn(false);
        am.setMode(AudioManager.MODE_NORMAL);
        WsClient w = ws;
        if (w != null) w.close();
        main.post(() -> { status.setText(msg); main.postDelayed(this::finish, 1800); });
        MainActivity.refreshLater();
    }

    @Override protected void onDestroy() { if (!finished) hangup(); super.onDestroy(); }
}
