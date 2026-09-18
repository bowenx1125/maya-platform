# ADR-007: Trial the single-image courtyard splat in a fixed view

## Context

The debate stage has one Three.js canvas for the licensed figures and table,
with a static courtyard behind it. A Gaussian-splat courtyard could bring the
table and architecture into one spatial asset. The owner allowed the available
image generator and asked for PLY/SOG experimentation without waiting for a
specific image-model label.

Three courtyard views were generated locally. Their architecture, plants and
table details drift between views, so they are not a trustworthy capture of one
scene for multi-view reconstruction. The images and reconstructed media remain
under ignored `data/courtyard-splat/`; no generated media enters Git.

BLUNT with the Apache-2.0 Depth Anything V2 metric-outdoor small model lifted
the front view to a 1,228,800-Gaussian PLY. PlayCanvas SplatTransform 3.4.2
converted it to a 6.2 MB SOG. A standalone SuperSplat viewer loaded the model,
but camera movement exposed stretched architecture, missing surfaces and a
broken table silhouette. This is a depth-lifted single view, not a navigable
reconstruction. The low-spec classroom display has not been profiled.

## Decision

Keep the default classroom stage unchanged. The local `?splat=1` trial loads
the ignored SOG in the existing WebGL canvas, overlays the figures and hides
the procedural table only after loading succeeds. Missing media or decode
failure keeps the static courtyard and procedural table. The view remains
fixed, with only subtle background drift. A production splat needs consistent
overlapping real views or a world-generation service result, a visually
accepted table and floor, and measured Chrome/Edge performance.

The trial uses Spark in the existing Three.js renderer and canvas, with a
separate scene and camera for the calibrated single-view splat. Avoid embedding
generated media or provider responses in the repository.

## References

- [BLUNT](https://github.com/SonnyC56/blunt)
- [PlayCanvas SplatTransform](https://github.com/playcanvas/splat-transform)
- [Spark Three.js integration](https://sparkjs.dev/docs/)
