# Listings on MakerWorld and NIH 3D

* MakerWorld: <https://makerworld.com/en/models/3608272-open-wide-jaw-stretcher-for-trismus-rehab>
* NIH 3D: <https://3d.nih.gov/doi/023862/1>

Neither site has an upload API, so each release is posted by hand.
The listing stays short and sends readers to the guide, which is the single source for instructions.

## For each release

1. Push the tag and wait for the GitHub release to appear.
2. Download the zip from the release.
3. On each site, replace the model files and the guide PDF with the ones from the zip and add a line to the listing's change notes.
4. On MakerWorld, also re-slice in Bambu Studio and upload the project as the print profile.

## Fields

| Field | Value |
| --- | --- |
| Title | Open Wide: jaw stretcher for trismus rehab (no hardware) |
| Summary | A hand-squeezed jaw stretcher that follows the jaw's own arc, with a self-levelling lower tray and an adjustable limit. Eight printed parts, no screws, no supports. |
| License | Creative Commons Attribution 4.0 (CC BY 4.0) |
| Tags | trismus, jaw, jaw stretcher, TMJ, rehab, physical therapy, medical, PETG, no supports, no hardware |
| Category | The closest health or medical category the site offers |
| Material | PETG |
| Photos | `docs/images/photo.jpg` first, then `assembly_30mm.png`, `sections_overview.png`, `print_layout.png`, `tray_fitting_1_hook_on.png`, `scale_and_limit_screw.png` from `docs/images/` |

Keep the names of commercial jaw stretchers out of the listing: they are trademarks.

## Description

```
Squeeze the handles and the two mouthpieces push your teeth apart, gently and under your control. It is meant for the daily stretching that jaw-opening rehab (trismus) calls for.

• Moves the way a jaw moves: the lower mouthpiece swings down and back along the jaw's own arc.
• Sits flat on your teeth: the lower tray pivots freely and levels itself.
• You set the limit: a thumbscrew stops the handles at the opening you choose, from 14 to 46 mm.
• Everything is printed: eight parts, no screws, no springs, no supports.

PRINTING
PETG, 0.2 mm layers, 5 walls, 25 % infill or more. All parts are already oriented. Print two pivot pins. tooth_pads.stl is optional: templates for cutting soft tooth pads from silicone sheet, or the pads themselves if printed in TPU (see the guide).

FULL GUIDE (assembly, setting the limit, use, troubleshooting):
https://nocnokneo.github.io/open-wide/

SOURCE (parametric Python, every dimension adjustable):
https://github.com/nocnokneo/open-wide

DISCLAIMER
This is a hobby design, not a medical device. Nobody has tested, certified or clinically reviewed it, and stretching a jaw can cause injury. Build and use it at your own risk, and ask your clinician first.
```
