# Meshy GLB inspection — 2026-09-14

Source: `downloads/Meshy_AI_Character_output (5).glb`.
Original file was read only. Fingerprint and mesh counts: `RIG_REVIEW.json`.

38 joints, one skinned mesh, eight weight slots per vertex, no animation clips.
The **two lower forward legs** lack dedicated chains. The upper arms do have
chains; the first wireframe reading briefly misidentified the missing pair as
upper/front limbs, corrected after the textured render and spatial weight audit.

Spatial samples of the lower forward legs (y < .30; front z > -.15;
x < -.27 / x > .27 in glTF coordinates) contain 1,733 / 1,914 vertices.
Their aggregate skin influence includes 55.81% from `Bone_020` on one side and
43.46% from `Bone_016` on the other. Those bones end the upper arm chains.
These samples are evidence of cross-limb weight assignment, not exact anatomical
segmentation masks suitable for automatically rewriting the weights.

Required correction: two dedicated leg chains, parented to the appropriate body
joint, then anatomically reviewed weights. Test upper-arm movement separately
from each of the four lower legs. Preserve the existing character and original
file. This was the initial diagnosis; the authorized correction is recorded below.

Local evidence: `art/qa/meshy-rig-inspection.png` (three projected views) and
`art/qa/meshy-original-render.png` (Blender render of the unchanged input).

## Authorized correction — 2026-09-14

The two lower forward legs now have `FrontLeg_Upper/Lower/Foot/Toe_L` and `_R`
chains parented to the abdomen/body bone `Bone_002`. The skeleton has 46 joints.
Geometry, normals, UVs and triangle indices are unchanged. Skinning weights were
reassigned in each anatomically reviewed leg and its narrow topological collar;
the collar blends into the body, with no upper-arm influence. The original eight
weight slots are reduced to the four strongest normalized weights for WebGL
compatibility. These are **mesh skinning weights**, unrelated to neural weights.

`tools/character/repair_fly_glb.py` is a reproducible source-hash-pinned repair,
not a generic automatic rigger. It welds positions for connectivity selection
only, identifies each separate lower leg below the reviewed cut, extends a
bounded surface collar, and writes new inverse bind matrices. Assertions check
normalization, bind transforms, separation of the two selections and independent
skinning under hip/knee rotations. Moving either arm does not move either
corrected leg. `RIG_REPAIR.json` records the numerical evidence. Blender imports
the complete master with 46 bones and a valid armature modifier; see
`BLENDER_IMPORT.json`. No original mesh or source file was overwritten.

Artifacts:

- Full-resolution corrected master: `./output/meshy/the-fly-rigged.glb` (59,337,384 bytes; original texture pixels).
- Browser delivery: `spectacle/static/assets/the-fly.glb` (10,493,540 bytes; textures resized to a maximum 2048 px, then losslessly WebP encoded).
- Download copy: `./output/meshy/the-fly-web.glb`.
- Source/delivery hashes: `DELIVERY.json`.

Rebuild from the unchanged source:

```sh
python tools/character/repair_fly_glb.py --source 'downloads/Meshy_AI_Character_output (5).glb' --output output/meshy
```

The master uses core glTF PNG textures. The web version requires
`EXT_texture_webp`, supported by the bundled loader. Both carry the same mesh,
46-joint skeleton and corrected skinning. Neither contains baked animation clips;
`fly3d.js` drives presentation poses in the existing application.

Integration is live in the **local review viewer** at `http://localhost:8797/`.
`/rig-inspector.html` has independent controls for each upper/lower front leg,
front foot, upper arm and rear leg. Browser evidence covers both Chromium and
WebKit: actual mesh rendering, ten individual poses, context restoration,
reduced motion, stale idle rendering and a mobile fallback when the GLB fails.
The existing complete spectator browser flow also passed with the new model.
QA captures: `art/qa/*rig*.png`, `*fixture*.png`, `actual-history-*.png`.

The source's stylized glossy eyes and material detail are preserved. The initial
JPEG delivery experiment was discarded; the shipped version uses lossless WebP
after texture resampling. Character motion is explicitly illustrative and does
not pretend to be measured neural or motor activity. The live paper worker,
brain, trading inputs and canonical decisions are untouched by this correction.
