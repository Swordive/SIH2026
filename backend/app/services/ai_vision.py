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

Known limitation: Haar Cascade only reliably finds close-to-frontal,
unobstructed faces. A person at a sharp head angle, mid-speech, or
with a hand raised near their face can go undetected even though
they're clearly visible to a human -- this is a real accuracy
ceiling of the algorithm itself, not a threshold that can be tuned
away without also reopening the false-positive problem described
above. If that miss rate turns out to matter in practice, the fix is
a proper DNN face detector (e.g. OpenCV's bundled-model-free option
is gone, so this would mean shipping a small detector model file
such as the res10 SSD face detector alongside the app -- still fully
offline, just no longer literally zero extra files) rather than
further Haar parameter tuning.
"""
from dataclasses import dataclass

import cv2
import numpy as np

_face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

# Haar Cascade's minSize threshold is an *absolute* pixel size, not a
# fraction of the image. Modern phone selfies are routinely
# 3000-4000px on the long edge, so a fixed 40x40 minSize is a tiny
# sliver of the frame -- the detector ends up scanning a huge number
# of miniature windows and happily matches clothing wrinkles,
# background clutter, and JPEG noise as "faces" (this is how a photo
# with one real face was getting reported as 17).
#
# Downscaling to a sane working resolution first is what actually
# fixes that -- it's the same fixed minSize, just no longer a tiny
# sliver of a huge image. (An earlier version of this also scaled
# minSize to a *fraction* of the image, on top of the downscale --
# that was an overcorrection: in a group photo, each individual face
# is a much smaller fraction of the frame than in a solo selfie, so it
# ended up excluding every real face and reporting 0. A small fixed
# size on the normalized image handles solo selfies and group photos
# alike.)
#
# 1024 was too aggressive in the other direction: a real check-in
# selfie of 3+ people (a fairly ordinary photo, ~4500px wide, each
# face maybe 100-180px on the long edge) gets downscaled by ~4.4x at
# 1024, which shrinks those real faces to ~25-40px -- right at or
# *below* the 40px minSize floor, so the detector finds nothing at
# all and the check-in was reported as "0 faces detected" despite
# multiple clearly visible faces in frame. 1600 keeps real close-up
# faces comfortably above the floor after downscaling while still
# cutting a 4000px original down enough to avoid the noise-matching
# problem above.
_MAX_DIMENSION = 1600
_MIN_FACE_SIZE = 40


# A face closer to the camera occupies a larger area of the frame --
# that's the basis for the "closest to camera" logic below. A face
# is only counted if it's part of the closest cluster: within
# _CLOSE_CLUSTER_RATIO of the largest detected face's area. A face
# clearly farther back (much smaller) is excluded even though it was
# genuinely detected -- it's someone/something in the background, not
# a subject being checked in. Two (or more) people standing at
# roughly the same distance -- "not perfectly equal, not possible" --
# both clear that bar and both get counted; one dominant face up
# close with others clearly behind it means only that one counts.
#
# 0.7 was the initial guess; testing against a real 3-person photo
# showed it was too strict -- the cascade's box size for the same
# real-world distance varies more than that from head tilt/hair/angle
# alone (three genuinely equally-close faces came back at area ratios
# of 1.0, 0.87, and 0.50 relative to each other), so 0.7 silently
# dropped a real, equally-close face out of the count. A cascade
# false positive in that same test photo (a shirt-collar pattern
# mistaken for a face) came in at 0.23 -- well clear of the real
# faces -- so 0.4 comfortably keeps real close-up faces together
# while still rejecting things that are genuinely much smaller/farther.
_CLOSE_CLUSTER_RATIO = 0.4


class InvalidImageError(ValueError):
    """Raised when the given bytes can't be decoded as an image."""


@dataclass
class FaceDetectionResult:
    face_count: int
    """Count of faces in the closest-to-camera cluster -- see
    _CLOSE_CLUSTER_RATIO above. This is what attendance verification
    should check against: it answers 'how many people are actually
    up at the camera', not 'how many faces appear anywhere in the
    shot' (a photo taken in a busy office would otherwise flag every
    passer-by in the background as a failed check)."""
    total_faces_detected: int
    """Raw count of every face detected anywhere in the frame,
    regardless of distance from the camera -- kept for logging/audit
    so it's possible to tell 'flagged because 2 people were up close'
    apart from 'flagged, but there were also 4 more people in the
    background, for what it's worth'."""
    boxes: list[tuple[int, int, int, int]]
    """(x, y, w, h) for every detected face (not just the close
    cluster), in the coordinate space of the (possibly downscaled)
    image actually run through the cascade. Kept around for
    cropping/training data later, and for debugging."""


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

    height, width = image.shape[:2]
    longest_edge = max(height, width)
    if longest_edge > _MAX_DIMENSION:
        scale = _MAX_DIMENSION / longest_edge
        image = cv2.resize(
            image,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)  # evens out harsh/uneven field lighting

    detections = _face_cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=4, minSize=(_MIN_FACE_SIZE, _MIN_FACE_SIZE)
    )
    boxes = [tuple(int(v) for v in box) for box in detections]

    if not boxes:
        return FaceDetectionResult(face_count=0, total_faces_detected=0, boxes=[])

    areas = [w * h for (_x, _y, w, h) in boxes]
    max_area = max(areas)

    close_cluster = [box for box, area in zip(boxes, areas) if area >= max_area * _CLOSE_CLUSTER_RATIO]

    return FaceDetectionResult(
        face_count=len(close_cluster),
        total_faces_detected=len(boxes),
        boxes=boxes,
    )
