"""landline-hub command line.

  python -m landline_hub serve  -c config.toml
  python -m landline_hub pair   -c config.toml --name alex-phone [--role handset|agent]
  python -m landline_hub clients -c config.toml
  python -m landline_hub revoke -c config.toml NAME
  python -m landline_hub grant  -c config.toml NAME --kind emergency
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from . import config as config_mod
from .clients import ClientStore
from .domain.number import Kind
from .domain.permissions import ClientRole


async def _serve(cfg) -> None:
    from aiohttp import web
    from .api import build_app
    from .service import Hub
    hub = Hub(cfg)
    await hub.start()
    runner = web.AppRunner(build_app(hub, ClientStore(cfg.data_dir)))
    await runner.setup()
    await web.TCPSite(runner, cfg.host, cfg.port).start()
    print(f"landline-hub listening on http://{cfg.host}:{cfg.port}  mode={cfg.mode}  gateway={cfg.gateway.kind}", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await hub.stop()
        await runner.cleanup()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="landline-hub")
    ap.add_argument("command", choices=["serve", "pair", "clients", "revoke", "grant"])
    ap.add_argument("name", nargs="?")
    ap.add_argument("-c", "--config", default="config.toml")
    ap.add_argument("--name", dest="pair_name")
    ap.add_argument("--role", default="handset", choices=[r.value for r in ClientRole])
    ap.add_argument("--kind", choices=[k.value for k in Kind])
    a = ap.parse_args(argv)
    cfg = config_mod.load(a.config)
    store = ClientStore(cfg.data_dir)
    if a.command == "serve":
        asyncio.run(_serve(cfg))
    elif a.command == "pair":
        if not a.pair_name:
            ap.error("pair needs --name")
        code = store.new_pairing(a.pair_name, ClientRole(a.role))
        print(f"Pairing code for {a.pair_name} ({a.role}), valid 10 minutes:\n\n    {code}\n")
    elif a.command == "clients":
        for c in store.list():
            print(f"{c['id']:20} {c['role']:8} extra={','.join(c['extra_kinds']) or '-'}")
    elif a.command == "revoke":
        print("revoked" if store.revoke(a.name) else "no such client")
    elif a.command == "grant":
        if not (a.name and a.kind):
            ap.error("grant needs NAME and --kind")
        store.grant(a.name, Kind(a.kind))
        print(f"{a.name} may now dial {a.kind} numbers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
