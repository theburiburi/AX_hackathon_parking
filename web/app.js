const CAMERA_IDS = [
    "cam01",
    "cam02",
    "cam03",
    "cam05",
    "cam06",
    "cam07",
    "cam08",
];


const videos = CAMERA_IDS.map(
    id => document.getElementById(id)
);


const videoMap = {};

for (const video of videos) {

    videoMap[
        video.id
    ] = video;
}


const overlayCanvases = {};

const overlayContexts = {};

for (const cameraId of CAMERA_IDS) {

    const canvas =
        document.getElementById(
            `${cameraId}-overlay`
        );

    overlayCanvases[
        cameraId
    ] = canvas;

    overlayContexts[
        cameraId
    ] = canvas.getContext(
        "2d"
    );
}


/* =========================================================
 * UI
 * =========================================================
 */


const playButton =
    document.getElementById(
        "play-button"
    );

const backButton =
    document.getElementById(
        "back-button"
    );

const forwardButton =
    document.getElementById(
        "forward-button"
    );

const back30Button =
    document.getElementById(
        "back-30-button"
    );

const forward30Button =
    document.getElementById(
        "forward-30-button"
    );

const resetButton =
    document.getElementById(
        "reset-button"
    );

const reloadTrackingButton =
    document.getElementById(
        "reload-tracking-button"
    );

const speedSelect =
    document.getElementById(
        "speed-select"
    );

const timeline =
    document.getElementById(
        "timeline"
    );

const currentTimeLabel =
    document.getElementById(
        "current-time"
    );

const durationLabel =
    document.getElementById(
        "duration-time"
    );

const cameraStatus =
    document.getElementById(
        "camera-status"
    );

const trackingStatus =
    document.getElementById(
        "tracking-status"
    );

const cameraTimeLabels =
    document.querySelectorAll(
        ".camera-time"
    );


const HARD_SYNC_THRESHOLD =
    0.15;

const IGNORE_SYNC_THRESHOLD =
    0.04;

const TRACKING_REQUEST_INTERVAL_MS =
    50;


let readyCount = 0;

let duration = 0;

let playing = false;

let masterTime = 0;

let playbackRate = 1.0;

let playStartedAt = 0;

let playStartedMasterTime = 0;

let animationFrame = null;


/* =========================================================
 * Tracking state
 * =========================================================
 */


let trackingInfo = null;

let latestTracking = null;

let trackingRequestInFlight = false;

let pendingTrackingFrame = null;

let lastRenderedTrackingFrame = -1;

let lastTrackingRequestAt = 0;

let timelineTrackingTimer = null;


/* =========================================================
 * Colors
 * =========================================================
 */


const STATE_COLORS = {
    UNKNOWN: "#8b929c",
    ACTIVE: "#22e86f",
    STOPPED: "#ffd740",
    PARKED: "#ff4fdb",
};


const CAMERA_COLORS = {
    cam01: "#ff3b3b",
    cam02: "#ff9800",
    cam03: "#ffeb3b",
    cam05: "#34df65",
    cam06: "#00d9ff",
    cam07: "#4c76ff",
    cam08: "#e34cff",
};


/* =========================================================
 * Time
 * =========================================================
 */


function formatTime(
    seconds
) {

    if (!Number.isFinite(seconds)) {

        return "00:00.000";
    }

    const minutes =
        Math.floor(
            seconds / 60
        );

    const remaining =
        seconds % 60;

    return (
        String(minutes)
            .padStart(
                2,
                "0"
            )
        +
        ":"
        +
        remaining
            .toFixed(3)
            .padStart(
                6,
                "0"
            )
    );
}


function clampTime(
    value
) {

    if (duration <= 0) {

        return Math.max(
            0,
            value
        );
    }

    return Math.min(
        Math.max(
            0,
            value
        ),
        duration
    );
}


function timeToFrame(
    seconds
) {

    if (!trackingInfo) {

        return 0;
    }

    const frame =
        Math.floor(
            Math.max(
                0,
                seconds
            )
            *
            trackingInfo.fps
        );

    return Math.max(
        0,
        Math.min(
            frame,
            trackingInfo.frame_count - 1
        )
    );
}


/* =========================================================
 * Video sync
 * =========================================================
 */


function setAllVideosTime(
    targetTime,
    force = false
) {

    const time =
        clampTime(
            targetTime
        );

    for (const video of videos) {

        if (
            video.readyState
            <
            HTMLMediaElement.HAVE_METADATA
        ) {

            continue;
        }

        const drift =
            video.currentTime
            -
            time;

        if (
            force
            ||
            Math.abs(
                drift
            )
            >
            HARD_SYNC_THRESHOLD
        ) {

            video.currentTime =
                Math.min(
                    time,
                    video.duration || time
                );

            video.playbackRate =
                playbackRate;

            continue;
        }

        if (
            Math.abs(
                drift
            )
            <
            IGNORE_SYNC_THRESHOLD
        ) {

            video.playbackRate =
                playbackRate;

            continue;
        }

        if (drift < 0) {

            video.playbackRate =
                playbackRate
                *
                1.02;
        }
        else {

            video.playbackRate =
                playbackRate
                *
                0.98;
        }
    }
}


function updateLabels() {

    currentTimeLabel.textContent =
        formatTime(
            masterTime
        );

    timeline.value =
        masterTime;

    for (
        const label
        of cameraTimeLabels
    ) {

        label.textContent =
            formatTime(
                masterTime
            );
    }
}


/* =========================================================
 * Playback
 * =========================================================
 */


function updateMasterClock() {

    if (!playing) {

        return;
    }

    const now =
        performance.now();

    const elapsed =
        (
            now
            -
            playStartedAt
        )
        /
        1000;

    masterTime =
        playStartedMasterTime
        +
        elapsed
        *
        playbackRate;

    if (
        duration > 0
        &&
        masterTime >= duration
    ) {

        masterTime =
            duration;

        pausePlayback();

        updateLabels();

        requestTrackingForTime(
            masterTime,
            true
        );

        return;
    }

    setAllVideosTime(
        masterTime,
        false
    );

    updateLabels();

    requestTrackingForTime(
        masterTime,
        false
    );

    animationFrame =
        requestAnimationFrame(
            updateMasterClock
        );
}


async function startPlayback() {

    if (
        readyCount
        <
        videos.length
    ) {

        return;
    }

    setAllVideosTime(
        masterTime,
        true
    );

    const playPromises = [];

    for (const video of videos) {

        video.playbackRate =
            playbackRate;

        playPromises.push(
            video
                .play()
                .catch(
                    error => {

                        console.error(
                            "Video play failed:",
                            video.id,
                            error
                        );
                    }
                )
        );
    }

    await Promise.all(
        playPromises
    );

    playing = true;

    playStartedAt =
        performance.now();

    playStartedMasterTime =
        masterTime;

    playButton.textContent =
        "일시정지";

    cancelAnimationFrame(
        animationFrame
    );

    animationFrame =
        requestAnimationFrame(
            updateMasterClock
        );
}


function pausePlayback() {

    if (playing) {

        const now =
            performance.now();

        const elapsed =
            (
                now
                -
                playStartedAt
            )
            /
            1000;

        masterTime =
            clampTime(
                playStartedMasterTime
                +
                elapsed
                *
                playbackRate
            );
    }

    playing = false;

    cancelAnimationFrame(
        animationFrame
    );

    for (const video of videos) {

        video.pause();

        video.playbackRate =
            playbackRate;
    }

    setAllVideosTime(
        masterTime,
        true
    );

    playButton.textContent =
        "재생";

    updateLabels();

    requestTrackingForTime(
        masterTime,
        true
    );
}


function togglePlayback() {

    if (playing) {

        pausePlayback();
    }
    else {

        startPlayback();
    }
}


function seekTo(
    value,
    requestTracking = true
) {

    masterTime =
        clampTime(
            Number(
                value
            )
        );

    setAllVideosTime(
        masterTime,
        true
    );

    updateLabels();

    if (playing) {

        playStartedAt =
            performance.now();

        playStartedMasterTime =
            masterTime;
    }

    if (requestTracking) {

        requestTrackingForTime(
            masterTime,
            true
        );
    }
}


function seekRelative(
    seconds
) {

    seekTo(
        masterTime
        +
        seconds,
        true
    );
}


async function resetPlayback() {

    pausePlayback();

    try {

        await fetch(
            "/api/tracking/reset",
            {
                method: "POST"
            }
        );
    }
    catch (error) {

        console.error(
            "Tracking reset failed:",
            error
        );
    }

    latestTracking = null;

    lastRenderedTrackingFrame = -1;

    seekTo(
        0,
        true
    );
}


/* =========================================================
 * Ready
 * =========================================================
 */


function updateReadyState() {

    readyCount =
        videos.filter(
            video =>
                Number.isFinite(
                    video.duration
                )
        ).length;

    cameraStatus.textContent =
        `${readyCount} / ${videos.length} cameras ready`;

    if (
        readyCount
        ===
        videos.length
    ) {

        cameraStatus.classList.remove(
            "loading"
        );

        cameraStatus.classList.add(
            "ready"
        );

        duration =
            Math.min(
                ...videos.map(
                    video =>
                        video.duration
                )
            );

        if (
            trackingInfo
            &&
            Number.isFinite(
                trackingInfo.duration
            )
        ) {

            duration =
                Math.min(
                    duration,
                    trackingInfo.duration
                );
        }

        timeline.max =
            duration;

        durationLabel.textContent =
            formatTime(
                duration
            );

        playButton.disabled =
            false;

        setAllVideosTime(
            0,
            true
        );

        requestTrackingForTime(
            0,
            true
        );
    }
}


/* =========================================================
 * Tracking API
 * =========================================================
 */


function setTrackingStatus(
    text,
    className = ""
) {

    trackingStatus.textContent =
        text;

    trackingStatus.classList.remove(
        "busy",
        "error"
    );

    if (className) {

        trackingStatus.classList.add(
            className
        );
    }
}


async function loadTrackingInfo() {

    try {

        const response =
            await fetch(
                "/api/tracking/info"
            );

        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );
        }

        trackingInfo =
            await response.json();

        setTrackingStatus(
            `Tracking ready · ${trackingInfo.fps.toFixed(1)} FPS`
        );

        if (
            readyCount
            ===
            videos.length
        ) {

            duration =
                Math.min(
                    duration,
                    trackingInfo.duration
                );

            timeline.max =
                duration;

            durationLabel.textContent =
                formatTime(
                    duration
                );

            requestTrackingForTime(
                masterTime,
                true
            );
        }
    }
    catch (error) {

        console.error(
            "Failed to load tracking info:",
            error
        );

        setTrackingStatus(
            "Tracking API error",
            "error"
        );
    }
}


function requestTrackingForTime(
    seconds,
    force = false
) {

    if (!trackingInfo) {

        return;
    }

    const now =
        performance.now();

    if (
        !force
        &&
        now
        -
        lastTrackingRequestAt
        <
        TRACKING_REQUEST_INTERVAL_MS
    ) {

        return;
    }

    lastTrackingRequestAt =
        now;

    const frameIndex =
        timeToFrame(
            seconds
        );

    requestTrackingFrame(
        frameIndex
    );
}


function requestTrackingFrame(
    frameIndex
) {

    if (
        frameIndex
        ===
        lastRenderedTrackingFrame
        &&
        latestTracking
    ) {

        return;
    }

    pendingTrackingFrame =
        frameIndex;

    if (!trackingRequestInFlight) {

        pumpTrackingRequest();
    }
}


async function pumpTrackingRequest() {

    if (
        trackingRequestInFlight
        ||
        pendingTrackingFrame
        ===
        null
    ) {

        return;
    }

    const frameIndex =
        pendingTrackingFrame;

    pendingTrackingFrame =
        null;

    trackingRequestInFlight =
        true;

    try {

        const response =
            await fetch(
                `/api/tracking/frame/${frameIndex}`
            );

        if (!response.ok) {

            let message =
                `HTTP ${response.status}`;

            try {

                const errorData =
                    await response.json();

                if (errorData.detail) {

                    message =
                        errorData.detail;
                }
            }
            catch {
                // ignore
            }

            throw new Error(
                message
            );
        }

        const result =
            await response.json();

        latestTracking =
            result;

        lastRenderedTrackingFrame =
            result.frame_index;

        drawAllCameraOverlays();

        drawBev();

        setTrackingStatus(
            `frame ${result.frame_index}`
        );
    }
    catch (error) {

        console.error(
            "Tracking request failed:",
            error
        );

        setTrackingStatus(
            "Tracking error",
            "error"
        );
    }
    finally {

        trackingRequestInFlight =
            false;

        if (
            pendingTrackingFrame
            !==
            null
            &&
            pendingTrackingFrame
            !==
            lastRenderedTrackingFrame
        ) {

            pumpTrackingRequest();
        }
    }
}


/* =========================================================
 * Config reload
 * =========================================================
 */


async function reloadTrackingConfig() {

    const wasPlaying =
        playing;

    if (wasPlaying) {

        pausePlayback();
    }

    reloadTrackingButton.disabled =
        true;

    setTrackingStatus(
        "Reloading...",
        "busy"
    );

    try {

        const response =
            await fetch(
                "/api/tracking/reload",
                {
                    method: "POST"
                }
            );

        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );
        }

        trackingInfo =
            await response.json();

        latestTracking =
            null;

        lastRenderedTrackingFrame =
            -1;

        setTrackingStatus(
            "Tracking config reloaded"
        );

        requestTrackingForTime(
            masterTime,
            true
        );
    }
    catch (error) {

        console.error(
            "Tracking reload failed:",
            error
        );

        setTrackingStatus(
            "Reload error",
            "error"
        );
    }
    finally {

        reloadTrackingButton.disabled =
            false;
    }
}


/* =========================================================
 * Camera Canvas
 * =========================================================
 */


function resizeCameraCanvas(
    cameraId
) {

    const canvas =
        overlayCanvases[
            cameraId
        ];

    const video =
        videoMap[
            cameraId
        ];

    const stage =
        video.parentElement;

    const width =
        stage.clientWidth;

    const height =
        stage.clientHeight;

    const dpr =
        window.devicePixelRatio
        ||
        1;

    canvas.width =
        Math.max(
            1,
            Math.floor(
                width
                *
                dpr
            )
        );

    canvas.height =
        Math.max(
            1,
            Math.floor(
                height
                *
                dpr
            )
        );

    canvas.style.width =
        `${width}px`;

    canvas.style.height =
        `${height}px`;

    const context =
        overlayContexts[
            cameraId
        ];

    context.setTransform(
        dpr,
        0,
        0,
        dpr,
        0,
        0
    );

    drawCameraOverlay(
        cameraId
    );
}


function calculateVideoLayout(
    cameraId
) {

    const video =
        videoMap[
            cameraId
        ];

    const stage =
        video.parentElement;

    const containerWidth =
        stage.clientWidth;

    const containerHeight =
        stage.clientHeight;

    const videoWidth =
        video.videoWidth;

    const videoHeight =
        video.videoHeight;

    if (
        videoWidth <= 0
        ||
        videoHeight <= 0
    ) {

        return null;
    }

    const scale =
        Math.min(
            containerWidth
            /
            videoWidth,

            containerHeight
            /
            videoHeight
        );

    const drawWidth =
        videoWidth
        *
        scale;

    const drawHeight =
        videoHeight
        *
        scale;

    const offsetX =
        (
            containerWidth
            -
            drawWidth
        )
        /
        2;

    const offsetY =
        (
            containerHeight
            -
            drawHeight
        )
        /
        2;

    return {
        scale,
        offsetX,
        offsetY,
        containerWidth,
        containerHeight,
    };
}


function drawCameraOverlay(
    cameraId
) {

    const context =
        overlayContexts[
            cameraId
        ];

    const stage =
        videoMap[
            cameraId
        ].parentElement;

    const width =
        stage.clientWidth;

    const height =
        stage.clientHeight;

    context.clearRect(
        0,
        0,
        width,
        height
    );

    if (
        !latestTracking
        ||
        !latestTracking.cameras
    ) {

        return;
    }

    const detections =
        latestTracking.cameras[
            cameraId
        ]
        ||
        [];

    const layout =
        calculateVideoLayout(
            cameraId
        );

    if (!layout) {

        return;
    }

    for (
        const detection
        of detections
    ) {

        const color =
            STATE_COLORS[
                detection.state
            ]
            ||
            "#ffffff";

        const x =
            layout.offsetX
            +
            detection.x1
            *
            layout.scale;

        const y =
            layout.offsetY
            +
            detection.y1
            *
            layout.scale;

        const boxWidth =
            (
                detection.x2
                -
                detection.x1
            )
            *
            layout.scale;

        const boxHeight =
            (
                detection.y2
                -
                detection.y1
            )
            *
            layout.scale;

        /*
         * 모든 상태:
         * bbox 색으로만 표시.
         */
        context.strokeStyle =
            color;

        context.lineWidth =
            2;

        context.strokeRect(
            x,
            y,
            boxWidth,
            boxHeight
        );

        /*
         * ACTIVE인 차량에만 ID를 표시한다.
         */
        if (
            detection.state
            !==
            "ACTIVE"
        ) {

            continue;
        }

        let label;

        if (
            detection.global_id
            !==
            null
        ) {

            label =
                `G${String(
                    detection.global_id
                ).padStart(
                    3,
                    "0"
                )}`;
        }
        else {

            label =
                `L${String(
                    detection.local_id
                ).padStart(
                    3,
                    "0"
                )}`;
        }

        context.font =
            "bold 12px Arial";

        const textWidth =
            context.measureText(
                label
            ).width;

        const labelX =
            x;

        const labelY =
            Math.max(
                0,
                y - 18
            );

        context.fillStyle =
            "rgba(0, 0, 0, 0.75)";

        context.fillRect(
            labelX,
            labelY,
            textWidth + 8,
            17
        );

        context.fillStyle =
            color;

        context.fillText(
            label,
            labelX + 4,
            labelY + 12
        );
    }
}


function drawAllCameraOverlays() {

    for (
        const cameraId
        of CAMERA_IDS
    ) {

        drawCameraOverlay(
            cameraId
        );
    }
}


/* =========================================================
 * BEV
 * =========================================================
 */


const BEV_MAP_PATH =
    "/map/map.png";

const ZONES_PATH =
    "/parking/zones.json";


const bevCanvas =
    document.getElementById(
        "bev-canvas"
    );

const bevContainer =
    document.getElementById(
        "bev-container"
    );

const bevStatus =
    document.getElementById(
        "bev-status"
    );

const bevContext =
    bevCanvas.getContext(
        "2d"
    );

const bevImage =
    new Image();

let zoneData = null;


const ZONE_COLORS = {
    A: "#ff5252",
    B: "#ff9800",
    C: "#ffc107",
    D: "#cddc39",
    E: "#4caf50",
    F: "#00bcd4",
    G: "#2196f3",
    H: "#3f51b5",
    I: "#673ab7",
    J: "#9c27b0",
    K: "#e91e63",
    L: "#795548",
    M: "#607d8b",
    N: "#00e5ff",
};


const zoneOccupancy = {};


function initializeOccupancy() {

    if (!zoneData) {

        return;
    }

    for (
        const zone
        of zoneData.zones
    ) {

        zoneOccupancy[
            zone.id
        ] = 0;
    }
}


function resizeBevCanvas() {

    const width =
        bevContainer.clientWidth;

    const height =
        bevContainer.clientHeight;

    const dpr =
        window.devicePixelRatio
        ||
        1;

    bevCanvas.width =
        Math.max(
            1,
            Math.floor(
                width
                *
                dpr
            )
        );

    bevCanvas.height =
        Math.max(
            1,
            Math.floor(
                height
                *
                dpr
            )
        );

    bevCanvas.style.width =
        `${width}px`;

    bevCanvas.style.height =
        `${height}px`;

    bevContext.setTransform(
        dpr,
        0,
        0,
        dpr,
        0,
        0
    );

    drawBev();
}


function calculateMapLayout() {

    const canvasWidth =
        bevContainer.clientWidth;

    const canvasHeight =
        bevContainer.clientHeight;

    const imageWidth =
        bevImage.naturalWidth;

    const imageHeight =
        bevImage.naturalHeight;

    if (
        imageWidth <= 0
        ||
        imageHeight <= 0
    ) {

        return null;
    }

    const scale =
        Math.min(
            canvasWidth
            /
            imageWidth,

            canvasHeight
            /
            imageHeight
        );

    const drawWidth =
        imageWidth
        *
        scale;

    const drawHeight =
        imageHeight
        *
        scale;

    const offsetX =
        (
            canvasWidth
            -
            drawWidth
        )
        /
        2;

    const offsetY =
        (
            canvasHeight
            -
            drawHeight
        )
        /
        2;

    return {
        scale,
        drawWidth,
        drawHeight,
        offsetX,
        offsetY,
    };
}


function drawZone(
    zone,
    layout
) {

    const box =
        zone.bndbox;

    const x =
        layout.offsetX
        +
        box.xmin
        *
        layout.scale;

    const y =
        layout.offsetY
        +
        box.ymin
        *
        layout.scale;

    const width =
        (
            box.xmax
            -
            box.xmin
        )
        *
        layout.scale;

    const height =
        (
            box.ymax
            -
            box.ymin
        )
        *
        layout.scale;

    const color =
        ZONE_COLORS[
            zone.id
        ]
        ||
        "#ffffff";

    bevContext.strokeStyle =
        color;

    bevContext.lineWidth =
        2;

    bevContext.strokeRect(
        x,
        y,
        width,
        height
    );

    const occupancy =
        zoneOccupancy[
            zone.id
        ]
        ??
        0;

    const label =
        `${zone.id} ${occupancy}/${zone.capacity}`;

    bevContext.font =
        "bold 12px Arial";

    const textWidth =
        bevContext.measureText(
            label
        ).width;

    const labelHeight =
        19;

    const labelWidth =
        textWidth
        +
        10;

    bevContext.fillStyle =
        color;

    bevContext.fillRect(
        x,
        y,
        labelWidth,
        labelHeight
    );

    bevContext.fillStyle =
        "#ffffff";

    bevContext.fillText(
        label,
        x + 5,
        y + 14
    );
}


function drawBevTracking(
    layout
) {

    if (
        !latestTracking
        ||
        !Array.isArray(
            latestTracking.bev
        )
    ) {

        return;
    }

    for (
        const item
        of latestTracking.bev
    ) {

        const x =
            layout.offsetX
            +
            item.x
            *
            layout.scale;

        const y =
            layout.offsetY
            +
            item.y
            *
            layout.scale;

        const cameraColor =
            CAMERA_COLORS[
                item.camera_id
            ]
            ||
            "#ffffff";

        const stateColor =
            STATE_COLORS[
                item.state
            ]
            ||
            "#ffffff";

        bevContext.beginPath();

        bevContext.arc(
            x,
            y,
            8,
            0,
            Math.PI * 2
        );

        bevContext.fillStyle =
            cameraColor;

        bevContext.fill();

        bevContext.beginPath();

        bevContext.arc(
            x,
            y,
            5,
            0,
            Math.PI * 2
        );

        bevContext.fillStyle =
            stateColor;

        bevContext.fill();

        let label =
            `L${String(
                item.local_id
            ).padStart(
                3,
                "0"
            )}`;

        if (
            item.global_id
            !==
            null
        ) {

            label =
                `G${String(
                    item.global_id
                ).padStart(
                    3,
                    "0"
                )}`;
        }

        label +=
            ` ${item.state}`;

        bevContext.font =
            "bold 10px Arial";

        const textWidth =
            bevContext.measureText(
                label
            ).width;

        bevContext.fillStyle =
            "rgba(0, 0, 0, 0.75)";

        bevContext.fillRect(
            x + 8,
            y - 15,
            textWidth + 6,
            15
        );

        bevContext.fillStyle =
            stateColor;

        bevContext.fillText(
            label,
            x + 11,
            y - 4
        );
    }
}


function drawBev() {

    const canvasWidth =
        bevContainer.clientWidth;

    const canvasHeight =
        bevContainer.clientHeight;

    bevContext.clearRect(
        0,
        0,
        canvasWidth,
        canvasHeight
    );

    if (
        !bevImage.complete
        ||
        bevImage.naturalWidth === 0
    ) {

        return;
    }

    const layout =
        calculateMapLayout();

    if (!layout) {

        return;
    }

    bevContext.drawImage(
        bevImage,
        layout.offsetX,
        layout.offsetY,
        layout.drawWidth,
        layout.drawHeight
    );

    if (zoneData) {

        for (
            const zone
            of zoneData.zones
        ) {

            drawZone(
                zone,
                layout
            );
        }
    }

    drawBevTracking(
        layout
    );

    if (latestTracking) {

        bevStatus.textContent =
            `frame ${latestTracking.frame_index}`;
    }
}


async function loadZones() {

    try {

        const response =
            await fetch(
                ZONES_PATH
            );

        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );
        }

        zoneData =
            await response.json();

        initializeOccupancy();

        drawBev();

        bevStatus.textContent =
            `${zoneData.zones.length} zones`;
    }
    catch (error) {

        console.error(
            "Failed to load zones:",
            error
        );

        bevStatus.textContent =
            "zone error";
    }
}


/* =========================================================
 * Events
 * =========================================================
 */


for (const video of videos) {

    video.controls =
        false;

    video.addEventListener(
        "loadedmetadata",
        () => {

            updateReadyState();

            resizeCameraCanvas(
                video.id
            );
        }
    );
}


playButton.addEventListener(
    "click",
    togglePlayback
);


backButton.addEventListener(
    "click",
    () => {

        seekRelative(
            -5
        );
    }
);


forwardButton.addEventListener(
    "click",
    () => {

        seekRelative(
            5
        );
    }
);


back30Button.addEventListener(
    "click",
    () => {

        seekRelative(
            -30
        );
    }
);


forward30Button.addEventListener(
    "click",
    () => {

        seekRelative(
            30
        );
    }
);


resetButton.addEventListener(
    "click",
    resetPlayback
);


reloadTrackingButton.addEventListener(
    "click",
    reloadTrackingConfig
);


speedSelect.addEventListener(
    "change",
    event => {

        const oldRate =
            playbackRate;

        playbackRate =
            Number(
                event.target.value
            );

        if (
            !Number.isFinite(
                playbackRate
            )
            ||
            playbackRate <= 0
        ) {

            playbackRate =
                1;
        }

        if (playing) {

            const now =
                performance.now();

            const elapsed =
                (
                    now
                    -
                    playStartedAt
                )
                /
                1000;

            masterTime =
                clampTime(
                    playStartedMasterTime
                    +
                    elapsed
                    *
                    oldRate
                );

            playStartedAt =
                performance.now();

            playStartedMasterTime =
                masterTime;
        }

        for (const video of videos) {

            video.playbackRate =
                playbackRate;
        }
    }
);


timeline.addEventListener(
    "input",
    event => {

        seekTo(
            event.target.value,
            false
        );

        clearTimeout(
            timelineTrackingTimer
        );

        timelineTrackingTimer =
            setTimeout(
                () => {

                    requestTrackingForTime(
                        masterTime,
                        true
                    );
                },
                150
            );
    }
);


timeline.addEventListener(
    "change",
    event => {

        clearTimeout(
            timelineTrackingTimer
        );

        seekTo(
            event.target.value,
            true
        );
    }
);


window.addEventListener(
    "keydown",
    event => {

        if (
            event.code
            ===
            "Space"
        ) {

            event.preventDefault();

            togglePlayback();

            return;
        }

        if (
            event.key === "a"
            ||
            event.key === "A"
        ) {

            if (event.shiftKey) {

                seekRelative(
                    -30
                );
            }
            else {

                seekRelative(
                    -5
                );
            }

            return;
        }

        if (
            event.key === "d"
            ||
            event.key === "D"
        ) {

            if (event.shiftKey) {

                seekRelative(
                    30
                );
            }
            else {

                seekRelative(
                    5
                );
            }

            return;
        }

        if (
            event.key === "r"
            ||
            event.key === "R"
        ) {

            resetPlayback();
        }
    }
);


/* =========================================================
 * Resize
 * =========================================================
 */


for (
    const cameraId
    of CAMERA_IDS
) {

    const video =
        videoMap[
            cameraId
        ];

    const stage =
        video.parentElement;

    const observer =
        new ResizeObserver(
            () => {

                resizeCameraCanvas(
                    cameraId
                );
            }
        );

    observer.observe(
        stage
    );
}


const bevResizeObserver =
    new ResizeObserver(
        () => {

            resizeBevCanvas();
        }
    );

bevResizeObserver.observe(
    bevContainer
);


/* =========================================================
 * BEV load
 * =========================================================
 */


bevImage.addEventListener(
    "load",
    () => {

        drawBev();
    }
);


bevImage.addEventListener(
    "error",
    () => {

        bevStatus.textContent =
            "map error";
    }
);


bevImage.src =
    BEV_MAP_PATH;


loadZones();


/* =========================================================
 * Initialize
 * =========================================================
 */


updateLabels();

loadTrackingInfo();