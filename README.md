# landline-hub

> Work in progress. Not usable yet.

Turn a landline into a small phone system that reaches your mobile phone.

- **Direct forwarding**: the landline rings, your phone rings, you answer from anywhere.
- **Auto-attendant**: the system picks up, asks for an extension, and rings the phone(s) behind it — office extensions that live on employees' mobiles.
- **Dial out from your phone** through the landline.

Works with an FXO gateway (Grandstream HT813 tested). Optional AI calling: landline-agent.

## Status

- [x] Pure domain: numbers, incoming calls, auto-attendant, line ownership (`python -m unittest discover -s tests -t .`)
- [ ] SIP + fake gateway
- [ ] HT813 adapter + Android app
- [ ] Auto-attendant on real hardware

## Safety

Key presses from a caller can only select an extension or "keep waiting / operator". There is no code path from an incoming call to an outside line (the classic PBX toll-fraud trick), and a test hammers the attendant with random key storms to prove it.

## License

MIT
