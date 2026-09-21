# ADR-007: Use one world camera for the navigable splat prototype

## Context

The debate stage has one Three.js canvas for the licensed figures and table.
The owner requires the environment, table, five figure slots and collisions to
occupy fixed 3D world coordinates while only the camera moves. The desired
experience matches a scanned environment imported into an engine, not a flat
background shifted behind camera-relative figures.

Independently generated courtyard views drifted in architecture, plants and
table details, so they were not a trustworthy capture of one scene. A single
2:1 equirectangular courtyard is now the visual authority. The source and
reconstructed media remain under ignored `data/courtyard-splat/`; no generated
media enters Git.

BLUNT with the Apache-2.0 Depth Anything V2 metric-outdoor small model lifted
the front view to a 1,228,800-Gaussian PLY. PlayCanvas SplatTransform 3.4.2
converted it to a 6.2 MB SOG. Camera movement exposed stretched architecture,
missing surfaces and a broken table silhouette. That single-image lift cannot
be the navigation surface.

The public painted-room prototype proved the camera path, but it did not match
Maya's national-style visual language. BLUNT's cube-face Depth Anything V2
pipeline now lifts the authoritative panorama into 1,531,786 Gaussians while
preserving the capture origin. PlayCanvas SplatTransform 3.4.2 compresses the
PLY to a 15 MB SPZ version 3; Spark 2.2 does not render version 4 here. The first
runtime combined sparse splats with a radius-150 panorama sphere, but the
recording showed that the courtyard still behaved like a camera-relative image
during translation.

The first correction rasterized the 1,531,786 Gaussian centres into a radial
depth texture and displaced a 256 by 128 equirectangular shell on the CPU. It
reduced holes but still looked like a painted surface when the camera moved.
The owner subsequently chose real Gaussian rendering despite that monocular
reconstruction limit. Spark 2.2 therefore renders the stable SPZ again at
full opacity. A same-source radius-150 panorama sits behind it only to fill
surfaces the single image could not reconstruct; it does not replace the SPZ.

## Decision

Keep the default classroom stage unchanged. The local `?splat=1` route creates
one Spark renderer and loads `courtyard-360.spz` into a separate Three.js scene,
then renders that scene with the exact same live perspective camera used for
figures and the procedural table. BLUNT's negative-Y panorama convention is
mirrored once at the fixed capture origin. A same-source far sphere fills only
unreconstructed holes. If SPZ loading fails, the previous Gaussian-derived
radial depth shell is the fallback. There is no second camera, screen-space
compensation, figure follow, root animation or FOV zoom.

The navigable variant moves the complete table-and-figure arrangement 0.95
world units into the courtyard, uses a roughly 2.1-metre table and normalizes
figures to 1.68 units. Those figure values apply only to the opt-in courtyard;
the table size is shared with the default stage.

The binary and intermediate PLY remain ignored generated media. Rebuild them
locally with:

```powershell
data/courtyard-splat/.venv/Scripts/python.exe `
  data/courtyard-splat/blunt-source/blunt.py `
  data/courtyard-splat/source/courtyard-equirect.png `
  --mode 360 --engine da2 --device cpu --resolution 768 `
  --depth-mode metric-outdoor --fast --no-normalize `
  -o data/courtyard-splat/courtyard-360-origin.ply
pnpm dlx @playcanvas/splat-transform -w `
  data/courtyard-splat/courtyard-360-origin.ply `
  frontend/public/stage/courtyard-360.spz --spz-version 3
py -3 scripts/build_courtyard_depth_shell.py `
  data/courtyard-splat/courtyard-360-origin.ply `
  frontend/public/stage/courtyard-equirect-depth.png `
  --width 1024 --height 512 --max-depth 40
py -3 scripts/render_courtyard_view_sets.py `
  data/courtyard-splat/source/courtyard-equirect.png `
  data/courtyard-splat/view-sets --views 24 --width 960 --height 540
```

The old single-image SOG and `?depth=1` depth mesh remain historical experiments.
Neither qualifies as a navigable world and neither informs the new camera path.

A non-renderable `Box3` resolves each visible model bound onto one floor
surface, with a compact contact shadow fixed under it. Slots A-E are five
stable world positions; roster size and speaking state never translate a
figure. Speaking may animate bones and morph targets only. The splat has no
trusted collision mesh, so the camera is bounded by a numeric 2.5-metre walk
circle around the capture origin. The table and slot exclusion volumes exist
in `stageCameraPositionBlocked`, but the walk circle keeps the camera over
four metres from every one of them, so the active constraint in practice is
the walk circle alone; they are retained as safety rails for any future
larger walk bound. No collision material or wall is attached to either render
scene.

WASD continuously translates relative to yaw; A is camera-left and D is
camera-right. Q/left-arrow turn left and E/right-arrow turn right,
and clicking the canvas enables pointer-lock mouse look. Reset restores the
authored first-person pose. Overview saves the exact pose, follows a cubic curve
up and back while looking at the stage, and reverses the same curve before
restoring that pose. Debate audio, mouth animation and bubbles continue during
the transition. Sustained slow frames may lower render pixel ratio to 0.75, but
never change world transforms, collision or the path.

Local Chromium inspection covered a nonblank Spark shader pass, first-person
approach, table collision and the fixed figure/table transforms. Earlier Chrome
inspection covered yaw, overview round-trip, 1920x1080 and 4:3 layouts. The
current asset is a monocular depth reconstruction, not captured photogrammetry;
derived views share one camera centre and must not be treated as translated
multi-view evidence. Source sharpness, ordinary-Mac performance and classroom
acceptance remain open.

## References

- [BLUNT](https://github.com/SonnyC56/blunt)
- [PlayCanvas SplatTransform](https://github.com/playcanvas/splat-transform)
- [Spark Three.js integration](https://sparkjs.dev/docs/)
