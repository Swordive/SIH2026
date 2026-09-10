"""
Geofencing helper for attendance check-in.

Compares the GPS coordinates an inspector's device reports at
check-in time against a project's registered site coordinates (i.e.
the physical location where that project's CCTV feed actually is)
to catch check-ins made from somewhere else entirely -- an admin's
desk, home, a different site, etc.
"""
import math

EARTH_RADIUS_METERS = 6_371_000

# How far a check-in is allowed to be from the registered site before
# it's flagged as an anomaly. Generous enough to absorb ordinary GPS
# drift/inaccuracy on a phone, tight enough to catch "not actually
# there".
GEOFENCE_RADIUS_METERS = 250


def distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in meters."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_METERS * c


def is_within_geofence(lat1: float, lon1: float, lat2: float, lon2: float) -> bool:
    return distance_meters(lat1, lon1, lat2, lon2) <= GEOFENCE_RADIUS_METERS
