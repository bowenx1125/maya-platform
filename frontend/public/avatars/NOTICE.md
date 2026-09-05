# Maya avatar preview notices

## `female_1.glb`

This local demo asset is provided by the audited `lhupyn/motion-engine` demo
asset and is retained only for the private Maya demo. The accompanying MIT
license is in `LICENSE-motion-engine.txt`. The asset is a shared compatible
mesh used by all three Maya avatar presets; presets are parameter choices, not
three independently modeled characters. The upstream demo credits Ready
Player Me as the avatar creator; this local inclusion is not a public asset
licence clearance. Recheck the asset terms before sharing or deploying Maya.

## Draco decoder

The files under `draco/` are the GLTF Draco decoder assets distributed with
`three` 0.185.1. They are served locally so preview loading never reaches a
CDN. The decoder build is distributed under Apache License 2.0; the local
license text is in `LICENSE-draco.txt`. Three.js itself is distributed under
the MIT license; its license text is in `LICENSE-threejs.txt` and the
dependency version is pinned in the workspace lockfile.

## `laozi/` — Debates (beta) bench

`scholar_base.glb`, `clip_sit.glb`, `clip_talk.glb`, `clip_wave.glb` and
`sumie_bg.jpg` come from the project owner's own Laozi digital-human prototype,
supplied for this repository by the owner. The character and its animations
were generated with Meshy AI; the ink-wash backdrop ships with the same
prototype. **This inclusion is not a public asset licence clearance:** confirm
the Meshy AI output terms for classroom and any public use before Maya is
deployed or shared outside the private demo.

The three clip files are re-packed. The source exports were four ~11 MB GLBs
that each repeated the same mesh and a 6 MB texture; only `scholar_base.glb`
keeps the mesh, and the other three were reduced to their animation samplers
and node names alone, taking the bench from 44 MB to 11.9 MB. The re-pack
changes no geometry, no texture and no keyframe values.

The figures carry a skeleton but no blendshapes, so the beta stage drives head
and torso bones where the platform's head-only avatar drives ARKit morph
targets. Expression and mouth parameters have no effect on these meshes.
