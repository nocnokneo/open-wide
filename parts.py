"""3D parts of the jaw stretcher, each in the frame it is designed in.

Plate parts (base, lever) are built in their print orientation: the side
profile lies in XY (x = device x, y = device z) and is extruded along Z.
`plate_to_device` turns them into the device frame (x forward, y lateral, z up).
Mouthpieces are built directly in device-like frames.
"""

import numpy as np
import shapely.affinity
from manifold3d import CrossSection, Manifold
from scipy.interpolate import PchipInterpolator
from shapely.geometry import LineString, Polygon, box as rectangle

import geom
from design import DESIGN, Design, direction, offset_point


def plate_to_device(solid: Manifold) -> Manifold:
    return solid.rotate((90, 0, 0))


def extrude_side(profile_xz, lateral_min: float, lateral_max: float) -> Manifold:
    """Extrude a side profile (x, z) along the lateral axis, in the device frame."""
    return plate_to_device(geom.extrude(profile_xz, -lateral_max, -lateral_min))


def lateral_cylinder(centre_xz, radius: float, lateral_min: float, lateral_max: float) -> Manifold:
    return plate_to_device(geom.cylinder_z(centre_xz, radius, -lateral_max, -lateral_min))


# --------------------------------------------------------------------- plates
def base(d: Design = DESIGN) -> Manifold:
    half_width = d.base_width_mm / 2
    half_slot = d.slot_width_mm / 2
    solid = geom.extrude_chamfered(d.base_profile, -half_width, half_width, chamfer=1.0)

    pivot_pocket = geom.extrude(d.pivot_pocket_shape, -half_slot, half_slot)
    socket = geom.extrude(
        rectangle(d.head_front_x_mm - 1, -d.tray_floor_mm, d.head_front_x_mm + d.tang_length_mm + 0.4, d.socket_top_z_mm),
        -half_slot,
        half_slot,
    )
    hole_radius = d.pin_hole_diameter_mm / 2
    holes = [
        geom.cylinder_z(d.pivot_xz, hole_radius, -half_width, half_width),
        geom.cylinder_z(d.mouthpiece_pin_xz, hole_radius, -half_width, half_width),
    ]
    return solid - geom.union([pivot_pocket, socket, *holes, _screw_hole(d), _nut_pocket(d)])


def _handle_frame(d: Design):
    """Origin on the screw axis at the pivot line; unit vectors along the handle and up."""
    return d.screw_axis_point_xz, d.base_handle_direction, d.base_handle_up


def nut_centre_offset_mm(d: Design) -> float:
    """Perpendicular position of the nut centre relative to the pivot line of the base handle."""
    return 3.0


def _screw_hole(d: Design) -> Manifold:
    origin, _, up = _handle_frame(d)
    radius = d.thread_major_diameter_mm / 2 + 0.45
    hole = Manifold.cylinder(60, radius, radius, geom.CIRCLE_SEGMENTS).translate((0, 0, -30))
    angle_deg = np.degrees(np.arctan2(up[1], up[0]))
    # cylinder along Z -> along X -> along `up` in the profile plane
    return hole.rotate((0, 90, 0)).rotate((0, 0, angle_deg)).translate((origin[0], origin[1], 0))


def _nut_pocket(d: Design) -> Manifold:
    origin, along, up = _handle_frame(d)
    half_length = d.nut_size_mm / 2 + 0.25
    half_height = d.nut_thickness_mm / 2 + 0.2
    centre = np.asarray(offset_point(origin, up, nut_centre_offset_mm(d)))
    corners = [centre + sx * half_length * along + sy * half_height * up for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    floor = 2.1
    return geom.extrude(Polygon(corners), -d.base_width_mm / 2 + floor, d.base_width_mm / 2 + 1)


def lever(d: Design = DESIGN) -> Manifold:
    half = d.lever_thickness_mm / 2
    solid = geom.extrude_chamfered(d.lever_profile, -half, half, chamfer=0.8)
    hole = geom.cylinder_z(d.pivot_xz, d.pin_hole_diameter_mm / 2, -half, half)
    engraving = geom.extrude(d.scale_engraving, half - 0.6, half + 1)
    return solid - geom.union([hole, engraving])


# ----------------------------------------------------------------------- trays
def _arch_centreline(arch, depth_mm: float) -> LineString:
    depth_points, half_widths = np.array(arch).T
    # interpolating against sqrt(depth) keeps the front of the arch blunt and smooth
    half_width = PchipInterpolator(np.sqrt(depth_points), half_widths)
    roots = np.linspace(0, np.sqrt(depth_mm + 4.0), 60)
    right = [(-root**2, float(half_width(root))) for root in roots]
    left = [(x, -y) for x, y in right[:0:-1]]
    return LineString(left + right)


def _clip_rear(shape, depth_mm: float):
    return shape.intersection(rectangle(-depth_mm, -60, 60, 60))


def _plate(shape, z_back: float, z_tooth_side: float) -> Manifold:
    """Tray floor with its back edge (the face away from the teeth) broken."""
    step = 0.6 if z_tooth_side > z_back else -0.6
    full = geom.extrude(shape, min(z_back + step, z_tooth_side), max(z_back + step, z_tooth_side))
    edge = geom.extrude(shape.buffer(-0.6), min(z_back, z_back + step), max(z_back, z_back + step))
    return full + edge


def _rim(band, z_from: float, z_to: float) -> Manifold:
    """Rim with a rounded-off free edge at z_to."""
    band = geom.rounded(band, convex_radius=0.5)
    step = 0.4 if z_to > z_from else -0.4
    full = geom.extrude(band, min(z_from, z_to - step), max(z_from, z_to - step))
    cap = geom.extrude(band.buffer(-0.4), min(z_to - step, z_to), max(z_to - step, z_to))
    return full + cap


def upper_mouthpiece(d: Design = DESIGN) -> Manifold:
    """Upper tray, stem and tang in the device frame; prints as modelled (flat face down)."""
    centreline = _arch_centreline(d.upper_arch, d.tray_depth_mm)
    half_channel = d.upper_channel_width_mm / 2
    outline = _clip_rear(centreline.buffer(half_channel + d.rim_width_mm), d.tray_depth_mm)
    channel = centreline.buffer(half_channel)
    plate_shape = geom.rounded(outline.convex_hull, convex_radius=2.0)
    plate = _plate(plate_shape, -d.tray_floor_mm, 0)
    rims = _rim(outline.difference(channel), 0, d.rim_height_mm)

    front_x = half_channel + d.rim_width_mm - 2.0
    tang_start = d.head_front_x_mm + 0.3
    tang_end = d.head_front_x_mm + d.tang_length_mm
    tang_top = d.socket_top_z_mm - 0.35
    stem_top = 5.6
    stem_profile = Polygon(
        [(front_x, -d.tray_floor_mm), (front_x, d.rim_height_mm), (front_x + 4, stem_top), (tang_start - 6, stem_top), (tang_start, tang_top), (tang_start + 1, tang_top), (tang_start + 1, -d.tray_floor_mm)]
    )
    half_stem, half_tang = 12.0, d.lever_thickness_mm / 2 - 0.1
    stem_plan = Polygon(
        [(front_x, -half_stem), (tang_start - 6.5, -half_stem), (tang_start - 1.0, -half_tang), (tang_start + 1, -half_tang), (tang_start + 1, half_tang), (tang_start - 1.0, half_tang), (tang_start - 6.5, half_stem), (front_x, half_stem)]
    )
    stem = _soft_edged(geom.rounded(stem_profile, convex_radius=1.0), geom.rounded(stem_plan, convex_radius=1.5), half_stem, softness=1.2)

    tang_profile = geom.rounded(rectangle(tang_start, -d.tray_floor_mm, tang_end, tang_top), convex_radius=0.8)
    tang = extrude_side(tang_profile, -half_tang, half_tang)
    pin_hole = lateral_cylinder(d.mouthpiece_pin_xz, d.pin_hole_diameter_mm / 2, -half_tang - 1, half_tang + 1)
    return geom.union([plate, rims, stem, tang]) - pin_hole


def _soft_edged(profile_xz, plan_xy, half_width: float, softness: float, layer: float = 0.3) -> Manifold:
    """Intersection of a side extrusion and a plan extrusion with chamfered meeting edges."""
    steps = int(round(softness / layer))
    pieces = []
    for i in range(steps + 1):
        inset = i * layer
        side = extrude_side(profile_xz.buffer(-inset), -half_width, half_width)
        plan = geom.extrude(plan_xy.buffer(-(softness - inset)), -50, 50)
        pieces.append(side ^ plan)
    return geom.union(pieces)


def lower_tray(d: Design = DESIGN) -> Manifold:
    """Lower tray in its own frame: origin at the lower incisal edge, tooth plane z = 0, teeth below."""
    centreline = _arch_centreline(d.lower_arch, d.tray_depth_mm)
    half_channel = d.lower_channel_width_mm / 2
    outline = _clip_rear(centreline.buffer(half_channel + d.rim_width_mm), d.tray_depth_mm)
    channel = centreline.buffer(half_channel)
    web = _clip_rear(Polygon(centreline.coords), d.tray_depth_mm).intersection(rectangle(-60, -60, -6.0, 60))
    hinge_x, hinge_z = d.hinge_in_tray_xz
    half_slot = d.slot_width_mm / 2
    reach = d.hook_inner_radius_mm + d.hook_lip_mm + 0.6
    # open to the rear so the tray can swing right over the lever tip when it is hooked on
    window = rectangle(-60, -half_slot, hinge_x + reach, half_slot)
    plate_shape = geom.rounded(geom.union_2d([outline, web]), convex_radius=1.5).difference(window)
    plate = _plate(plate_shape, d.tray_floor_mm, 0)
    rims = _rim(outline.difference(channel), 0, -d.rim_height_mm)

    bar_profile = geom.circle((hinge_x, hinge_z), d.hinge_bar_radius_mm).intersection(rectangle(-60, -10, 60, d.tray_floor_mm))
    anchor_width = 3.4
    bar = extrude_side(bar_profile, -half_slot - anchor_width, half_slot + anchor_width)
    anchor_profile = geom.rounded(rectangle(hinge_x - 4.5, hinge_z - d.hinge_bar_radius_mm - 0.7, hinge_x + 4.5, d.tray_floor_mm), convex_radius=0.6)
    anchors = [extrude_side(anchor_profile, sign * half_slot, sign * (half_slot + anchor_width)) if sign > 0 else extrude_side(anchor_profile, -half_slot - anchor_width, -half_slot) for sign in (1, -1)]
    return geom.union([plate, rims, bar, *anchors])


# -------------------------------------------------------------------- hardware
def snap_pin(grip_length_mm: float, d: Design = DESIGN) -> Manifold:
    """Pivot pin, modelled lying down as printed: axis along X, flats top and bottom."""
    radius = d.pivot_pin_diameter_mm / 2
    head_thickness, barb_length, barb_overhang = 2.0, 6.5, 0.55
    half_flat = radius * 0.82
    # half-profile (axial x, radial r), revolved about the axis
    x0 = grip_length_mm + 0.5
    profile = [
        (-head_thickness, 0),
        (-head_thickness, radius + 2.0),
        (0, radius + 2.0),
        (0, radius),
        (x0, radius),
        (x0, radius + barb_overhang),
        (x0 + barb_length, radius - 1.3),
        (x0 + barb_length, 0),
    ]
    # revolve wants (r, axial) and makes the axis Z
    body = CrossSection([np.array([(r, x) for x, r in profile])]).revolve(geom.CIRCLE_SEGMENTS).rotate((0, 90, 0))
    flats = geom.box((-10, 200), (-20, 20), (-half_flat, half_flat))
    slot_start = x0 - 11.0
    slot = geom.box((slot_start, x0 + barb_length + 1), (-0.9, 0.9), (-20, 20))
    relief = geom.cylinder_z((slot_start, 0), 1.3, -20, 20)
    return (body ^ flats) - slot - relief


def _thread(radius_major: float, length: float, d: Design) -> Manifold:
    """Single-start thread with 45-degree-ish flanks, as a twisted extrusion."""
    angles = np.linspace(0, 2 * np.pi, 180, endpoint=False)
    saw = np.abs(angles / np.pi - 1)  # 1 at angle 0, 0 at pi
    crest_flat, root_flat = 0.12, 0.12
    radial = np.clip((saw - root_flat) / (1 - root_flat - crest_flat), 0, 1)
    radii = radius_major - d.thread_depth_mm + d.thread_depth_mm * radial
    section = CrossSection([np.column_stack([radii * np.cos(angles), radii * np.sin(angles)])])
    turns = length / d.thread_pitch_mm
    # a right-handed helix turns counter-clockwise, seen from above, as it rises
    twist_deg = -360 * turns if d.thread_is_left_handed else 360 * turns
    return section.extrude(length, int(length / 0.2), twist_deg)


SCREW_KNOB_HEIGHT_MM, SCREW_THREAD_LENGTH_MM, SCREW_TIP_LENGTH_MM = 9.0, 47.0, 3.0
SCREW_TIP_END_RADIUS_MM = 3.0


def limit_screw(d: Design = DESIGN) -> Manifold:
    """Thumbscrew, modelled as printed: knob on the bed, thread pointing up."""
    knob_height, thread_length, tip_length = SCREW_KNOB_HEIGHT_MM, SCREW_THREAD_LENGTH_MM, SCREW_TIP_LENGTH_MM
    major = d.thread_major_diameter_mm / 2
    lobes = geom.union_2d([geom.circle((14.2 * np.cos(a), 14.2 * np.sin(a)), 3.0) for a in np.linspace(0, 2 * np.pi, 10, endpoint=False)])
    knob_shape = geom.rounded(geom.circle((0, 0), 13.5).difference(lobes), convex_radius=0.8)
    knob = geom.extrude_chamfered(knob_shape, 0, knob_height, chamfer=0.8)
    thread = _thread(major, thread_length, d).translate((0, 0, knob_height))
    tip_radius = major - d.thread_depth_mm - 0.3
    tip = Manifold.cylinder(tip_length, tip_radius, SCREW_TIP_END_RADIUS_MM, geom.CIRCLE_SEGMENTS).translate((0, 0, knob_height + thread_length))
    return geom.union([knob, thread, tip])


def limit_nut(d: Design = DESIGN) -> Manifold:
    """Square, split nut for the limit screw, printed flat."""
    half = d.nut_size_mm / 2
    thread_radius = d.thread_major_diameter_mm / 2 + d.nut_thread_radial_clearance_mm
    body = geom.extrude_chamfered(geom.rounded(rectangle(-half, -half, half, half), convex_radius=1.0), 0, d.nut_thickness_mm, chamfer=0.6)
    bore = _thread(thread_radius, d.nut_thickness_mm + 2, d).translate((0, 0, -1))
    lead_in = Manifold.cylinder(1.4, thread_radius + 0.2, thread_radius - 1.2, geom.CIRCLE_SEGMENTS)
    lead_out = Manifold.cylinder(1.4, thread_radius - 1.2, thread_radius + 0.2, geom.CIRCLE_SEGMENTS).translate((0, 0, d.nut_thickness_mm - 1.4))
    split = geom.box((0, half + 1), (-0.5, 0.5), (-1, d.nut_thickness_mm + 1))
    return body - geom.union([bore, lead_in, lead_out, split])
