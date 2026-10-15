package org.landlinehub.app;

import java.io.BufferedInputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.net.Socket;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.Base64;

import javax.net.ssl.SSLSocketFactory;

/** Minimal WebSocket client (Android has none built in; no Gradle dependency wanted):
 *  handshake, send text/binary, read frames, answer pings, close.  ws:// and wss://. */
final class WsClient {
    interface Listener {
        void onText(String s);
        void onBinary(byte[] b);
        void onClosed(String why);
    }

    private final Socket sock;
    private final OutputStream out;
    private final DataInputStream in;
    private final SecureRandom rnd = new SecureRandom();
    private volatile boolean closed;

    WsClient(String httpUrl, String token) throws IOException {
        URI u = URI.create(httpUrl);
        boolean tls = "https".equals(u.getScheme());
        int port = u.getPort() > 0 ? u.getPort() : (tls ? 443 : 80);
        sock = tls ? SSLSocketFactory.getDefault().createSocket(u.getHost(), port) : new Socket(u.getHost(), port);
        sock.setTcpNoDelay(true);
        out = sock.getOutputStream();
        in = new DataInputStream(new BufferedInputStream(sock.getInputStream()));
        byte[] k = new byte[16];
        rnd.nextBytes(k);
        String path = u.getRawPath() + (u.getRawQuery() != null ? "?" + u.getRawQuery() : "");
        String req = "GET " + path + " HTTP/1.1\r\n"
                + "Host: " + u.getHost() + (u.getPort() > 0 ? ":" + u.getPort() : "") + "\r\n"
                + "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                + "Sec-WebSocket-Key: " + Base64.getEncoder().encodeToString(k) + "\r\n"
                + "Sec-WebSocket-Version: 13\r\n"
                + "Authorization: Bearer " + token + "\r\n\r\n";
        out.write(req.getBytes(StandardCharsets.US_ASCII));
        out.flush();
        String status = readLine();
        if (status == null || !status.contains(" 101")) throw new IOException("handshake: " + status);
        String l;
        while ((l = readLine()) != null && !l.isEmpty()) { /* skip headers */ }
    }

    private String readLine() throws IOException {
        StringBuilder sb = new StringBuilder();
        int c;
        while ((c = in.read()) != -1) {
            if (c == '\n') break;
            if (c != '\r') sb.append((char) c);
        }
        return c == -1 && sb.length() == 0 ? null : sb.toString();
    }

    synchronized void send(int opcode, byte[] data) throws IOException {
        if (closed) return;
        int n = data.length;
        byte[] hdr;
        if (n < 126) hdr = new byte[]{(byte) (0x80 | opcode), (byte) (0x80 | n)};
        else if (n < 65536) hdr = new byte[]{(byte) (0x80 | opcode), (byte) (0x80 | 126), (byte) (n >> 8), (byte) n};
        else throw new IOException("frame too large");
        byte[] mask = new byte[4];
        rnd.nextBytes(mask);
        byte[] masked = new byte[n];
        for (int i = 0; i < n; i++) masked[i] = (byte) (data[i] ^ mask[i & 3]);
        out.write(hdr); out.write(mask); out.write(masked); out.flush();
    }

    void sendText(String s) throws IOException { send(1, s.getBytes(StandardCharsets.UTF_8)); }
    void sendBinary(byte[] b) throws IOException { send(2, b); }

    /** Blocking read until the connection ends; call on its own thread. */
    void readLoop(Listener l) {
        String why = "closed";
        try {
            while (!closed) {
                int b0 = in.readUnsignedByte(), b1 = in.readUnsignedByte();
                int op = b0 & 0x0F;
                long len = b1 & 0x7F;
                if (len == 126) len = in.readUnsignedShort();
                else if (len == 127) len = in.readLong();
                byte[] mask = null;
                if ((b1 & 0x80) != 0) { mask = new byte[4]; in.readFully(mask); }
                byte[] p = new byte[(int) len];
                in.readFully(p);
                if (mask != null) for (int i = 0; i < p.length; i++) p[i] ^= mask[i & 3];
                if (op == 1) l.onText(new String(p, StandardCharsets.UTF_8));
                else if (op == 2) l.onBinary(p);
                else if (op == 9) send(10, p);
                else if (op == 8) { why = "remote closed"; break; }
            }
        } catch (IOException e) {
            if (!closed) why = e.getMessage();
        }
        close();
        l.onClosed(why);
    }

    void close() {
        if (closed) return;
        try { send(8, new byte[0]); } catch (Exception ignored) {}
        closed = true;
        try { sock.close(); } catch (Exception ignored) {}
    }
}
