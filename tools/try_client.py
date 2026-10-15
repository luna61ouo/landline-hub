"""Exercise the hub API like a phone would.

  python tools/try_client.py URL TOKEN dial NUMBER [SECONDS]
  python tools/try_client.py URL TOKEN wait [SECONDS]     # wait for a call, answer it, talk
  python tools/try_client.py URL - pair CODE
"""
import asyncio
import json
import math
import struct
import sys
import time

import aiohttp


def beep_frame(i):
    return b"".join(struct.pack("<h", int(4000 * math.sin(2 * math.pi * 600 * (i * 160 + n) / 8000))) for n in range(160))


async def talk(s, url, token, call_id, seconds):
    got, events = 0, []
    async with s.ws_connect(f"{url}/v1/calls/{call_id}/media", headers={"Authorization": f"Bearer {token}"}) as ws:
        async def send():
            t0 = time.monotonic()
            for i in range(int(seconds * 50)):
                await ws.send_bytes(beep_frame(i))
                await asyncio.sleep(max(0, t0 + (i + 1) * 0.02 - time.monotonic()))
            await ws.send_str(json.dumps({"type": "hangup"}))
        sender = asyncio.create_task(send())
        async for m in ws:
            if m.type == aiohttp.WSMsgType.BINARY:
                got += 1
            elif m.type == aiohttp.WSMsgType.TEXT:
                events.append(json.loads(m.data))
        sender.cancel()
    print(f"received {got} audio frames ({got * 0.02:.1f} s); events: {[e['type'] for e in events]}")
    if events:
        print("last:", events[-1])


async def main():
    url, token, cmd = sys.argv[1], sys.argv[2], sys.argv[3]
    h = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as s:
        if cmd == "pair":
            async with s.post(f"{url}/v1/pair", json={"code": sys.argv[4]}) as r:
                print(json.dumps(await r.json()))
            return
        if cmd == "dial":
            secs = float(sys.argv[5]) if len(sys.argv) > 5 else 5
            async with s.post(f"{url}/v1/outbound", json={"number": sys.argv[4]}, headers=h) as r:
                res = await r.json()
                print("outbound:", r.status, res)
            if res.get("ok"):
                await talk(s, url, token, res["call_id"], secs)
            return
        if cmd == "wait":
            secs = float(sys.argv[4]) if len(sys.argv) > 4 else 5
            async with s.get(f"{url}/v1/events", headers=h) as r:
                async for line in r.content:
                    line = line.decode().strip()
                    if not line.startswith("data:"):
                        continue
                    ev = json.loads(line[5:])
                    print("event:", ev)
                    if ev["type"] == "incoming":
                        async with s.post(f"{url}/v1/calls/{ev['call_id']}/answer", headers=h) as a:
                            print("answer:", a.status, await a.json())
                        await talk(s, url, token, ev["call_id"], secs)
                        return


asyncio.run(main())
