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
 * 영상끼리 이 이상 차이가 나면
 * 전체 동기화를 다시 수행한다.
 *
 * 30 FPS 기준:
 * 1 frame ≈ 0.033초
 *
 * 0.08초는 약 2.4 frame.
 */
const MAX_DRIFT_SECONDS = 0.08;


/*
 * seek 완료 후 목표 지점과 이 정도 이하 차이면
 * 정상적으로 이동한 것으로 본다.
 */
const SEEK_TOLERANCE_SECONDS = 0.03;


/*
 * 재생 중 영상 간 drift 검사 주기
 */
const DRIFT_CHECK_INTERVAL_MS = 200;


/*
 * 재생 준비 여부 확인 주기
 */
const READY_CHECK_INTERVAL_MS = 50;


/*
 * 동기화 작업이 무한 대기하지 않도록 하는 제한.
 */
const READY_TIMEOUT_MS = 10000;


/*
 * 현재 영상 메타데이터가 준비된 개수
 */
let readyCount = 0;


/*
 * 7개 영상이 공통으로 재생 가능한 최대 길이
 */
let duration = 0;


/*
 * 사용자가 재생 상태를 원하는지.
 *
 * buffering 때문에 실제 영상이 멈춰 있더라도
 * 사용자가 Pause를 누르지 않았다면 true.
 */
let wantsToPlay = false;


/*
 * 현재 실제로 7개 영상이 재생되고 있는지.
 */
let actuallyPlaying = false;


/*
 * 전체 영상의 논리적인 공통 시간.
 */
let masterTime = 0;


/*
 * requestAnimationFrame ID
 */
let animationFrame = null;


/*
 * drift 검사 시간
 */
let lastDriftCheck = 0;


/*
 * seek / resync 같은 비동기 작업의 세대 번호.
 *
 * 사용자가 재생바를 빠르게 여러 번 움직일 경우
 * 이전 작업 결과가 뒤늦게 적용되는 것을 막는다.
 */
let operationId = 0;


/*
 * 이미 복구 작업이 수행 중인지.
 */
let recovering = false;


/*
 * 내부 pause() 때문에 발생한 pause 이벤트와
 * 예상하지 못한 pause 이벤트를 구분한다.
 */
let internalPause = false;


/*
 * 같은 buffering 복구 요청이 중복으로 실행되는 것을 막는다.
 */
let resumeTimer = null;


/* =========================================================
 * 기본 Utility
 * =========================================================
 */


function formatTime(seconds) {

    if (!Number.isFinite(seconds)) {
        return "00:00.000";
    }


    const safeSeconds =
        Math.max(0, seconds);


    const minutes =
        Math.floor(
            safeSeconds / 60
        );


    const remaining =
        safeSeconds % 60;


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

    const number =
        Number(value);


    if (!Number.isFinite(number)) {
        return 0;
    }


    if (duration <= 0) {
        return Math.max(
            0,
            number
        );
    }


    return Math.min(
        Math.max(
            0,
            number
        ),
        duration
    );
}


function sleep(ms) {

    return new Promise(
        resolve => {
            setTimeout(
                resolve,
                ms
            );
        }
    );
}


/* =========================================================
 * 상태 표시
 * =========================================================
 */


function setStatus(
    text,
    ready = false
) {

    cameraStatus.textContent =
        text;


    cameraStatus.classList.remove(
        "loading",
        "ready"
    );


    if (ready) {
        cameraStatus.classList.add(
            "ready"
        );
    }
    else {
        cameraStatus.classList.add(
            "loading"
        );
    }
}


function updateLabels() {

    const text =
        formatTime(masterTime);


    currentTimeLabel.textContent =
        text;


    timeline.value =
        masterTime;


    for (
        const label
        of cameraTimeLabels
    ) {

        label.textContent =
            text;
    }
}


/* =========================================================
 * 영상 상태
 * =========================================================
 */


function allMetadataLoaded() {

    return videos.every(
        video =>
            Number.isFinite(
                video.duration
            )
            &&
            video.duration > 0
    );
}


function videoCanStart(video) {

    return (
        !video.seeking
        &&
        !video.ended
        &&
        video.readyState
        >=
        HTMLMediaElement.HAVE_CURRENT_DATA
    );
}


function allVideosCanStart() {

    return videos.every(
        video =>
            videoCanStart(video)
    );
}


function getVideoTimes() {

    return videos
        .filter(
            video =>
                Number.isFinite(
                    video.currentTime
                )
        )
        .map(
            video =>
                video.currentTime
        );
}


/*
 * 현재 실제 공통 재생 시간.
 *
 * 가장 느린 영상을 기준으로 한다.
 *
 * 예:
 *
 * CAM01 10.050
 * CAM02 10.047
 * CAM03 10.051
 * CAM07 10.010  <- buffering 직전
 *
 * masterTime = 10.010
 *
 * 따라서 한 영상이 진행하지 않으면
 * 화면 시간도 앞서 나가지 않는다.
 */
function updateMasterFromVideos() {

    const times =
        getVideoTimes();


    if (times.length === 0) {
        return;
    }


    masterTime =
        clampTime(
            Math.min(...times)
        );
}


/*
 * 가장 앞선 영상과
 * 가장 느린 영상의 시간 차이.
 */
function getMaxDrift() {

    const times =
        getVideoTimes();


    if (times.length < 2) {
        return 0;
    }


    const min =
        Math.min(...times);

    const max =
        Math.max(...times);


    return max - min;
}


/* =========================================================
 * 전체 Pause
 * =========================================================
 */


function pauseAllVideos() {

    internalPause = true;


    for (const video of videos) {

        if (!video.paused) {
            video.pause();
        }


        video.playbackRate = 1;
    }


    internalPause = false;
}


/*
 * 실제 재생을 멈춘다.
 *
 * wantsToPlay은 변경하지 않는다.
 *
 * buffering 때문에 일시적으로 멈출 때 사용.
 */
function freezePlayback() {

    if (actuallyPlaying) {

        updateMasterFromVideos();
    }


    actuallyPlaying = false;


    cancelAnimationFrame(
        animationFrame
    );


    animationFrame = null;


    pauseAllVideos();


    updateLabels();
}


/* =========================================================
 * Seek Barrier
 * =========================================================
 */


function seekSingleVideo(
    video,
    targetTime
) {

    return new Promise(
        resolve => {

            const safeTarget =
                Math.min(
                    targetTime,
                    video.duration || targetTime
                );


            /*
             * 이미 목표 위치라면
             * seek 작업 불필요.
             */
            if (
                !video.seeking
                &&
                Math.abs(
                    video.currentTime
                    -
                    safeTarget
                )
                <=
                SEEK_TOLERANCE_SECONDS
            ) {

                resolve();

                return;
            }


            let resolved = false;


            const finish = () => {

                if (resolved) {
                    return;
                }


                resolved = true;


                video.removeEventListener(
                    "seeked",
                    handleSeeked
                );


                clearTimeout(
                    timeout
                );


                resolve();
            };


            const handleSeeked = () => {

                finish();
            };


            const timeout =
                setTimeout(
                    () => {

                        console.warn(
                            "Seek timeout:",
                            video.id
                        );


                        finish();

                    },
                    READY_TIMEOUT_MS
                );


            video.addEventListener(
                "seeked",
                handleSeeked,
                {
                    once: true
                }
            );


            try {

                video.currentTime =
                    safeTarget;

            }
            catch (error) {

                console.error(
                    "Seek failed:",
                    video.id,
                    error
                );


                finish();
            }
        }
    );
}


/*
 * 7개 영상 전부가 목표 시간으로 이동할 때까지 기다린다.
 */
async function seekAllVideos(
    targetTime,
    currentOperation
) {

    const safeTarget =
        clampTime(targetTime);


    await Promise.all(
        videos.map(
            video =>
                seekSingleVideo(
                    video,
                    safeTarget
                )
        )
    );


    /*
     * 기다리는 사이 새로운 seek가 발생했다면
     * 현재 작업은 폐기.
     */
    if (
        currentOperation
        !==
        operationId
    ) {

        return false;
    }


    masterTime =
        safeTarget;


    updateLabels();


    return true;
}


/* =========================================================
 * 재생 준비 Barrier
 * =========================================================
 */


async function waitUntilAllReady(
    currentOperation
) {

    const startedAt =
        performance.now();


    while (true) {

        if (
            currentOperation
            !==
            operationId
        ) {

            return false;
        }


        if (!wantsToPlay) {

            return false;
        }


        if (allVideosCanStart()) {

            return true;
        }


        if (
            performance.now()
            -
            startedAt
            >
            READY_TIMEOUT_MS
        ) {

            console.warn(
                "Video ready timeout"
            );


            return false;
        }


        await sleep(
            READY_CHECK_INTERVAL_MS
        );
    }
}


/* =========================================================
 * 동기 재생
 * =========================================================
 */


async function playAllTogether(
    currentOperation
) {

    if (
        currentOperation
        !==
        operationId
    ) {

        return;
    }


    if (!wantsToPlay) {

        return;
    }


    /*
     * 재생 직전에 7개 영상 모두
     * 정확히 masterTime으로 다시 이동.
     */

    setStatus(
        "Synchronizing 7 cameras..."
    );


    pauseAllVideos();


    const seekSuccess =
        await seekAllVideos(
            masterTime,
            currentOperation
        );


    if (!seekSuccess) {
        return;
    }


    const ready =
        await waitUntilAllReady(
            currentOperation
        );


    if (!ready) {

        if (
            currentOperation
            ===
            operationId
            &&
            wantsToPlay
        ) {

            scheduleResumeCheck();
        }


        return;
    }


    if (
        currentOperation
        !==
        operationId
    ) {

        return;
    }


    /*
     * Promise.all로 7개 play를 한 번에 요청.
     */

    try {

        await Promise.all(
            videos.map(
                video => {

                    video.playbackRate = 1;

                    return video.play();
                }
            )
        );

    }
    catch (error) {

        console.warn(
            "Playback start delayed:",
            error
        );


        freezePlayback();

        scheduleResumeCheck();

        return;
    }


    if (
        currentOperation
        !==
        operationId
    ) {

        pauseAllVideos();

        return;
    }


    actuallyPlaying = true;

    recovering = false;


    playButton.textContent =
        "일시정지";


    setStatus(
        `${videos.length} / ${videos.length} cameras synchronized`,
        true
    );


    lastDriftCheck =
        performance.now();


    cancelAnimationFrame(
        animationFrame
    );


    animationFrame =
        requestAnimationFrame(
            playbackLoop
        );
}


/* =========================================================
 * 재생 Loop
 * =========================================================
 */


function playbackLoop(timestamp) {

    if (
        !actuallyPlaying
        ||
        !wantsToPlay
    ) {

        return;
    }


    /*
     * 실제 영상 시간을 기준으로
     * masterTime을 갱신한다.
     *
     * 별도의 wall clock을 사용하지 않는다.
     */

    updateMasterFromVideos();


    updateLabels();


    /*
     * 공통 끝 지점
     */

    if (
        duration > 0
        &&
        masterTime
        >=
        duration
        - 0.02
    ) {

        wantsToPlay = false;

        freezePlayback();

        masterTime =
            duration;

        updateLabels();

        playButton.textContent =
            "재생";

        return;
    }


    /*
     * 주기적으로 drift 확인
     */

    if (
        timestamp
        -
        lastDriftCheck
        >=
        DRIFT_CHECK_INTERVAL_MS
    ) {

        lastDriftCheck =
            timestamp;


        const drift =
            getMaxDrift();


        if (
            drift
            >
            MAX_DRIFT_SECONDS
        ) {

            console.warn(
                `Camera drift detected: ${
                    (
                        drift * 1000
                    ).toFixed(1)
                } ms`
            );


            recoverSynchronization();

            return;
        }
    }


    animationFrame =
        requestAnimationFrame(
            playbackLoop
        );
}


/* =========================================================
 * Drift / Buffering 복구
 * =========================================================
 */


async function recoverSynchronization() {

    if (recovering) {
        return;
    }


    if (!wantsToPlay) {
        return;
    }


    recovering = true;


    /*
     * 가장 느린 영상 시점에서
     * 전체를 다시 맞춘다.
     */

    updateMasterFromVideos();


    freezePlayback();


    setStatus(
        "Resynchronizing..."
    );


    operationId += 1;


    const currentOperation =
        operationId;


    await playAllTogether(
        currentOperation
    );
}


/*
 * buffering 중에는 계속 시간을 증가시키지 않고,
 * 모든 영상이 다시 준비됐는지만 확인한다.
 */
function scheduleResumeCheck() {

    if (!wantsToPlay) {
        return;
    }


    if (resumeTimer !== null) {
        return;
    }


    resumeTimer =
        setTimeout(
            async () => {

                resumeTimer = null;


                if (!wantsToPlay) {
                    return;
                }


                if (!allVideosCanStart()) {

                    scheduleResumeCheck();

                    return;
                }


                operationId += 1;


                const currentOperation =
                    operationId;


                recovering = true;


                await playAllTogether(
                    currentOperation
                );

            },
            READY_CHECK_INTERVAL_MS
        );
}


/*
 * 어느 한 영상이라도 waiting/stalled 상태가 되면
 * 전부 정지한다.
 */
function handleBuffering(video) {

    if (!wantsToPlay) {
        return;
    }


    console.log(
        "Buffering:",
        video.id
    );


    updateMasterFromVideos();


    freezePlayback();


    recovering = true;


    setStatus(
        `Waiting for ${video.id}...`
    );


    scheduleResumeCheck();
}


/* =========================================================
 * 사용자 Play / Pause
 * =========================================================
 */


async function startPlayback() {

    if (!allMetadataLoaded()) {
        return;
    }


    wantsToPlay = true;


    operationId += 1;


    const currentOperation =
        operationId;


    recovering = true;


    await playAllTogether(
        currentOperation
    );
}


function pausePlayback() {

    /*
     * 사용자가 직접 Pause했으므로
     * 자동 재개 금지.
     */

    wantsToPlay = false;


    operationId += 1;


    recovering = false;


    if (resumeTimer !== null) {

        clearTimeout(
            resumeTimer
        );

        resumeTimer = null;
    }


    updateMasterFromVideos();


    freezePlayback();


    playButton.textContent =
        "재생";


    setStatus(
        `${videos.length} / ${videos.length} cameras ready`,
        true
    );
}


function togglePlayback() {

    if (wantsToPlay) {

        pausePlayback();

    }
    else {

        startPlayback();
    }
}


/* =========================================================
 * 사용자 Seek
 * =========================================================
 */


async function seekTo(value) {

    const targetTime =
        clampTime(
            value
        );


    /*
     * seek하기 전에 사용자가 재생 중이었는지 기억.
     */

    const resumeAfterSeek =
        wantsToPlay;


    operationId += 1;


    const currentOperation =
        operationId;


    recovering = true;


    /*
     * 모든 영상 즉시 정지.
     *
     * 이 순간부터 master clock도 움직이지 않는다.
     */

    updateMasterFromVideos();


    actuallyPlaying = false;


    cancelAnimationFrame(
        animationFrame
    );


    animationFrame = null;


    pauseAllVideos();


    masterTime =
        targetTime;


    updateLabels();


    setStatus(
        "Seeking all cameras..."
    );


    /*
     * 7개 모두 seek 완료될 때까지 대기
     */

    const seekSuccess =
        await seekAllVideos(
            targetTime,
            currentOperation
        );


    if (!seekSuccess) {
        return;
    }


    /*
     * 사용자가 seek 도중 Pause를 눌렀거나
     * 또 다른 seek를 했다면 여기서 중단.
     */

    if (
        currentOperation
        !==
        operationId
    ) {

        return;
    }


    recovering = false;


    /*
     * seek 전에 재생 중이었다면
     * 7개 모두 준비된 후 함께 재생.
     */

    if (
        resumeAfterSeek
        &&
        wantsToPlay
    ) {

        recovering = true;


        await playAllTogether(
            currentOperation
        );

    }
    else {

        setStatus(
            `${videos.length} / ${videos.length} cameras ready`,
            true
        );


        playButton.textContent =
            "재생";
    }
}


function seekRelative(seconds) {

    seekTo(
        masterTime + seconds
    );
}


function resetPlayback() {

    /*
     * Reset은 항상 정지 상태로 이동.
     */

    pausePlayback();


    seekTo(0);
}


/* =========================================================
 * Metadata
 * =========================================================
 */


function updateReadyState() {

    readyCount =
        videos.filter(
            video =>
                Number.isFinite(
                    video.duration
                )
                &&
                video.duration > 0
        ).length;


    setStatus(
        `${readyCount} / ${videos.length} cameras ready`,
        readyCount === videos.length
    );


    if (
        readyCount
        !==
        videos.length
    ) {

        return;
    }


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


    masterTime = 0;


    updateLabels();
}


/* =========================================================
 * Video Event 등록
 * =========================================================
 */


for (const video of videos) {

    /*
     * 기본 브라우저 컨트롤은 사용하지 않는다.
     */

    video.controls = false;


    video.addEventListener(
        "loadedmetadata",
        updateReadyState
    );


    /*
     * 실제로 데이터가 부족해서 재생이 멈추는 경우.
     */

    video.addEventListener(
        "waiting",
        () => {

            handleBuffering(
                video
            );
        }
    );


    video.addEventListener(
        "stalled",
        () => {

            handleBuffering(
                video
            );
        }
    );


    /*
     * 예상하지 못한 개별 영상 Pause 방지.
     */

    video.addEventListener(
        "pause",
        () => {

            if (internalPause) {
                return;
            }


            if (
                wantsToPlay
                &&
                actuallyPlaying
            ) {

                handleBuffering(
                    video
                );
            }
        }
    );


    /*
     * 영상이 다시 재생 가능한 상태가 되면
     * 7개 전체 상태를 확인.
     */

    video.addEventListener(
        "canplay",
        () => {

            if (
                wantsToPlay
                &&
                !actuallyPlaying
            ) {

                scheduleResumeCheck();
            }
        }
    );


    video.addEventListener(
        "error",
        () => {

            console.error(
                "Video error:",
                video.id,
                video.error
            );


            wantsToPlay = false;


            freezePlayback();


            setStatus(
                `Video error: ${video.id}`
            );


            playButton.textContent =
                "재생";
        }
    );
}


/* =========================================================
 * Button
 * =========================================================
 */


playButton.addEventListener(
    "click",
    () => {

        togglePlayback();
    }
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
    () => {

        resetPlayback();
    }
);


/* =========================================================
 * Timeline
 * =========================================================
 */


timeline.addEventListener(
    "input",
    event => {

        seekTo(
            Number(
                event.target.value
            )
        );
    }
);


/* =========================================================
 * Keyboard
 * =========================================================
 */


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
 * 초기화
 * =========================================================
 */


updateLabels();