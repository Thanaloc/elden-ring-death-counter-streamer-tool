"""
Cadrage du template dans le navigateur.

La detection automatique du bloc de texte s'est revelee peu fiable : selon
la scene ou le joueur meurt, le texte peut etre moins lumineux que le decor
qui l'entoure. Un cadrage fait a la main une seule fois est plus court a
expliquer et ne se trompe jamais.
"""

from __future__ import annotations

import base64
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Cadrer le texte de mort</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,500;1,500&display=swap" rel="stylesheet">
<style>
  :root { --bone:#EDE6D6; --gold:#C6A664; --ground:#141210; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body {
    background: var(--ground);
    color: var(--bone);
    font-family: "Cormorant Garamond", Georgia, serif;
    display: flex; flex-direction: column; align-items: center;
    gap: 20px; padding: 40px 24px;
  }
  h1 { font-weight:300; font-size:30px; letter-spacing:.02em; }
  p { max-width: 62ch; font-size:19px; line-height:1.5; opacity:.8; text-align:center; }
  #stage { position:relative; cursor:crosshair; line-height:0;
           outline:1px solid rgba(198,166,100,.35); }
  #stage img { display:block; max-width:100%; user-select:none; -webkit-user-drag:none; }
  #box { position:absolute; border:2px solid var(--gold);
         background:rgba(198,166,100,.14); display:none; pointer-events:none; }
  #bar { display:flex; align-items:center; gap:18px; min-height:44px; }
  button {
    font-family:inherit; font-size:19px; padding:9px 26px;
    background:transparent; color:var(--gold);
    border:1px solid var(--gold); cursor:pointer;
  }
  button:disabled { opacity:.3; cursor:default; }
  button:not(:disabled):hover { background:var(--gold); color:var(--ground); }
  #status { font-style:italic; font-size:18px; opacity:.75; }
  #done { font-size:22px; color:var(--gold); display:none; }
</style>
</head>
<body>
  <h1>Cadre le texte de mort</h1>
  <p>Trace un rectangle serré autour du texte, sans englober le décor autour.
     Recommence autant de fois que nécessaire, seul le dernier compte.</p>

  <div id="stage">
    <img id="shot" src="__IMAGE__" alt="Capture de la zone analysée">
    <div id="box"></div>
  </div>

  <div id="bar">
    <button id="save" disabled>Enregistrer le cadrage</button>
    <span id="status"></span>
  </div>
  <div id="done">C'est enregistré. Tu peux fermer cet onglet et revenir au terminal.</div>

<script>
  const stage = document.getElementById("stage");
  const shot = document.getElementById("shot");
  const box = document.getElementById("box");
  const save = document.getElementById("save");
  const status = document.getElementById("status");

  let origin = null, rect = null;

  function scale() { return shot.naturalWidth / shot.clientWidth; }

  function at(event) {
    const bounds = shot.getBoundingClientRect();
    return {
      x: Math.min(Math.max(event.clientX - bounds.left, 0), bounds.width),
      y: Math.min(Math.max(event.clientY - bounds.top, 0), bounds.height),
    };
  }

  function draw() {
    box.style.display = "block";
    box.style.left = rect.x + "px";
    box.style.top = rect.y + "px";
    box.style.width = rect.w + "px";
    box.style.height = rect.h + "px";
  }

  stage.addEventListener("pointerdown", (e) => {
    origin = at(e);
    rect = { x: origin.x, y: origin.y, w: 0, h: 0 };
    stage.setPointerCapture(e.pointerId);
    draw();
  });

  stage.addEventListener("pointermove", (e) => {
    if (!origin) return;
    const p = at(e);
    rect = {
      x: Math.min(origin.x, p.x), y: Math.min(origin.y, p.y),
      w: Math.abs(p.x - origin.x), h: Math.abs(p.y - origin.y),
    };
    draw();
  });

  stage.addEventListener("pointerup", () => {
    origin = null;
    const k = scale();
    const wide = rect && rect.w * k > 20 && rect.h * k > 8;
    save.disabled = !wide;
    status.textContent = wide
      ? Math.round(rect.w * k) + " × " + Math.round(rect.h * k) + " pixels"
      : "Le rectangle est trop petit.";
  });

  save.addEventListener("click", async () => {
    const k = scale();
    const payload = {
      x0: Math.round(rect.x * k), y0: Math.round(rect.y * k),
      x1: Math.round((rect.x + rect.w) * k), y1: Math.round((rect.y + rect.h) * k),
    };
    save.disabled = true;
    const res = await fetch("/confirm", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      document.getElementById("bar").style.display = "none";
      document.getElementById("done").style.display = "block";
      status.textContent = "";
    } else {
      save.disabled = false;
      status.textContent = "Échec de l'enregistrement, réessaie.";
    }
  });
</script>
</body>
</html>
"""


def crop_in_browser(band: np.ndarray, on_crop, port: int = 4748) -> None:
    """
    Sert la bande capturee dans le navigateur et attend un cadrage.

    on_crop(x0, y0, x1, y1) est appele quand l'utilisateur valide ; la
    fonction rend la main une fois le cadrage enregistre.
    """
    ok, buffer = cv2.imencode(".png", band)
    if not ok:
        raise OSError("Impossible d'encoder la capture.")
    data_uri = "data:image/png;base64," + base64.b64encode(buffer).decode()
    page = PAGE.replace("__IMAGE__", data_uri).encode("utf-8")

    finished = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            try:
                coords = json.loads(self.rfile.read(length))
                on_crop(int(coords["x0"]), int(coords["y0"]),
                        int(coords["x1"]), int(coords["y1"]))
            except Exception as exc:
                body = json.dumps({"error": str(exc)}).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            finished.set()

    class Quiet(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            pass

    httpd = Quiet(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    url = f"http://127.0.0.1:{port}"
    print(f"Ouvre {url} pour cadrer le texte.")
    print("(la page devrait s'ouvrir toute seule)\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        finished.wait()
    finally:
        httpd.shutdown()


def save_template(band: np.ndarray, box, template_path: Path,
                  preview_path: Path) -> np.ndarray:
    """Decoupe, ecrit le template et un apercu annote. Retourne le template."""
    from .detector import imwrite_png

    x0, y0, x1, y1 = box
    x0, x1 = sorted((max(0, x0), min(band.shape[1], x1)))
    y0, y1 = sorted((max(0, y0), min(band.shape[0], y1)))
    template = band[y0:y1, x0:x1]
    if template.size == 0:
        raise ValueError("Le cadrage est vide.")

    template_path.parent.mkdir(parents=True, exist_ok=True)
    if not imwrite_png(template_path, template):
        raise OSError(f"Impossible d'ecrire {template_path}")

    preview = cv2.cvtColor(band, cv2.COLOR_GRAY2BGR)
    cv2.rectangle(preview, (x0, y0), (x1, y1), (100, 200, 240), 2)
    imwrite_png(preview_path, preview)
    return template
