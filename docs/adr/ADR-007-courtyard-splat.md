# ADR-007: Keep the single-image courtyard splat out of the classroom stage

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

Do not replace the classroom backdrop or hide the Three.js table with this
asset. Keep the existing stage while retaining the local PLY, SOG, images and
viewer for comparison. A production splat needs consistent overlapping real
views or a world-generation service result, a visually accepted table and
floor, measured Chrome/Edge performance, and a fallback when loading fails.

When an accepted SOG exists, render it in the existing Three.js scene via a
compatible splat renderer rather than introducing a second WebGL scene. Avoid
embedding generated media or provider responses in the repository.

## References

- [BLUNT](https://github.com/SonnyC56/blunt)
- [PlayCanvas SplatTransform](https://github.com/playcanvas/splat-transform)
- [Spark Three.js integration](https://sparkjs.dev/docs/)
