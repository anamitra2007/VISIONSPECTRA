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
"""

import asyncio
import base64
import io
import logging
import os
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
# Core scan endpoint — this is what the ESP32 calls
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

    # Run YOLO classification
    results = model(image, verbose=False)
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
_frame_event = asyncio.Event()


@app.post("/camera/upload")
async def camera_upload(request: Request, x_api_key: str | None = Header(default=None)):
    """The ESP32-CAM POSTs one raw JPEG frame (as the request body) here,
    over and over, as fast as it can capture them."""
    if CAMERA_API_KEY and x_api_key != CAMERA_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Api-Key header.")

    global _latest_frame
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty request body — expected a JPEG image.")

    _latest_frame = body
    _frame_event.set()
    _frame_event.clear()
    return {"ok": True, "bytes": len(body)}


@app.get("/camera/stream")
async def camera_stream():
    """Re-serves the latest uploaded frame(s) as a multipart/x-mixed-replace
    MJPEG stream, which browsers render natively inside a plain <img> tag."""

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


@app.get("/camera/latest.jpg")
async def camera_latest():
    """Single-frame snapshot fallback — handy for testing with curl/browser,
    or for clients that can't render MJPEG."""
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
        "connected_dashboards": len(connected_clients),
        "camera_connected": _latest_frame is not None,
    }