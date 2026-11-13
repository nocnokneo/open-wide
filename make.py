"""Build every part, verify the assembly, and write STLs, renders and a numeric report."""

import pathlib

import numpy as np
import shapely
import trimesh
from manifold3d import Manifold

import parts
from assembly import Assembly, about_lateral_axis
from design import DESIGN as d
from render import render

ROOT = pathlib.Path(__file__).parent
STL_DIR, IMAGE_DIR = ROOT / "stl", ROOT / "images"
BED_MM = 250.0


def to_trimesh(solid: Manifold) -> trimesh.Trimesh:
    mesh = solid.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3], faces=np.asarray(mesh.tri_verts), process=False)


def laid_out_for_printing(solid: Manifold) -> Manifold:
    """Turn about Z so the footprint is as compact as possible, then sit it on the bed at the origin."""
    mesh = solid.to_mesh()
    footprint = shapely.MultiPoint(np.asarray(mesh.vert_properties)[:, :2]).minimum_rotated_rectangle
    corners = np.asarray(footprint.exterior.coords)
    edges = np.diff(corners[:3], axis=0)
    longest = edges[np.argmax(np.linalg.norm(edges, axis=1))]
    turned = solid.rotate((0, 0, -np.degrees(np.arctan2(longest[1], longest[0]))))
    x_min, y_min, z_min, x_max, y_max, _ = turned.bounding_box()
    return turned.translate((-(x_min + x_max) / 2, -(y_min + y_max) / 2, -z_min))


def printable_parts() -> dict[str, Manifold]:
    return {
        "base": parts.base(d),
        "lever": parts.lever(d),
        "upper_mouthpiece": parts.upper_mouthpiece(d),
        "lower_tray": parts.lower_tray(d).rotate((180, 0, 0)),  # hinge side on the bed, rims up
        "limit_screw": parts.limit_screw(d),
        **{f"limit_nut_{dots}_dot": parts.limit_nut(dots, d) for dots in parts.nut_dots(d)},
        "pivot_pin_print_2": parts.snap_pin(d.base_width_mm, d),
        "hinge_fit_test": parts.hinge_fit_test(d),
    }


def export_stls(report: list[str]) -> dict[str, Manifold]:
    STL_DIR.mkdir(exist_ok=True)
    laid_out = {name: laid_out_for_printing(solid) for name, solid in printable_parts().items()}
    report.append("Printable parts (as laid on the bed):")
    for name, solid in laid_out.items():
        mesh = to_trimesh(solid)
        assert mesh.is_watertight, name
        mesh.export(STL_DIR / f"{name}.stl")
        size = mesh.extents
        assert max(size[:2]) <= BED_MM, (name, size)
        report.append(f"  {name:20s} {size[0]:6.1f} x {size[1]:5.1f} x {size[2]:5.1f} mm   {solid.volume() / 1000:5.1f} cm3 solid")
    return laid_out


def check_assembly(assembly: Assembly, report: list[str]):
    grip_mm = 85.0
    report.append(f"\nHand force = {d.lever_length_mm / grip_mm:.2f} x force on the teeth (hand {grip_mm:.0f} mm from the pivot)")
    for opening in (d.closed_opening_mm, 20, 30, 40, d.max_opening_mm):
        remaining = d.max_lever_rotation_rad - d.lever_rotation_rad(opening)
        gap = d.handle_gap_at_max_opening_mm + grip_mm * np.tan(remaining)
        report.append(f"  handle gap at the grip, opening {opening:4.1f} mm: {gap:4.1f} mm (grip span {gap + d.base_handle_depth_mm + d.lever_depth_mm:4.1f} mm)")
    report.append(f"\nMain pivot at x = {d.pivot_xz[0]:.1f}, z = {d.pivot_xz[1]:.1f} mm from the upper incisal edge")
    report.append(f"Scale reads {d.closed_opening_mm:.1f} mm fully closed, {d.max_opening_mm:.0f} mm at the hard stop")
    report.append("\nopening  lever turn  tray tilt  path error  interference")
    for opening in [d.closed_opening_mm, *range(14, int(d.max_opening_mm) + 1, 4)]:
        worst = max(assembly.interference_mm3(opening).values())
        hardware = {**assembly.posed(opening), **assembly.hardware(max(opening, 14))}
        names = list(hardware)
        worst = max([worst] + [(hardware[a] ^ hardware[b]).volume() for i, a in enumerate(names) for b in names[i + 1 :]])
        assert worst < 0.05, (opening, worst)
        report.append(
            f"{opening:6.1f}   {np.degrees(d.lever_rotation_rad(opening)):6.1f} deg {np.degrees(d.tray_tilt_rad(opening)):6.1f} deg"
            f" {d.path_error_mm(opening):7.2f} mm  {worst:6.3f} mm3"
        )


def check_thread(report: list[str]):
    """Every nut must screw onto the limit screw, and the handedness must be the one the README states."""
    screw = parts.limit_screw(d)
    for dots in parts.nut_dots(d):
        # one whole number of pitches above where the screw's thread starts, the threads are in phase
        meshed = parts.limit_nut(dots, d).translate((0, 0, parts.SCREW_KNOB_HEIGHT_MM + 1 + 4 * d.thread_pitch_mm))
        assert (screw ^ meshed).volume() < 1.5, dots  # mm3; faceting alone gives ~0.7, a thread out of phase ~80
    # crest direction a quarter pitch up the thread: -90 deg for a left-handed thread, +90 for right-handed
    quarter_up = parts.SCREW_KNOB_HEIGHT_MM + 10 * d.thread_pitch_mm + d.thread_pitch_mm / 4
    section = np.vstack(screw.slice(quarter_up).to_polygons())
    crest = section[np.argmax(np.linalg.norm(section, axis=1))]
    crest_deg = np.degrees(np.arctan2(crest[1], crest[0]))
    assert abs(crest_deg - (-90 if d.thread_is_left_handed else 90)) < 20, crest_deg  # the crest has a flat
    hand = "left" if d.thread_is_left_handed else "right"
    fits = ", ".join(f"{dots} dot = {c:.2f} mm" for dots, c in zip(parts.nut_dots(d), d.nut_thread_clearance_by_dots_mm))
    report.append(f"\nLimit screw: {hand}-handed thread; nut radial clearances: {fits}")


def check_hinge_retention(assembly: Assembly, report: list[str]):
    """The tray must stay hooked at every working tilt and come off only when folded right back."""
    hinge, hinge_in_tray = d.closed_hinge_xz, d.hinge_in_tray_xz
    out = np.array([np.cos(np.radians(d.hook_mouth_direction_deg)), np.sin(np.radians(d.hook_mouth_direction_deg))])

    def comes_off(tilt_deg: float) -> bool:
        for step in np.arange(0, 12.01, 0.25):
            shift = hinge - hinge_in_tray + step * out
            tray = about_lateral_axis(assembly.lower_tray, hinge_in_tray, -np.radians(tilt_deg)).translate((shift[0], 0, shift[1]))
            if (tray ^ assembly.lever_closed).volume() > 0.02:
                return False
        return True

    releasing = [tilt for tilt in range(0, 200, 5) if comes_off(tilt)]
    working_max = np.degrees(d.tray_tilt_rad(d.max_opening_mm) + d.max_lever_rotation_rad)
    assert releasing and min(releasing) > working_max + 30, (releasing, working_max)
    report.append(f"\nLower tray hinge: working tilt up to {working_max:.0f} deg relative to the lever tip; comes off only at {min(releasing)}-{max(releasing)} deg")


def write_renders(assembly: Assembly, laid_out: dict[str, Manifold]):
    IMAGE_DIR.mkdir(exist_ok=True)
    for opening in (d.closed_opening_mm, 30.0, d.max_opening_mm):
        scene = {**assembly.posed(opening), **assembly.hardware(max(opening, 14))}
        tag = "closed" if opening == d.closed_opening_mm else f"{opening:.0f}mm"
        render(scene, str(IMAGE_DIR / f"side_{tag}.png"), "side")
        render(scene, str(IMAGE_DIR / f"section_{tag}.png"), "side", clip_y=0.01)
    scene = {**assembly.posed(30.0), **assembly.hardware(30.0)}
    render(scene, str(IMAGE_DIR / "assembly_30mm.png"), "iso")
    render(scene, str(IMAGE_DIR / "assembly_30mm_front.png"), "front")
    handle_end = d.pivot_xz + 118 * d.base_handle_direction
    render(scene, str(IMAGE_DIR / "scale_and_limit_screw.png"), "iso", zoom=1.0, camera=[(handle_end[0] + 30, -170, handle_end[1] - 10), (handle_end[0] - 12, 0, handle_end[1] + 4), (0, 0, 1)])
    closed = {**assembly.posed(d.closed_opening_mm), **assembly.hardware(14)}
    render(closed, str(IMAGE_DIR / "mouth_end_closed_section.png"), "side", clip_y=0.01, focus=(8, -4, 52), size=(1500, 900))
    wide = {**assembly.posed(d.max_opening_mm), **assembly.hardware(d.max_opening_mm)}
    render(wide, str(IMAGE_DIR / "mouth_end_46mm_section.png"), "side", clip_y=0.01, focus=(2, -22, 80), size=(1500, 900))
    _write_sections_overview()
    # the printable parts spread out, seen from above
    spread, x = {}, 0.0
    for name, solid in laid_out.items():
        x_min, y_min, _, x_max, y_max, _ = solid.bounding_box()
        if name == "hinge_fit_test":
            continue
        key = {"base": "base", "lever": "lever", "upper_mouthpiece": "upper", "lower_tray": "lower", "limit_screw": "screw"}.get(name, "nut" if name.startswith("limit_nut") else "pin")
        spread[f"{key}_{name}"] = solid.rotate((0, 0, 90)).translate((x + (y_max - y_min) / 2, 0, 0))
        x += (y_max - y_min) + 8
    render(spread, str(IMAGE_DIR / "print_layout.png"), "top", size=(1600, 1100), zoom=1.3)


def _write_sections_overview():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt

    titles = {"closed": f"Closed (scale reads {d.closed_opening_mm:.1f} mm)", "30mm": "30 mm opening, limit screw set to 30", "46mm": "46 mm opening (hard stop)"}
    figure, axes = plt.subplots(1, 3, figsize=(21, 7.2))
    for axis, (tag, title) in zip(axes, titles.items()):
        axis.imshow(mpimg.imread(IMAGE_DIR / f"section_{tag}.png"))
        axis.set_title(title, fontsize=16)
        axis.axis("off")
    figure.tight_layout()
    figure.savefig(IMAGE_DIR / "sections_overview.png", dpi=70)


def main():
    report: list[str] = []
    laid_out = export_stls(report)
    assembly = Assembly(d)
    check_assembly(assembly, report)
    check_hinge_retention(assembly, report)
    check_thread(report)
    (ROOT / "report.txt").write_text("\n".join(report) + "\n")
    print("\n".join(report))
    write_renders(assembly, laid_out)


if __name__ == "__main__":
    main()
