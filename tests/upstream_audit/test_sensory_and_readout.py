"""
(3)+(4) The sensory injection path and the motor readout, run end to end.

``flyeye.FlyEye`` and ``flyeye.FlyPilot`` are exercised unmodified over a
synthetic retinotopic graph, so the claims about units, normalisation and
readout arithmetic in docs/UPSTREAM_NOTES.md are measured rather than read.

What cannot be established here is the *size* of the real populations -- how
many L1/L2 columns, how many DNa02, how many MBONs. That needs
``data/body-annotations.feather`` from the FlyEM bucket, which this wave is
not permitted to download. See UPSTREAM_NOTES.md "Not established".
"""
from __future__ import annotations

import os

import numpy as np
import pytest

from .synthetic import Graph, Neuron, write_graph_npz

ON_MAX_HZ = 180.0        # flyeye.py:54 max_hz
OFF_SCALE = 0.6          # flyeye.py:77
DN_NORMALISER = 450.0    # flyeye.py:133-136
CLICK_HZ = 330.0         # flyeye.py:96


# Synthetic retina: two ON columns at the extremes of the hex axis so one
# samples the left half of the window and the other the right, and six OFF
# columns converging on DNp09 -- convergence is what lets a 108 Hz drive push a
# descending neuron past the 330 Hz click threshold, which is also how it works
# on the real connectome.
N_OFF = 24
RETINA = (
    ["L1"] * 2 + ["L2"] * N_OFF +
    ["DNa02", "DNa02", "DNa01", "DNa01", "MDN", "DNp09", "MN9"]
)
L1_LEFT, L1_RIGHT = 0, 1
L2 = list(range(2, 2 + N_OFF))
DNA02_L, DNA02_R, DNA01_L, DNA01_R, MDN, DNP09, MN9 = (
    2 + N_OFF + i for i in range(7))
DNA02_L, DNA02_R, DNA01_L, DNA01_R, MDN, DNP09, MN9 = (
    2 + N_OFF, 3 + N_OFF, 4 + N_OFF, 5 + N_OFF, 6 + N_OFF, 7 + N_OFF,
    8 + N_OFF)

HEX1 = [0, N_OFF - 1] + list(range(N_OFF)) + [None] * 7
HEX2 = [0, 0] + [0] * N_OFF + [None] * 7
SIDE = [""] * (2 + N_OFF) + ["L", "R", "L", "R", "", "", ""]

EDGES = (
    [(L1_LEFT, DNA02_L, 60.0), (L1_RIGHT, DNA02_R, 60.0),
     (L1_LEFT, DNA01_L, 60.0), (L1_RIGHT, DNA01_R, 60.0),
     (L1_LEFT, MN9, 60.0)] +
    [(i, DNP09, 60.0) for i in L2] +
    [(L2[0], MDN, 60.0)]
)


def _build(tmp_path, flysim):
    # synthetic.Graph resolves edges by name, and the real type names repeat,
    # so wire on unique names and rewrite `types` afterwards.
    uniq = [Neuron(f"{t}#{i}") for i, t in enumerate(RETINA)]
    g = Graph(uniq, [(uniq[a].name, uniq[b].name, w) for a, b, w in EDGES])
    p = write_graph_npz(g, tmp_path / "retina.npz")

    z = dict(np.load(p, allow_pickle=False))
    z["types"] = np.array(RETINA, dtype=str)
    np.savez_compressed(p, **z)

    import pandas as pd
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    pd.DataFrame({
        "bodyId": z["bodies"],
        "assignedOlHex1": pd.array(HEX1, dtype="Float64"),
        "assignedOlHex2": pd.array(HEX2, dtype="Float64"),
        "somaSide": SIDE,
    }).to_feather(data / "body-annotations.feather")
    return flysim.FlyBrain(graph_path=p), tmp_path


@pytest.fixture
def rig(tmp_path, flysim, monkeypatch):
    fb, root = _build(tmp_path, flysim)
    monkeypatch.chdir(root)          # flyeye.py:99 reads a CWD-relative path
    import flyeye
    return fb, flyeye


def test_only_l1_and_l2_are_stimulated(rig):
    """
    flyeye.py:26-27 selects exactly ``types == "L1"`` and ``types == "L2"``,
    and only where the annotation carries hex coordinates. Nothing else in the
    connectome receives external drive.
    """
    fb, flyeye = rig
    eye = flyeye.FlyEye(fb)
    assert eye.on_mask.sum() == 2 and eye.off_mask.sum() == N_OFF
    assert set(fb.types[eye.on_idx]) == {"L1"}
    assert set(fb.types[eye.off_idx]) == {"L2"}
    img = np.ones((800, 1280), dtype=np.float32)
    drive = eye.look(img, 640, 400)
    stimulated = set(np.concatenate([np.asarray(k) for k in drive]).tolist())
    assert stimulated == set(eye.on_idx.tolist()) | set(eye.off_idx.tolist())


def test_drive_units_are_hz_and_the_scaling_is_linear_in_luminance(rig):
    """
    flyeye.py:76-77. L1 = clip(lum, 0, 1) * 180 Hz. L2 = clip(1 - lum, 0, 1) *
    180 * 0.6 Hz. The image is expected in [0, 1] luminance; there is no
    contrast normalisation, no adaptation and no temporal filter.
    """
    fb, flyeye = rig
    eye = flyeye.FlyEye(fb)

    white = eye.look(np.ones((800, 1280), np.float32), 640, 400)
    on, off = [np.asarray(v, dtype=float) for v in white.values()]
    assert np.allclose(on, ON_MAX_HZ)
    assert np.allclose(off, 0.0)

    black = eye.look(np.zeros((800, 1280), np.float32), 640, 400)
    on, off = [np.asarray(v, dtype=float) for v in black.values()]
    assert np.allclose(on, 0.0)
    assert np.allclose(off, ON_MAX_HZ * OFF_SCALE)

    grey = eye.look(np.full((800, 1280), 0.25, np.float32), 640, 400)
    on, off = [np.asarray(v, dtype=float) for v in grey.values()]
    assert np.allclose(on, 0.25 * ON_MAX_HZ)
    assert np.allclose(off, 0.75 * ON_MAX_HZ * OFF_SCALE)


def test_out_of_range_luminance_is_clipped_not_rejected(rig):
    """Values outside [0, 1] saturate silently. An encoder must normalise."""
    fb, flyeye = rig
    eye = flyeye.FlyEye(fb)
    hot = eye.look(np.full((800, 1280), 5.0, np.float32), 640, 400)
    on, off = [np.asarray(v, dtype=float) for v in hot.values()]
    assert np.allclose(on, ON_MAX_HZ)
    assert np.allclose(off, 0.0)


def test_sampling_is_egocentric_and_clipped_at_the_image_edge(rig):
    """
    flyeye.py:68-69: the 300x210 px window is centred on the cursor and each
    pixel index is clipped into the image. At an edge the same pixel is
    sampled by several columns, so the retinal image is not translation
    invariant there.
    """
    fb, flyeye = rig
    eye = flyeye.FlyEye(fb)
    img = np.zeros((800, 1280), np.float32)
    img[:, :200] = 1.0                    # bright band down the left edge

    centre = np.asarray(list(eye.look(img, 640, 400).values())[0], dtype=float)
    left = np.asarray(list(eye.look(img, 10, 400).values())[0], dtype=float)
    assert centre.max() == 0.0            # band is outside the window
    assert left.min() == ON_MAX_HZ        # every column lands on the band


def test_motor_readout_populations_are_the_documented_seven(rig):
    """flyeye.py:109-117."""
    fb, flyeye = rig
    pilot = flyeye.FlyPilot(fb, sim_steps=60)
    assert set(pilot.motor) == {"steer_L", "steer_R", "fwd_L", "fwd_R",
                                "back", "stop", "click"}
    assert set(fb.types[pilot.motor["steer_L"]]) == {"DNa02"}
    assert set(fb.types[pilot.motor["back"]]) == {"MDN"}
    assert set(fb.types[pilot.motor["stop"]]) == {"DNp09"}
    assert set(fb.types[pilot.motor["click"]]) == {"MN9"}
    # steering is split by measured soma side, nothing else is
    assert pilot.motor["steer_L"].tolist() == [DNA02_L]
    assert pilot.motor["steer_R"].tolist() == [DNA02_R]


def test_steering_is_a_right_minus_left_difference(rig):
    """
    flyeye.py:133 ``turn = (steer_R - steer_L) / 450``, then clipped to
    [-1, 1] and scaled by 90 px. A bright right hemifield must move the
    cursor right, a bright left hemifield left.
    """
    fb, flyeye = rig
    pilot = flyeye.FlyPilot(fb, sim_steps=200)
    img = np.zeros((800, 1280), np.float32)

    # the two ON columns sample the left and right halves of the window
    u = pilot.eye.on_uv[0]
    assert u.min() == 0.0 and u.max() == 1.0

    img[:, 640:] = 1.0
    dx_r, _, _, hz_r = pilot.step(img, 640, 400, seed=1)
    img[:] = 0.0
    img[:, :640] = 1.0
    dx_l, _, _, hz_l = pilot.step(img, 640, 400, seed=1)

    assert hz_r["steer_R"] > hz_r["steer_L"] and dx_r > 0
    assert hz_l["steer_L"] > hz_l["steer_R"] and dx_l < 0
    assert dx_r == pytest.approx(
        np.clip((hz_r["steer_R"] - hz_r["steer_L"]) / DN_NORMALISER, -1, 1) * 90.0)


def test_forward_is_the_sum_and_the_screen_y_axis_is_inverted(rig):
    """flyeye.py:134,140: fwd = mean(DNa01 L, R) / 450; dy = -speed * 90."""
    fb, flyeye = rig
    pilot = flyeye.FlyPilot(fb, sim_steps=200)
    img = np.ones((800, 1280), np.float32)
    dx, dy, click, hz = pilot.step(img, 640, 400, seed=1)
    fwd = (hz["fwd_L"] + hz["fwd_R"]) / 2.0 / DN_NORMALISER
    back = hz["back"] / DN_NORMALISER
    stop = hz["stop"] / DN_NORMALISER
    speed = np.clip(fwd - back, -1, 1) * (1.0 - np.clip(stop, 0, 1))
    assert dy == pytest.approx(-speed * 90.0)
    assert hz["fwd_L"] > 0 and hz["fwd_R"] > 0


def test_the_commit_action_is_a_threshold_on_dnp09_not_on_mn9(rig):
    """
    flyeye.py:148 ``click = hz['stop'] >= 330 and speed < 0.25``. MN9 -- the
    proboscis motor neuron the docstring calls the obvious commit signal -- is
    recorded but does not gate the click. The only discrete action upstream
    produces is this one bit.
    """
    fb, flyeye = rig
    pilot = flyeye.FlyPilot(fb, sim_steps=400)

    dark = np.zeros((800, 1280), np.float32)   # dark -> L2 -> DNp09 hard
    dx, dy, click, hz = pilot.step(dark, 640, 400, seed=1)
    assert hz["stop"] >= CLICK_HZ
    assert bool(click) is True
    # flyeye.py:148 ands a Python bool with a numpy comparison, so the flag
    # that reaches a caller is np.bool_, not bool. Trivial, but a Phase-One
    # DecisionRecord that json-serialises it will raise.
    assert isinstance(click, np.bool_)

    bright = np.ones((800, 1280), np.float32)  # bright -> DNa01 -> moving
    dx, dy, click, hz = pilot.step(bright, 640, 400, seed=1)
    assert hz["stop"] == 0.0
    assert bool(click) is False


def test_readout_is_a_mean_rate_over_the_population(rig):
    """flyeye.py:130: one scalar Hz per group, averaged over its neurons."""
    fb, flyeye = rig
    pilot = flyeye.FlyPilot(fb, sim_steps=200)
    img = np.ones((800, 1280), np.float32)
    drive = pilot.eye.look(img, 640, 400)
    r = fb.run(drive, steps=200, record=pilot.motor, seed=1)
    assert r["fwd_L"].shape == (1,)
    _, _, _, hz = pilot.step(img, 640, 400, seed=1)
    assert hz["fwd_L"] == pytest.approx(float(r["fwd_L"].mean()))


def test_one_control_step_is_a_fresh_simulation_window(rig):
    """
    Nothing carries over between control steps except the weights, so the
    readout is a function of the current frame alone -- there is no neural
    memory of the previous decision in this loop.
    """
    fb, flyeye = rig
    pilot = flyeye.FlyPilot(fb, sim_steps=200)
    bright = np.ones((800, 1280), np.float32)
    dark = np.zeros((800, 1280), np.float32)
    a = pilot.step(bright, 640, 400, seed=1)[3]
    pilot.step(dark, 640, 400, seed=1)
    b = pilot.step(bright, 640, 400, seed=1)[3]
    assert a == b
