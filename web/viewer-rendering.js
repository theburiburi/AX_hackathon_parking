// Drawing code from the repository viewer, shared without a second renderer.
// Tracking, state classification and BEV projection remain in server.py/src.
import { collapseBevItems, detectionLabel, globalVehicleColor, globalVehicleLabel, isExpiredParked } from "./bev_items.js";
export const STATE_COLORS = {
    UNKNOWN: "#8b929c",
    ACTIVE: "#22e86f",
    STOPPED: "#ffd740",
    PARKED: "#ff4fdb",
};


export const CAMERA_COLORS = {
    cam01: "#ff3b3b",
    cam02: "#ff9800",
    cam03: "#ffeb3b",
    cam05: "#34df65",
    cam06: "#00d9ff",
    cam07: "#4c76ff",
    cam08: "#e34cff",
};

export function drawCameraLabel(
    overlayContext,
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

export function drawDetection(
    overlayContext,
    layout,
    camera,
    detection
) {

    if (isExpiredParked(detection)) {
        return;
    }

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
        3;

    overlayContext.strokeRect(
        x,
        y,
        boxWidth,
        boxHeight
    );

    // Confirmed GIDs stay visible after parking; provisional IDs carry "?".
    const vehicleLabel = detectionLabel(detection);
    if (vehicleLabel === null) {
        return;
    }

    const label = vehicleLabel.text;

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

    const previousAlpha = overlayContext.globalAlpha ?? 1;
    overlayContext.globalAlpha = previousAlpha * (vehicleLabel.provisional ? 0.6 : 1);
    overlayContext.fillText(
        label,
        x + 3,
        labelY + 11
    );
    overlayContext.globalAlpha = previousAlpha;
}

export function drawBevTracking(
    bevContext,
    layout,
    latestTracking
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
        of collapseBevItems(
            latestTracking.bev.filter(item => !isExpiredParked(item))
        )
    ) {

        // Retain parked observations and draw one marker per shared GID.

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

        // GID가 있으면 카메라가 바뀌어도 같은 색, 없으면 카메라 색.
        const cameraColor =
            globalVehicleColor(item.global_id)
            ||
            CAMERA_COLORS[
                item.camera_id
            ]
            ||
            "#ffffff";

        const stateColor =
            STATE_COLORS[item.state] || STATE_COLORS.ACTIVE;

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

        const label = globalVehicleLabel(item.global_id);
        if (label === null) {
            continue;
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
