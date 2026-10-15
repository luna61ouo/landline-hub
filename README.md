# landline-hub

**Turn the landline at your home or office into a small phone system that reaches your mobile phone.**
把家裡或公司的市話，變成會響到手機上的小型電話總機。

[![Intro video (30 s)](docs/media/intro.jpg)](docs/media/intro-30s.mp4)

- **Forward calls to your phone** – the landline rings, your phone rings, answer from anywhere.
- **Auto-attendant** – the hub picks up, asks for an extension, and rings the phone(s) behind it. Office extensions that live on employees' mobiles, inside or outside the office.
- **Dial out through the landline from your phone** – the other side sees your landline number.
- **Let programs use the line** – an AI that makes calls for you ([landline-agent](https://github.com/luna61ouo/landline-agent)) is just another client of the hub. You don't need it to use the hub.

Tested with a Grandstream HT813 gateway and Taiwanese phone numbers.

## How it fits together

```
 landline ── FXO gateway ──SIP── landline-hub ──HTTPS / WebSocket── Android app (your phone)
 (wall jack)   (HT813)              │                               landline-agent (AI calls, optional)
                                    └─ call history, pairing,       your own program
                                       numbers & permissions
```

The gateway turns the analog line into SIP. The hub is the only thing that talks SIP. Phones and programs pair with the hub and use one small HTTP API: they get events (a call is ringing, answered, ended), ask to dial out, and exchange audio over a WebSocket (8 kHz, 16-bit PCM, 20 ms frames).

## What you need

- A landline and an **FXO gateway** (Grandstream HT813 tested; a gateway that forwards incoming calls as plain SIP should work with `kind = "sip"`).
- A Linux machine on the same network, Python 3.11+.
- Android phones for the app (Android 10+). Building it needs the Android SDK with platform 35 and build-tools 35.0.0. To reach the hub from outside, put it behind a VPN or a reverse proxy with TLS – the hub itself listens on localhost by default.

## Install

```bash
git clone https://github.com/luna61ouo/landline-hub && cd landline-hub
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
cp config.example.toml config.toml        # then edit [gateway]
```

Gateway setup (wiring, the settings that matter, caller ID): [docs/ht813-setup.md](docs/ht813-setup.md).

### Try it without hardware

`tools/fakegw` is a fake gateway in Docker (baresip) that answers and plays a tone.

```bash
tools/fakegw/run.sh start                  # set [gateway].host in config.toml to your LAN IP
landline-hub serve -c config.toml
landline-hub pair -c config.toml --name my-phone          # prints a one-time code (10 minutes)
python tools/try_client.py http://127.0.0.1:8910 - pair <code>
python tools/try_client.py http://127.0.0.1:8910 <token> dial 0212345678 5
```

### Run it as a service

Any process manager works. With systemd (user service):

```ini
[Service]
WorkingDirectory=/path/to/landline-hub
ExecStart=/path/to/landline-hub/.venv/bin/landline-hub serve -c config.toml
Restart=on-failure
```

## Configure

`config.example.toml` is commented; the main choices:

| Section | What it decides |
|---|---|
| `[gateway]` | `kind = "ht813"` (ring detection from the HT813's syslog, answers only when someone accepts) or `"sip"` (the gateway sends incoming calls as SIP right away). Only the gateway's address may send SIP to the hub. |
| `[forward] mode` | `direct`: every paired phone rings, first to answer talks. `pbx`: the hub answers and routes by extension. |
| `[pbx]` | Extensions and the phones behind each, the operator extension, timeouts, and the voice prompts (`greeting.wav`, `invalid.wav`, …, 8 kHz mono). Extension numbers must not be prefixes of one another, otherwise "1" and "12" cannot be told apart while dialling. |
| `[numbers] policy` | Number rules. Only `tw` (Taiwan) exists today. |

## Phones and programs (clients)

Every client pairs once and gets its own credential (the hub stores only a hash).

```bash
landline-hub pair    -c config.toml --name alex-phone              # a person's phone (role: handset)
landline-hub pair    -c config.toml --name my-agent --role agent   # a program
landline-hub clients -c config.toml
landline-hub revoke  -c config.toml alex-phone
landline-hub grant   -c config.toml NAME --kind emergency          # see below
```

What each role may dial:

| | regular numbers | emergency (110, 119, …) | premium-rate |
|---|---|---|---|
| **handset** (a person) | ✅ | ✅ – it is a telephone | ❌ |
| **agent** (a program) | ✅ | ❌ unless granted | ❌ |

The line belongs to one client at a time: a second call while the line is busy gets `409`.

## API

| | |
|---|---|
| `POST /v1/pair` `{code}` | → `{client_id, token}`; no auth, the one-time code is the credential |
| `GET /v1/events` | Server-sent events: `incoming`, `answered`, `ended`, … A client that reconnects gets the calls still ringing right away. |
| `POST /v1/outbound` `{number, answer_detection?}` | → `{call_id}`; `403` not permitted, `409` line busy |
| `POST /v1/calls/{id}/answer`, `/hangup` | |
| `WS /v1/calls/{id}/media` | Binary frames: 20 ms 8 kHz PCM16 both ways. Text in: `{"type":"hangup"}`, `{"type":"clear"}`, `{"type":"dtmf","digits":"1"}`. Text out: this call's events. |
| `GET /v1/status`, `GET /v1/history` | Line state; last 50 calls |

All except pairing need `Authorization: Bearer <token>`.

**Pick-up detection.** An analog line never says "the other side answered" – the gateway connects as soon as it has dialled. With `answer_detection: true` the hub listens to the ringback rhythm and holds the audio back until a person (or a machine) actually picks up, then sends `callee_answered {how, talking}`. The constants are tuned to Taiwan's ringback (1 s ring, 3 s pause).

**Live audio for people.** For a person's phone the hub never queues audio: anything before the call connects is dropped and the backlog is capped at 200 ms, so a slow network costs a word, not a 10-second delay.

## The Android app

In `android/`. No Gradle – `build.sh` uses the SDK's command-line tools.

```bash
cd android
ANDROID_HOME=/path/to/android-sdk KEYSTORE=/path/to/your.jks KS_PASS_FILE=/path/to/pass bash build.sh
adb install -r build/landline-hub.apk
```

- Pair with a one-time code, then it stays connected in the background and rings like a phone call.
- Dial pad, recent calls, in-call keypad (DTMF), speaker / earpiece with the proximity sensor.
- English and Traditional Chinese.
- Package `org.landlinehub.app`. **Keep your signing key safe** – Android only installs updates signed with the same key.

The first install from a computer may need a confirmation on the phone (some vendors block silent adb installs).

## Safety

- **No toll fraud.** A caller's key presses can only pick an extension or "keep waiting / operator". There is no code path from an incoming call to an outside line, and a test drives the attendant with 500 rounds of random key storms to show it.
- **Programs can't dial emergency or premium numbers** unless you grant it by name. Numbers are normalised first, so `110#`, `(110)` and `+886 110` are all recognised as 110.
- **A paired phone is a telephone.** It can call anything a normal phone can, emergency numbers included – on purpose. If an AI on the same machine can operate one of your phones (for example over adb), that path does not go through any approval; block it on the AI's side.
- The hub listens on localhost by default. Don't expose it to the internet without TLS and a VPN or proxy in front.

## Known limitations

- **Taiwan only, for now**: number rules (`[numbers] policy = "tw"`) and the ringback timing in pick-up detection. Other countries need their own rules and constants – contributions welcome.
- One line per hub.
- Tested on one gateway model (HT813).

## Development

```bash
python3 -m unittest discover -s tests -t .     # standard library only
```

## Authors

Luke Liu & Luna Liu

## License

MIT — Copyright (c) 2026 Luke Liu. See [LICENSE](LICENSE).
