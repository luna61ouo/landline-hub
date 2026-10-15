"""Client API (phones and programs use the same one).

  POST /v1/pair                      {code} -> {client_id, token}       (no auth: one-time code)
  GET  /v1/events                    SSE: incoming / answered / ended / ...
  POST /v1/outbound                  {number, answer_detection?} -> {call_id}
  POST /v1/calls/{id}/answer
  POST /v1/calls/{id}/hangup
  WS   /v1/calls/{id}/media          binary: 20 ms 8 kHz PCM16 both ways
                                     text in:  {"type":"hangup"} | {"type":"clear"} | {"type":"dtmf","digits":"1"}
                                     text out: the same events as /v1/events for this call
  GET  /v1/status
"""
from __future__ import annotations

import asyncio
import json

from aiohttp import WSMsgType, web

from .clients import ClientStore
from .service import Hub


def build_app(hub: Hub, store: ClientStore) -> web.Application:
    app = web.Application()

    def auth(request):
        h = request.headers.get("Authorization", "")
        token = h[7:] if h.startswith("Bearer ") else request.query.get("token", "")
        return store.authenticate(token)

    def need(request):
        c = auth(request)
        if c is None:
            raise web.HTTPUnauthorized(text=json.dumps({"error": "unauthorized"}), content_type="application/json")
        return c

    async def pair(request):
        body = await request.json()
        r = store.pair(str(body.get("code", "")))
        if r is None:
            return web.json_response({"error": "invalid_or_expired_code"}, status=403)
        client, token = r
        return web.json_response({"client_id": client.client_id, "role": client.role.value, "token": token})

    async def events(request):
        c = need(request)
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await resp.prepare(request)
        key, q = hub.bus.subscribe(c)
        try:
            await resp.write(b": hello\n\n")
            for ev in hub.ringing_for(c):
                await resp.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode())
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    await resp.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode())
                except asyncio.TimeoutError:
                    await resp.write(b": ping\n\n")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            hub.bus.unsubscribe(key)
        return resp

    async def outbound(request):
        c = need(request)
        body = await request.json()
        r = await hub.outbound(c, str(body.get("number", "")), bool(body.get("answer_detection", False)))
        status = 200 if r["ok"] else {"busy": 409, "not_permitted": 403}.get(r["error"], 400)
        return web.json_response(r, status=status)

    async def answer(request):
        c = need(request)
        r = await hub.answer(c, request.match_info["cid"])
        return web.json_response(r, status=200 if r["ok"] else 409)

    async def hangup(request):
        c = need(request)
        r = await hub.hangup(c, request.match_info["cid"])
        return web.json_response(r, status=200 if r["ok"] else 404)

    async def media(request):
        c = need(request)
        s = hub.sessions.get(request.match_info["cid"])
        if not s or s.owner != c.client_id:
            raise web.HTTPNotFound()
        ws = web.WebSocketResponse(heartbeat=15, max_msg_size=1 << 20)
        await ws.prepare(request)
        loop = asyncio.get_running_loop()
        out: asyncio.Queue = asyncio.Queue(maxsize=250)

        def sink(pcm: bytes) -> None:
            try:
                out.put_nowait(pcm)
            except asyncio.QueueFull:
                pass

        s.sink = sink
        key, evq = hub.bus.subscribe(c)

        async def down():
            while True:
                pcm = await out.get()
                await ws.send_bytes(pcm)

        async def evs():
            while True:
                ev = await evq.get()
                if ev.get("call_id") == s.call_id:
                    await ws.send_str(json.dumps(ev, ensure_ascii=False))
                    if ev.get("type") == "ended":
                        await ws.close()
                        return

        async def up():
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    hub.play(s, msg.data)
                elif msg.type == WSMsgType.TEXT:
                    try:
                        cmd = json.loads(msg.data)
                    except ValueError:
                        continue
                    t = cmd.get("type")
                    if t == "hangup":
                        await s.line.hangup()
                    elif t == "clear":
                        s.line.clear()
                    elif t == "dtmf":
                        hub.press(s, str(cmd.get("digits", "")))

        tasks = [loop.create_task(x) for x in (down(), evs(), up(), s.line.ended.wait())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            hub.bus.unsubscribe(key)
            if s.sink is sink:
                s.sink = None
            if not ws.closed:
                await ws.send_str(json.dumps({"type": "ended", "call_id": s.call_id,
                                              "reason": hub.end_reason_of(s), "by": s.line.ended_by}))
                await ws.close()
        return ws

    async def status(request):
        need(request)
        ls = hub.line_state
        return web.json_response({"mode": hub.cfg.mode, "line": "free" if ls.__class__.__name__ == "Free" else "busy",
                                  "calls": [{"call_id": s.call_id, "direction": s.direction, "state": s.state}
                                            for s in hub.sessions.values()]})

    app.router.add_post("/v1/pair", pair)
    app.router.add_get("/v1/events", events)
    app.router.add_post("/v1/outbound", outbound)
    app.router.add_post("/v1/calls/{cid}/answer", answer)
    app.router.add_post("/v1/calls/{cid}/hangup", hangup)
    app.router.add_get("/v1/calls/{cid}/media", media)
    app.router.add_get("/v1/status", status)
    return app
