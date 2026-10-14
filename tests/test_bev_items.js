const assert = require("node:assert/strict");
const { test } = require("node:test");
const { collapseBevItems, detectionLabel, globalVehicleLabel } = require("../web/bev_items.js");

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
