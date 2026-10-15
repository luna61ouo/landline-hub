# landline-hub

> Work in progress. Not usable yet.

Turn a landline into a small phone system that reaches your mobile phone.

- **Direct forwarding**: the landline rings, your phone rings, you answer from anywhere.
- **Auto-attendant**: the system picks up, asks for an extension, and rings the phone(s) behind it — office extensions that live on employees' mobiles.
- **Dial out from your phone** through the landline.

Works with an FXO gateway (Grandstream HT813 tested). Optional AI calling: landline-agent.

## Quick start (no hardware needed)

```bash
pip install -e .
cp config.example.toml config.toml            # point [gateway].host at your LAN IP for the fake gateway
tools/fakegw/run.sh start                      # Docker: a fake FXO gateway that answers and plays a tone
landline-hub pair -c config.toml --name my-phone
landline-hub serve -c config.toml
python tools/try_client.py http://127.0.0.1:8910 - pair <code>
python tools/try_client.py http://127.0.0.1:8910 <token> dial 0212345678 5
```

The Android app is in `android/` (`ANDROID_HOME=... ./build.sh`, no Gradle).
Real hardware: see [docs/ht813-setup.md](docs/ht813-setup.md).

## Status

- [x] Domain: numbers, per-client permissions, incoming calls, auto-attendant, line ownership (unit tests)
- [x] SIP client/server, answer detection, DTMF, client API, direct forwarding, auto-attendant (verified with the fake gateway)
- [x] Grandstream HT813 adapter (verified in simulation)
- [x] Android app: pairing, incoming calls, answer, dial out, keypad (builds; not yet run on a phone)
- [ ] Run on a real HT813 and phone

## Safety

Key presses from a caller can only select an extension or "keep waiting / operator". There is no code path from an incoming call to an outside line (the classic PBX toll-fraud trick), and a test hammers the attendant with random key storms to prove it.

## License

MIT
