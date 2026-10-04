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


const playButton =
    document.getElementById("play-button");

const backButton =
    document.getElementById("back-button");

const forwardButton =
    document.getElementById("forward-button");

const resetButton =
    document.getElementById("reset-button");

const timeline =
    document.getElementById("timeline");

const currentTimeLabel =
    document.getElementById("current-time");

const durationLabel =
    document.getElementById("duration-time");

const cameraStatus =
    document.getElementById("camera-status");

const cameraTimeLabels =
    document.querySelectorAll(".camera-time");


const SEEK_SECONDS = 5;


const HARD_SYNC_THRESHOLD = 0.15;

const IGNORE_SYNC_THRESHOLD = 0.04;


let readyCount = 0;

let duration = 0;

let playing = false;

let masterTime = 0;


let playStartedAt = 0;

let playStartedMasterTime = 0;

let animationFrame = null;


/* =========================================================
 * VIDEO PLAYER
 * =========================================================
 */


function formatTime(seconds) {

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
        String(minutes).padStart(2, "0")
        +
        ":"
        +
        remaining
            .toFixed(3)
            .padStart(6, "0")
    );
}


function clampTime(value) {

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
            Math.abs(drift)
            >
            HARD_SYNC_THRESHOLD
        ) {

            video.currentTime =
                Math.min(
                    time,
                    video.duration || time
                );


            video.playbackRate = 1;


            continue;
        }


        if (
            Math.abs(drift)
            <
            IGNORE_SYNC_THRESHOLD
        ) {

            video.playbackRate = 1;

            continue;
        }


        if (drift < 0) {

            video.playbackRate =
                1.02;

        }
        else {

            video.playbackRate =
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
        elapsed;


    if (
        duration > 0
        &&
        masterTime >= duration
    ) {

        masterTime =
            duration;


        pausePlayback();


        updateLabels();


        return;
    }


    setAllVideosTime(
        masterTime,
        false
    );


    updateLabels();


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
            1;


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
            );
    }


    playing = false;


    cancelAnimationFrame(
        animationFrame
    );


    for (const video of videos) {

        video.pause();

        video.playbackRate =
            1;
    }


    setAllVideosTime(
        masterTime,
        true
    );


    playButton.textContent =
        "재생";


    updateLabels();
}


function togglePlayback() {

    if (playing) {

        pausePlayback();

    }
    else {

        startPlayback();
    }
}


function seekTo(value) {

    masterTime =
        clampTime(
            Number(value)
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
}


function seekRelative(seconds) {

    seekTo(
        masterTime
        +
        seconds
    );
}


function resetPlayback() {

    pausePlayback();

    seekTo(0);
}


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
    }
}


for (const video of videos) {

    video.controls = false;


    video.addEventListener(
        "loadedmetadata",
        updateReadyState
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
            -SEEK_SECONDS
        );
    }
);


forwardButton.addEventListener(
    "click",
    () => {

        seekRelative(
            SEEK_SECONDS
        );
    }
);


resetButton.addEventListener(
    "click",
    resetPlayback
);


timeline.addEventListener(
    "input",
    event => {

        seekTo(
            event.target.value
        );
    }
);


window.addEventListener(
    "keydown",
    event => {

        if (
            event.code === "Space"
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
                -SEEK_SECONDS
            );

            return;
        }


        if (
            event.key === "d"
            ||
            event.key === "D"
        ) {

            seekRelative(
                SEEK_SECONDS
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
 * BEV MAP
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


/*
 * 현재 occupancy는 아직 실제 추적 결과가 없으므로
 * 모두 0으로 시작한다.
 */
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


/*
 * Canvas 실제 픽셀 크기를
 * 화면 크기에 맞춘다.
 *
 * 고해상도 모니터에서도
 * 선과 글자가 흐려지지 않도록
 * devicePixelRatio를 적용한다.
 */
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
                width * dpr
            )
        );


    bevCanvas.height =
        Math.max(
            1,
            Math.floor(
                height * dpr
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


/*
 * 지도 이미지가 카드 안에
 * object-fit: contain처럼 들어가도록
 * 실제 표시 영역을 계산한다.
 */
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


    /*
     * BBOX
     */
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


    /*
     * Label
     */
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


    /*
     * 라벨 배경
     */
    bevContext.fillStyle =
        color;


    bevContext.fillRect(
        x,
        y,
        labelWidth,
        labelHeight
    );


    /*
     * 라벨 글자
     */
    bevContext.fillStyle =
        "#ffffff";


    bevContext.fillText(
        label,
        x + 5,
        y + 14
    );
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


    /*
     * 지도
     */
    bevContext.drawImage(
        bevImage,
        layout.offsetX,
        layout.offsetY,
        layout.drawWidth,
        layout.drawHeight
    );


    /*
     * Zone BBOX
     */
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
}


/*
 * 나중에 Tracking 결과를 연결할 때
 * 이 함수만 호출하면 occupancy를 갱신할 수 있다.
 *
 * 예:
 *
 * setZoneOccupancy("A", 3)
 */
function setZoneOccupancy(
    zoneId,
    count
) {

    if (
        !Object.prototype.hasOwnProperty.call(
            zoneOccupancy,
            zoneId
        )
    ) {

        return;
    }


    zoneOccupancy[
        zoneId
    ] = count;


    drawBev();
}


/*
 * zones.json 로딩
 */
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


/*
 * 지도 이미지 로딩
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

        console.error(
            "Failed to load BEV map"
        );


        bevStatus.textContent =
            "map error";
    }
);


bevImage.src =
    BEV_MAP_PATH;


/*
 * BEV 카드 크기가 변하면
 * Canvas도 자동 재계산한다.
 */
const bevResizeObserver =
    new ResizeObserver(
        () => {

            resizeBevCanvas();
        }
    );


bevResizeObserver.observe(
    bevContainer
);


loadZones();


/* =========================================================
 * INITIALIZE
 * =========================================================
 */


updateLabels();