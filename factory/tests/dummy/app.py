"""A deliberately tiny service for exercising the gates. MODE picks a defect:
good, racy (lost updates), dupe (concurrent retries applied twice), nohealth, netcall, wideui."""
import json
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODE = os.environ.get("MODE", "good")
STATE = {"value": 0, "seen": {}}
LOCK = threading.Lock()

if MODE == "netcall":
    urllib.request.urlopen("https://pypi.org", timeout=5)

WIDE = '<div style="width:2000px">wide</div><input id="x">' if MODE == "wideui" else ""
PAGE = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Tally</title>
<style>:root{{--fg:#1d1d1b;--bg:#ffffff;--gap:16px}}body{{color:var(--fg);background:var(--bg);
font:16px system-ui;margin:0;padding:var(--gap)}}button,input{{min-height:44px;min-width:44px}}</style></head>
<body><main><h1>Tally</h1><p id="v" data-state="loading">Loading…</p>
<template><p data-state="empty">Nothing yet</p><p data-state="error">Could not load</p></template>
<label for="n">Amount</label><input id="n" type="number" value="1">
<button type="button" id="add">Add</button>{WIDE}</main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def reply(self, status, payload=None, content_type="application/json"):
        body = b"" if payload is None else (payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return None

    def do_GET(self):
        if self.path == "/health":
            return self.reply(503 if MODE == "nohealth" else 200, {"status": "ok"})
        if self.path == "/value":
            return self.reply(200, {"value": STATE["value"]})
        if self.path == "/":
            return self.reply(200, PAGE.encode(), "text/html; charset=utf-8")
        return self.reply(404, {"error": "not found"})

    def do_POST(self):
        data = self.body()
        if data is None:
            return self.reply(400, {"error": "bad json"})
        if self.path == "/reset":
            with LOCK:
                STATE.update(value=int(data.get("value", 0)), seen={})
            return self.reply(204)
        if self.path == "/add":
            n, key = data.get("n", 1), data.get("key")
            if not isinstance(n, int) or isinstance(n, bool) or n < 1:
                return self.reply(400, {"error": "n must be a positive integer"})
            if MODE == "racy":
                current = STATE["value"]
                time.sleep(0.002)
                STATE["value"] = current + n
                return self.reply(200, {"value": STATE["value"]})
            if MODE == "dupe" and key is not None:  # retry check outside the lock
                if key in STATE["seen"]:
                    return self.reply(200, STATE["seen"][key])
                time.sleep(0.005)
                with LOCK:
                    STATE["value"] = STATE["value"] + n
                    STATE["seen"][key] = {"value": STATE["value"]}
                    return self.reply(200, STATE["seen"][key])
            with LOCK:
                if key is not None and key in STATE["seen"]:
                    return self.reply(200, STATE["seen"][key])
                STATE["value"] = STATE["value"] + n
                result = {"value": STATE["value"]}
                if key is not None:
                    STATE["seen"][key] = result
            return self.reply(200, result)
        return self.reply(404, {"error": "not found"})


class Server(ThreadingHTTPServer):
    request_queue_size = 256
    daemon_threads = True


if __name__ == "__main__":
    Server(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
