"""Change HT813 settings without a browser: log in, read the whole settings
form, change only what we need, post the whole form back the way the
browser's "Apply" does.

Pitfalls learned on the device (firmware 1.0.17.x):
  - Log in through /cgi-bin/login (the front page form lacks `username`), and the
    password is base64'd by the page's JS before it is sent.
  - Login attempts are limited (default 5, then locked 15 min): never retry blindly.
  - session_token in a form is single-use and every page read invalidates the
    previous one, so all access is serialized and a prepared form is sent at most once.
  - The update must contain exactly the fields the browser sends, in the browser's
    order (forms.json was recorded from a real browser).  Sorted or partial posts
    only answer "please click Apply" and change nothing.
  - Some fields are written by JavaScript (e.g. P2499) and must be scraped from <script>.
  - The web UI is slow: login ~4 s, page read ~3 s, apply ~2.6 s.
"""
from __future__ import annotations

import base64
import http.cookiejar
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

FORMS = json.loads((Path(__file__).parent / "forms.json").read_text())


class _Form(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields, self.radios, self._select, self._sel_first = {}, {}, None, None

    def handle_starttag(self, tag, a):
        a = dict(a)
        n = a.get("name")
        if tag == "input" and n:
            t = (a.get("type") or "text").lower()
            if t in ("submit", "button", "reset", "image", "file"):
                return
            if t == "radio":
                self.radios.setdefault(n, None)
                if "checked" in a:
                    self.radios[n] = a.get("value", "")
            elif t == "checkbox":
                if "checked" in a:
                    self.fields[n] = a.get("value", "on")
            else:
                self.fields[n] = a.get("value", "")
        elif tag == "select" and n:
            self._select, self._sel_first = n, None
        elif tag == "option" and self._select:
            v = a.get("value", "")
            if self._sel_first is None:
                self._sel_first = v
            if "selected" in a:
                self.fields[self._select] = v

    def handle_endtag(self, tag):
        if tag == "select" and self._select:
            self.fields.setdefault(self._select, self._sel_first or "")
            self._select = None

    def values(self):
        out = dict(self.fields)
        out.update({k: v for k, v in self.radios.items() if v is not None})
        return out


class HT813:
    def __init__(self, host: str, password: str):
        self.base = f"http://{host}"
        self._pw = password
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.logged_at = 0.0
        self.lock = threading.RLock()

    def _get(self, path):
        return self.op.open(self.base + path, timeout=5).read().decode("utf-8", "replace")

    def _post(self, path, data, referer="/cgi-bin/login"):
        req = urllib.request.Request(self.base + path, urllib.parse.urlencode(data).encode(),
                                     headers={"Referer": self.base + referer, "Origin": self.base})
        return self.op.open(req, timeout=8).read().decode("utf-8", "replace")

    def login(self):
        page = self._get("/cgi-bin/login")
        hidden = {n: v for n, v in re.findall(r'name="?(csrf_token|gnkey)"?[^>]*?value="?([^"\s>]*)', page)}
        if set(hidden) != {"csrf_token", "gnkey"}:
            raise RuntimeError("login page format changed; not sending the password (attempts are limited)")
        body = self._post("/cgi-bin/dologin", {"username": "admin", "P2": base64.b64encode(self._pw.encode()).decode(),
                                               "Login": "Login", **hidden})
        if "STATUS" not in body:
            left = re.search(r"Remaining Attempts:?\s*(\d+)", body)
            raise RuntimeError("HT813 login failed" + (f" ({left.group(1)} attempts left)" if left else ""))
        self.logged_at = time.time()

    def _ensure(self):
        if time.time() - self.logged_at > 300:
            self.login()

    def read(self, page):
        self._ensure()
        html = self._get("/cgi-bin/" + page)
        if "session_token" not in html:
            self.login()
            html = self._get("/cgi-bin/" + page)
        f = _Form()
        f.feed(html)
        vals = f.values()
        js = _Form()
        for tag in re.findall(r"<input[^>]*>", html.replace('\\"', '"')):
            js.feed(tag)
        for k, v in js.values().items():
            vals.setdefault(k, v)
        return vals

    def prepare(self, page, changes):
        with self.lock:
            return self._prepare(page, changes)

    def _prepare(self, page, changes):
        vals = self.read(page)
        missing = [k for k in changes if k not in vals]
        if missing:
            raise KeyError(f"{page} has no field {missing}")
        if page not in FORMS:
            raise RuntimeError(f"no recorded field list for {page}; not sending")
        names = FORMS[page]
        lost = [n for n in names if n not in vals and n not in ("session_token", "apply")]
        if lost:
            raise RuntimeError(f"{page}: could not read fields {lost[:5]}; not sending (would wipe settings)")
        vals.update({k: str(v) for k, v in changes.items()})
        vals["apply"] = "Apply"
        return page, [(n, vals[n]) for n in names if n in vals]

    def send(self, prepared):
        with self.lock:
            page, body = prepared
            r = self._post("/cgi-bin/update", body, referer="/cgi-bin/" + page)
            if "applied" not in r and "saved" not in r:
                raise RuntimeError("HT813 did not confirm the change")
            return True

    def set(self, page, changes):
        with self.lock:
            return self.send(self._prepare(page, changes))

    # -- what the hub uses --
    def prepare_answer(self):
        """A ready-to-send form that makes the FXO pick up after the next ring."""
        return self.prepare("config_a2", {"P798": 1})

    def set_rings(self, n: int):
        return self.set("config_a2", {"P798": n})

    def rings(self) -> int:
        with self.lock:
            return int(self.read("config_a2")["P798"])
