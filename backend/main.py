"""
SpectraLink Backend
--------------------
Receives image + NIR sensor data from the ESP32 station, runs YOLO
classification, fuses it with the sensor reading, looks up recyclability,
decides a sort route, broadcasts the result to the dashboard over
WebSocket, and returns the route so the ESP32 can drive the servo.

Also proxies a live MJPEG feed from an ESP32-CAM: the camera POSTs JPEG
frames to /camera/upload, and the dashboard reads them back from
/camera/stream. This indirection is what lets the camera be viewed from
anywhere on the internet even though it sits behind a home router with
no public IP — the ESP32-CAM only ever makes outbound requests.

Access control: a single shared username/password (SITE_USERNAME /
SITE_PASSWORD) gates the WebSocket and camera stream. POST /login with
the correct credentials to receive a token; every /ws connection and
/camera/stream request must include that token as a query parameter.
Tokens live in memory only — they're cleared on server restart, which is
fine for a single shared account.
"""

import asyncio
import base64
import io
import logging
import os
import secrets
import time
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from PIL import Image

try:
    from ultralytics import YOLO
except ImportError:  # allows the server to boot even before ultralytics is installed
    YOLO = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("spectralink")

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="SpectraLink Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this to your actual frontend URL in production
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_PATH = "best.pt"
model = None
if YOLO is not None:
    try:
        model = YOLO(MODEL_PATH)
        logger.info(f"Loaded model from {MODEL_PATH}")
    except Exception as e:
        logger.warning(f"Could not load {MODEL_PATH} yet: {e}")

# ---------------------------------------------------------------------------
# Authentication — single shared account, token-based
# ---------------------------------------------------------------------------
# Shared dashboard credentials. These are intentionally set directly so the
# deployed service uses the same credentials even if Render has old
# environment-variable values configured.
SITE_USERNAME = "anamitra"
SITE_PASSWORD = "12345"

# In-memory token store. Fine for a single shared account with no need
# for per-user tracking — tokens are just "is this person allowed in."
valid_tokens: set[str] = set()


def is_valid_token(token: str | None) -> bool:
    return token is not None and token in valid_tokens


@app.post("/login")
async def login(payload: dict):
    """
    Expected payload: {"username": "...", "password": "..."}
    Returns {"success": true, "token": "..."} on success.
    """
    username = payload.get("username", "")
    password = payload.get("password", "")

    if username == SITE_USERNAME and password == SITE_PASSWORD:
        token = secrets.token_urlsafe(32)
        valid_tokens.add(token)
        logger.info("Successful login, token issued.")
        return {"success": True, "token": token}

    logger.info(f"Failed login attempt for username: {username!r}")
    raise HTTPException(status_code=401, detail="Invalid username or password.")


@app.post("/logout")
async def logout(payload: dict):
    """Expected payload: {"token": "..."}"""
    token = payload.get("token")
    valid_tokens.discard(token)
    return {"success": True}


# ---------------------------------------------------------------------------
# Recyclability lookup table
# ---------------------------------------------------------------------------

MATERIAL_INFO = {
    "PET":   {"recyclable": True,  "reason": "Simple polymer chain, easily reprocessed."},
    "HDPE":  {"recyclable": True,  "reason": "Simple polymer chain, easily reprocessed."},
    "PP":    {"recyclable": True,  "reason": "Stable polymer, growing recycling infrastructure."},
    "LDPE":  {"recyclable": False, "reason": "Low density makes sorting/processing uneconomical at most facilities."},
    "PVC":   {"recyclable": False, "reason": "Chlorine content releases toxins when reprocessed."},
    "PS":    {"recyclable": False, "reason": "Brittle, breaks into microplastics, low recycling value."},
    "OTHER": {"recyclable": False, "reason": "Mixed/multi-polymer composition, can't be separated for reprocessing."},
}

# ---------------------------------------------------------------------------
# WebSocket connection management (for the live dashboard)
# ---------------------------------------------------------------------------

connected_clients: list[WebSocket] = []


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not is_valid_token(token):
        # 4401 is a custom close code in the app-specific range (4000-4999);
        # the frontend can use this to distinguish "wrong token" from a
        # generic dropped connection if it ever needs to.
        await websocket.close(code=4401)
        return

    await websocket.accept()
    connected_clients.append(websocket)
    logger.info(f"Dashboard client connected ({len(connected_clients)} total)")
    try:
        while True:
            # Keep the connection alive; dashboard doesn't need to send anything.
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        logger.info(f"Dashboard client disconnected ({len(connected_clients)} total)")


async def broadcast_result(result: dict):
    stale = []
    for client in connected_clients:
        try:
            await client.send_json(result)
        except Exception:
            stale.append(client)
    for client in stale:
        connected_clients.remove(client)


# ---------------------------------------------------------------------------
# Fusion logic (placeholder — refine once real NIR calibration data exists)
# ---------------------------------------------------------------------------

def fuse_prediction(yolo_class: str, yolo_confidence: float, nir_reading: list):
    """
    Combine YOLO's vision-based guess with the NIR spectral reading.

    For now this is a pass-through: it trusts YOLO's prediction as-is.
    Once you have real sensor data, replace this with logic that compares
    `nir_reading` against known reference spectral signatures per material
    (e.g. nearest-neighbor match) and uses that to confirm or override
    the vision-only guess — especially useful for the PS/PP confusion.
    """
    if not nir_reading:
        return yolo_class, yolo_confidence

    # TODO: real fusion logic goes here once NIR calibration data is collected.
    return yolo_class, yolo_confidence


# ---------------------------------------------------------------------------
# Core scan endpoint — this is what the ESP32 calls (image-based path)
# ---------------------------------------------------------------------------

@app.post("/scan")
async def scan_item(payload: dict):
    """
    Expected payload:
    {
        "image": "<base64 encoded JPEG>",
        "nir_reading": [0.42, 0.38, 0.91, ...],   # optional
        "timestamp": "2026-07-19T15:22:05"        # optional
    }
    """
    if model is None:
        return {"error": "Model not loaded. Place best.pt next to main.py and restart the server."}

    if "image" not in payload:
        return {"error": "Missing 'image' field in payload."}

    # Decode the incoming image
    try:
        image_bytes = base64.b64decode(payload["image"])
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as e:
        return {"error": f"Could not decode image: {e}"}

    # Run YOLO classification (offloaded to a thread so this blocking,
    # CPU-bound call doesn't freeze /camera/stream or /camera/upload while
    # it runs — same reasoning as auto_scan_loop's _classify_frame_sync).
    results = await asyncio.to_thread(model, image, verbose=False)
    predicted_class = results[0].names[results[0].probs.top1]
    confidence = float(results[0].probs.top1conf)

    # Fuse with NIR sensor reading
    nir_reading = payload.get("nir_reading", [])
    final_material, final_confidence = fuse_prediction(predicted_class, confidence, nir_reading)

    # Look up recyclability
    info = MATERIAL_INFO.get(final_material, {"recyclable": False, "reason": "Unknown material."})
    route = "LEFT" if info["recyclable"] else "RIGHT"

    result = {
        "material": final_material,
        "confidence": round(final_confidence * 100, 1),
        "recyclable": info["recyclable"],
        "reason": info["reason"],
        "route": route,
        "timestamp": payload.get("timestamp", datetime.utcnow().isoformat()),
    }

    logger.info(f"Scan result: {result}")
    await broadcast_result(result)

    # This is what the ESP32 uses to decide which way to move the servo
    return {"route": route, "material": final_material, "confidence": result["confidence"]}


# ---------------------------------------------------------------------------
# NIR-based scan endpoint — the intended primary classification path once
# real AS7343 sensor data + a trained classifier exist. Currently a stub:
# it returns a clear "not ready yet" error rather than pretending to work,
# so it fails loudly instead of silently returning nonsense.
# ---------------------------------------------------------------------------

nir_model = None  # populate once trained, e.g. via joblib.load("nir_classifier.pkl")

NIR_EXPECTED_CHANNELS = 14  # AS7343 channel count


@app.post("/nir-scan")
async def nir_scan(payload: dict):
    """
    Expected payload:
    {
        "nir_reading": [ch1, ch2, ..., ch14],
        "timestamp": "2026-07-19T15:22:05"   # optional
    }
    """
    if nir_model is None:
        return {"error": "NIR classifier not trained/loaded yet. See nir_readings.csv workflow."}

    readings = payload.get("nir_reading")
    if not readings or len(readings) != NIR_EXPECTED_CHANNELS:
        return {"error": f"Expected {NIR_EXPECTED_CHANNELS} NIR channel values."}

    import numpy as np  # local import: only needed once nir_model exists

    X = np.array(readings).reshape(1, -1)
    predicted_class = nir_model.predict(X)[0]
    confidence = float(max(nir_model.predict_proba(X)[0]))

    info = MATERIAL_INFO.get(predicted_class, {"recyclable": False, "reason": "Unknown material."})
    route = "LEFT" if info["recyclable"] else "RIGHT"

    result = {
        "material": predicted_class,
        "confidence": round(confidence * 100, 1),
        "recyclable": info["recyclable"],
        "reason": info["reason"],
        "route": route,
        "timestamp": payload.get("timestamp", datetime.utcnow().isoformat()),
    }

    logger.info(f"NIR scan result: {result}")
    await broadcast_result(result)

    return {"route": route, "material": predicted_class, "confidence": result["confidence"]}


# ---------------------------------------------------------------------------
# Auto-scan loop — classifies the live camera feed without waiting for the
# ESP32 to explicitly call /scan. Runs on a timer in the background: every
# AUTO_SCAN_INTERVAL_SECONDS it grabs whatever frame the camera most
# recently uploaded and runs it through YOLO, same as /scan does manually.
#
# This exists as a demo/fallback path. Once the NIR classifier is the real
# source of truth, this can be left running purely for display purposes
# (showing what the camera "also thinks") or disabled entirely via
# AUTO_SCAN_ENABLED = False.
# ---------------------------------------------------------------------------
AUTO_SCAN_ENABLED = True
AUTO_SCAN_INTERVAL_SECONDS = 2.0

# Below this confidence, treat it as "nothing recognizable in frame" (e.g.
# empty conveyor belt) rather than broadcasting a low-quality guess.
AUTO_SCAN_CONFIDENCE_THRESHOLD = 0.60

# Once an item is broadcast, don't broadcast it again on every single tick
# while it just sits there — only re-broadcast if the detected material
# changes, or after this many seconds have passed (a "heartbeat" so the
# dashboard doesn't look stuck if the same item is still there).
AUTO_SCAN_REBROADCAST_COOLDOWN_SECONDS = 8.0

_auto_scan_last_material: str | None = None
_auto_scan_last_broadcast_time: float = 0.0
_auto_scan_last_processed_frame_time: float | None = None

# Approximates where the dashboard's on-screen bounding-box reticle sits,
# so auto-scan classifies roughly "what's inside the box" instead of the
# entire frame (background, hands, conveyor edges, etc). This is only an
# approximation — the reticle is CSS-positioned against a responsive video
# panel with no pixel-exact link to the camera's actual resolution — so
# it's expressed as a fraction of the frame, not fixed pixels.
#
# Box on screen is w-96 h-80 (384x320px, ~1.2:1 ratio). CROP_WIDTH_FRAC /
# CROP_HEIGHT_FRAC control how much of the frame (centered) counts as
# "inside the box." If you resize the box in index.html, update these to
# match its new ratio.
AUTO_SCAN_CROP_WIDTH_FRAC = 0.55   # fraction of frame width kept, centered
AUTO_SCAN_CROP_HEIGHT_FRAC = 0.65  # fraction of frame height kept, centered


def crop_to_bbox_region(image: Image.Image) -> Image.Image:
    """Crops the center of `image` down to the region approximating where
    the dashboard's bounding-box overlay sits, using AUTO_SCAN_CROP_WIDTH_FRAC
    / AUTO_SCAN_CROP_HEIGHT_FRAC."""
    w, h = image.size
    crop_w = int(w * AUTO_SCAN_CROP_WIDTH_FRAC)
    crop_h = int(h * AUTO_SCAN_CROP_HEIGHT_FRAC)
    left = (w - crop_w) // 2
    top = (h - crop_h) // 2
    return image.crop((left, top, left + crop_w, top + crop_h))


def _classify_frame_sync(frame_bytes: bytes):
    """Runs the actual decode + crop + YOLO inference. Synchronous and
    CPU-bound on purpose — this is meant to be called via
    asyncio.to_thread(), never awaited directly, so it doesn't block the
    event loop (which also needs to keep serving /camera/stream and
    accepting /camera/upload while this runs)."""
    image = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
    image = crop_to_bbox_region(image)
    results = model(image, verbose=False)
    predicted_class = results[0].names[results[0].probs.top1]
    confidence = float(results[0].probs.top1conf)
    return predicted_class, confidence


async def auto_scan_loop():
    global _auto_scan_last_material, _auto_scan_last_broadcast_time, _auto_scan_last_processed_frame_time

    while True:
        await asyncio.sleep(AUTO_SCAN_INTERVAL_SECONDS)

        if not AUTO_SCAN_ENABLED or model is None:
            continue
        if _latest_frame is None or _last_frame_time is None:
            continue

        # Skip if the camera feed has gone stale (ESP32-CAM disconnected) —
        # no point re-classifying the same frozen frame over and over.
        if time.time() - _last_frame_time > CAMERA_STALE_SECONDS:
            continue

        # Skip if we've already classified this exact frame (camera hasn't
        # uploaded anything new since our last pass).
        if _auto_scan_last_processed_frame_time == _last_frame_time:
            continue
        _auto_scan_last_processed_frame_time = _last_frame_time

        try:
            predicted_class, confidence = await asyncio.to_thread(_classify_frame_sync, _latest_frame)
        except Exception as e:
            logger.warning(f"Auto-scan: classification failed: {e}")
            continue

        if confidence < AUTO_SCAN_CONFIDENCE_THRESHOLD:
            continue

        now = time.time()
        material_changed = predicted_class != _auto_scan_last_material
        cooldown_elapsed = (now - _auto_scan_last_broadcast_time) >= AUTO_SCAN_REBROADCAST_COOLDOWN_SECONDS
        if not material_changed and not cooldown_elapsed:
            continue

        info = MATERIAL_INFO.get(predicted_class, {"recyclable": False, "reason": "Unknown material."})
        route = "LEFT" if info["recyclable"] else "RIGHT"

        result = {
            "material": predicted_class,
            "confidence": round(confidence * 100, 1),
            "recyclable": info["recyclable"],
            "reason": info["reason"],
            "route": route,
            "timestamp": datetime.utcnow().isoformat(),
        }

        logger.info(f"Auto-scan result: {result}")
        await broadcast_result(result)

        _auto_scan_last_material = predicted_class
        _auto_scan_last_broadcast_time = now


@app.on_event("startup")
async def start_auto_scan_loop():
    asyncio.create_task(auto_scan_loop())


# ---------------------------------------------------------------------------
# ESP32-CAM live stream
# ---------------------------------------------------------------------------
# The ESP32-CAM never talks to the browser directly — it only ever makes
# an outbound POST to this server. That's what lets the camera be viewed
# from anywhere on the internet even though it sits behind a home
# router/NAT with no public IP or port-forwarding.
#
# Flow: ESP32-CAM --POST JPEG--> /camera/upload --> stored in memory
#       Browser <--MJPEG stream-- /camera/stream <-- re-served from memory
#
# Set CAMERA_API_KEY as an environment variable in production, then send
# the same value as the "X-Api-Key" header from the ESP32-CAM firmware.
# Leave it unset only for local testing.
CAMERA_API_KEY = os.environ.get("CAMERA_API_KEY", "")

_latest_frame: bytes | None = None
_last_frame_time: float | None = None
_frame_event = asyncio.Event()

# How long without a new uploaded frame before we consider the camera
# "disconnected." GET /camera/status reports this to the dashboard, which
# polls it to decide whether to show the live feed or fall back to the
# default conveyor animation — since an MJPEG <img> stream itself never
# signals staleness (the HTTP connection to the browser stays open even
# when the ESP32-CAM has gone quiet).
CAMERA_STALE_SECONDS = 6


@app.post("/camera/upload")
async def camera_upload(request: Request, x_api_key: str | None = Header(default=None)):
    """The ESP32-CAM POSTs one raw JPEG frame (as the request body) here,
    over and over, as fast as it can capture them."""
    if CAMERA_API_KEY and x_api_key != CAMERA_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Api-Key header.")

    global _latest_frame, _last_frame_time
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body — expected a JPEG image.")

    _latest_frame = body
    _last_frame_time = time.time()
    _frame_event.set()
    _frame_event.clear()
    return {"ok": True, "bytes": len(body)}


@app.get("/camera/stream")
async def camera_stream(token: str | None = None):
    """Re-serves the latest uploaded frame(s) as a multipart/x-mixed-replace
    MJPEG stream, which browsers render natively inside a plain <img> tag.

    Gated by the same shared-account token as /ws — pass it as
    ?token=... in the URL, since <img> tags can't send custom headers."""
    if not is_valid_token(token):
        raise HTTPException(status_code=401, detail="Invalid or missing token.")

    async def frame_generator():
        boundary = b"--frame\r\n"
        while True:
            if _latest_frame is None:
                # No frames received from the ESP32-CAM yet.
                await asyncio.sleep(0.5)
                continue
            frame = _latest_frame
            yield boundary
            yield b"Content-Type: image/jpeg\r\n"
            yield f"Content-Length: {len(frame)}\r\n\r\n".encode()
            yield frame
            yield b"\r\n"
            # Caps how fast we re-serve to each connected browser,
            # independent of how fast the ESP32-CAM is uploading.
            await asyncio.sleep(0.1)

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/camera/status")
async def camera_status():
    """Tells the dashboard whether the camera feed is actually live right
    now — i.e. whether a real frame arrived within the last
    CAMERA_STALE_SECONDS — rather than just whether the MJPEG connection
    to the browser happens to still be open (which it always is).

    Deliberately NOT gated by token: it reveals no image data, only a
    boolean/timing status, and the dashboard polls it before knowing
    whether login has completed in some edge cases."""
    if _latest_frame is None or _last_frame_time is None:
        return {"connected": False, "seconds_since_last_frame": None}
    elapsed = time.time() - _last_frame_time
    return {"connected": elapsed < CAMERA_STALE_SECONDS, "seconds_since_last_frame": round(elapsed, 1)}


@app.get("/camera/latest.jpg")
async def camera_latest(token: str | None = None):
    """Single-frame snapshot fallback — handy for testing with curl/browser,
    or for clients that can't render MJPEG."""
    if not is_valid_token(token):
        raise HTTPException(status_code=401, detail="Invalid or missing token.")
    if _latest_frame is None:
        raise HTTPException(status_code=404, detail="No frames received from the camera yet.")
    from fastapi.responses import Response
    return Response(content=_latest_frame, media_type="image/jpeg")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "status": "SpectraLink backend running",
        "model_loaded": model is not None,
        "nir_model_loaded": nir_model is not None,
        "connected_dashboards": len(connected_clients),
        "camera_connected": _latest_frame is not None,
    }
