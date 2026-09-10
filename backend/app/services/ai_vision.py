"""
Lightweight, fully-offline computer-vision helpers for the
"AI-based anomaly and attendance analytics" feature area of the
problem statement.

Deliberately built on OpenCV's bundled Haar Cascade face detector
rather than a hosted face-recognition API: the model file ships
inside the opencv-python-headless wheel itself (cv2.data.haarcascades),
so this runs with no network call, no API key, and no third-party
service -- identical behaviour in an offline field deployment and in
a demo.

Scope note: this is PRESENCE detection ("is there a human face in
this photo, and how many"), used as a cheap proxy-attendance check --
not IDENTITY verification ("is this a photo of inspector X
specifically"). Real identity matching would need a registered
reference photo per inspector and a face-recognition/embedding model
(e.g. face_recognition/dlib or a hosted API); that's a natural next
step once this groundwork -- the check-in photo capture, the
Inspection columns, and the alert wiring -- is in place.
"""
from dataclasses import dataclass

import cv2
import numpy as np

_face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)


class InvalidImageError(ValueError):
    """Raised when the given bytes can't be decoded as an image."""


@dataclass
class FaceDetectionResult:
    face_count: int
    boxes: list[tuple[int, int, int, int]]  # (x, y, w, h) per detected face


def detect_faces(image_bytes: bytes) -> FaceDetectionResult:
    """Runs Haar Cascade frontal-face detection on raw image bytes
    (as read straight from an uploaded file). Raises InvalidImageError
    if the bytes don't decode as an image OpenCV can read."""
    if not image_bytes:
        raise InvalidImageError("Empty image")

    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise InvalidImageError("Could not decode image data")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)  # evens out harsh/uneven field lighting

    detections = _face_cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40)
    )
    boxes = [tuple(int(v) for v in box) for box in detections]
    return FaceDetectionResult(face_count=len(boxes), boxes=boxes)
