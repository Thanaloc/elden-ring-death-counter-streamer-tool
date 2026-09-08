"""
Confirmation de la zone detectee, dans le navigateur.

L'extraction automatique trouve la bonne zone la plupart du temps, mais
quand elle se trompe elle le fait en silence et le streamer ne s'en rend
compte qu'en constatant que rien ne s'incremente. Un coup d'oeil et un clic
au moment du setup coutent dix secondes et suppriment ce mode de panne.

La detection reste automatique : cette page propose deja une reponse.
"""

from __future__ import annotations

import base64
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np  # noqa: F401  (type des captures)

PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Vérifier la zone détectée</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;500&display=swap" rel="stylesheet">
<style>
  :root { --bone:#EDE6D6; --gold:#C6A664; --ground:#141210; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--ground); color:var(--bone);
         font-family:"Cormorant Garamond", Georgia, serif;
         display:flex; flex-direction:column; align-items:center;
         gap:18px; padding:36px 24px; }
  h1 { font-weight:300; font-size:29px; }
  p { max-width:64ch; font-size:19px; line-height:1.5; opacity:.8; text-align:center; }
  #stage { position:relative; cursor:crosshair; line-height:0;
           outline:1px solid rgba(198,166,100,.3); }
  #stage img { display:block; max-width:100%; user-select:none; -webkit-user-drag:none; }
  #box { position:absolute; border:2px solid var(--gold);
         background:rgba(198,166,100,.12); pointer-events:none; }
  #bar { display:flex; align-items:center; gap:16px; min-height:44px; }
  button { font-family:inherit; font-size:19px; padding:9px 26px;
           background:transparent; color:var(--gold);
           border:1px solid var(--gold); cursor:pointer; }
  button:hover { background:var(--gold); color:var(--ground); }
  button.ghost { color:var(--bone); border-color:rgba(237,230,214,.35); }
  button.ghost:hover { background:rgba(237,230,214,.12); color:var(--bone); }
  #status { font-size:18px; opacity:.7; }
  #done { font-size:22px; color:var(--gold); display:none; }
</style>
</head>
<body>
  <h1>Le cadre est-il sur le texte&nbsp;?</h1>
  <p>Si le cadre entoure le texte de mort, valide. Sinon, trace un rectangle
     autour du texte pour corriger. Serre-le sur les lettres&nbsp;: un cadre
     trop large fait chuter la lecture.</p>

  <div id="stage">
    <img id="shot" src="__IMAGE__" alt="Capture de l'écran de mort">
    <div id="box"></div>
  </div>

  <div id="bar">
    <button id="ok">C'est le bon cadre</button>
    <button id="reset" class="ghost">Rétablir la proposition</button>
    <span id="status"></span>
  </div>
  <div id="done">Enregistré. Tu peux fermer cet onglet et revenir au terminal.</div>

<script>
  const DETECTED = __BOX__;
  const stage = document.getElementById("stage");
  const shot = document.getElementById("shot");
  const box = document.getElementById("box");
  const status = document.getElementById("status");

  let origin = null, rect = null;

  const scale = () => shot.naturalWidth / shot.clientWidth;

  function show(r) { rect = r;
    const k = scale();
    box.style.left = (r.x0 / k) + "px";
    box.style.top = (r.y0 / k) + "px";
    box.style.width = ((r.x1 - r.x0) / k) + "px";
    box.style.height = ((r.y1 - r.y0) / k) + "px";
  }

  function at(e) {
    const b = shot.getBoundingClientRect();
    return { x: Math.min(Math.max(e.clientX - b.left, 0), b.width) * scale(),
             y: Math.min(Math.max(e.clientY - b.top, 0), b.height) * scale() };
  }

  stage.addEventListener("pointerdown", (e) => {
    origin = at(e);
    stage.setPointerCapture(e.pointerId);
    show({ x0: origin.x, y0: origin.y, x1: origin.x, y1: origin.y });
  });
  stage.addEventListener("pointermove", (e) => {
    if (!origin) return;
    const p = at(e);
    show({ x0: Math.min(origin.x, p.x), y0: Math.min(origin.y, p.y),
           x1: Math.max(origin.x, p.x), y1: Math.max(origin.y, p.y) });
  });
  stage.addEventListener("pointerup", () => {
    origin = null;
    const w = rect.x1 - rect.x0, h = rect.y1 - rect.y0;
    status.textContent = (w > 20 && h > 8)
      ? Math.round(w) + " × " + Math.round(h) + " pixels"
      : "Rectangle trop petit.";
  });

  document.getElementById("reset").addEventListener("click", () => {
    show(DETECTED); status.textContent = "Proposition rétablie.";
  });

  document.getElementById("ok").addEventListener("click", async () => {
    const res = await fetch("/confirm", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ x0: Math.round(rect.x0), y0: Math.round(rect.y0),
                             x1: Math.round(rect.x1), y1: Math.round(rect.y1) }),
    });
    if (res.ok) {
      document.getElementById("bar").style.display = "none";
      document.getElementById("done").style.display = "block";
      status.textContent = "";
    } else { status.textContent = "Échec, réessaie."; }
  });

  window.addEventListener("load", () => show(DETECTED));
</script>
</body>
</html>
"""


def confirm_zone(frame: np.ndarray, box, mask=None, port: int = 4748):
    """
    Affiche la capture avec la zone proposee et retourne la zone validee.

    Retourne un tuple (x0, y0, x1, y1) : celui propose si l'utilisateur
    valide tel quel, ou celui qu'il a trace.
    """
    display = cv2.convertScaleAbs(frame, alpha=2.2, beta=25)
    display = cv2.cvtColor(display, cv2.COLOR_GRAY2BGR)
    x0, y0, x1, y1 = box
    if mask is not None:
        display[y0:y1, x0:x1][mask > 0] = (90, 220, 255)
    cv2.rectangle(display, (x0, y0), (x1 - 1, y1 - 1), (90, 220, 255), 1)

    ok, buffer = cv2.imencode(".png", display)
    if not ok:
        raise OSError("Impossible d'encoder la capture.")

    page = (PAGE
            .replace("__IMAGE__", "data:image/png;base64,"
                     + base64.b64encode(buffer).decode())
            .replace("__BOX__", json.dumps(
                {"x0": int(x0), "y0": int(y0), "x1": int(x1), "y1": int(y1)}))
            .encode("utf-8"))

    chosen = {}
    finished = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _reply(self, body: bytes, mime: str, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._reply(page, "text/html; charset=utf-8")

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            try:
                coords = json.loads(self.rfile.read(length))
                chosen["box"] = (int(coords["x0"]), int(coords["y0"]),
                                 int(coords["x1"]), int(coords["y1"]))
            except Exception as exc:
                self._reply(json.dumps({"error": str(exc)}).encode(),
                            "application/json", 400)
                return
            self._reply(b'{"ok":true}', "application/json")
            finished.set()

    class Quiet(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            pass

    httpd = Quiet(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    url = f"http://127.0.0.1:{port}"
    print(f"Verifie la zone detectee sur {url}")
    print("(la page devrait s'ouvrir toute seule)\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        finished.wait()
    finally:
        httpd.shutdown()

    return chosen.get("box", tuple(box))
