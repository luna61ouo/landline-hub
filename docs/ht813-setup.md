# Grandstream HT813 setup

Measured on firmware 1.0.17.3.  Parameter numbers (Pxxx) are what the web UI
submits; the page names are `config2` = BASIC, `config` = ADVANCED,
`config_a1` = FXS, `config_a2` = FXO.

## Wiring

- Line from the wall -> **grey FXO** port.  (Plugging it into the green FXS port
  puts the FXS ring voltage against the line; the status page then shows the FXO as
  "Not Connected".  Correct wiring shows "Idle".)
- Your existing telephone -> **green FXS** port; it keeps working as before.
- WAN (globe) -> your router.

## Admin password

There is no default password on the label.  Hold RESET for 7 s to restore factory
settings, log in as `admin` / `admin`, and set a long random password when asked.
Login attempts are limited (default 5, then locked for 15 min).

## Settings

| Where | Parameter | Value | Why |
|---|---|---|---|
| BASIC | Device Mode (P231) | Bridge | optional; keeps the LAN port as a plain switch |
| BASIC | Unconditional forward to VoIP: user (P3305) / host (P3306) / port (P3307) | `hub` / hub IP / `5090` | where incoming calls are forwarded |
| FXO | SIP server (P747) | `hub IP:5090` | without it the forward fails before it is sent |
| FXO | SIP registration (P731) | No | not needed on a LAN |
| FXO | Outgoing call without registration (P813) | Yes | |
| FXO | Allow incoming SIP messages from SIP proxy only (P743) | Yes | **only the hub can make it dial** |
| FXO | Stage method (P3304) | 1 | the number in the INVITE is dialled directly |
| FXO | Number of rings (P798) | **50** (direct) / **1** (pbx) | direct: never answers by itself; the hub flips it to 1 when you press Answer |
| FXO | PSTN disconnect tone detection (P712) | Yes, `f1=480@-32,f2=620@-32,c=250/250;` | detects the busy tone after the other side hangs up (Taiwan) |
| ADVANCED | Syslog server (P207) / level (P208) | `hub IP:5520` / DEBUG | ring and caller-id detection |
| BASIC | Time zone (P64) | yours | |

## What an analog line cannot tell you

- **When the callee picks up.**  The HT813 answers SIP as soon as the number is
  dialled.  The hub listens to the ringback rhythm to detect the pick-up
  (`line/answer_gate.py`, tuned for Taiwan: 1 s ring, 3 s pause).
- **When the HT813 is asked to pick up while ringing**, it refuses (486 Busy).  That
  is why the hub changes P798 instead.

## Caller ID shows "private"?

That is a carrier setting, not the HT813.  In Taiwan (Chunghwa Telecom), dialling
`020304051` cancels "hide my number"; `020304050` enables it.
