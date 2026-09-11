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

try:
    import joblib
except ImportError:  # allows the server to boot even before joblib is installed
    joblib = None

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
# NIR model and vision/NIR fusion
# ---------------------------------------------------------------------------

# Feature order the model was trained on (see train_nir_classifier.py /
# merge_csvs.py). The ESP32/serial_logger.py MUST send nir_reading values
# in exactly this order — the model has no column names at inference time,
# only positions.
NIR_FEATURE_ORDER = ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8",
                      "FZ", "FY", "FXL", "NIR", "Clear"]
NIR_EXPECTED_CHANNELS = len(NIR_FEATURE_ORDER)  # 13 — AS7343 8 spectral + FZ/FY/FXL + NIR + Clear

NIR_MODEL_PATH = "nir_classifier.pkl"
nir_model = None
if joblib is not None:
    try:
        nir_model = joblib.load(NIR_MODEL_PATH)
        logger.info(f"Loaded NIR classifier from {NIR_MODEL_PATH}")
    except Exception as e:
        logger.warning(f"Could not load {NIR_MODEL_PATH} yet: {e}")


def validate_nir_reading(readings: object) -> list[float] | None:
    """Returns 13 numeric sensor channels, or None when no usable reading was sent."""
    if readings is None:
        return None
    if not isinstance(readings, list) or len(readings) != NIR_EXPECTED_CHANNELS:
        raise HTTPException(status_code=422, detail=f"Expected {NIR_EXPECTED_CHANNELS} NIR channel values.")
    try:
        return [float(value) for value in readings]
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="NIR channel values must be numeric.")


def predict_nir(readings: list[float] | None) -> dict[str, float] | None:
    """Returns class probabilities only when both a reading and NIR model exist."""
    if readings is None or nir_model is None:
        return None

    import numpy as np

    probabilities = nir_model.predict_proba(np.array(readings).reshape(1, -1))[0]
    return {
        str(label): float(probability)
        for label, probability in zip(nir_model.classes_, probabilities)
    }


def predict_yolo_sync(image: Image.Image) -> dict[str, float]:
    """Runs YOLO and exposes probabilities by material label for fusion."""
    results = model(image, verbose=False)
    result = results[0]
    probabilities = result.probs.data.tolist()
    return {
        str(result.names[index]): float(probability)
        for index, probability in enumerate(probabilities)
    }


def combine_predictions(
    yolo_scores: dict[str, float] | None,
    nir_scores: dict[str, float] | None,
) -> tuple[str, float, str]:
    """Uses the available classifier, or averages both probability vectors."""
    if yolo_scores is None and nir_scores is None:
        raise HTTPException(
            status_code=503,
            detail="No usable classifier is available: camera/YOLO and NIR are both unavailable.",
        )
    if yolo_scores is None:
        material, confidence = max(nir_scores.items(), key=lambda item: item[1])
        return material, confidence, "nir"
    if nir_scores is None:
        material, confidence = max(yolo_scores.items(), key=lambda item: item[1])
        return material, confidence, "yolo"

    # Both sources are live. Equal weighting prevents either source from
    # silently overriding the other and makes their agreement raise confidence.
    labels = set(yolo_scores) | set(nir_scores)
    combined_scores = {
        label: (yolo_scores.get(label, 0.0) + nir_scores.get(label, 0.0)) / 2
        for label in labels
    }
    material, confidence = max(combined_scores.items(), key=lambda item: item[1])
    return material, confidence, "combined"


async def predict_yolo(image: Image.Image | None) -> dict[str, float] | None:
    if image is None or model is None:
        return None
    return await asyncio.to_thread(predict_yolo_sync, image)


def build_scan_result(material: str, confidence: float, source: str, timestamp: str | None) -> dict:
    info = MATERIAL_INFO.get(material, {"recyclable": False, "reason": "Unknown material."})
    return {
        "material": material,
        "confidence": round(confidence * 100, 1),
        "recyclable": info["recyclable"],
        "reason": info["reason"],
        "route": "LEFT" if info["recyclable"] else "RIGHT",
        "source": source,
        "timestamp": timestamp or datetime.utcnow().isoformat(),
    }


async def publish_scan_result(
    yolo_image: Image.Image | None, readings: list[float] | None, timestamp: str | None
) -> dict:
    yolo_scores, nir_scores = await predict_yolo(yolo_image), predict_nir(readings)
    material, confidence, source = combine_predictions(yolo_scores, nir_scores)
    result = build_scan_result(material, confidence, source, timestamp)
    logger.info(f"Scan result: {result}")
    await broadcast_result(result)
    return result


def decode_image(image_data: object) -> Image.Image | None:
    if image_data is None:
        return None
    if not isinstance(image_data, str):
        raise HTTPException(status_code=422, detail="The image field must be base64-encoded JPEG data.")
    try:
        return Image.open(io.BytesIO(base64.b64decode(image_data))).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not decode image: {exc}")


def latest_camera_image() -> Image.Image | None:
    if _latest_frame is None or _last_frame_time is None:
        return None
    if time.time() - _last_frame_time > CAMERA_STALE_SECONDS:
        return None
    try:
        return Image.open(io.BytesIO(_latest_frame)).convert("RGB")
    except Exception as exc:
        logger.warning(f"Could not decode latest camera frame: {exc}")
        return None


@app.post("/scan")
async def scan_item(payload: dict):
    """Classifies a supplied image, NIR reading, or both; both are fused."""
    image = decode_image(payload.get("image"))
    readings = validate_nir_reading(payload.get("nir_reading"))
    result = await publish_scan_result(image, readings, payload.get("timestamp"))
    return {key: result[key] for key in ("route", "material", "confidence", "source")}


@app.post("/nir-scan")
async def nir_scan(payload: dict):
    """Classifies NIR readings and fuses a fresh camera frame when available."""
    readings = validate_nir_reading(payload.get("nir_reading"))
    if readings is not None and all(value == 0 for value in readings):
        result = {
            "material": "NONE", "confidence": 100.0, "recyclable": None,
            "reason": "No object detected on the conveyor belt.", "route": "NONE",
            "source": "nir", "timestamp": payload.get("timestamp") or datetime.utcnow().isoformat(),
        }
        await broadcast_result(result)
        return {key: result[key] for key in ("route", "material", "confidence", "source")}

    result = await publish_scan_result(latest_camera_image(), readings, payload.get("timestamp"))
    return {key: result[key] for key in ("route", "material", "confidence", "source")}


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
        "nir_expected_channels": NIR_EXPECTED_CHANNELS,
        "connected_dashboards": len(connected_clients),
        "camera_connected": _latest_frame is not None,
    }
