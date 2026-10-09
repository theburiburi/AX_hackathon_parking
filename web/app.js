/* =========================================================
 * Mosaic video
 * =========================================================
 *
 * 원본은 모자이크 영상 1개 (카메라 칸들이 격자로 배치됨).
 *
 * - 영상이 실제로 화면에 표시한 프레임 번호
 *   (requestVideoFrameCallback의 mediaTime)로 tracking 결과를 요청한다.
 *   그래서 bbox / BEV가 영상과 같은 프레임을 가리킨다.
 * - bbox 좌표는 카메라 칸 기준이므로,
 *   /api/tracking/info 의 scene.cameras[].rect 위치만큼 옮겨 그린다.
 */


const video =
    document.getElementById(
        "mosaic-video"
    );

const overlayCanvas =
    document.getElementById(
        "mosaic-overlay"
    );

const overlayContext =
    overlayCanvas.getContext(
        "2d"
    );


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

const videoStatus =
    document.getElementById(
        "video-status"
    );

const trackingStatus =
    document.getElementById(
        "tracking-status"
    );

const sceneTitle =
    document.getElementById(
        "scene-title"
    );

const videoTimeLabel =
    document.getElementById(
        "video-time"
    );


/* =========================================================
 * State
 * =========================================================
 */


let duration = 0;

let playbackRate = 1.0;

// 타임라인을 드래그하는 동안에는 timeline 값을 영상 시각으로 덮어쓰지 않는다.
let timelineDragging = false;

// 영상이 마지막으로 표시한 프레임 번호
let displayedFrame = 0;


/* =========================================================
 * Tracking state
 * =========================================================
 */


let trackingInfo = null;

// 지금 그려진 tracking 결과. 영상에 표시된 프레임의 결과만 그린다.
let latestTracking = null;

// frame index -> tracking 결과. 재생 중에는 앞 프레임을 미리 받아 둔다.
const trackingCache = new Map();

const TRACKING_CACHE_SIZE = 600;

const TRACKING_PREFETCH_FRAMES = 15;

// 받아 와야 하는 기준 프레임 (재생바를 옮기면 영상 표시보다 먼저 바뀐다)
let targetFrame = 0;

// 처리 중인 요청 { frame, controller, failed }
let trackingRequest = null;


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


function fps() {

    return (
        trackingInfo
            ? trackingInfo.fps
            : 30
    );
}


function timeToFrame(
    seconds
) {

    // 프레임 i의 표시 시각은 i / fps.
    // 부동소수 오차로 한 프레임 앞을 가리키지 않도록 작은 여유를 둔다.
    const frame =
        Math.floor(
            Math.max(
                0,
                seconds
            )
            *
            fps()
            +
            1e-3
        );

    if (!trackingInfo) {

        return frame;
    }

    return Math.max(
        0,
        Math.min(
            frame,
            trackingInfo.frame_count - 1
        )
    );
}


function frameToTime(
    frame
) {

    // 프레임 구간의 가운데로 이동해야 경계 오차 없이 해당 프레임이 표시된다.
    return (
        (
            frame
            +
            0.5
        )
        /
        fps()
    );
}


function updateLabels() {

    const time =
        video.currentTime || 0;

    currentTimeLabel.textContent =
        formatTime(
            time
        );

    if (!timelineDragging) {

        timeline.value =
            time;
    }

    videoTimeLabel.textContent =
        `${formatTime(time)} · frame ${displayedFrame}`;
}


/* =========================================================
 * Frame sync
 * =========================================================
 */


function onDisplayedFrame(
    mediaTime
) {

    displayedFrame =
        timeToFrame(
            mediaTime
        );

    updateLabels();

    renderGateLog();

    showTracking(
        displayedFrame
    );

    // 이동 중에 표시된 중간 프레임으로 요청하면
    // 재생바를 옮긴 마지막 위치의 요청을 덮어쓰므로 건너뛴다.
    if (!video.seeking) {

        requestTrackingFrame(
            displayedFrame
        );
    }
}


function startFrameSync() {

    if (
        "requestVideoFrameCallback"
        in
        HTMLVideoElement.prototype
    ) {

        const onFrame = (
            now,
            metadata
        ) => {

            onDisplayedFrame(
                metadata.mediaTime
            );

            video.requestVideoFrameCallback(
                onFrame
            );
        };

        video.requestVideoFrameCallback(
            onFrame
        );

        return;
    }

    // requestVideoFrameCallback 미지원 브라우저: currentTime으로 근사
    let lastTime = -1;

    const poll = () => {

        if (
            video.currentTime
            !==
            lastTime
        ) {

            lastTime =
                video.currentTime;

            onDisplayedFrame(
                video.currentTime
            );
        }

        requestAnimationFrame(
            poll
        );
    };

    requestAnimationFrame(
        poll
    );
}


/* =========================================================
 * Playback
 * =========================================================
 */


async function startPlayback() {

    if (
        !Number.isFinite(
            video.duration
        )
    ) {

        return;
    }

    video.playbackRate =
        playbackRate;

    try {

        await video.play();
    }
    catch (error) {

        console.error(
            "Video play failed:",
            error
        );
    }
}


function pausePlayback() {

    video.pause();

    requestTrackingFrame(
        timeToFrame(
            video.currentTime
        )
    );
}


function togglePlayback() {

    if (video.paused) {

        startPlayback();
    }
    else {

        pausePlayback();
    }
}


function updatePlayButton() {

    playButton.textContent =
        video.paused
            ? "재생"
            : "일시정지";
}


function seekTo(
    value
) {

    video.currentTime =
        clampTime(
            Number(
                value
            )
        );

    updateLabels();

    // 영상이 새 프레임을 표시하기 전에 tracking 요청을 먼저 보낸다.
    requestTrackingFrame(
        timeToFrame(
            video.currentTime
        )
    );
}


function seekRelative(
    seconds
) {

    seekTo(
        video.currentTime
        +
        seconds
    );
}


function seekFrames(
    count
) {

    video.pause();

    const frame =
        timeToFrame(
            video.currentTime
        )
        +
        count;

    seekTo(
        frameToTime(
            Math.max(
                0,
                frame
            )
        )
    );
}


async function resetPlayback() {

    video.pause();

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

    clearTrackingCache();

    seekTo(
        0
    );
}


/* =========================================================
 * Ready
 * =========================================================
 */


function updateDuration() {

    if (
        !Number.isFinite(
            video.duration
        )
    ) {

        return;
    }

    duration =
        video.duration;

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
}


function onVideoReady() {

    updateDuration();

    videoStatus.textContent =
        `mosaic ready · ${video.videoWidth}x${video.videoHeight}`;

    videoStatus.classList.remove(
        "loading"
    );

    videoStatus.classList.add(
        "ready"
    );

    playButton.disabled =
        false;

    resizeOverlay();

    requestTrackingFrame(
        timeToFrame(
            video.currentTime
        )
    );
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

        const scene =
            trackingInfo.scene;

        sceneTitle.textContent =
            `SCENE ${scene.name} · ${scene.cameras.length} cameras`;

        setTrackingStatus(
            `Tracking ready · ${trackingInfo.fps.toFixed(1)} FPS`
        );

        // 영상 경로는 서버의 scene 설정에서 받는다.
        if (!video.src) {

            video.src =
                scene.video_url;
        }

        updateDuration();
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

        videoStatus.textContent =
            "video not loaded";
    }
}


function clearTrackingCache() {

    trackingCache.clear();

    if (trackingRequest) {

        trackingRequest.controller.abort();

        trackingRequest = null;
    }

    latestTracking = null;

    drawOverlay();

    drawBev();
}


function showTracking(
    frameIndex
) {

    const result =
        trackingCache.get(
            frameIndex
        );

    if (result) {

        if (latestTracking !== result) {

            latestTracking =
                result;

            drawOverlay();

            drawBev();

            setTrackingStatus(
                `frame ${result.frame_index}`
            );
        }

        return;
    }

    // 이 프레임의 결과가 아직 없으면 다른 프레임의 bbox를 그리지 않는다.
    if (latestTracking) {

        latestTracking =
            null;

        drawOverlay();

        drawBev();
    }

    setTrackingStatus(
        `frame ${frameIndex} loading`,
        "busy"
    );
}


function nextFrameToFetch() {

    if (!trackingInfo) {

        return null;
    }

    const ahead =
        video.paused
            ? 0
            : TRACKING_PREFETCH_FRAMES;

    const last =
        Math.min(
            targetFrame + ahead,
            trackingInfo.frame_count - 1
        );

    for (
        let frame = targetFrame;
        frame <= last;
        frame++
    ) {

        if (!trackingCache.has(frame)) {

            return frame;
        }
    }

    return null;
}


function requestTrackingFrame(
    frameIndex
) {

    if (!trackingInfo) {

        return;
    }

    // 재생으로 조금 앞으로 간 것이 아니면 재생바 이동으로 본다.
    // 서버는 이동한 위치에서 tracking을 새로 시작하므로
    // 이전 위치의 결과(다른 track id)와 섞이지 않게 캐시를 비우고,
    // 처리 중인 요청은 중단한 뒤 이 프레임을 바로 요청한다.
    const isSeek =
        frameIndex < targetFrame
        ||
        frameIndex > targetFrame + TRACKING_PREFETCH_FRAMES;

    targetFrame =
        frameIndex;

    if (isSeek) {

        clearTrackingCache();
    }

    pumpTrackingRequest();
}


async function pumpTrackingRequest() {

    if (trackingRequest) {

        return;
    }

    const frameIndex =
        nextFrameToFetch();

    if (frameIndex === null) {

        return;
    }

    const request = {
        frame: frameIndex,
        controller: new AbortController(),
        failed: false,
    };

    trackingRequest =
        request;

    try {

        const response =
            await fetch(
                `/api/tracking/frame/${frameIndex}`,
                {
                    signal:
                        request.controller.signal
                }
            );

        // 409: 서버가 더 최근 요청 때문에 계산을 중단함
        if (response.status === 409) {

            return;
        }

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

        if (trackingRequest !== request) {

            return;
        }

        trackingCache.set(
            result.frame_index,
            result
        );

        if (trackingCache.size > TRACKING_CACHE_SIZE) {

            trackingCache.delete(
                trackingCache.keys().next().value
            );
        }

        if (result.frame_index === displayedFrame) {

            showTracking(
                displayedFrame
            );
        }
    }
    catch (error) {

        if (error.name === "AbortError") {

            return;
        }

        request.failed =
            true;

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

        if (trackingRequest === request) {

            trackingRequest =
                null;

            // 실패하면 같은 프레임을 계속 다시 요청하지 않는다.
            if (!request.failed) {

                pumpTrackingRequest();
            }
        }
    }
}


/* =========================================================
 * Config reload
 * =========================================================
 */


async function reloadTrackingConfig() {

    video.pause();

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

        clearTrackingCache();

        setTrackingStatus(
            "Tracking config reloaded"
        );

        loadGateLog();

        requestTrackingFrame(
            timeToFrame(
                video.currentTime
            )
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
 * Overlay
 * =========================================================
 */


function resizeOverlay() {

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

    overlayCanvas.width =
        Math.max(
            1,
            Math.floor(
                width
                *
                dpr
            )
        );

    overlayCanvas.height =
        Math.max(
            1,
            Math.floor(
                height
                *
                dpr
            )
        );

    overlayCanvas.style.width =
        `${width}px`;

    overlayCanvas.style.height =
        `${height}px`;

    overlayContext.setTransform(
        dpr,
        0,
        0,
        dpr,
        0,
        0
    );

    drawOverlay();
}


function calculateVideoLayout() {

    // 영상은 object-fit: contain 으로 표시되므로
    // 실제 그려진 영역의 배율과 여백을 계산한다.
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

    return {
        scale,

        offsetX:
            (
                containerWidth
                -
                videoWidth
                *
                scale
            )
            /
            2,

        offsetY:
            (
                containerHeight
                -
                videoHeight
                *
                scale
            )
            /
            2,
    };
}


function drawCameraLabel(
    layout,
    camera
) {

    const x =
        layout.offsetX
        +
        camera.rect[0]
        *
        layout.scale;

    const y =
        layout.offsetY
        +
        camera.rect[1]
        *
        layout.scale;

    const label =
        camera.id.toUpperCase();

    overlayContext.font =
        "bold 11px Arial";

    const textWidth =
        overlayContext.measureText(
            label
        ).width;

    overlayContext.fillStyle =
        "rgba(0, 0, 0, 0.6)";

    overlayContext.fillRect(
        x + 4,
        y + 4,
        textWidth + 8,
        16
    );

    overlayContext.fillStyle =
        CAMERA_COLORS[
            camera.id
        ]
        ||
        "#ffffff";

    overlayContext.fillText(
        label,
        x + 8,
        y + 16
    );
}


function drawDetection(
    layout,
    camera,
    detection
) {

    const color =
        STATE_COLORS[
            detection.state
        ]
        ||
        "#ffffff";

    // 칸 기준 좌표 -> 모자이크 좌표 -> 화면 좌표
    const x =
        layout.offsetX
        +
        (
            camera.rect[0]
            +
            detection.x1
        )
        *
        layout.scale;

    const y =
        layout.offsetY
        +
        (
            camera.rect[1]
            +
            detection.y1
        )
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

    overlayContext.strokeStyle =
        color;

    overlayContext.lineWidth =
        1;

    overlayContext.strokeRect(
        x,
        y,
        boxWidth,
        boxHeight
    );

    /*
     * ACTIVE 차량만 번호 표시.
     */
    if (
        detection.state
        !==
        "ACTIVE"
    ) {

        return;
    }

    const label =
        detection.global_id !== null
            ? `G${String(detection.global_id).padStart(3, "0")}`
            : `L${String(detection.local_id).padStart(3, "0")}`;

    overlayContext.font =
        "bold 11px Arial";

    const textWidth =
        overlayContext.measureText(
            label
        ).width;

    const labelY =
        Math.max(
            0,
            y - 16
        );

    overlayContext.fillStyle =
        "rgba(0, 0, 0, 0.72)";

    overlayContext.fillRect(
        x,
        labelY,
        textWidth + 7,
        15
    );

    overlayContext.fillStyle =
        color;

    overlayContext.fillText(
        label,
        x + 3,
        labelY + 11
    );
}


function drawOverlay() {

    const stage =
        video.parentElement;

    overlayContext.clearRect(
        0,
        0,
        stage.clientWidth,
        stage.clientHeight
    );

    if (!trackingInfo) {

        return;
    }

    const layout =
        calculateVideoLayout();

    if (!layout) {

        return;
    }

    for (
        const camera
        of trackingInfo.scene.cameras
    ) {

        drawCameraLabel(
            layout,
            camera
        );

        if (
            !latestTracking
            ||
            !latestTracking.cameras
        ) {

            continue;
        }

        const detections =
            latestTracking.cameras[
                camera.id
            ]
            ||
            [];

        for (
            const detection
            of detections
        ) {

            drawDetection(
                layout,
                camera,
                detection
            );
        }
    }
}


/* =========================================================
 * BEV
 * =========================================================
 */


const BEV_MAP_PATH =
    "/map/map.png";

const ZONES_PATH =
    "/map/zones.json";


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

        /*
         * BEV에는 ACTIVE 차량만 표시.
         *
         * STOPPED / PARKED는 CCTV bbox에는 남지만
         * BEV에서는 사라진다.
         */
        if (
            item.state
            !==
            "ACTIVE"
        ) {

            continue;
        }

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
            STATE_COLORS.ACTIVE;

        /*
         * 기존 outer 8px -> 6px.
         */
        bevContext.beginPath();

        bevContext.arc(
            x,
            y,
            6,
            0,
            Math.PI * 2
        );

        bevContext.fillStyle =
            cameraColor;

        bevContext.fill();

        /*
         * 기존 inner 5px -> 3.5px.
         */
        bevContext.beginPath();

        bevContext.arc(
            x,
            y,
            3.5,
            0,
            Math.PI * 2
        );

        bevContext.fillStyle =
            stateColor;

        bevContext.fill();

        let label;

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
        else {

            label =
                `L${String(
                    item.local_id
                ).padStart(
                    3,
                    "0"
                )}`;
        }

        bevContext.font =
            "bold 9px Arial";

        const textWidth =
            bevContext.measureText(
                label
            ).width;

        bevContext.fillStyle =
            "rgba(0, 0, 0, 0.72)";

        bevContext.fillRect(
            x + 6,
            y - 12,
            textWidth + 5,
            13
        );

        bevContext.fillStyle =
            stateColor;

        bevContext.fillText(
            label,
            x + 8,
            y - 3
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
 * Gate log
 * =========================================================
 *
 * 차단기 입출차 기록 (/api/gate-log).
 * 이벤트마다 영상 프레임 번호(frame)가 있으며,
 * 화면에 표시된 프레임(displayedFrame)까지의 기록만 보여 준다.
 * 그래서 재생, 일시정지, 이동, 1프레임 이동 모두 영상과 맞게 동기화된다.
 */


const gateLogList =
    document.getElementById(
        "gate-log-list"
    );

const gateLogStatus =
    document.getElementById(
        "gate-log-status"
    );

// 방금 발생한 기록을 강조하는 시간(프레임 수 = 2초)
const GATE_LOG_RECENT_FRAMES =
    60;

const GATE_TYPE_STYLES = {
    IN: "in",
    IN_DONE: "in",
    OUT: "out",
    OUT_DONE: "out",
    GATE_OPEN: "gate",
    GATE_CLOSE: "gate",
};

let gateLog = null;

// 마지막으로 그린 상태 (같으면 다시 그리지 않음)
let gateLogRenderKey = null;


async function loadGateLog() {

    try {

        const response =
            await fetch(
                "/api/gate-log"
            );

        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );
        }

        gateLog =
            await response.json();

        const gateName =
            gateLog.gate
                ? gateLog.gate.name
                : "기록 없음";

        gateLogStatus.textContent =
            `${gateName} · ${gateLog.events.length}건`;
    }
    catch (error) {

        console.error(
            "Failed to load gate log:",
            error
        );

        gateLog = null;

        gateLogStatus.textContent =
            "gate log error";
    }

    gateLogRenderKey = null;

    renderGateLog();
}


function formatGateTime(
    value
) {

    // "2026-10-01 07:31:48.667" -> "07:31:48.667"
    if (typeof value !== "string") {

        return "";
    }

    const parts =
        value.split(" ");

    return parts[parts.length - 1];
}


function createGateLogItem(
    event,
    recent
) {

    const item =
        document.createElement(
            "li"
        );

    item.className =
        recent
            ? "gate-log-item recent"
            : "gate-log-item";

    item.title =
        `frame ${event.frame} · 클릭하면 이 시점으로 이동`;

    const time =
        document.createElement(
            "span"
        );

    time.className =
        "gate-log-time";

    time.textContent =
        formatGateTime(
            event.time
        );

    const type =
        document.createElement(
            "span"
        );

    type.className =
        `gate-log-type ${GATE_TYPE_STYLES[event.type] || ""}`;

    type.textContent =
        event.label
        ||
        event.type;

    const text =
        document.createElement(
            "span"
        );

    text.className =
        "gate-log-text";

    if (event.plate) {

        const plate =
            document.createElement(
                "span"
            );

        plate.className =
            "gate-log-plate";

        plate.textContent =
            `${event.plate} `;

        text.appendChild(
            plate
        );
    }

    if (event.detail) {

        const detail =
            document.createElement(
                "span"
            );

        detail.className =
            "gate-log-detail";

        detail.textContent =
            event.detail;

        text.appendChild(
            detail
        );
    }

    item.append(
        time,
        type,
        text
    );

    item.addEventListener(
        "click",
        () => {

            video.pause();

            seekTo(
                frameToTime(
                    event.frame
                )
            );
        }
    );

    return item;
}


function renderGateLog() {

    if (
        !gateLog
        ||
        !Array.isArray(
            gateLog.events
        )
    ) {

        return;
    }

    // events는 서버에서 frame 순으로 정렬돼 있다.
    const visible =
        gateLog.events.filter(
            event =>
                event.frame
                <=
                displayedFrame
        );

    const recentCount =
        visible.filter(
            event =>
                displayedFrame
                -
                event.frame
                <
                GATE_LOG_RECENT_FRAMES
        ).length;

    const renderKey =
        `${visible.length}:${recentCount}`;

    if (
        renderKey
        ===
        gateLogRenderKey
    ) {

        return;
    }

    gateLogRenderKey =
        renderKey;

    gateLogList.replaceChildren();

    if (visible.length === 0) {

        const empty =
            document.createElement(
                "li"
            );

        empty.className =
            "gate-log-empty";

        empty.textContent =
            gateLog.events.length > 0
                ? "아직 발생한 기록이 없습니다."
                : "이 영상의 차단기 기록이 없습니다.";

        gateLogList.appendChild(
            empty
        );

        return;
    }

    // 최신 기록이 위로 오도록 역순으로 표시
    for (
        let index = visible.length - 1;
        index >= 0;
        index--
    ) {

        const event =
            visible[index];

        gateLogList.appendChild(
            createGateLogItem(
                event,
                displayedFrame
                -
                event.frame
                <
                GATE_LOG_RECENT_FRAMES
            )
        );
    }
}


/* =========================================================
 * Events
 * =========================================================
 */


video.controls =
    false;


video.addEventListener(
    "loadedmetadata",
    onVideoReady
);


video.addEventListener(
    "error",
    () => {

        console.error(
            "Video load failed:",
            video.error
        );

        videoStatus.textContent =
            "video error (codec?)";

        videoStatus.classList.remove(
            "loading",
            "ready"
        );
    }
);


video.addEventListener(
    "play",
    () => {

        updatePlayButton();

        // 재생 중에는 앞 프레임을 미리 받아 둔다.
        pumpTrackingRequest();
    }
);


video.addEventListener(
    "pause",
    updatePlayButton
);


video.addEventListener(
    "seeked",
    () => {

        // requestVideoFrameCallback이 seek 후 프레임을
        // 알려 주지 않는 경우를 대비한 보조 요청.
        onDisplayedFrame(
            video.currentTime
        );
    }
);


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

        video.playbackRate =
            playbackRate;
    }
);


timeline.addEventListener(
    "input",
    event => {

        timelineDragging =
            true;

        // 드래그 중 여러 번 이동해도 처리 중인 요청은 중단되고
        // 마지막 위치만 계산된다.
        seekTo(
            event.target.value
        );
    }
);


timeline.addEventListener(
    "change",
    event => {

        timelineDragging =
            false;

        seekTo(
            event.target.value
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

            seekRelative(
                event.shiftKey
                    ? -30
                    : -5
            );

            return;
        }

        if (
            event.key === "d"
            ||
            event.key === "D"
        ) {

            seekRelative(
                event.shiftKey
                    ? 30
                    : 5
            );

            return;
        }

        if (
            event.key === ","
        ) {

            seekFrames(
                -1
            );

            return;
        }

        if (
            event.key === "."
        ) {

            seekFrames(
                1
            );

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


const overlayResizeObserver =
    new ResizeObserver(
        () => {

            resizeOverlay();
        }
    );

overlayResizeObserver.observe(
    video.parentElement
);


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

startFrameSync();

loadTrackingInfo();

loadGateLog();
