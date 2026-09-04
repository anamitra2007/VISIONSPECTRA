"""
SpectraLink Backend
--------------------
Receives NIR sensor data from the ESP32 station, classifies the material
by fusing that spectrum with the latest ESP32-CAM frame (same /nir-scan
contract — the image is never sent on a new endpoint), looks up
recyclability, decides a sort route, broadcasts the result to the
dashboard over WebSocket, and returns the route so the ESP32 can drive the
servo.

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
import io
import logging
import math
import os
import secrets
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
try:
    import joblib
except ImportError:  # allows the server to boot even before joblib is installed
    joblib = None
try:
    import numpy as np
except ImportError:
    np = None
try:
    from PIL import Image
except ImportError:
    Image = None

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

# Resolve artifacts from this file's directory rather than the process working
# directory. Railway may start the service from the repository root.
ARTIFACTS_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Authentication — single shared account, token-based
# ---------------------------------------------------------------------------
# Shared dashboard credentials. These are intentionally set directly so the
# deployed service uses the same credentials even if Render has old
# environment-variable values configured.
SITE_USERNAME = os.environ.get("SITE_USERNAME", "anamitra")
SITE_PASSWORD = os.environ.get("SITE_PASSWORD", "12345") 

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

MATERIAL_CLASSES = ("PET", "HDPE", "PP", "LDPE", "PVC", "PS", "OTHER")

# How long without a new uploaded frame before we treat the camera as
# disconnected (dashboard status) and skip image fusion on /nir-scan.
CAMERA_STALE_SECONDS = 6
_latest_frame: bytes | None = None
_last_frame_time: float | None = None
_frame_event = asyncio.Event()

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


def _softmax(logits: dict[str, float]) -> dict[str, float]:
    peak = max(logits.values())
    exps = {key: math.exp(value - peak) for key, value in logits.items()}
    total = sum(exps.values()) or 1.0
    return {key: value / total for key, value in exps.items()}


def classify_camera_frame(jpeg_bytes: bytes) -> dict | None:
    """Visual polymer prior from the latest JPEG. Complements NIR: black
    plastics, empty belt, and color/texture cues that a 13-channel AS7343
    cannot see. Not a substitute for a trained CNN — it is a safety prior
    fused with the NIR classifier."""
    if Image is None or np is None:
        return None
    try:
        image = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
        image = image.resize((96, 96), Image.BILINEAR)
        rgb = np.asarray(image, dtype=np.float32) / 255.0
    except Exception as exc:
        logger.warning(f"Could not decode camera frame for fusion: {exc}")
        return None

    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    saturation = np.max(rgb, axis=2) - np.min(rgb, axis=2)
    dark_frac = float((luminance < 0.18).mean())
    bright_frac = float((luminance > 0.72).mean())
    low_sat_frac = float((saturation < 0.10).mean())
    mid_sat_frac = float(((saturation >= 0.10) & (saturation < 0.35)).mean())
    texture = float(
        np.mean(np.abs(np.diff(luminance, axis=0)))
        + np.mean(np.abs(np.diff(luminance, axis=1)))
    )
    mean_r, mean_g, mean_b = float(red.mean()), float(green.mean()), float(blue.mean())
    empty = float(luminance.var()) < 0.004 and texture < 0.02

    logits = {name: 0.0 for name in MATERIAL_CLASSES}
    if empty:
        logits["OTHER"] = 3.0
    elif dark_frac > 0.42:
        # Carbon-black objects absorb NIR; prefer a conservative visual call.
        logits["OTHER"] = 2.8
        logits["PVC"] = 0.5
        logits["PS"] = 0.4
    else:
        if bright_frac > 0.22 and low_sat_frac > 0.35:
            logits["PET"] += 2.2
            logits["PS"] += 0.7
        if float(luminance.mean()) > 0.45 and low_sat_frac > 0.3 and mean_b >= mean_r:
            logits["HDPE"] += 1.8
        if mean_r > mean_b + 0.05 and mid_sat_frac > 0.2:
            logits["PP"] += 1.6
        if texture > 0.045 and 0.25 < float(luminance.mean()) < 0.7:
            logits["LDPE"] += 1.5
        if mean_g > mean_r and mean_g > mean_b:
            logits["PVC"] += 0.9
        if bright_frac > 0.3 and texture > 0.04:
            logits["PS"] += 1.2
        logits["OTHER"] += 0.3

    probs = _softmax(logits)
    material = max(probs, key=probs.get)
    return {
        "material": material,
        "confidence": float(probs[material]),
        "probs": probs,
        "dark_frac": dark_frac,
        "empty": empty,
    }


def latest_live_frame() -> bytes | None:
    """Return the in-memory JPEG only if the camera is still posting frames."""
    if _latest_frame is None or _last_frame_time is None:
        return None
    if time.time() - _last_frame_time > CAMERA_STALE_SECONDS:
        return None
    return _latest_frame


def fuse_nir_and_image(nir_classes, nir_proba) -> tuple[str, float, str, dict | None]:
    """Combine NIR class probabilities with the current camera frame.

    NIR stays dominant when the image is missing, empty, or low-contrast.
    Vision gets more weight on very dark objects (typical NIR failure).
    Conflicting recyclable vs reject calls are resolved conservatively.
    """
    nir_probs = {name: 0.0 for name in MATERIAL_CLASSES}
    for cls, probability in zip(nir_classes, nir_proba):
        key = str(cls)
        if key in nir_probs:
            nir_probs[key] = float(probability)
    total = sum(nir_probs.values())
    if total > 0:
        nir_probs = {key: value / total for key, value in nir_probs.items()}

    nir_material = max(nir_probs, key=nir_probs.get)
    frame = latest_live_frame()
    image_result = classify_camera_frame(frame) if frame else None

    if image_result is None:
        return nir_material, float(nir_probs[nir_material]), "nir", None

    img_probs = {name: float(image_result["probs"].get(name, 0.0)) for name in MATERIAL_CLASSES}
    nir_weight = 0.72
    if image_result["empty"]:
        nir_weight = 0.9
    elif image_result["dark_frac"] > 0.42:
        nir_weight = 0.28
    elif image_result["material"] == nir_material:
        nir_weight = 0.62

    fused = {
        name: nir_weight * nir_probs[name] + (1.0 - nir_weight) * img_probs[name]
        for name in MATERIAL_CLASSES
    }
    fused_total = sum(fused.values()) or 1.0
    fused = {name: value / fused_total for name, value in fused.items()}
    material = max(fused, key=fused.get)
    confidence = float(fused[material])

    nir_recyclable = MATERIAL_INFO.get(nir_material, {}).get("recyclable", False)
    img_recyclable = MATERIAL_INFO.get(image_result["material"], {}).get("recyclable", False)
    if (
        nir_material != image_result["material"]
        and nir_probs[nir_material] >= 0.45
        and image_result["confidence"] >= 0.35
        and nir_recyclable != img_recyclable
    ):
        if not nir_recyclable:
            material = nir_material
            confidence = min(confidence, nir_probs[nir_material])
        else:
            material = image_result["material"]
            confidence = min(confidence, image_result["confidence"])
        confidence *= 0.85

    if image_result["dark_frac"] > 0.5 and MATERIAL_INFO.get(material, {}).get("recyclable"):
        material = "OTHER"
        confidence = max(float(fused["OTHER"]), 0.55)

    return material, float(confidence), "nir+image", image_result


# ---------------------------------------------------------------------------
# NIR + image scan — same /nir-scan contract as before. The ESP32 still
# POSTs only spectral channels; the latest camera JPEG is fused server-side.
# ---------------------------------------------------------------------------

# Feature order the model was trained on (see train_nir_classifier.py /
# merge_csvs.py). The ESP32/serial_logger.py MUST send nir_reading values
# in exactly this order — the model has no column names at inference time,
# only positions.
NIR_FEATURE_ORDER = ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8",
                      "FZ", "FY", "FXL", "NIR", "Clear"]
NIR_EXPECTED_CHANNELS = len(NIR_FEATURE_ORDER)  # 13 — AS7343 8 spectral + FZ/FY/FXL + NIR + Clear

NIR_MODEL_PATH = ARTIFACTS_DIR / "nir_classifier.pkl"
nir_model = None
latest_nir_reading: list[float] | None = None
if joblib is not None:
    try:
        nir_model = joblib.load(NIR_MODEL_PATH)
        logger.info(f"Loaded NIR classifier from {NIR_MODEL_PATH}")
    except Exception as e:
        logger.warning(f"Could not load {NIR_MODEL_PATH} yet: {e}")


@app.post("/nir-scan")
async def nir_scan(payload: dict):
    global latest_nir_reading

    """
    Expected payload:
    {
        "nir_reading": [F1, F2, F3, F4, F5, F6, F7, F8, FZ, FY, FXL, NIR, Clear],  # 13 values, in this exact order
        "timestamp": "2026-07-19T15:22:05"   # optional
    }

    The ESP32 may alternatively send the 13 readings as named fields, using
    the same names as the training CSV (F1 through Clear). A CSV `Label`
    field, if present, is ignored because the sensor does not know the class.
    """
    if nir_model is None:
        return {"error": "NIR classifier not trained/loaded yet. See nir_readings.csv workflow."}

    readings = payload.get("nir_reading")
    if readings is None:
        try:
            readings = [payload[channel] for channel in NIR_FEATURE_ORDER]
        except KeyError as e:
            return {"error": f"Missing NIR channel: {e.args[0]}. Send all {NIR_EXPECTED_CHANNELS} channels."}

    if not readings or len(readings) != NIR_EXPECTED_CHANNELS:
        return {"error": f"Expected {NIR_EXPECTED_CHANNELS} NIR channel values."}

    if np is None:
        return {"error": "numpy is required for NIR classification."}

    try:
        X = np.asarray(readings, dtype=float).reshape(1, -1)
    except (TypeError, ValueError):
        return {"error": "All NIR channel values must be numeric."}
    if not np.isfinite(X).all():
        return {"error": "NIR channel values must be finite numbers."}

    # Retain the latest sensor sample so the backend status page can show
    # exactly what the ESP32 most recently sent.
    latest_nir_reading = [int(value) if value.is_integer() else float(value) for value in X.flatten()]

    nir_proba = nir_model.predict_proba(X)[0]
    predicted_class, confidence, fusion_source, image_result = fuse_nir_and_image(
        nir_model.classes_, nir_proba
    )
    predicted_class = str(predicted_class)

    info = MATERIAL_INFO.get(predicted_class, {"recyclable": False, "reason": "Unknown material."})
    route = "LEFT" if info["recyclable"] else "RIGHT"

    reason = info["reason"]
    nir_guess = str(nir_model.classes_[int(nir_proba.argmax())])
    nir_conf_pct = round(float(max(nir_proba)) * 100, 1)
    if image_result is None:
        reason = f"{reason} Camera unavailable or stale — NIR-only decision ({nir_guess} {nir_conf_pct}%)."
    else:
        img_conf_pct = round(image_result["confidence"] * 100, 1)
        reason = (
            f"{reason} Fused NIR ({nir_guess} {nir_conf_pct}%) with camera "
            f"({image_result['material']} {img_conf_pct}%)."
        )

    result = {
        "material": predicted_class,
        "confidence": round(confidence * 100, 1),
        "recyclable": info["recyclable"],
        "reason": reason,
        "route": route,
        "timestamp": payload.get("timestamp", datetime.utcnow().isoformat()),
        "source": fusion_source,
        "nir_material": nir_guess,
        "image_material": None if image_result is None else image_result["material"],
    }

    logger.info(f"NIR scan result: {result}")
    await broadcast_result(result)

    return {"route": route, "material": predicted_class, "confidence": result["confidence"]}


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
        # `model_loaded` remains for the dashboard's existing status display.
        # Sorting fuses the NIR model with the latest camera frame when live.
        "model_loaded": nir_model is not None,
        "nir_model_loaded": nir_model is not None,
        "image_fusion_ready": Image is not None and np is not None,
        "nir_expected_channels": NIR_EXPECTED_CHANNELS,
        "latest_nir_reading": latest_nir_reading,
        "connected_dashboards": len(connected_clients),
        "camera_connected": _latest_frame is not None,
    }
