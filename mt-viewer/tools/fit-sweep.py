#!/usr/bin/env python3
"""fit-sweep.py — numeric check that every vehicle is framed on every screen shape.

For each (viewport, vehicle, camera preset) it reads, from the live page:
  ndc    - the largest |NDC| of the model's 8 bounding-box corners (<=1 means on screen)
  scrollW/innerW - horizontal overflow of the document
  over   - control-bar children whose right edge passes the viewport
A mobile layout is only "done" when ndc <= 0.95 and over == 0 and scrollW == innerW.
"""
import base64, json, os, socket, subprocess, sys, tempfile, time, urllib.request

CH = os.environ.get("CH", "/nix/store/66fwidpz045aq5s9szdkg7znc4skgdwx-chromium-143.0.7499.169/bin/chromium")
BASE = os.environ.get("BASE", "http://127.0.0.1:8322/index.html")
VEHICLES = os.environ.get("VEH", "cotra_40_3,atlas_6x2_tanker,townie_bus,boxy").split(",")
VIEWPORTS = [("phone-portrait", 390, 844, 3), ("phone-landscape", 844, 390, 2),
             ("tablet-portrait", 768, 1024, 2), ("desktop", 1440, 900, 1)]
CAMS = ["iso", "front", "top"]


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def http_json(url, method="GET"):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


class CDP:
    def __init__(self, url):
        from websockets.sync.client import connect
        self.ws = connect(url, max_size=64 * 1024 * 1024)
        self.n = 0

    def send(self, method, **params):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == mid:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})

    def eval(self, expr):
        return self.send("Runtime.evaluate", expression=expr, returnByValue=True,
                         awaitPromise=True).get("result", {}).get("value")


PROBE = """(() => {
  const lay = document.title.split('|LAY=')[1];
  const L = lay ? JSON.parse(lay) : null;
  return JSON.stringify({
    ndc: window.__fit ? +window.__fit.ndc.toFixed(3) : null,
    dist: window.__fit ? +window.__fit.dist.toFixed(2) : null,
    look: window.__fit ? window.__fit.look : null,
    vw: innerWidth, vh: innerHeight,
    scrollW: document.documentElement.scrollWidth,
    over: L ? L.over : null,
    ctl: L ? L.ctl : null,
    status: (document.getElementById('status') || {}).textContent || '',
  });
})()"""


def main():
    port = free_port()
    prof = tempfile.mkdtemp(prefix="fitsweep-")
    proc = subprocess.Popen(
        [CH, "--headless", "--no-sandbox", "--disable-gpu", "--enable-unsafe-swiftshader",
         "--disable-dev-shm-usage", "--hide-scrollbars",
         "--remote-debugging-port=%d" % port, "--user-data-dir=" + prof, "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rows, bad = [], 0
    try:
        ws = None
        for _ in range(100):
            try:
                ws = http_json("http://127.0.0.1:%d/json/version" % port)["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.1)
        tgt = http_json("http://127.0.0.1:%d/json/new?about:blank" % port, method="PUT")
        c = CDP(tgt["webSocketDebuggerUrl"])
        c.send("Page.enable"); c.send("Runtime.enable")
        c.send("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
        for label, w, h, dpr in VIEWPORTS:
            c.send("Emulation.setDeviceMetricsOverride", width=w, height=h,
                   deviceScaleFactor=dpr, mobile=(w < 900))
            for v in VEHICLES:
                for cam in CAMS:
                    url = f"{BASE}?vehicle={v}&sync&debug&layout&ui=1&cam={cam}"
                    c.send("Page.navigate", url=url)
                    t0 = time.time()
                    data = None
                    while time.time() - t0 < 40:
                        try:
                            d = json.loads(c.eval(PROBE) or "{}")
                        except Exception:
                            d = {}
                        # the LAY block is written after the 350ms texture settle, so
                        # "loaded" alone is not enough — wait for the measurements too
                        if d.get("status", "").startswith("loaded") and d.get("over") is not None:
                            data = d
                            break
                        time.sleep(0.2)
                    if not data:
                        rows.append((label, v, cam, None, None, "TIMEOUT"))
                        bad += 1
                        continue
                    ok = (data["ndc"] is not None and data["ndc"] <= 0.95
                          and data["over"] == 0 and data["scrollW"] == data["vw"])
                    if not ok:
                        bad += 1
                    rows.append((label, v, cam, data["ndc"], data["over"],
                                 "ok" if ok else "FAIL"))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    print(f"{'viewport':16} {'vehicle':20} {'cam':6} {'ndc':>6} {'over':>5}  verdict")
    for r in rows:
        print(f"{r[0]:16} {r[1]:20} {r[2]:6} {str(r[3]):>6} {str(r[4]):>5}  {r[5]}")
    print(f"\n{len(rows) - bad}/{len(rows)} pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
