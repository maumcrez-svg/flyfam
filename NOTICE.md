# Third-party notices

## flycoinrh — MIT

This repository vendors https://github.com/fruitflydev/flycoinrh at commit
`5aab4e7895a1f5930319bf3bde8010b350a163a2` under `upstream/`, unmodified.

It is MIT licensed, © 2026 fruitflydev. The license text is preserved verbatim
at `upstream/LICENSE` and its own notice at `upstream/NOTICE`. MIT requires
that the copyright notice and permission notice accompany any copy or
substantial portion of the software; both files stay in this tree for that
reason, and must not be removed or relocated without replacing them here.

`docs/UPSTREAM_MANIFEST.txt` pins the exact bytes (commit, tree hash, and every
blob hash) so the vendored copy can be diffed against a fresh clone.

## FlyEM male CNS connectome v1.0 — CC-BY 4.0

The connectome data is **not** covered by the MIT grant above and is not
currently present in this repository. Quoting `upstream/NOTICE`:

> The male Drosophila CNS dataset is © HHMI Janelia FlyEM, the Cambridge
> Connectomics Group and Google Research, released under CC-BY 4.0, and it
> stays under CC-BY wherever it goes.

The attribution obligation attaches the moment the data is downloaded, and
applies to any derived artifact — including a built `graph.npz`, any figure,
and any public page that displays measured anatomy. Attribution must name
HHMI Janelia FlyEM, the Cambridge Connectomics Group and Google Research, and
state CC-BY 4.0.

Simulation approach after Shiu et al. 2024 and Lappalainen et al. 2024. This
project is not affiliated with any of them.

## PONS protocol contracts — MIT

`experiments/d10/evidence/PonsV2BondingCurve.sourcify.sol` and
`PonsV2BondingCurveMath.sol` are verbatim copies of first-party PONS contracts,
frozen from the Sourcify-verified PONS V2 factory bundle (Sourcify match
`43289536`) and from source commit
`8b9bf371030279133017b5c1b713823f5889c5d2` of
<https://github.com/ponsdotdev/ponsfamily>. They are **MIT licensed**, © the
PONS authors, and are kept here as the frozen source the Python quote in
`flytrade/pons/curve.py` is a port of. MIT requires the copyright notice and
permission notice to accompany any copy or substantial portion; the SPDX
identifier and the notice inside each file are preserved and must not be
stripped. The port itself is a re-expression of that arithmetic in Python and
carries the same obligation of attribution.

`PonsTickMath.sol` in the same upstream repository is **GPL-2.0-or-later** and
is **not** used, copied, ported or linked by this project. The Uniswap V3 and
V4 routes it belongs to are recorded as UNSUPPORTED for this wave.

This project is not affiliated with PONS, Robinhood, or Uniswap.
