#!/usr/bin/env python3
"""cdp-shot.py — screenshot/evaluate the viewer at a *real* mobile viewport.

Headless Chromium clamps --window-size to a 500px minimum width, so phone widths
cannot be tested from the command line; this drives CDP instead and applies
Emulation.setDeviceMetricsOverride (+ touch emulation, so `pointer: coarse`
matches like a phone).

usage: cdp-shot.py --url URL --out FILE [--w 390] [--h 844] [--dpr 3]
                   [--eval 'expr'] [--settle 800] [--timeout 60]
"""
import argparse, base64, json, os, socket, subprocess, sys, tempfile, time, urllib.request

CH = os.environ.get(
    "CH", "/nix/store/66fwidpz045aq5s9szdkg7znc4skgdwx-chromium-143.0.7499.169/bin/chromium"
)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http_json(url, method="GET"):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


class CDP:
    def __init__(self, ws_url):
        from websockets.sync.client import connect
        self.ws = connect(ws_url, max_size=64 * 1024 * 1024)
        self.n = 0
        self.pending = {}

    def send(self, method, **params):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            # buffered events are irrelevant here

    def eval(self, expr):
        r = self.send("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out")
    ap.add_argument("--w", type=int, default=390)
    ap.add_argument("--h", type=int, default=844)
    ap.add_argument("--dpr", type=float, default=3)
    ap.add_argument("--eval")
    ap.add_argument("--settle", type=float, default=1.0)
    ap.add_argument("--timeout", type=float, default=60)
    ap.add_argument("--throttle", type=int, default=0, help="kbit/s download cap, 0 = none")
    ap.add_argument("--wait-for", default="loaded", help="status text to wait for; empty = fixed settle only")
    a = ap.parse_args()

    port = free_port()
    prof = tempfile.mkdtemp(prefix="cdpshot-")
    proc = subprocess.Popen(
        [CH, "--headless", "--no-sandbox", "--disable-gpu",
         "--enable-unsafe-swiftshader", "--disable-dev-shm-usage", "--hide-scrollbars",
         "--remote-debugging-port=%d" % port, "--user-data-dir=" + prof,
         "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        ws_base = None
        for _ in range(100):
            try:
                ws_base = http_json("http://127.0.0.1:%d/json/version" % port)["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.1)
        if not ws_base:
            print("chromium did not expose a devtools endpoint", file=sys.stderr)
            return 1
        tgt = http_json("http://127.0.0.1:%d/json/new?about:blank" % port, method="PUT")
        cdp = CDP(tgt["webSocketDebuggerUrl"])
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        cdp.send("Emulation.setDeviceMetricsOverride", width=a.w, height=a.h,
                 deviceScaleFactor=a.dpr, mobile=True)
        cdp.send("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
        if a.throttle:
            # Slow the pipe down so the progressive/streaming path is observable at
            # all: on localhost the whole vehicle lands before the first frame.
            cdp.send("Network.enable")
            cdp.send("Network.emulateNetworkConditions", offline=False, latency=150,
                     downloadThroughput=a.throttle * 1000 // 8, uploadThroughput=a.throttle * 1000 // 8)
        cdp.send("Page.navigate", url=a.url)
        deadline = time.time() + a.timeout
        # poll for the app to finish loading instead of sleeping blind
        while time.time() < deadline:
            try:
                st = cdp.eval("document.getElementById('status')?.textContent || ''")
            except Exception:
                st = ""
            if a.wait_for and st and a.wait_for in st:
                break
            time.sleep(0.25)
        time.sleep(a.settle)
        if a.eval:
            val = cdp.eval(a.eval)
            print("EVAL " + json.dumps(val))
        if a.out:
            shot = cdp.send("Page.captureScreenshot", format="png", captureBeyondViewport=False)
            with open(a.out, "wb") as f:
                f.write(base64.b64decode(shot["data"]))
            print("SAVED %s %d bytes" % (a.out, os.path.getsize(a.out)))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
