# ADR-007: Use one world camera for the navigable splat prototype

## Context

The debate stage has one Three.js canvas for the licensed figures and table.
The owner requires the environment, table, five figure slots and collisions to
occupy fixed 3D world coordinates while only the camera moves. The desired
experience matches a scanned environment imported into an engine, not a flat
background shifted behind camera-relative figures.

Three courtyard views were generated locally. Their architecture, plants and
table details drift between views, so they are not a trustworthy capture of one
scene for multi-view reconstruction. The images and reconstructed media remain
under ignored `data/courtyard-splat/`; no generated media enters Git.

BLUNT with the Apache-2.0 Depth Anything V2 metric-outdoor small model lifted
the front view to a 1,228,800-Gaussian PLY. PlayCanvas SplatTransform 3.4.2
converted it to a 6.2 MB SOG. Camera movement exposed stretched architecture,
missing surfaces and a broken table silhouette. That single-image lift cannot
be the navigation surface.

For architecture validation, the local prototype instead uses the public World
Labs painted-room SPZ demonstrated by Spark. The binary remains ignored under
`frontend/public/stage/`; it is not a Maya product asset and is not the final
national-style courtyard.

## Decision

Keep the default classroom stage unchanged. The local `?splat=1` route loads
the ignored full SPZ in a separate Three.js scene but renders it with the exact
same live perspective camera used for figures and the procedural table. The
splat mesh has one fixed scale/rotation/translation. There is no splat camera,
screen-space compensation, figure follow, root animation or FOV zoom. Missing
media or decode failure keeps the static courtyard fallback.

The old single-image SOG and `?depth=1` depth mesh remain historical experiments.
Neither qualifies as a navigable world and neither informs the new camera path.

An invisible floor slab resolves each visible model bound onto one top surface,
with a compact contact shadow fixed under it. Slots A-E are five stable world
positions; roster size and speaking state never translate a figure. Speaking
may animate bones and morph targets only. The splat has no trusted collision
mesh, so explicit conservative world-space proxies provide walk bounds plus
table and loaded-figure collision at a fixed eye height.

WASD continuously translates relative to yaw; Q/E and arrow controls rotate,
and clicking the canvas enables pointer-lock mouse look. Reset restores the
authored first-person pose. Overview saves the exact pose, follows a cubic curve
up and back while looking at the stage, and reverses the same curve before
restoring that pose. Debate audio, mouth animation and bubbles continue during
the transition. Sustained slow frames may lower render pixel ratio to 0.75, but
never change world transforms, collision or the path.

Local Chrome inspection covered first-person approach, table collision, yaw,
overview round-trip, 1920x1080 and 4:3 layouts. Ordinary-Mac performance and
Chrome/Edge classroom acceptance are still unmeasured. Production requires a
coherent multi-view or generated national-style courtyard with a visual table,
plus authored collision proxies matched to that asset.

## References

- [BLUNT](https://github.com/SonnyC56/blunt)
- [PlayCanvas SplatTransform](https://github.com/playcanvas/splat-transform)
- [Spark Three.js integration](https://sparkjs.dev/docs/)
- [Spark public assets](https://github.com/sparkjsdev/assets)
