package org.landlinehub.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Start the background connection after boot / app update; also the "Silence" notification action. */
public class BootReceiver extends BroadcastReceiver {
    static final String ACTION_MUTE = "org.landlinehub.app.MUTE";

    @Override public void onReceive(Context c, Intent i) {
        if (ACTION_MUTE.equals(i.getAction())) { Ringer.mute(c); return; }
        if (Config.paired(c)) ListenService.start(c);
    }
}
