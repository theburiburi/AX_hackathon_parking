const assert = require("node:assert/strict");
const { test } = require("node:test");
const { collapseBevItems, detectionLabel, globalVehicleColor, globalVehicleLabel, isExpiredParked, pathUntil } = require("../web/bev_items.js");

test("parked cars disappear 15 s after becoming PARKED", () => {
    assert.equal(isExpiredParked({ state: "PARKED", stopped_seconds: 19.9 }), false);
    assert.equal(isExpiredParked({ state: "PARKED", stopped_seconds: 20 }), true);
    assert.equal(isExpiredParked({ state: "STOPPED", stopped_seconds: 60 }), false);
});

test("vehicle numbers appear only for assigned Global IDs", () => {
    assert.equal(globalVehicleLabel(1), "G001");
    assert.equal(globalVehicleLabel(12), "G012");
    assert.equal(globalVehicleLabel(null), null);
    assert.equal(globalVehicleLabel(undefined), null);
});

test("overlapping cameras draw one marker for a shared Global ID", () => {
    const items = collapseBevItems([
        { camera_id: "cam01", local_id: 1, global_id: 3, state: "ACTIVE", x: 100, y: 50 },
        { camera_id: "cam07", local_id: 8, global_id: 3, state: "ACTIVE", x: 110, y: 54 },
        { camera_id: "cam07", local_id: 9, global_id: 4, state: "ACTIVE", x: 115, y: 55 },
    ]);
    assert.equal(items.length, 2);
    assert.deepEqual([items[0].x, items[0].y], [105, 52]);
    assert.equal(items[1].global_id, 4);
});

test("confirmed IDs win over provisional candidates, which are marked", () => {
    assert.deepEqual(detectionLabel({ global_id: 2, provisional_global_id: 5 }),
        { text: "G002", provisional: false });
    assert.deepEqual(detectionLabel({ global_id: null, provisional_global_id: 2 }),
        { text: "G002?", provisional: true });
    assert.equal(detectionLabel({ global_id: null, provisional_global_id: null }), null);
    assert.deepEqual(detectionLabel({ global_id: null, provisional_global_id: 4, candidate_global_id: 7 }),
        { text: "G004?", provisional: true });
    assert.deepEqual(detectionLabel({ global_id: null, provisional_global_id: null, candidate_global_id: 7 }),
        { text: "G007?", provisional: true });
});

test("cam07 position wins over cam02 for a shared Global ID", () => {
    for (const order of [["cam02", "cam07"], ["cam07", "cam02"]]) {
        const items = collapseBevItems(order.map(camera_id => ({
            camera_id, local_id: 1, global_id: 5, state: "ACTIVE",
            x: camera_id === "cam07" ? 200 : 260, y: camera_id === "cam07" ? 80 : 120,
        })));
        assert.equal(items.length, 1);
        assert.deepEqual([items[0].x, items[0].y], [200, 80]);
    }
    const alone = collapseBevItems([
        { camera_id: "cam02", local_id: 1, global_id: 5, state: "ACTIVE", x: 260, y: 120 },
    ]);
    assert.deepEqual([alone[0].x, alone[0].y], [260, 120]);
});

test("parked cars stay on the BEV map with their Global ID", () => {
    const items = collapseBevItems([
        { camera_id: "cam08", local_id: 36, global_id: 2, state: "PARKED", x: 370, y: 150 },
        { camera_id: "cam03", local_id: 71, global_id: 2, state: "ACTIVE", x: 380, y: 150 },
        { camera_id: "cam06", local_id: 4, global_id: null, state: "STOPPED", x: 10, y: 10 },
    ]);
    assert.equal(items.length, 2);
    assert.equal(items[0].state, "ACTIVE");
    assert.equal(items[1].state, "STOPPED");
});

test("path mode draws up to the current frame and links camera gaps", () => {
    const points = [[0, 0, 0], [3, 10, 0], [6, 20, 0], [90, 80, 40], [93, 90, 40], [96, 99, 40]];
    const early = pathUntil(points, 4, 30);
    assert.deepEqual(early.runs, [[[0, 0], [10, 0]]]);
    assert.deepEqual(early.gaps, []);
    assert.deepEqual(early.last, [10, 0]);

    const late = pathUntil(points, 93, 30);
    assert.deepEqual(late.runs, [[[0, 0], [10, 0], [20, 0]], [[80, 40], [90, 40]]]);
    assert.deepEqual(late.gaps, [[[20, 0], [80, 40]]]);
    assert.deepEqual(late.last, [90, 40]);
    assert.equal(pathUntil(points, -1, 30).last, null);
});

test("a Global ID keeps one color whichever camera sees it", () => {
    assert.equal(globalVehicleColor(7), globalVehicleColor("7"));
    assert.notEqual(globalVehicleColor(1), globalVehicleColor(2));
    assert.equal(globalVehicleColor(1), globalVehicleColor(11));
    assert.equal(globalVehicleColor(null), null);
});
