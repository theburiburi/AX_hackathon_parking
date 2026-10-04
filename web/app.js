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


/*
 * 영상 간 차이가 이 값보다 크면
 * currentTime을 강제로 master time에 맞춘다.
 */
const HARD_SYNC_THRESHOLD = 0.15;


/*
 * 이 정도 차이는 브라우저 디코딩 오차로 보고
 * 그대로 둔다.
 */
const IGNORE_SYNC_THRESHOLD = 0.04;


let readyCount = 0;

let duration = 0;

let playing = false;

let masterTime = 0;


/*
 * 재생을 시작한 실제 브라우저 시간
 */
let playStartedAt = 0;


/*
 * 재생 버튼을 눌렀을 당시
 * 영상상의 기준 시간
 */
let playStartedMasterTime = 0;


let animationFrame = null;


function formatTime(seconds) {

    if (!Number.isFinite(seconds)) {
        return "00:00.000";
    }

    const minutes =
        Math.floor(seconds / 60);

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
        return Math.max(0, value);
    }

    return Math.min(
        Math.max(0, value),
        duration
    );
}


function setAllVideosTime(
    targetTime,
    force = false
) {

    const time =
        clampTime(targetTime);


    for (const video of videos) {

        if (
            video.readyState
            <
            HTMLMediaElement.HAVE_METADATA
        ) {
            continue;
        }


        const drift =
            video.currentTime - time;


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


        /*
         * 아주 작은 차이는 무시한다.
         */
        if (
            Math.abs(drift)
            <
            IGNORE_SYNC_THRESHOLD
        ) {
            video.playbackRate = 1;
            continue;
        }


        /*
         * 약간 느린 영상은 조금 빠르게,
         * 앞선 영상은 조금 느리게 맞춘다.
         */

        if (drift < 0) {
            video.playbackRate = 1.02;
        }
        else {
            video.playbackRate = 0.98;
        }
    }
}


function updateLabels() {

    currentTimeLabel.textContent =
        formatTime(masterTime);


    timeline.value =
        masterTime;


    for (
        const label
        of cameraTimeLabels
    ) {

        label.textContent =
            formatTime(masterTime);
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
            now - playStartedAt
        ) / 1000;


    masterTime =
        playStartedMasterTime
        +
        elapsed;


    if (
        duration > 0
        &&
        masterTime >= duration
    ) {

        masterTime = duration;

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

    if (readyCount < videos.length) {
        return;
    }


    setAllVideosTime(
        masterTime,
        true
    );


    const playPromises = [];


    for (const video of videos) {

        video.playbackRate = 1;

        playPromises.push(
            video.play().catch(
                error => {
                    console.error(
                        "Video play failed:",
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
                now - playStartedAt
            ) / 1000;


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

        video.playbackRate = 1;
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


    /*
     * 재생 중에 탐색한 경우
     * master clock 기준도 새로 설정한다.
     */

    if (playing) {

        playStartedAt =
            performance.now();

        playStartedMasterTime =
            masterTime;
    }
}


function seekRelative(seconds) {

    seekTo(
        masterTime + seconds
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


        /*
         * 7개 영상 중 가장 짧은 영상의 길이를
         * 공통 재생 범위로 사용한다.
         */

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
            formatTime(duration);


        playButton.disabled =
            false;


        setAllVideosTime(
            0,
            true
        );
    }
}


for (const video of videos) {

    video.addEventListener(
        "loadedmetadata",
        updateReadyState
    );


    /*
     * 각각의 video 기본 control은 사용하지 않는다.
     */

    video.controls = false;
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