"""Side-view (sagittal plane) kinematics of the jaw stretcher.

Frame: origin at the upper incisal edge on the upper tray's tooth surface,
+x out of the mouth (anterior), +z up.  All lengths in mm, angles in radians.
"""

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq, least_squares


def rotation(angle_rad: float) -> np.ndarray:
    c, s = np.cos(angle_rad), np.sin(angle_rad)
    return np.array([[c, -s], [s, c]])


def rotate_about(point, centre, angle_rad):
    centre = np.asarray(centre, float)
    return centre + rotation(angle_rad) @ (np.asarray(point, float) - centre)


@dataclass(frozen=True)
class JawModel:
    """Habitual mouth opening approximated as rotation about one fixed centre.

    The effective centre sits near the mandibular foramen, which reproduces
    the usual incisal path: straight down at first, then increasingly back
    (about 14 mm posterior at 45 mm opening).
    """

    centre_xz: tuple[float, float] = (-78.0, -4.0)
    lower_incisal_edge_closed_xz: tuple[float, float] = (-2.5, 0.0)

    def jaw_angle_rad(self, opening_mm: float) -> float:
        """Mandible rotation (positive = opening) for an interincisal opening."""

        def residual(angle):
            edge = rotate_about(self.lower_incisal_edge_closed_xz, self.centre_xz, -angle)
            return -edge[1] - opening_mm

        return brentq(residual, -0.2, 1.2)

    def mandible_point(self, point_closed_xz, opening_mm: float) -> np.ndarray:
        return rotate_about(point_closed_xz, self.centre_xz, -self.jaw_angle_rad(opening_mm))


def fit_lever_pivot(target_points: np.ndarray, lever_length_mm: float, initial_xz) -> np.ndarray:
    """Pivot whose circle of the given radius best fits the target path."""

    def residuals(pivot):
        return np.linalg.norm(target_points - pivot, axis=1) - lever_length_mm

    return least_squares(residuals, np.asarray(initial_xz, float)).x
