"""
Perceptual-hash based duplicate-photo detection.

Used to flag attendance check-in selfies that look like the same
photo reused across multiple check-ins -- a classic proxy-attendance
pattern: take one photo once, then resubmit it (or a lightly-cropped/
recompressed copy of it) at every future check-in instead of taking a
fresh one each time.

Uses a difference hash (dHash): shrink the image to a tiny grayscale
grid and record which adjacent pixels get brighter left-to-right. Two
copies of the same photo -- even resized, recompressed, or with a
slightly different JPEG quality -- hash to the same or a very close
value; two genuinely different photos (including two different real
selfies of the same person) hash to very different values. No
network, no external model, no extra dependency -- just OpenCV/numpy,
already required for face detection.
"""
import cv2
import numpy as np

HASH_GRID = 8  # 8x8 -> 64-bit hash

# Two check-in selfies with a Hamming distance at or below this, out
# of 64 bits, are treated as "the same photo". Chosen to absorb minor
# recompression/resize noise while still requiring the images to be
# essentially identical -- two different photos of the same person in
# the same room will comfortably exceed this.
DUPLICATE_THRESHOLD = 6


def compute_phash(image_bytes: bytes) -> str:
    """Returns a 64-bit difference hash as a 16-character hex string."""
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError("Could not decode image data")

    resized = cv2.resize(
        image, (HASH_GRID + 1, HASH_GRID), interpolation=cv2.INTER_AREA
    )
    diff = resized[:, 1:] > resized[:, :-1]
    bits = "".join("1" if v else "0" for v in diff.flatten())
    return f"{int(bits, 2):016x}"


def hamming_distance(hash_a: str, hash_b: str) -> int:
    return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")


def is_duplicate(hash_a: str, hash_b: str) -> bool:
    return hamming_distance(hash_a, hash_b) <= DUPLICATE_THRESHOLD
