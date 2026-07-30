// ---------------------------------------------------------------------------
// Tailwind config. Must execute before Tailwind's Play CDN scans the DOM,
// so this file is loaded via <script src="script.js"> right after the CDN
// <script> tag in <head> (no "defer"/"async").
// ---------------------------------------------------------------------------
tailwind.config = {
    darkMode: "class",
    theme: {
        extend: {
            colors: {
                "surface-tint": "#adc6ff",
                "primary-fixed": "#d8e2ff",
                "on-secondary-fixed": "#2a1700",
                "surface-dim": "#0d1322",
                "surface-variant": "#2f3445",
                "on-tertiary-fixed-variant": "#723600",
                "on-secondary-fixed-variant": "#653e00",
                "on-surface": "#dde2f8",
                "on-primary": "#002e6a",
                "on-secondary-container": "#5b3800",
                "primary-fixed-dim": "#adc6ff",
                "error-container": "#93000a",
                "on-secondary": "#472a00",
                "on-primary-fixed-variant": "#004395",
                "on-error-container": "#ffdad6",
                "on-tertiary-container": "#461f00",
                "on-background": "#dde2f8",
                "surface-container-high": "#242a3a",
                "inverse-primary": "#005ac2",
                "on-tertiary-fixed": "#311400",
                "tertiary-fixed-dim": "#ffb786",
                "tertiary-fixed": "#ffdcc6",
                "surface-container-low": "#151b2b",
                "primary-container": "#4d8eff",
                tertiary: "#ffb786",
                "secondary-container": "#ee9800",
                outline: "#8c909f",
                "on-tertiary": "#502400",
                "outline-variant": "#424754",
                "surface-container-highest": "#2f3445",
                "inverse-surface": "#dde2f8",
                "on-primary-fixed": "#001a42",
                "on-surface-variant": "#c2c6d6",
                "on-error": "#690005",
                primary: "#adc6ff",
                error: "#ffb4ab",
                background: "#0d1322",
                "surface-bright": "#33394a",
                "surface-container-lowest": "#080e1d",
                "secondary-fixed": "#ffddb8",
                surface: "#0d1322",
                "surface-container": "#191f2f",
                "tertiary-container": "#df7412",
                "on-primary-container": "#00285d",
                "inverse-on-surface": "#2a3040",
                "secondary-fixed-dim": "#ffb95f",
                secondary: "#ffb95f",
            },
            borderRadius: {
                DEFAULT: "0.25rem",
                lg: "0.5rem",
                xl: "0.75rem",
                full: "9999px",
            },
            spacing: {
                base: "8px",
                "stack-md": "24px",
                "stack-sm": "12px",
                "stack-lg": "48px",
                "card-padding": "24px",
                gutter: "16px",
                "container-margin": "24px",
            },
            fontFamily: {
                "label-caps": ["Space Grotesk"],
                "body-lg": ["Inter"],
                "headline-md": ["Space Grotesk"],
                "headline-lg-mobile": ["Space Grotesk"],
                "body-md": ["Inter"],
                "headline-lg": ["Space Grotesk"],
                "headline-xl": ["Space Grotesk"],
                "mono-data": ["Inter"],
            },
            fontSize: {
                "label-caps": ["12px", { lineHeight: "1", letterSpacing: "0.1em", fontWeight: "700" }],
                "body-lg": ["18px", { lineHeight: "1.6", fontWeight: "400" }],
                "headline-md": ["20px", { lineHeight: "1.4", fontWeight: "500" }],
                "headline-lg-mobile": ["24px", { lineHeight: "1.2", fontWeight: "600" }],
                "body-md": ["16px", { lineHeight: "1.5", fontWeight: "400" }],
                "headline-lg": ["32px", { lineHeight: "1.2", letterSpacing: "-0.01em", fontWeight: "600" }],
                "headline-xl": ["48px", { lineHeight: "1.1", letterSpacing: "-0.02em", fontWeight: "700" }],
                "mono-data": ["14px", { lineHeight: "1", letterSpacing: "0.05em", fontWeight: "500" }],
            },
        },
    },
};


// ---------------------------------------------------------------------------
// Dashboard — live backend connection
// ---------------------------------------------------------------------------
(function () {
    "use strict";

    // Change this if the backend runs on a different machine/IP than the
    // one opening this page (e.g. "ws://192.168.1.42:8000/ws"). Mutable —
    // the Settings page can point this at a different backend at runtime.
    let BACKEND_WS_URL = "wss://visionspectra.onrender.com/ws";
    const RECONNECT_DELAY_MS = 3000;

    // Derives the plain HTTP origin from the WS URL, for the Settings
    // page's health-check fetch (main.py's GET / endpoint) and for the
    // ESP32-CAM stream, which is proxied through the same backend so it
    // works over the public internet (see main.py additions: GET /camera/stream).
    function backendHttpUrl() {
        return BACKEND_WS_URL.replace(/^ws/, "http").replace(/\/ws\/?$/, "/");
    }

    // Path on the backend that serves the ESP32-CAM's live MJPEG stream.
    // The ESP32-CAM itself is never contacted directly by the browser —
    // it pushes frames to the backend, and the backend re-streams them.
    // This is what makes the camera reachable over the internet even
    // though the ESP32-CAM sits behind your home router/NAT.
    const CAMERA_STREAM_PATH = "camera/stream";

    function cameraStreamUrl() {
        return backendHttpUrl() + CAMERA_STREAM_PATH;
    }

    // ------------------------------------------------------------------
    // Support modal — team roster + complaint form (sent via EmailJS).
    // ------------------------------------------------------------------

    // TODO: fill in real values. Names below are placeholders except
    // Anamitra Laha's — replace email/role for everyone as needed.
    const TEAM_MEMBERS = [
        { name: "Anamitra Laha", email: "anamitra.laha2007@gmail.com", role: "Add role here" },
        { name: "Rupam Sasmal", email: "sasmalrupam2417@gmail.com", role: "Add role here" },
        { name: "Biswajit Dey", email: "deybiswajit2005@gmail.com", role: "Add role here" },
        { name: "Pratyush Chakarborty", email: "pratyushchak06@gmail.com", role: "Add role here" },
    ];

    // TODO: replace with your real EmailJS Service ID, Template ID, and
    // Public Key from https://dashboard.emailjs.com/admin — the form will
    // show a clear error instead of silently failing until these are set.
    // Your template should reference: {{from_name}}, {{from_email}},
    // {{message}}, {{to_email}}, {{time}}.
    const EMAILJS_CONFIG = {
        SERVICE_ID: "service_i0zlalq",
        TEMPLATE_ID:"template_nl1cjuc",
        PUBLIC_KEY: "1VfqYsBhgKaKPDWBT",
        TO_EMAIL: "anamitra.laha2007@gmail.com",
    };

    // Cosmetic/display info per material class. The backend only sends
    // { material, confidence, recyclable, reason, route, timestamp } —
    // everything below (description text, chart shape, item color, icon)
    // is presentation-only and keyed off the material name it returns.
    const MATERIAL_DISPLAY = {
        HDPE: {
            desc: "High-density polyethylene detected. Suitable for mechanical recycling. Material consistency matches industrial-grade detergent container standards.",
            analysis: "Opaque bottle, consistent density reading.",
            properties: "Opaque, Rigid",
            carbonOffset: "+1.2kg CO2e",
            peakLabel: "1420nm",
            peakPos: { cx: 80, cy: 10 },
            path: "M0 60 Q 10 20, 20 50 T 40 40 T 60 70 T 80 10 T 100 80",
            itemColor: "linear-gradient(160deg, #e7ecff 0%, #adc6ff 55%, #7ba2f0 100%)",
            icon: "recycling",
        },
        PET: {
            desc: "Clear polymer signature detected. Consistent with beverage-grade bottle stock and high recyclability value.",
            analysis: "Clear bottle, slight contamination.",
            properties: "Transparent, Semi-rigid",
            carbonOffset: "+0.9kg CO2e",
            peakLabel: "1660nm",
            peakPos: { cx: 62, cy: 24 },
            path: "M0 40 Q 12 70, 24 30 T 46 55 T 68 20 T 84 65 T 100 35",
            itemColor: "linear-gradient(160deg, #f2f6ff 0%, #cfe0ff 60%, #9fc0ff 100%)",
            icon: "local_drink",
        },
        PP: {
            desc: "Polypropylene signature identified. High heat resistance profile detected in the NIR band.",
            analysis: "Opaque food container.",
            properties: "Opaque, Flexible",
            carbonOffset: "+0.7kg CO2e",
            peakLabel: "1210nm",
            peakPos: { cx: 38, cy: 68 },
            path: "M0 50 Q 14 25, 26 60 T 48 35 T 66 58 T 82 30 T 100 55",
            itemColor: "linear-gradient(160deg, #fff2df 0%, #ffd9a3 55%, #ffb95f 100%)",
            icon: "package_2",
        },
        LDPE: {
            desc: "Low-density polyethylene signature detected. Flexible film-grade material — not economical to reprocess at most facilities.",
            analysis: "Flexible film / bag material.",
            properties: "Flexible, Translucent",
            carbonOffset: null,
            peakLabel: "1155nm",
            peakPos: { cx: 30, cy: 55 },
            path: "M0 55 Q 10 35, 22 58 T 44 45 T 64 60 T 82 40 T 100 58",
            itemColor: "linear-gradient(160deg, #f5f7ff 0%, #dfe6f5 55%, #b9c3d6 100%)",
            icon: "package_2",
        },
        PVC: {
            desc: "Chlorinated polymer signature detected. Releases toxins under reprocessing — routed for rejection.",
            analysis: "Chlorine signature present.",
            properties: "Rigid, Chlorinated",
            carbonOffset: null,
            peakLabel: "1720nm",
            peakPos: { cx: 90, cy: 20 },
            path: "M0 45 Q 16 60, 28 40 T 50 50 T 70 35 T 88 55 T 100 45",
            itemColor: "linear-gradient(160deg, #fdeeee 0%, #f2b8b8 55%, #d97575 100%)",
            icon: "warning",
        },
        PS: {
            desc: "Polystyrene signature detected. Brittle structure, breaks into microplastics — low recycling value.",
            analysis: "Brittle foam/rigid structure.",
            properties: "Brittle, Low-density",
            carbonOffset: null,
            peakLabel: "1680nm",
            peakPos: { cx: 55, cy: 15 },
            path: "M0 60 Q 14 30, 26 55 T 48 30 T 66 55 T 84 25 T 100 50",
            itemColor: "linear-gradient(160deg, #f7f7f7 0%, #dcdcdc 55%, #b0b0b0 100%)",
            icon: "delete_forever",
        },
        OTHER: {
            desc: "Spectral response does not converge on a known polymer class. Possible multi-layer laminate or mixed composite.",
            analysis: "Multi-layer laminate detected.",
            properties: "Composite, Unclassified",
            carbonOffset: null,
            peakLabel: "\u2014",
            peakPos: null,
            path: "M0 50 Q 12 46, 24 52 T 48 48 T 66 52 T 84 47 T 100 51",
            itemColor: "linear-gradient(160deg, #4a4f5c 0%, #33394a 60%, #23283a 100%)",
            icon: "delete_forever",
        },
    };

    // NOTE: this file is loaded in <head> (needed so the tailwind.config
    // above runs before Tailwind's CDN script scans the page), which means
    // it executes before <body> exists. So `els` must be populated inside
    // init() (after DOMContentLoaded), not up here at parse time — querying
    // getElementById this early would just return null for everything.
    let els = {};

    function collectEls() {
        els = {
            bboxLabel: document.getElementById("bboxLabel"),
            conveyorItem: document.getElementById("conveyorItem"),
            conveyorScene: document.getElementById("conveyorScene"),
            camStreamImg: document.getElementById("camStreamImg"),
            camStatusBadge: document.getElementById("camStatusBadge"),
            materialBadge: document.getElementById("materialBadge"),
            materialName: document.getElementById("materialName"),
            materialConfidence: document.getElementById("materialConfidence"),
            materialDesc: document.getElementById("materialDesc"),
            materialProperties: document.getElementById("materialProperties"),
            carbonOffset: document.getElementById("carbonOffset"),
            routeText: document.getElementById("routeText"),
            routeArrowIcon: document.getElementById("routeArrowIcon"),
            routeArrowWrap: document.getElementById("routeArrowWrap"),
            nirBars: document.getElementById("nirBars") ? document.getElementById("nirBars").children : [],
            latencyText: document.getElementById("latencyText"),
            fpsText: document.getElementById("fpsText"),
            spectralLine: document.getElementById("spectralLine"),
            spectralFill: document.getElementById("spectralFill"),
            spectralPeak: document.getElementById("spectralPeak"),
            spectralPeakTitle: document.getElementById("spectralPeakTitle"),
            servoAngle: document.getElementById("servoAngle"),
            pneumaticsStatus: document.getElementById("pneumaticsStatus"),
            pressureStatus: document.getElementById("pressureStatus"),
            itemsSortedCount: document.getElementById("itemsSortedCount"),
            recyclablePct: document.getElementById("recyclablePct"),
            modelAccuracy: document.getElementById("modelAccuracy"),
            historyTableBody: document.getElementById("historyTableBody"),
            exportDataBtn: document.getElementById("exportDataBtn"),
            viewFullLogBtn: document.getElementById("viewFullLogBtn"),
            systemStatusLabel: document.getElementById("systemStatusLabel"),
            headerStatus: document.getElementById("headerStatus"),

            // History page
            historyPageTableBody: document.getElementById("historyPageTableBody"),
            historyEmptyState: document.getElementById("historyEmptyState"),
            historyResultCount: document.getElementById("historyResultCount"),
            historySearchInput: document.getElementById("historySearchInput"),
            historyMaterialFilter: document.getElementById("historyMaterialFilter"),
            historyDecisionFilter: document.getElementById("historyDecisionFilter"),
            historyClearFiltersBtn: document.getElementById("historyClearFiltersBtn"),
            historyExportBtn: document.getElementById("historyExportBtn"),

            // Analytics page
            analyticsSampleSize: document.getElementById("analyticsSampleSize"),
            analyticsAvgConfidence: document.getElementById("analyticsAvgConfidence"),
            analyticsRecycleSplit: document.getElementById("analyticsRecycleSplit"),
            analyticsTopMaterial: document.getElementById("analyticsTopMaterial"),
            materialChartEmpty: document.getElementById("materialChartEmpty"),

            // Settings page
            settingsConnectionBadge: document.getElementById("settingsConnectionBadge"),
            settingsWsUrlInput: document.getElementById("settingsWsUrlInput"),
            settingsReconnectBtn: document.getElementById("settingsReconnectBtn"),
            settingsModelStatus: document.getElementById("settingsModelStatus"),
            settingsDashboardCount: document.getElementById("settingsDashboardCount"),
            settingsHealthStatus: document.getElementById("settingsHealthStatus"),
            settingsRefreshHealthBtn: document.getElementById("settingsRefreshHealthBtn"),
            settingsCollapsedCountInput: document.getElementById("settingsCollapsedCountInput"),
            settingsExportBtn: document.getElementById("settingsExportBtn"),
            settingsClearHistoryBtn: document.getElementById("settingsClearHistoryBtn"),

            // Support modal
            supportOpenBtn: document.getElementById("supportOpenBtn"),
            sidebarSupportBtn: document.getElementById("sidebarSupportBtn"),
            supportModalOverlay: document.getElementById("supportModalOverlay"),
            supportModal: document.getElementById("supportModal"),
            supportCloseBtn: document.getElementById("supportCloseBtn"),
            supportTeamGrid: document.getElementById("supportTeamGrid"),
            complaintForm: document.getElementById("complaintForm"),
            complaintName: document.getElementById("complaintName"),
            complaintEmail: document.getElementById("complaintEmail"),
            complaintMessage: document.getElementById("complaintMessage"),
            complaintStatus: document.getElementById("complaintStatus"),
            complaintSubmitBtn: document.getElementById("complaintSubmitBtn"),
            complaintCancelBtn: document.getElementById("complaintCancelBtn"),
        };
    }

    let itemsSortedToday = 14203;
    let historyLog = [];
    let socket = null;
    let reconnectTimer = null;

    function rand(min, max) {
        return Math.random() * (max - min) + min;
    }

    function roundTo(value, decimals) {
        const factor = Math.pow(10, decimals);
        return Math.round(value * factor) / factor;
    }

    function nowStamp() {
        const d = new Date();
        return d.toTimeString().split(" ")[0];
    }

    function formatTimestamp(iso) {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return nowStamp();
        return d.toTimeString().split(" ")[0];
    }

    let HISTORY_COLLAPSED_COUNT = 4;
    let showFullHistory = false;

    function buildHistoryRow(entry) {
        const tr = document.createElement("tr");
        tr.className = "row-enter hover:bg-surface-variant/10 transition-colors";

        const decisionClasses = entry.recyclable
            ? "px-2 py-1 rounded bg-primary/10 text-primary text-xs font-bold border border-primary/20"
            : "px-2 py-1 rounded bg-error/10 text-error text-xs font-bold border border-error/20";

        tr.innerHTML =
            '<td class="p-4 font-mono-data text-mono-data">' + entry.time + "</td>" +
            '<td class="p-4">' +
            '<div class="flex items-center space-x-3">' +
            '<div class="w-8 h-8 rounded bg-surface-container-highest flex items-center justify-center">' +
            '<span class="material-symbols-outlined ' + (entry.recyclable ? "text-primary" : "text-error") + ' text-lg">' + entry.icon + "</span>" +
            "</div>" +
            '<span class="font-body-md font-medium">' + entry.material + "</span>" +
            "</div>" +
            "</td>" +
            '<td class="p-4 ' + (entry.recyclable ? "text-primary" : "text-error") + ' font-mono-data">' + entry.confidence + "%</td>" +
            '<td class="p-4"><span class="' + decisionClasses + '">' + entry.decision + "</span></td>" +
            '<td class="p-4 text-on-surface-variant text-sm">' + entry.analysis + "</td>";

        return tr;
    }

    // Re-draws the whole history table from historyLog — either the
    // 4 most recent rows, or everything, depending on showFullHistory.
    function renderHistoryTable() {
        if (!els.historyTableBody) return;
        els.historyTableBody.innerHTML = "";
        const rows = showFullHistory ? historyLog : historyLog.slice(0, HISTORY_COLLAPSED_COUNT);
        rows.forEach((entry) => els.historyTableBody.appendChild(buildHistoryRow(entry)));

        if (els.viewFullLogBtn) {
            const label = els.viewFullLogBtn.querySelector("span:first-child");
            if (label) label.textContent = showFullHistory ? "Show Recent" : "View Full Log";
        }
    }

    function toggleFullHistory() {
        showFullHistory = !showFullHistory;
        renderHistoryTable();
    }

    // Applies one real scan result (received over the WebSocket) to the UI.
    // `data` shape (sent by main.py's /scan endpoint via broadcast_result):
    //   { material, confidence, recyclable, reason, route, timestamp }
    function applyBackendResult(data) {
        const materialId = (data.material || "OTHER").toUpperCase();
        const display = MATERIAL_DISPLAY[materialId] || MATERIAL_DISPLAY.OTHER;
        const confidence = typeof data.confidence === "number" ? data.confidence : 0;
        const recyclable = !!data.recyclable;
        const route = data.route || "\u2014";
        const arrow = route === "LEFT" ? "west" : route === "RIGHT" ? "east" : "south";

        els.bboxLabel.textContent = materialId + " - " + confidence + "%";
        els.conveyorItem.style.background = display.itemColor;

        els.materialName.textContent = materialId;
        els.materialConfidence.textContent = confidence + "% Confidence";
        els.materialDesc.textContent = data.reason || display.desc;
        els.materialProperties.textContent = "Properties: " + display.properties;

        if (recyclable) {
            els.materialBadge.textContent = "Recyclable";
            els.materialBadge.className =
                "bg-secondary/20 text-secondary border border-secondary/40 px-3 py-1 rounded-full font-label-caps text-label-caps";
            // Note: the carbon-offset element is commented out in index.html
            // right now, so this stays a no-op until that markup is restored.
            if (els.carbonOffset && display.carbonOffset) {
                els.carbonOffset.textContent = "Carbon Offset: " + display.carbonOffset;
                els.carbonOffset.parentElement.style.display = "flex";
            }
        } else {
            els.materialBadge.textContent = "Rejected";
            els.materialBadge.className =
                "bg-error/20 text-error border border-error/40 px-3 py-1 rounded-full font-label-caps text-label-caps";
            if (els.carbonOffset) els.carbonOffset.parentElement.style.display = "none";
        }

        els.routeText.textContent = "Route: " + route;
        els.routeArrowIcon.textContent = arrow;
        els.routeArrowWrap.style.borderColor = recyclable ? "#adc6ff" : "#ffb4ab";
        els.routeArrowIcon.style.color = recyclable ? "#adc6ff" : "#ffb4ab";

        // NIR bars / latency / FPS / servo / pressure: the backend doesn't
        // stream this telemetry yet (no ESP32 attached), so these stay
        // decorative/randomized until real sensor data is wired in.
        for (let i = 0; i < els.nirBars.length; i++) {
            els.nirBars[i].style.height = roundTo(rand(25, 100), 0) + "%";
        }
        els.latencyText.textContent = Math.round(rand(8, 18));
        els.fpsText.textContent = roundTo(rand(28, 60), 1);

        els.spectralLine.style.transition = "opacity 0.25s ease";
        els.spectralFill.style.transition = "opacity 0.25s ease";
        els.spectralLine.style.opacity = "0";
        els.spectralFill.style.opacity = "0";
        setTimeout(() => {
            els.spectralLine.setAttribute("d", display.path);
            els.spectralFill.setAttribute("d", display.path + " L 100 100 L 0 100 Z");
            if (display.peakPos) {
                els.spectralPeak.style.display = "";
                els.spectralPeak.setAttribute("cx", display.peakPos.cx);
                els.spectralPeak.setAttribute("cy", display.peakPos.cy);
                els.spectralPeakTitle.textContent = "Peak identified at " + display.peakLabel;
            } else {
                els.spectralPeak.style.display = "none";
            }
            els.spectralLine.style.opacity = "1";
            els.spectralFill.style.opacity = "1";
        }, 250);

        const angle = roundTo(rand(15, 70), 1);
        els.servoAngle.textContent = angle + "\u00B0 Offset";
        const pressure = roundTo(rand(5.6, 6.8), 1);
        els.pressureStatus.textContent = "PRESSURE " + pressure + " BAR";
        const nominal = pressure >= 5.8 && pressure <= 6.6;
        els.pneumaticsStatus.textContent = nominal ? "PNEUMATICS OK" : "PNEUMATICS WARN";
        els.pneumaticsStatus.className =
            "px-3 py-1 rounded font-label-caps text-[10px] border " +
            (nominal
                ? "bg-green-500/10 text-green-400 border-green-500/30"
                : "bg-error/10 text-error border-error/30");

        // Stats
        itemsSortedToday += 1;
        els.itemsSortedCount.textContent = itemsSortedToday.toLocaleString();

        // History (built from the real scan result)
        const entry = {
            time: data.timestamp ? formatTimestamp(data.timestamp) : nowStamp(),
            material: materialId,
            icon: display.icon,
            confidence: confidence,
            decision: route === "LEFT" ? "SORTED LEFT" : route === "RIGHT" ? "SORTED RIGHT" : "REJECTED",
            analysis: data.reason || display.analysis,
            recyclable: recyclable,
        };
        historyLog.unshift(entry);
        renderHistoryTable();
        renderHistoryPage();
        updateAnalytics();

        const recyclableCount = historyLog.slice(0, 20).filter((h) => h.recyclable).length;
        const total = Math.min(historyLog.length, 20);
        els.recyclablePct.textContent = total ? Math.round((recyclableCount / total) * 100) + "%" : "0%";
    }

    // ------------------------------------------------------------------
    // ESP32-CAM live stream
    // ------------------------------------------------------------------
    // The <img id="camStreamImg"> tag points at the backend's MJPEG
    // endpoint (GET /camera/stream). Browsers render MJPEG streams
    // natively inside an <img> tag — every new JPEG frame the backend
    // writes just replaces the previous one, giving live video with no
    // extra JS needed for the frames themselves.
    //
    // We still need JS for two things:
    //   1. Point the <img> at the *current* backend (it can change via
    //      the Settings page), so we (re)assign .src whenever that
    //      happens rather than hardcoding it in the HTML.
    //   2. Fall back to the decorative CSS conveyor animation, and show
    //      a clear status badge, if the stream can't be reached (camera
    //      not connected yet, backend has no frames, etc).
    let camRetryTimer = null;

    function showCameraFallback(label) {
        if (els.camStreamImg) els.camStreamImg.classList.add("hidden");
        if (els.conveyorScene) els.conveyorScene.classList.remove("hidden");
        if (els.camStatusBadge) els.camStatusBadge.textContent = label || "CAM OFFLINE";
    }

    function showCameraLive() {
        if (els.camStreamImg) els.camStreamImg.classList.remove("hidden");
        if (els.conveyorScene) els.conveyorScene.classList.add("hidden");
        if (els.camStatusBadge) els.camStatusBadge.textContent = "CAM_04_SORTER";
    }

    function startCameraStream() {
        if (!els.camStreamImg) return;
        clearTimeout(camRetryTimer);
        if (els.camStatusBadge) els.camStatusBadge.textContent = "CAM CONNECTING\u2026";

        // Cache-bust so switching backend URLs (Settings page) or retrying
        // after an error doesn't just reuse a cached broken image.
        els.camStreamImg.src = cameraStreamUrl() + "?t=" + Date.now();
    }

    function wireCameraStream() {
        if (!els.camStreamImg) return;

        els.camStreamImg.addEventListener("load", showCameraLive);
        els.camStreamImg.addEventListener("error", () => {
            showCameraFallback("CAM OFFLINE \u2014 retrying\u2026");
            // MJPEG <img> streams fire "error" once if the connection
            // drops (backend restarted, camera disconnected, network
            // hiccup). Retry every few seconds rather than giving up.
            clearTimeout(camRetryTimer);
            camRetryTimer = setTimeout(startCameraStream, RECONNECT_DELAY_MS);
        });

        startCameraStream();
    }

    // ------------------------------------------------------------------
    // WebSocket connection to the FastAPI backend (main.py's /ws route)
    // ------------------------------------------------------------------
    function setConnectionStatus(connected) {
        if (els.systemStatusLabel) {
            els.systemStatusLabel.textContent = connected ? "Scanning Active" : "Disconnected \u2014 retrying...";
        }
        if (els.headerStatus) {
            els.headerStatus.textContent = connected ? "SCANNING" : "OFFLINE";
        }
        updateSettingsConnectionBadge(connected);
    }

    function connectWebSocket() {
        socket = new WebSocket(BACKEND_WS_URL);

        socket.onopen = () => {
            clearTimeout(reconnectTimer);
            setConnectionStatus(true);
        };

        socket.onmessage = (event) => {
            let data;
            try {
                data = JSON.parse(event.data);
            } catch (e) {
                console.error("SpectraLink: could not parse message from backend", event.data);
                return;
            }
            applyBackendResult(data);
        };

        socket.onclose = () => {
            setConnectionStatus(false);
            reconnectTimer = setTimeout(connectWebSocket, RECONNECT_DELAY_MS);
        };

        socket.onerror = () => {
            // onclose will fire right after this and handle the retry.
            socket.close();
        };
    }

    function exportHistoryAsCsv() {
        const header = ["Timestamp", "Material", "Confidence", "Decision", "Analysis"];
        const rows = historyLog.map((h) => [h.time, h.material, h.confidence + "%", h.decision, h.analysis]);
        const csv = [header, ...rows]
            .map((row) => row.map((cell) => '"' + String(cell).replace(/"/g, '""') + '"').join(","))
            .join("\r\n");

        const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "spectralink-sort-history-" + Date.now() + ".csv";
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    }

    // ------------------------------------------------------------------
    // History page — full, filterable log (separate from the Dashboard's
    // collapsed 4-row preview table).
    // ------------------------------------------------------------------
    function getFilteredHistory() {
        const query = (els.historySearchInput && els.historySearchInput.value || "").trim().toLowerCase();
        const materialFilter = els.historyMaterialFilter ? els.historyMaterialFilter.value : "ALL";
        const decisionFilter = els.historyDecisionFilter ? els.historyDecisionFilter.value : "ALL";

        return historyLog.filter((entry) => {
            if (materialFilter !== "ALL" && entry.material !== materialFilter) return false;
            if (decisionFilter === "RECYCLABLE" && !entry.recyclable) return false;
            if (decisionFilter === "REJECTED" && entry.recyclable) return false;
            if (query) {
                const haystack = (entry.material + " " + entry.analysis + " " + entry.decision).toLowerCase();
                if (haystack.indexOf(query) === -1) return false;
            }
            return true;
        });
    }

    function renderHistoryPage() {
        if (!els.historyPageTableBody) return;
        const rows = getFilteredHistory();

        els.historyPageTableBody.innerHTML = "";
        rows.forEach((entry) => els.historyPageTableBody.appendChild(buildHistoryRow(entry)));

        if (els.historyResultCount) {
            els.historyResultCount.textContent = rows.length + (rows.length === 1 ? " result" : " results");
        }
        if (els.historyEmptyState) {
            els.historyEmptyState.style.display = rows.length ? "none" : "";
        }
    }

    function wireHistoryPage() {
        [els.historySearchInput, els.historyMaterialFilter, els.historyDecisionFilter].forEach((el) => {
            if (!el) return;
            const evt = el.tagName === "SELECT" ? "change" : "input";
            el.addEventListener(evt, renderHistoryPage);
        });
        if (els.historyClearFiltersBtn) {
            els.historyClearFiltersBtn.addEventListener("click", () => {
                if (els.historySearchInput) els.historySearchInput.value = "";
                if (els.historyMaterialFilter) els.historyMaterialFilter.value = "ALL";
                if (els.historyDecisionFilter) els.historyDecisionFilter.value = "ALL";
                renderHistoryPage();
            });
        }
        if (els.historyExportBtn) {
            els.historyExportBtn.addEventListener("click", exportHistoryAsCsv);
        }
    }

    // ------------------------------------------------------------------
    // Analytics page — Chart.js visualizations driven by historyLog.
    // Charts are created lazily the first time the Analytics tab is
    // opened (canvases inside a `hidden` / display:none section report
    // zero size, so creating them earlier would render blank).
    // ------------------------------------------------------------------
    const MATERIAL_CHART_COLORS = {
        PET: "#9fc0ff",
        HDPE: "#adc6ff",
        PP: "#ffb95f",
        LDPE: "#b9c3d6",
        PVC: "#d97575",
        PS: "#b0b0b0",
        OTHER: "#4a4f5c",
    };

    let charts = {
        material: null,
        decision: null,
        confidence: null,
        confidenceByMaterial: null,
    };
    let chartsInitialized = false;

    function initCharts() {
        if (chartsInitialized || typeof Chart === "undefined") return;
        chartsInitialized = true;

        const gridColor = "rgba(226, 232, 240, 0.08)";
        const tickColor = "#c2c6d6";
        Chart.defaults.color = tickColor;
        Chart.defaults.font.family = "Inter";

        const materialCanvas = document.getElementById("materialDoughnutChart");
        if (materialCanvas) {
            charts.material = new Chart(materialCanvas, {
                type: "doughnut",
                data: { labels: [], datasets: [{ data: [], backgroundColor: [], borderWidth: 0 }] },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { position: "bottom", labels: { boxWidth: 12, padding: 16 } } },
                },
            });
        }

        const decisionCanvas = document.getElementById("decisionBarChart");
        if (decisionCanvas) {
            charts.decision = new Chart(decisionCanvas, {
                type: "bar",
                data: {
                    labels: ["Recyclable", "Rejected"],
                    datasets: [{ data: [0, 0], backgroundColor: ["#adc6ff", "#ffb4ab"], borderRadius: 6 }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: gridColor } },
                        x: { grid: { display: false } },
                    },
                },
            });
        }

        const confidenceCanvas = document.getElementById("confidenceLineChart");
        if (confidenceCanvas) {
            charts.confidence = new Chart(confidenceCanvas, {
                type: "line",
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: "Confidence %",
                            data: [],
                            borderColor: "#adc6ff",
                            backgroundColor: "rgba(173, 198, 255, 0.15)",
                            fill: true,
                            tension: 0.35,
                            pointRadius: 2,
                            borderWidth: 2,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { min: 0, max: 100, grid: { color: gridColor } },
                        x: { grid: { display: false } },
                    },
                },
            });
        }

        const byMaterialCanvas = document.getElementById("confidenceByMaterialChart");
        if (byMaterialCanvas) {
            charts.confidenceByMaterial = new Chart(byMaterialCanvas, {
                type: "bar",
                data: { labels: [], datasets: [{ label: "Avg. Confidence %", data: [], backgroundColor: [], borderRadius: 6 }] },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    indexAxis: "y",
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { min: 0, max: 100, grid: { color: gridColor } },
                        y: { grid: { display: false } },
                    },
                },
            });
        }

        updateAnalytics();
    }

    function updateAnalytics() {
        if (!chartsInitialized) return; // nothing to draw into yet

        const total = historyLog.length;
        if (els.analyticsSampleSize) {
            els.analyticsSampleSize.textContent = total + (total === 1 ? " scan this session" : " scans this session");
        }

        if (els.materialChartEmpty) {
            els.materialChartEmpty.style.display = total ? "none" : "";
        }

        // Material composition
        const counts = {};
        let confidenceSum = 0;
        let recyclableCount = 0;
        const confidenceByMaterial = {};

        historyLog.forEach((entry) => {
            counts[entry.material] = (counts[entry.material] || 0) + 1;
            confidenceSum += entry.confidence || 0;
            if (entry.recyclable) recyclableCount += 1;

            if (!confidenceByMaterial[entry.material]) confidenceByMaterial[entry.material] = [];
            confidenceByMaterial[entry.material].push(entry.confidence || 0);
        });

        const materials = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);

        if (charts.material) {
            charts.material.data.labels = materials;
            charts.material.data.datasets[0].data = materials.map((m) => counts[m]);
            charts.material.data.datasets[0].backgroundColor = materials.map((m) => MATERIAL_CHART_COLORS[m] || "#8c909f");
            charts.material.update();
        }

        if (charts.decision) {
            charts.decision.data.datasets[0].data = [recyclableCount, total - recyclableCount];
            charts.decision.update();
        }

        if (charts.confidence) {
            const recent = historyLog.slice(0, 20).slice().reverse(); // oldest -> newest, most recent 20
            charts.confidence.data.labels = recent.map((e) => e.time);
            charts.confidence.data.datasets[0].data = recent.map((e) => e.confidence);
            charts.confidence.update();
        }

        if (charts.confidenceByMaterial) {
            charts.confidenceByMaterial.data.labels = materials;
            charts.confidenceByMaterial.data.datasets[0].data = materials.map((m) => {
                const vals = confidenceByMaterial[m];
                return roundTo(vals.reduce((a, b) => a + b, 0) / vals.length, 1);
            });
            charts.confidenceByMaterial.data.datasets[0].backgroundColor = materials.map((m) => MATERIAL_CHART_COLORS[m] || "#8c909f");
            charts.confidenceByMaterial.update();
        }

        // Summary stat cards
        if (els.analyticsAvgConfidence) {
            els.analyticsAvgConfidence.textContent = total ? roundTo(confidenceSum / total, 1) + "%" : "\u2014";
        }
        if (els.analyticsRecycleSplit) {
            els.analyticsRecycleSplit.textContent = total ? recyclableCount + " / " + (total - recyclableCount) : "\u2014";
        }
        if (els.analyticsTopMaterial) {
            els.analyticsTopMaterial.textContent = materials.length ? materials[0] : "\u2014";
        }
    }

    // ------------------------------------------------------------------
    // Settings page
    // ------------------------------------------------------------------
    function updateSettingsConnectionBadge(connected) {
        if (!els.settingsConnectionBadge) return;
        els.settingsConnectionBadge.textContent = connected ? "Connected" : "Disconnected";
        els.settingsConnectionBadge.className = connected
            ? "px-3 py-1 rounded-full font-label-caps text-label-caps border bg-primary/10 text-primary border-primary/30"
            : "px-3 py-1 rounded-full font-label-caps text-label-caps border bg-error/10 text-error border-error/30";
    }

    function reconnectWithUrl(newUrl) {
        const trimmed = (newUrl || "").trim();
        if (!trimmed) return;
        BACKEND_WS_URL = trimmed;
        clearTimeout(reconnectTimer);
        if (socket) {
            // Prevent the old socket's onclose from scheduling a duplicate
            // reconnect against the URL we're replacing.
            socket.onclose = null;
            socket.onerror = null;
            socket.close();
        }
        setConnectionStatus(false);
        connectWebSocket();
        // The camera stream lives on the same backend, so re-point it too.
        startCameraStream();
    }

    function refreshBackendHealth() {
        if (els.settingsHealthStatus) els.settingsHealthStatus.textContent = "Checking\u2026";
        fetch(backendHttpUrl())
            .then((res) => res.json())
            .then((data) => {
                if (els.settingsHealthStatus) els.settingsHealthStatus.textContent = data.status || "OK";
                if (els.settingsModelStatus) {
                    els.settingsModelStatus.textContent = data.model_loaded ? "Loaded" : "Not loaded";
                }
                if (els.settingsDashboardCount) {
                    els.settingsDashboardCount.textContent =
                        typeof data.connected_dashboards === "number" ? String(data.connected_dashboards) : "\u2014";
                }
            })
            .catch(() => {
                if (els.settingsHealthStatus) els.settingsHealthStatus.textContent = "Unreachable";
                if (els.settingsModelStatus) els.settingsModelStatus.textContent = "\u2014";
                if (els.settingsDashboardCount) els.settingsDashboardCount.textContent = "\u2014";
            });
    }

    function wireSettingsPage() {
        if (els.settingsWsUrlInput) els.settingsWsUrlInput.value = BACKEND_WS_URL;

        if (els.settingsReconnectBtn) {
            els.settingsReconnectBtn.addEventListener("click", () => {
                reconnectWithUrl(els.settingsWsUrlInput ? els.settingsWsUrlInput.value : BACKEND_WS_URL);
            });
        }
        if (els.settingsRefreshHealthBtn) {
            els.settingsRefreshHealthBtn.addEventListener("click", refreshBackendHealth);
        }
        if (els.settingsCollapsedCountInput) {
            els.settingsCollapsedCountInput.value = HISTORY_COLLAPSED_COUNT;
            els.settingsCollapsedCountInput.addEventListener("change", () => {
                const val = parseInt(els.settingsCollapsedCountInput.value, 10);
                if (!isNaN(val) && val > 0) {
                    HISTORY_COLLAPSED_COUNT = val;
                    renderHistoryTable();
                }
            });
        }
        if (els.settingsExportBtn) {
            els.settingsExportBtn.addEventListener("click", exportHistoryAsCsv);
        }
        if (els.settingsClearHistoryBtn) {
            els.settingsClearHistoryBtn.addEventListener("click", () => {
                if (!confirm("Clear all sort history for this session? This cannot be undone.")) return;
                historyLog = [];
                renderHistoryTable();
                renderHistoryPage();
                updateAnalytics();
            });
        }
    }

    // ------------------------------------------------------------------
    // Support modal
    // ------------------------------------------------------------------
    function buildTeamCard(member) {
        const div = document.createElement("div");
        div.className = "glass-panel rounded-lg p-4 flex items-start space-x-3";
        div.innerHTML =
            '<div class="avatar-badge flex-shrink-0">' +
            (member.name || "?").split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase() +
            "</div>" +
            '<div class="min-w-0 flex-1">' +
            '<p class="font-body-md font-semibold text-on-surface truncate">' + escapeHtml(member.name) + "</p>" +
            '<p class="font-label-caps text-label-caps text-primary uppercase mt-0.5">' + escapeHtml(member.role) + "</p>" +
            '<p class="font-mono-data text-on-surface-variant break-all mt-1.5 text-[15px] leading-snug">' + escapeHtml(member.email) + "</p>" +
            "</div>";
        return div;
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = String(str == null ? "" : str);
        return div.innerHTML;
    }

    function renderTeamCards() {
        if (!els.supportTeamGrid) return;
        els.supportTeamGrid.innerHTML = "";
        TEAM_MEMBERS.forEach((member) => els.supportTeamGrid.appendChild(buildTeamCard(member)));
    }

    let supportModalPreviouslyFocused = null;

    function openSupportModal() {
        if (!els.supportModalOverlay) return;
        supportModalPreviouslyFocused = document.activeElement;
        els.supportModalOverlay.style.display = "flex";
        document.body.style.overflow = "hidden";
        setComplaintStatus(null);
        if (els.complaintName) els.complaintName.focus();
    }

    function closeSupportModal() {
        if (!els.supportModalOverlay) return;
        els.supportModalOverlay.style.display = "none";
        document.body.style.overflow = "";
        if (supportModalPreviouslyFocused && supportModalPreviouslyFocused.focus) {
            supportModalPreviouslyFocused.focus();
        }
    }

    function setComplaintStatus(kind, text) {
        if (!els.complaintStatus) return;
        if (!kind) {
            els.complaintStatus.classList.add("hidden");
            els.complaintStatus.textContent = "";
            return;
        }
        const styles = {
            sending: "bg-surface-container-highest text-on-surface-variant border border-outline-variant/30",
            success: "bg-primary/10 text-primary border border-primary/30",
            error: "bg-error/10 text-error border border-error/30",
        };
        els.complaintStatus.className = "font-body-md text-sm rounded-lg px-4 py-3 " + (styles[kind] || styles.error);
        els.complaintStatus.textContent = text;
        els.complaintStatus.classList.remove("hidden");
    }

    function emailjsConfigured() {
        return (
            EMAILJS_CONFIG.SERVICE_ID !== "YOUR_SERVICE_ID" &&
            EMAILJS_CONFIG.TEMPLATE_ID !== "YOUR_TEMPLATE_ID" &&
            EMAILJS_CONFIG.PUBLIC_KEY !== "YOUR_PUBLIC_KEY"
        );
    }

    function handleComplaintSubmit(event) {
        event.preventDefault();
        if (!els.complaintForm.reportValidity()) return;

        if (typeof emailjs === "undefined") {
            setComplaintStatus("error", "Could not load the email service (EmailJS script blocked or offline).");
            return;
        }
        if (!emailjsConfigured()) {
            setComplaintStatus(
                "error",
                "Email sending isn't configured yet \u2014 add your EmailJS Service ID, Template ID, and Public Key in script.js (EMAILJS_CONFIG)."
            );
            return;
        }

        const params = {
            from_name: els.complaintName.value.trim(),
            from_email: els.complaintEmail.value.trim(),
            message: els.complaintMessage.value.trim(),
            to_email: EMAILJS_CONFIG.TO_EMAIL,
            time: new Date().toLocaleString(),
        };

        els.complaintSubmitBtn.disabled = true;
        els.complaintSubmitBtn.classList.add("opacity-60", "cursor-not-allowed");
        setComplaintStatus("sending", "Sending your complaint\u2026");

        emailjs
            .send(EMAILJS_CONFIG.SERVICE_ID, EMAILJS_CONFIG.TEMPLATE_ID, params, EMAILJS_CONFIG.PUBLIC_KEY)
            .then(() => {
                setComplaintStatus("success", "Thanks \u2014 your complaint was sent successfully.");
                els.complaintForm.reset();
            })
            .catch((err) => {
                console.error("SpectraLink: EmailJS send failed", err);
                setComplaintStatus("error", "Couldn't send your complaint. Please try again in a moment.");
            })
            .finally(() => {
                els.complaintSubmitBtn.disabled = false;
                els.complaintSubmitBtn.classList.remove("opacity-60", "cursor-not-allowed");
            });
    }

    function wireSupportModal() {
        renderTeamCards();

        if (typeof emailjs !== "undefined" && emailjsConfigured()) {
            emailjs.init(EMAILJS_CONFIG.PUBLIC_KEY);
        }

        if (els.supportOpenBtn) els.supportOpenBtn.addEventListener("click", openSupportModal);
        if (els.sidebarSupportBtn) els.sidebarSupportBtn.addEventListener("click", openSupportModal);
        if (els.supportCloseBtn) els.supportCloseBtn.addEventListener("click", closeSupportModal);
        if (els.complaintCancelBtn) els.complaintCancelBtn.addEventListener("click", closeSupportModal);

        if (els.supportModalOverlay) {
            els.supportModalOverlay.addEventListener("click", (event) => {
                if (event.target === els.supportModalOverlay) closeSupportModal();
            });
        }

        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && els.supportModalOverlay && els.supportModalOverlay.style.display !== "none") {
                closeSupportModal();
            }
        });

        if (els.complaintForm) els.complaintForm.addEventListener("submit", handleComplaintSubmit);
    }

    // ------------------------------------------------------------------
    // Navigation — toggles which <section id="view-*"> is visible and
    // lazily initializes the Analytics charts the first time they're needed.
    // ------------------------------------------------------------------
    function wireNav() {
        const buttons = document.querySelectorAll("#sidebarNav .nav-item");
        const views = {
            dashboard: document.getElementById("view-dashboard"),
            analytics: document.getElementById("view-analytics"),
            history: document.getElementById("view-history"),
            settings: document.getElementById("view-settings"),
        };

        function showView(name) {
            Object.keys(views).forEach((key) => {
                if (!views[key]) return;
                views[key].classList.toggle("hidden", key !== name);
            });
            if (name === "analytics") {
                initCharts();
                updateAnalytics();
            } else if (name === "history") {
                renderHistoryPage();
            } else if (name === "settings") {
                if (els.settingsWsUrlInput) els.settingsWsUrlInput.value = BACKEND_WS_URL;
                updateSettingsConnectionBadge(socket && socket.readyState === WebSocket.OPEN);
                refreshBackendHealth();
            }
        }

        buttons.forEach((btn) => {
            btn.addEventListener("click", () => {
                buttons.forEach((b) => {
                    b.classList.remove("nav-item--active");
                    b.removeAttribute("aria-current");
                });
                btn.classList.add("nav-item--active");
                btn.setAttribute("aria-current", "page");
                showView(btn.dataset.view);
                // The WebSocket connection keeps running regardless of
                // which tab is active.
            });
        });
    }

    function init() {
        collectEls();
        wireNav();
        wireHistoryPage();
        wireSettingsPage();
        wireSupportModal();
        wireCameraStream();
        connectWebSocket();
        setConnectionStatus(false);

        if (els.exportDataBtn) {
            els.exportDataBtn.addEventListener("click", exportHistoryAsCsv);
        }
        if (els.viewFullLogBtn) {
            els.viewFullLogBtn.addEventListener("click", toggleFullHistory);
        }
        renderHistoryTable();
        renderHistoryPage();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();