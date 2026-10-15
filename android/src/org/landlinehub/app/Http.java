package org.landlinehub.app;

import android.content.Context;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Scanner;

/** Tiny HTTP helper for the hub API (Bearer credential). */
final class Http {
    static String call(Context c, String method, String path, String body) throws Exception {
        HttpURLConnection h = (HttpURLConnection) new URL(Config.url(c) + path).openConnection();
        h.setRequestMethod(method);
        h.setConnectTimeout(8000);
        h.setReadTimeout(30000);
        String tok = Config.token(c);
        if (!tok.isEmpty()) h.setRequestProperty("Authorization", "Bearer " + tok);
        if (body != null) {
            h.setDoOutput(true);
            h.setRequestProperty("Content-Type", "application/json");
            try (OutputStream o = h.getOutputStream()) { o.write(body.getBytes("UTF-8")); }
        }
        int code = h.getResponseCode();
        InputStream in = code < 400 ? h.getInputStream() : h.getErrorStream();
        if (in == null) return "{}";
        try (Scanner s = new Scanner(in, "UTF-8").useDelimiter("\\A")) { return s.hasNext() ? s.next() : "{}"; }
    }
    static String post(Context c, String path, String body) throws Exception { return call(c, "POST", path, body); }
    static String get(Context c, String path) throws Exception { return call(c, "GET", path, null); }
    private Http() {}
}
