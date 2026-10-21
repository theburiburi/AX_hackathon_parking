"""
car / truck 중복 검출 제거 (src/detection/detector.py).
모델을 불러오지 않고 중복 제거 함수만 확인한다.
"""

from types import SimpleNamespace

from src.detection.detector import Detection, VehicleDetector, box_iou


def detection(class_name, confidence, x1, y1, x2, y2):

    return Detection(0, class_name, confidence, x1, y1, x2, y2)


def remove(detections, threshold=0.70):

    return VehicleDetector._remove_cross_class_duplicates(
        SimpleNamespace(class_agnostic_iou=threshold),
        detections,
    )


def test_box_iou():

    a = detection("car", 0.9, 0, 0, 10, 10)
    b = detection("car", 0.9, 5, 0, 15, 10)

    assert box_iou(a, a) == 1.0
    assert abs(box_iou(a, b) - 50 / 150) < 1e-9
    assert box_iou(a, detection("car", 0.9, 20, 20, 30, 30)) == 0.0


def test_same_vehicle_car_and_truck_keeps_higher_confidence():

    car = detection("car", 0.91, 0, 0, 100, 50)
    truck = detection("truck", 0.55, 1, 1, 100, 50)

    assert remove([truck, car]) == [car]


def test_different_vehicles_are_kept():

    left = detection("car", 0.9, 0, 0, 100, 50)
    right = detection("truck", 0.8, 60, 0, 160, 50)  # IoU 0.25

    assert len(remove([left, right])) == 2


def test_zero_threshold_disables():

    car = detection("car", 0.91, 0, 0, 100, 50)
    truck = detection("truck", 0.55, 0, 0, 100, 50)

    assert remove([car, truck], threshold=0.0) == [car, truck]
