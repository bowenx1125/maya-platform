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

## `laozi/sumie_bg.jpg`

The ink-wash backdrop behind the Debates (beta) bench comes from the project
owner's own Laozi digital-human prototype, supplied for this repository by the
owner. **This inclusion is not a public asset licence clearance:** confirm its
terms for classroom and any public use before Maya is deployed or shared
outside the private demo.

The animated character bodies that shipped alongside it were removed. They
carried a skeleton and no blendshapes, so a speaking Agent could never open its
mouth; the bench now uses `female_1.glb` above, whose full ARKit morph set is
what lets a speech read as speech. Dropping them also took the stage assets
from 11.9 MB to 3.8 MB and removed an unresolved licence question with them.
