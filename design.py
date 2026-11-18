"""Parametric design of the jaw stretcher.

Side-view frame (the "device frame"): origin at the upper incisal edge on the
upper tray's tooth surface, +x out of the mouth, +z up, y lateral.
All lengths in mm.  Side profiles are drawn with the device fully closed.
"""

from dataclasses import dataclass
from functools import cached_property

import numpy as np
import shapely.affinity
from scipy.optimize import brentq
from shapely.geometry import LineString, Polygon

import geom
from kinematics import JawModel, fit_lever_pivot, rotation


def unit(vector) -> np.ndarray:
    vector = np.asarray(vector, float)
    return vector / np.linalg.norm(vector)


def direction(angle_deg: float) -> np.ndarray:
    return np.array([np.cos(np.radians(angle_deg)), np.sin(np.radians(angle_deg))])


def left_normal(vector) -> np.ndarray:
    return np.array([-vector[1], vector[0]])


def offset_point(point, vector, distance: float) -> tuple[float, float]:
    return tuple(np.asarray(point, float) + distance * np.asarray(vector, float))


@dataclass(frozen=True)
class Design:
    jaw: JawModel = JawModel()

    # --- opening range -------------------------------------------------------
    max_opening_mm: float = 46.0
    scale_first_tick_mm: int = 14

    # --- fits ------------------------------------------------------------------
    sliding_clearance_mm: float = 0.4  # per side; one face of each slot is a bridge and sags a little
    pin_hole_clearance_mm: float = 0.35  # on diameter

    # --- trays -----------------------------------------------------------------
    tray_floor_mm: float = 2.4
    rim_height_mm: float = 2.6
    rim_width_mm: float = 1.6
    tray_depth_mm: float = 25.0  # how far the trays reach back from the incisal edge
    rim_edge_radius_mm: float = 0.4
    channel_width_mm: float = 12.0
    pad_thickness_mm: float = 1.6  # 1/16 in sheet
    pad_to_rim_gap_mm: float = 0.2  # all round the pad
    pad_lip_overhang_mm: float = 0.5  # each rim leans this far over the pad to hold it in
    pad_lip_squeeze_mm: float = 0.2  # how far the lips press into the edge of the pad
    # Both trays share one dental arch, midway between a typical upper and lower one, so one pad fits either.
    # It runs through the tooth centres: (depth behind the incisal edge, half-width)
    arch: tuple[tuple[float, float], ...] = ((0, 0), (1, 5.25), (3, 9.75), (6, 13.5), (9, 15.75), (13, 17.5), (17, 18.85), (21, 20.1), (25, 21.25), (30, 22.5))

    # --- lower tray hinge (bar on the tray, hook on the lever) --------------
    hinge_behind_incisal_edge_mm: float = 17.0
    hinge_bar_radius_mm: float = 2.75
    hinge_bar_centre_below_top_face_mm: float = 1.9  # the bar is flat where it meets the top face
    hook_inner_radius_mm: float = 3.1
    hook_lip_mm: float = 1.8
    hook_crown_mm: float = 4.0
    hook_mouth_clearance_mm: float = 0.2  # per side, around the bar as it slides through the mouth
    hook_mouth_direction_deg: float = 195.0  # points back; the bar only fits through with the tray folded right back

    # --- plates ----------------------------------------------------------------
    lever_thickness_mm: float = 14.0
    base_cheek_mm: float = 5.0
    upper_tray_to_lever_gap_mm: float = 0.5

    # --- pivot and handles ---------------------------------------------------
    lever_length_mm: float = 112.0  # main pivot to the lower tray hinge
    pivot_pin_diameter_mm: float = 8.0
    pivot_to_lever_edge_mm: float = 10.5
    lever_depth_mm: float = 18.0
    base_handle_angle_deg: float = -42.0
    base_handle_length_mm: float = 116.0
    base_handle_depth_mm: float = 20.0
    handle_gap_at_max_opening_mm: float = 5.0
    lever_handle_length_mm: float = 131.0

    # --- limit screw ---------------------------------------------------------
    screw_distance_from_pivot_mm: float = 100.0
    thread_major_diameter_mm: float = 12.0
    thread_pitch_mm: float = 3.0
    thread_depth_mm: float = 1.3
    thread_is_left_handed: bool = False
    # The nut is split, so it grips the screw like a spring and the setting does not drift.
    nut_thread_radial_clearance_mm: float = 0.15
    nut_size_mm: float = 20.0
    nut_thickness_mm: float = 10.0

    # --- base head / upper mouthpiece socket ------------------------------
    head_front_x_mm: float = 24.0
    head_rear_x_mm: float = 51.0
    head_top_z_mm: float = 19.5
    socket_top_z_mm: float = 12.3
    socket_floor_mm: float = 2.1
    tang_length_mm: float = 24.0
    mouthpiece_pin_xz: tuple[float, float] = (32.0, 4.9)

    # ------------------------------------------------------------------ fits
    @property
    def slot_width_mm(self) -> float:
        return self.lever_thickness_mm + 2 * self.sliding_clearance_mm

    @property
    def pad_lip_underside_height_mm(self) -> float:
        """Height above the tray floor at which the rims start to lean over the pad; the lip rises at 45 degrees from here."""
        return self.pad_thickness_mm - self.pad_lip_squeeze_mm - self.pad_to_rim_gap_mm

    @property
    def base_width_mm(self) -> float:
        return self.slot_width_mm + 2 * self.base_cheek_mm

    @property
    def pin_hole_diameter_mm(self) -> float:
        return self.pivot_pin_diameter_mm + self.pin_hole_clearance_mm

    # ------------------------------------------------------------ kinematics
    @property
    def lower_incisal_edge_xz(self) -> np.ndarray:
        return np.array(self.jaw.lower_incisal_edge_closed_xz)

    @property
    def hinge_in_tray_xz(self) -> np.ndarray:
        """Hinge bar centre in the lower-tray frame (origin: lower incisal edge on the tooth plane)."""
        return np.array([-self.hinge_behind_incisal_edge_mm, self.tray_floor_mm - self.hinge_bar_centre_below_top_face_mm])

    def hinge_target_xz(self, opening_mm: float) -> np.ndarray:
        """Where the jaw model puts the hinge bar for a given interincisal opening."""
        return self.jaw.mandible_point(self.lower_incisal_edge_xz + self.hinge_in_tray_xz, opening_mm)

    @cached_property
    def pivot_xz(self) -> np.ndarray:
        openings = np.linspace(14, self.max_opening_mm, 40)
        targets = np.array([self.hinge_target_xz(s) for s in openings])
        guess = targets[len(targets) // 2] + self.lever_length_mm * direction(-21)
        return fit_lever_pivot(targets, self.lever_length_mm, guess)

    def lever_angle_rad(self, opening_mm: float) -> float:
        """Polar angle about the pivot of the hinge bar, for the opening the scale reports."""
        target = self.hinge_target_xz(opening_mm) - self.pivot_xz
        return float(np.arctan2(target[1], target[0]))

    @property
    def closed_hinge_z_mm(self) -> float:
        lever_top_z = -(self.tray_floor_mm + self.upper_tray_to_lever_gap_mm)
        return lever_top_z - self.hook_crown_mm - self.hook_inner_radius_mm

    @cached_property
    def closed_opening_mm(self) -> float:
        """Opening the scale reports with the device fully closed."""
        return brentq(lambda s: self.hinge_xz(s)[1] - self.closed_hinge_z_mm, 5, 30)

    def lever_rotation_rad(self, opening_mm: float) -> float:
        """Lever rotation from the closed pose (positive = opening)."""
        return self.lever_angle_rad(opening_mm) - self.lever_angle_rad(self.closed_opening_mm)

    @property
    def max_lever_rotation_rad(self) -> float:
        return self.lever_rotation_rad(self.max_opening_mm)

    def hinge_xz(self, opening_mm: float) -> np.ndarray:
        """Actual hinge bar centre (on the lever's circle)."""
        return self.pivot_xz + self.lever_length_mm * np.array([np.cos(a := self.lever_angle_rad(opening_mm)), np.sin(a)])

    def tray_tilt_rad(self, opening_mm: float) -> float:
        """Tilt of the lower tray when it lies flat on the lower teeth."""
        return self.jaw.jaw_angle_rad(opening_mm)

    def path_error_mm(self, opening_mm: float) -> float:
        return float(np.linalg.norm(self.hinge_xz(opening_mm) - self.hinge_target_xz(opening_mm)))

    # ------------------------------------------------------------ directions
    @property
    def base_handle_direction(self) -> np.ndarray:
        return direction(self.base_handle_angle_deg)

    @property
    def lever_handle_direction_closed(self) -> np.ndarray:
        return rotation(-self.max_lever_rotation_rad) @ self.base_handle_direction

    @property
    def closed_hinge_xz(self) -> np.ndarray:
        return self.hinge_xz(self.closed_opening_mm)

    # ----------------------------------------------------------- lever outline
    @cached_property
    def lever_top_edge(self) -> list[tuple[float, float]]:
        """Lever top edge from the hinge to the tangent point below the pivot (closed pose)."""
        top_z = -(self.tray_floor_mm + self.upper_tray_to_lever_gap_mm)
        knee = np.array([33.0, -10.5])
        # the straight run to the pivot is tangent to a circle of radius pivot_to_lever_edge around it
        to_pivot = self.pivot_xz - knee
        distance = np.linalg.norm(to_pivot)
        tangent_angle = np.arctan2(to_pivot[1], to_pivot[0]) - np.arcsin(self.pivot_to_lever_edge_mm / distance)
        run = np.sqrt(distance**2 - self.pivot_to_lever_edge_mm**2)
        tangent_point = knee + run * np.array([np.cos(tangent_angle), np.sin(tangent_angle)])
        return [(self.closed_hinge_xz[0] - 1.0, top_z), (20.0, top_z), (24.0, -6.0), tuple(knee), tuple(tangent_point)]

    @property
    def lever_arm_direction(self) -> np.ndarray:
        """Unit vector along the lever arm towards the pivot (closed pose)."""
        return unit(np.subtract(self.lever_top_edge[-1], self.lever_top_edge[-2]))

    def _tray_top_line_z(self, x: float) -> float:
        """Top face of the lower tray in the closed pose, as z(x)."""
        tilt = self.tray_tilt_rad(self.closed_opening_mm)
        normal = np.array([np.sin(tilt), np.cos(tilt)])
        on_face = self.closed_hinge_xz + self.hinge_bar_centre_below_top_face_mm * normal
        return on_face[1] - np.tan(tilt) * (x - on_face[0])

    @property
    def _hook_mouth_edges_mm(self) -> tuple[float, float]:
        """Distances from the hinge centre to the mouth's two edges: flat side of the bar, round side."""
        return (
            self.hinge_bar_centre_below_top_face_mm + self.hook_mouth_clearance_mm,
            self.hinge_bar_radius_mm + self.hook_mouth_clearance_mm,
        )

    @property
    def tray_fitting_tilt_deg(self) -> float:
        """Tilt of the tray relative to the lever tip at which the hinge bar passes the hook mouth."""
        return 90.0 - (self.hook_mouth_direction_deg + 90.0 - 360.0)

    @cached_property
    def hook_shape(self):
        flat_edge, round_edge = self._hook_mouth_edges_mm
        start = self.hook_mouth_direction_deg + 90 - np.degrees(np.arccos(flat_edge / self.hook_inner_radius_mm))
        end = self.hook_mouth_direction_deg - 90 + np.degrees(np.arccos(round_edge / self.hook_inner_radius_mm)) + 360
        return geom.ring_sector(self.closed_hinge_xz, self.hook_inner_radius_mm, self.hook_inner_radius_mm + self.hook_lip_mm, start, end)

    @cached_property
    def hook_mouth_shape(self):
        flat_edge, round_edge = self._hook_mouth_edges_mm
        out = direction(self.hook_mouth_direction_deg)
        flat_side = direction(self.hook_mouth_direction_deg + 90)
        hinge = self.closed_hinge_xz
        return geom.polygon(
            [hinge + flat_edge * flat_side, hinge + flat_edge * flat_side + 12 * out, hinge - round_edge * flat_side + 12 * out, hinge - round_edge * flat_side]
        )

    @cached_property
    def lever_profile(self):
        d = self
        pivot = d.pivot_xz
        top = d.lever_top_edge
        arm = d.lever_arm_direction
        arm_down = -left_normal(arm) if left_normal(arm)[1] > 0 else left_normal(arm)
        hinge = d.closed_hinge_xz

        # mouth and lip zone: flat on top, resting on the lower tray underneath
        rest_clearance = 0.3
        mouth = [
            top[0],
            top[1],
            top[2],
            top[3],
            offset_point(top[3], arm_down, d.lever_depth_mm),
            (15.0, -13.5),
            (9.0, d._tray_top_line_z(9.0) + rest_clearance),
            (hinge[0] + 2.0, d._tray_top_line_z(hinge[0] + 2.0) + rest_clearance),
            (hinge[0] - 1.0, hinge[1] + 1.0),
        ]
        arm_band = [
            top[3],
            offset_point(top[4], arm, 10.0),
            offset_point(offset_point(top[4], arm, 10.0), arm_down, d.lever_depth_mm),
            offset_point(top[3], arm_down, d.lever_depth_mm),
        ]
        handle = d.lever_handle_direction_closed
        handle_down = left_normal(handle) if left_normal(handle)[1] < 0 else -left_normal(handle)
        handle_start = offset_point(offset_point(pivot, handle_down, d.pivot_to_lever_edge_mm), handle, -10.0)
        handle_end = offset_point(offset_point(pivot, handle_down, d.pivot_to_lever_edge_mm), handle, d.lever_handle_length_mm)
        handle_band = [
            handle_start,
            handle_end,
            offset_point(handle_end, handle_down, d.lever_depth_mm),
            offset_point(handle_start, handle_down, d.lever_depth_mm),
        ]
        neck_direction = unit(arm_down + handle_down)
        hump = geom.union_2d([geom.circle(pivot, 9.5), geom.capsule(pivot, offset_point(pivot, neck_direction, 16.0), 19.0)])

        body = geom.union_2d([geom.polygon(mouth), geom.polygon(arm_band), geom.polygon(handle_band), hump])
        body = geom.rounded(body, convex_radius=2.0, concave_radius=3.0)
        # keep the thin tip and the hook crisp
        tip = geom.polygon(mouth).intersection(geom.polygon([(-40, 0), (8, 0), (8, -30), (-40, -30)]))
        body = geom.union_2d([body, geom.rounded(tip, convex_radius=0.6)])
        body = body.difference(geom.circle(hinge, d.hook_inner_radius_mm))
        body = geom.union_2d([body, d.hook_shape]).difference(d.hook_mouth_shape)
        return geom.union_2d([body, d.scale_tab_shape])

    # ------------------------------------------------------------------ scale
    @property
    def scale_pointer_radius_mm(self) -> float:
        return self.scale_tab_inner_radius_mm - 0.8

    @property
    def scale_pointer_angle_deg(self) -> float:
        """Polar angle about the pivot of the pointer tip at the end of the base handle."""
        below = np.degrees(np.arcsin(self.handle_gap_offset_mm / self.scale_pointer_radius_mm))
        return self.base_handle_angle_deg - below

    @property
    def scale_pointer_shape(self):
        along, up = self.base_handle_direction, self.base_handle_up
        tip = self.pivot_xz + self.scale_pointer_radius_mm * direction(self.scale_pointer_angle_deg)
        return geom.rounded(geom.polygon([tip, tip - 6.0 * along, tip - 6.0 * along + 5.0 * up, tip - 2.5 * along + 3.2 * up]), convex_radius=0.3)

    @property
    def handle_gap_offset_mm(self) -> float:
        """Perpendicular distance from the pivot to the base handle's lower edge."""
        return self.pivot_to_lever_edge_mm - self.handle_gap_at_max_opening_mm

    scale_tab_inner_radius_mm: float = 119.0
    scale_tab_outer_radius_mm: float = 131.0

    @cached_property
    def scale_tab_shape(self):
        handle_angle = np.degrees(np.arctan2(*self.lever_handle_direction_closed[::-1]))
        bottom = handle_angle - np.degrees(np.arcsin((self.pivot_to_lever_edge_mm + 4.0) / self.scale_tab_inner_radius_mm))
        tab = geom.ring_sector(self.pivot_xz, self.scale_tab_inner_radius_mm, self.scale_tab_outer_radius_mm, bottom, self.scale_pointer_angle_deg + 1.2, 0.5)
        return geom.rounded(tab, convex_radius=1.0)

    def scale_tick_angle_deg(self, opening_mm: float) -> float:
        """Polar angle about the pivot, in the lever's closed pose, of the tick for an opening."""
        return self.scale_pointer_angle_deg - np.degrees(self.lever_rotation_rad(opening_mm))

    @cached_property
    def scale_engraving(self):
        d = self
        shapes = []
        for opening in range(d.scale_first_tick_mm, int(d.max_opening_mm) + 1, 2):
            angle = d.scale_tick_angle_deg(opening)
            length = 5.0 if opening % 10 == 0 else 2.6
            inner = d.pivot_xz + d.scale_tab_inner_radius_mm * direction(angle)
            outer = d.pivot_xz + (d.scale_tab_inner_radius_mm + length) * direction(angle)
            shapes.append(LineString([inner, outer]).buffer(0.3, cap_style="flat"))
            if opening % 10 == 0:
                label = geom.text_shape(str(opening), 4.2)
                width = label.bounds[2]
                label = shapely.affinity.translate(label, -width / 2, -2.1)
                label = shapely.affinity.rotate(label, angle + 90, origin=(0, 0))  # upright with the handles pointing down
                centre = d.pivot_xz + (d.scale_tab_inner_radius_mm + 8.2) * direction(angle)
                shapes.append(shapely.affinity.translate(label, *centre))
        return geom.union_2d(shapes).intersection(d.scale_tab_shape.buffer(-0.5))

    # ------------------------------------------------------------ base outline
    @property
    def screw_axis_point_xz(self) -> np.ndarray:
        return self.pivot_xz + self.screw_distance_from_pivot_mm * self.base_handle_direction

    @property
    def base_handle_up(self) -> np.ndarray:
        normal = left_normal(self.base_handle_direction)
        return normal if normal[1] > 0 else -normal

    @property
    def screw_boss_depth_mm(self) -> float:
        """Boss under the base handle; it meets the lever handle at maximum opening (hard stop)."""
        return self.handle_gap_at_max_opening_mm

    @cached_property
    def base_profile(self):
        d = self
        pivot = d.pivot_xz
        handle = d.base_handle_direction
        up = d.base_handle_up
        top_offset = d.base_handle_depth_mm - d.handle_gap_offset_mm

        head = geom.polygon(
            [
                (d.head_front_x_mm, -(d.tray_floor_mm + d.socket_floor_mm)),
                (d.head_front_x_mm, 12.5),
                (d.head_front_x_mm + 7.0, d.head_top_z_mm),
                (d.head_rear_x_mm, d.head_top_z_mm),
                (d.head_rear_x_mm, -(d.tray_floor_mm + d.socket_floor_mm)),
            ]
        )
        lever_gap = 1.5
        lever_top = LineString(d.lever_top_edge[2:] + [offset_point(d.lever_top_edge[-1], d.lever_arm_direction, 14.0)])
        arm_bottom = list(lever_top.offset_curve(lever_gap if lever_top.offset_curve(1).centroid.y > lever_top.centroid.y else -lever_gap).coords)
        if arm_bottom[0][0] > arm_bottom[-1][0]:
            arm_bottom.reverse()
        handle_top_start = offset_point(offset_point(pivot, up, top_offset), handle, -8.0)
        arm = geom.polygon(
            [(d.head_front_x_mm + 2.0, -(d.tray_floor_mm + d.socket_floor_mm)), (d.head_rear_x_mm - 4.0, d.head_top_z_mm - 6.0), handle_top_start]
            + [offset_point(pivot, up, -2.0)]
            + arm_bottom[::-1]
        )
        handle_end_top = offset_point(offset_point(pivot, up, top_offset), handle, d.base_handle_length_mm)
        handle_end_bottom = offset_point(offset_point(pivot, up, -d.handle_gap_offset_mm), handle, d.base_handle_length_mm)
        handle_band = geom.polygon(
            [
                handle_top_start,
                handle_end_top,
                handle_end_bottom,
                offset_point(offset_point(pivot, up, -d.handle_gap_offset_mm), handle, -6.0),
            ]
        )
        boss_centre = offset_point(d.screw_axis_point_xz, up, -d.handle_gap_offset_mm - d.screw_boss_depth_mm / 2)
        boss = geom.polygon(
            [
                offset_point(offset_point(boss_centre, handle, -13.0), up, d.screw_boss_depth_mm / 2 + 1.0),
                offset_point(offset_point(boss_centre, handle, 13.0), up, d.screw_boss_depth_mm / 2 + 1.0),
                offset_point(offset_point(boss_centre, handle, 10.0), up, -d.screw_boss_depth_mm / 2),
                offset_point(offset_point(boss_centre, handle, -10.0), up, -d.screw_boss_depth_mm / 2),
            ]
        )
        pivot_boss = geom.circle(pivot, 10.2)
        body = geom.union_2d([head, arm, handle_band, pivot_boss])
        body = geom.rounded(body, convex_radius=2.0, concave_radius=3.0)
        return geom.union_2d([body, boss, d.scale_pointer_shape])

    def lever_profile_at(self, rotation_rad: float):
        return geom.rotated(self.lever_profile, rotation_rad, self.pivot_xz)

    @cached_property
    def pivot_pocket_shape(self):
        """Space inside the base swept by the lever's pivot hump over its whole travel."""
        d = self
        angles = np.linspace(-np.radians(1.0), d.max_lever_rotation_rad + np.radians(1.5), 30)
        swept = geom.union_2d([d.lever_profile_at(a) for a in angles])
        near_pivot = geom.circle(d.pivot_xz, 30.0)
        return swept.intersection(near_pivot).buffer(0.5, quad_segs=8).intersection(d.base_profile.buffer(1.0))


DESIGN = Design()
