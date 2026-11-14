"""Poses of the parts in the device frame, and collision checks between them."""

import numpy as np
from manifold3d import Manifold

import parts
from design import DESIGN, Design


def about_lateral_axis(solid: Manifold, centre_xz, angle_rad: float) -> Manifold:
    """Rotate in the side view (counter-clockwise positive, seen with +x right and +z up)."""
    cx, cz = centre_xz
    return solid.translate((-cx, 0, -cz)).rotate((0, -np.degrees(angle_rad), 0)).translate((cx, 0, cz))


class Assembly:
    def __init__(self, d: Design = DESIGN):
        self.d = d
        self.base = parts.plate_to_device(parts.base(d))
        self.lever_closed = parts.plate_to_device(parts.lever(d))
        self.upper = parts.upper_mouthpiece(d)
        self.lower_tray = parts.lower_tray(d)

    def lever(self, opening_mm: float) -> Manifold:
        return about_lateral_axis(self.lever_closed, self.d.pivot_xz, self.d.lever_rotation_rad(opening_mm))

    def lower(self, opening_mm: float, tilt_rad: float | None = None) -> Manifold:
        d = self.d
        tilt = d.tray_tilt_rad(opening_mm) if tilt_rad is None else tilt_rad
        hinge = d.hinge_in_tray_xz
        tray = about_lateral_axis(self.lower_tray, hinge, -tilt)
        target = d.hinge_xz(opening_mm)
        return tray.translate((target[0] - hinge[0], 0, target[1] - hinge[1]))

    def posed(self, opening_mm: float, tilt_rad: float | None = None) -> dict[str, Manifold]:
        return {"base": self.base, "lever": self.lever(opening_mm), "upper": self.upper, "lower": self.lower(opening_mm, tilt_rad)}

    def screw_tip_offset_mm(self, limit_opening_mm: float) -> float:
        """Position of the screw tip along the screw axis (base-handle frame, up positive) when it
        stops the lever at the given opening."""
        d = self.d
        remaining = d.max_lever_rotation_rad - d.lever_rotation_rad(limit_opening_mm)
        on_axis = -d.pivot_to_lever_edge_mm / np.cos(remaining) - d.screw_distance_from_pivot_mm * np.tan(remaining)
        return on_axis + parts.SCREW_TIP_END_RADIUS_MM * np.tan(remaining)  # the tip's edge touches first

    def hardware(self, limit_opening_mm: float) -> dict[str, Manifold]:
        d = self.d
        up_angle = np.degrees(np.arctan2(d.base_handle_up[1], d.base_handle_up[0]))

        def along_screw_axis(solid: Manifold, offset_mm: float) -> Manifold:
            origin = d.screw_axis_point_xz + offset_mm * d.base_handle_up
            placed = solid.rotate((0, 90, 0)).rotate((0, 0, up_angle)).translate((origin[0], origin[1], 0))
            return parts.plate_to_device(placed)

        screw_length = parts.SCREW_KNOB_HEIGHT_MM + parts.SCREW_THREAD_LENGTH_MM + parts.SCREW_TIP_LENGTH_MM
        screw = parts.limit_screw(d).rotate((180, 0, 0)).translate((0, 0, screw_length))  # tip at z = 0, knob up
        nut = parts.limit_nut(d).translate((0, 0, -d.nut_thickness_mm / 2))
        half_width = d.base_width_mm / 2

        def pin_at(centre_xz) -> Manifold:
            pin = parts.snap_pin(d.base_width_mm, d).rotate((0, 0, 90)).translate((centre_xz[0], -half_width, centre_xz[1]))
            return pin

        tip_offset = self.screw_tip_offset_mm(limit_opening_mm)
        # turn the screw until its thread meshes with the nut at this setting
        turned = min(
            (screw.rotate((0, 0, angle)) for angle in range(0, 360, 10)),
            key=lambda candidate: (candidate.translate((0, 0, tip_offset - parts.nut_centre_offset_mm(d))) ^ nut).volume(),
        )
        return {
            "screw": along_screw_axis(turned, tip_offset),
            "nut": along_screw_axis(nut, parts.nut_centre_offset_mm(d)),
            "pin_pivot": pin_at(d.pivot_xz),
            "pin_mouthpiece": pin_at(d.mouthpiece_pin_xz),
        }

    def interference_mm3(self, opening_mm: float, tilt_rad: float | None = None) -> dict[str, float]:
        posed = self.posed(opening_mm, tilt_rad)
        names = list(posed)
        return {f"{a}-{b}": (posed[a] ^ posed[b]).volume() for i, a in enumerate(names) for b in names[i + 1 :]}
