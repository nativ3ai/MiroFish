#!/usr/bin/env python3
"""TRON YTP — PrediHermes showcase.

Rapid-fire smash-cut YTP with ASCII art animations, heavy 808 bass,
screen shake, stutter repeats, full-screen text slams, matrix rain,
CRT warp, and chaotic glitch energy.  Nothing slow, nothing boring.

1920x1080 landscape, ~30s @ 24fps, H.264 + AAC.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = Path(
    "/Users/native/.hermes/data/geopolitical-market-sim/runs/"
    "iran-conflict/20260316_025815/iran-conflict_snapshot.json"
)
BASE_SIM = ROOT / "backend" / "uploads" / "simulations" / "sim_039c095547c5"
BRANCH_SIM = ROOT / "backend" / "uploads" / "simulations" / "sim_b48c23571420"
FONT = "/System/Library/Fonts/Menlo.ttc"

W, H = 1920, 1080
FPS = 24
BPM = 140
DUR = 30.0

# -- colors --
BG = (1, 2, 5)
CYAN = (0, 220, 255)
ORANGE = (255, 100, 0)
WHITE = (240, 245, 255)
DIM = (40, 55, 80)
GRID_C = (8, 24, 40)

# ── ASCII art ──────────────────────────────────────────────────────────────
ASCII_LOGO = r"""
 ____  ____  _____ ____  _ _   _ _____ ____  __  __ _____ ____
|  _ \|  _ \| ____|  _ \| | | | | ____|  _ \|  \/  | ____/ ___|
| |_) | |_) |  _| | | | | | |_| |  _| | |_) | |\/| |  _| \___ \
|  __/|  _ <| |___| |_| | |  _  | |___|  _ <| |  | | |___ ___) |
|_|   |_| \_\_____|____/|_|_| |_|_____|_| \_\_|  |_|_____|____/
""".strip().split("\n")

ASCII_PH_SHORT = r"""
 ____  _   _
|  _ \| | | |
| |_) | |_| |
|  __/|  _  |
|_|   |_| |_|
 PREDIHERMES
""".strip().split("\n")

ASCII_OSINT = r"""
  ╔══════════════════════════════╗
  ║  W O R L D O S I N T        ║
  ║  ~~~~~~~~~~~~~~~~~~~~~~~~    ║
  ║  [■] rss_feeds       LIVE   ║
  ║  [■] military_intel   LIVE  ║
  ║  [■] maritime_track   LIVE  ║
  ║  [■] sanctions_db     LIVE  ║
  ║  [■] risk_scoring     LIVE  ║
  ║  modules: 63 / 63 ONLINE    ║
  ╚══════════════════════════════╝
""".strip().split("\n")

ASCII_SIM = r"""
  ┌─────────┐  counterfactual  ┌─────────┐
  │  BASE   │ ═══════════════> │ BRANCH  │
  │ sim_039 │    injection     │ sim_b48 │
  │ 44 agt  │    round 10      │ 45 agt  │
  │ 903 act │                  │ 1147act │
  └────┬────┘                  └────┬────┘
       │      ╔══════════╗          │
       └─────>║ DIFF MAP ║<────────┘
              ╚══════════╝
""".strip().split("\n")

ASCII_MARKET = r"""
  ╔═══════════════════════════════╗
  ║   P O L Y M A R K E T        ║
  ║  ┌─────────────────────────┐  ║
  ║  │ US-Iran Nuclear Deal?   │  ║
  ║  │ BID ████████░░  YES     │  ║
  ║  │ ASK ██████████░ YES     │  ║
  ║  │ VOL ████████████████    │  ║
  ║  └─────────────────────────┘  ║
  ╚═══════════════════════════════╝
""".strip().split("\n")

ASCII_BUTTERFLY = r"""
        .        .
       / \      / \
      /   \    /   \
     / B   \  / R   \
    / A     \/  A    \
   /  S      \  N     \
  /   E       \ C      \
 /             \ H      \
 \    ──────>   \        /
  \  DIVERGE  /  \      /
   \         /    \    /
    \       /      \  /
     \_____/        \/
""".strip().split("\n")

ASCII_PIPELINE = r"""
  OSINT ──> MARKET ──> SIM ──> BRANCH
    │          │         │        │
    ▼          ▼         ▼        ▼
  ┌────┐   ┌────┐   ┌────┐   ┌────┐
  │ 63 │   │ bid│   │ 44 │   │ 45 │
  │mod │   │ ask│   │agt │   │agt │
  └────┘   └────┘   └────┘   └────┘
""".strip().split("\n")

ASCII_WAVE = r"""
     /\      /\      /\      /\
    /  \    /  \    /  \    /  \
   /    \  /    \  /    \  /    \
  /      \/      \/      \/      \
 /                                \
/  S I G N A L   D E T E C T E D  \
""".strip().split("\n")

ASCII_EYE = r"""
          ___________
       .-'           '-.
     .'    ___   ___    '.
    /     /   \ /   \     \
   |     | (o) | (o) |     |
   |      \___/ \___/      |
    \     _____________     /
     '.  |  WATCHING  |  .'
       '-._________.-'
""".strip().split("\n")

ASCII_SKULL = r"""
       ████████████
     ██            ██
    █   ██      ██   █
   █   ████    ████   █
   █                   █
    █    ██████████    █
     █   ██  ██  ██   █
      █   ████████   █
       ██          ██
         ██████████
""".strip().split("\n")

# ── sub-scenes: rapid cuts ─────────────────────────────────────────────────
# Each "beat" is ~0.43s at 140bpm.  Scenes are 2-8 beats long.
# Format: (start_frame, end_frame, type, accent, data)
# We build these at 24fps.

def _f(sec: float) -> int:
    return int(sec * FPS)

# Scene timeline — much faster cuts
CUTS: list[tuple[int, int, str, str, Any]] = []

def _build_cuts(m: dict) -> None:
    CUTS.clear()
    mk = m["market"]
    bid = f"{mk.get('bestBid',0)*100:.0f}%"
    ask = f"{mk.get('bestAsk',0)*100:.0f}%"
    ba = m["base_state"]
    br = m["branch_state"]
    cf = m["counterfactual"]
    actor = cf.get("actor_name", "SHADOW HORMUZ UNDERWRITER")
    inj_round = cf.get("injection_round", 10)

    # (start_sec, end_sec, type, color_key, payload)
    raw = [
        # 0–1s: black + flash
        (0.0,  0.5,  "black",     "c", None),
        (0.5,  0.7,  "flash",     "c", None),
        (0.7,  1.0,  "black",     "c", None),
        # 1–3s: PREDIHERMES intro — ASCII PH + grid
        (1.0,  1.6,  "ascii",     "c", ASCII_PH_SHORT),
        (1.6,  1.72, "invert",    "c", None),
        (1.72, 2.2,  "grid_zoom", "c", None),
        (2.2,  2.32, "flash",     "o", None),
        (2.32, 3.0,  "text_slam", "c", "PREDIHERMES"),
        # 3–5.5s: install sequence
        (3.0,  3.12, "flash",     "o", None),
        (3.12, 3.7,  "terminal",  "o", "$ git clone nativ3ai/hermes-geo…"),
        (3.7,  3.82, "stutter",   "o", None),
        (3.82, 4.3,  "terminal",  "o", "Cloning into 'hermes-geopolitical'…"),
        (4.3,  4.42, "flash",     "c", None),
        (4.42, 5.0,  "terminal",  "o", "$ ./install.sh\ndeps: requests worldosint mirofish"),
        (5.0,  5.12, "invert",    "o", None),
        (5.12, 5.5,  "text_slam", "o", "INSTALLED"),
        # 5.5–8.5s: OSINT — ASCII OSINT panel + count-up + wave
        (5.5,  5.62, "flash",     "c", None),
        (5.62, 6.4,  "ascii",     "c", ASCII_OSINT),
        (6.4,  6.52, "stutter",   "c", None),
        (6.52, 7.4,  "countup",   "c", 63),
        (7.4,  7.52, "flash",     "c", None),
        (7.52, 8.0,  "ascii",     "c", ASCII_WAVE),
        (8.0,  8.12, "invert",    "c", None),
        (8.12, 8.5,  "text_slam", "c", "63 MODULES"),
        # 8.5–12s: market link — ASCII market + stats
        (8.5,  8.62, "flash",     "o", None),
        (8.62, 9.4,  "ascii",     "o", ASCII_MARKET),
        (9.4,  9.52, "invert",    "o", None),
        (9.52, 10.1, "big_stat",  "o", f"BID {bid}"),
        (10.1, 10.22,"flash",     "o", None),
        (10.22,10.8, "big_stat",  "o", f"ASK {ask}"),
        (10.8, 10.92,"stutter",   "o", None),
        (10.92,11.5, "terminal",  "o", f"liquidity ${mk.get('liquidityNum',0)/1000:.0f}K | vol ${mk.get('volumeNum',0)/1e6:.1f}M"),
        (11.5, 11.62,"flash",     "o", None),
        (11.62,12.0, "text_slam", "o", "POLYMARKET"),
        # 12–16s: sim engine — ASCII sim diagram + round spin
        (12.0, 12.12,"flash",     "c", None),
        (12.12,13.0, "ascii",     "c", ASCII_SIM),
        (13.0, 13.12,"stutter",   "c", None),
        (13.12,13.8, "terminal",  "c", f"base: {ba.get('total_actions_count',0)} actions / 44 agents"),
        (13.8, 14.6, "round_spin","c", ba.get("current_round", 28)),
        (14.6, 14.72,"invert",    "c", None),
        (14.72,15.3, "ascii",     "c", ASCII_PIPELINE),
        (15.3, 15.42,"flash",     "c", None),
        (15.42,16.0, "text_slam", "c", "MIROFISH"),
        # 16–20s: counterfactual — skull + butterfly + branch diff
        (16.0, 16.12,"flash",     "o", None),
        (16.12,16.8, "ascii",     "o", ASCII_SKULL),
        (16.8, 16.92,"invert",    "o", None),
        (16.92,17.5, "terminal",  "o", f"INJECTED: {actor}\nROUND {inj_round}"),
        (17.5, 18.2, "ascii",     "o", ASCII_BUTTERFLY),
        (18.2, 18.32,"stutter",   "o", None),
        (18.32,18.9, "terminal",  "o", "butterfly effect: shipping premium reframe"),
        (18.9, 19.02,"flash",     "o", None),
        (19.02,19.5, "ascii",     "o", ASCII_EYE),
        (19.5, 19.62,"invert",    "o", None),
        (19.62,20.0, "text_slam", "o", "COUNTERFACTUAL"),
        # 20–24s: montage — rapid ascii art barrage + stats
        (20.0, 20.12,"flash",     "c", None),
        (20.12,20.6, "ascii",     "c", ASCII_WAVE),
        (20.6, 20.72,"invert",    "c", None),
        (20.72,21.2, "big_stat",  "c", f"{m['headline_count']} HEADLINES"),
        (21.2, 21.32,"flash",     "o", None),
        (21.32,21.8, "ascii",     "o", ASCII_MARKET),
        (21.8, 21.92,"stutter",   "o", None),
        (21.92,22.4, "big_stat",  "o", f"{m['feeds_count']} FEEDS"),
        (22.4, 22.52,"flash",     "c", None),
        (22.52,23.0, "ascii",     "c", ASCII_PH_SHORT),
        (23.0, 23.12,"invert",    "o", None),
        (23.12,23.5, "ascii",     "o", ASCII_OSINT),
        (23.5, 23.62,"flash",     "c", None),
        (23.62,24.0, "text_slam", "c", "REAL DATA"),
        # 24–28s: endcard build
        (24.0, 24.12,"flash",     "c", None),
        (24.12,25.0, "ascii_big", "c", ASCII_LOGO),
        (25.0, 25.12,"stutter",   "c", None),
        (25.12,25.6, "ascii",     "o", ASCII_PIPELINE),
        (25.6, 25.72,"flash",     "o", None),
        (25.72,27.0, "endcard",   "c", None),
        (27.0, 27.12,"invert",    "o", None),
        (27.12,27.6, "ascii",     "c", ASCII_BUTTERFLY),
        (27.6, 27.72,"flash",     "c", None),
        (27.72,28.0, "endcard",   "c", None),
        # 28–30s: final hits + fade
        (28.0, 28.12,"flash",     "o", None),
        (28.12,28.6, "ascii",     "c", ASCII_EYE),
        (28.6, 28.72,"invert",    "c", None),
        (28.72,29.0, "endcard",   "c", None),
        (29.0, 29.12,"flash",     "c", None),
        (29.12,30.0, "fadeout",   "c", None),
    ]
    for s, e, kind, col, data in raw:
        CUTS.append((_f(s), _f(e), kind, col, data))


# ── data loading ───────────────────────────────────────────────────────────

def load_metrics() -> dict:
    snap = json.loads(SNAPSHOT.read_text())
    bs = json.loads((BASE_SIM / "run_state.json").read_text())
    brs = json.loads((BRANCH_SIM / "run_state.json").read_text())
    cfg = json.loads((BRANCH_SIM / "simulation_config.json").read_text()).get("counterfactual", {})
    news = snap.get("news") or {}
    return {
        "market": (snap.get("markets") or [{}])[0],
        "headline_count": len(news.get("items") or []),
        "feeds_count": len(news.get("feeds") or []),
        "base_state": bs,
        "branch_state": brs,
        "counterfactual": cfg,
    }


# ── fonts ──────────────────────────────────────────────────────────────────

def _font(sz: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT, size=sz, index=1 if bold else 0)
    except Exception:
        return ImageFont.load_default()

FNT_MEGA  = _font(120, True)
FNT_BIG   = _font(72, True)
FNT_MED   = _font(36, True)
FNT_TERM  = _font(26, False)
FNT_ASCII = _font(18, False)
FNT_SMALL = _font(14, False)


# ── rendering helpers ──────────────────────────────────────────────────────

def _col(key: str, frame: int = 0) -> tuple[int, int, int]:
    if key == "c":
        return CYAN
    if key == "o":
        return ORANGE
    return CYAN if (frame // 3) % 2 == 0 else ORANGE


def _shake(rng: random.Random, intensity: float = 1.0) -> tuple[int, int]:
    return (rng.randint(int(-8 * intensity), int(8 * intensity)),
            rng.randint(int(-6 * intensity), int(6 * intensity)))


def _matrix_rain(arr: np.ndarray, rng: random.Random, t: float, color: tuple) -> None:
    """Fast matrix-style falling characters baked into the array."""
    h, w = arr.shape[:2]
    num_drops = 60
    for i in range(num_drops):
        x = (i * 31 + int(t * 200)) % w
        speed = 80 + (i * 17) % 120
        y_head = int((t * speed + i * 47) % (h + 200)) - 100
        trail = 8 + i % 12
        for j in range(trail):
            y = y_head - j * 18
            if 0 <= y < h and 0 <= x < w:
                fade = max(0.1, 1.0 - j / trail)
                for c in range(3):
                    arr[y, x, c] = min(255, arr[y, x, c] + int(color[c] * fade * 0.3))


def _perspective_grid(arr: np.ndarray, t: float) -> None:
    """Fast vectorized TRON floor grid."""
    h, w = arr.shape[:2]
    horizon = h // 3
    floor_h = h - horizon
    scroll = (t * 120) % 100

    # Horizontal lines
    for i in range(25):
        frac = (((i * 100 / 25) + scroll) % 100 / 100.0) ** 2.0
        y = int(horizon + frac * floor_h)
        if 0 <= y < h:
            strength = int(15 + 35 * frac)
            arr[y, :, 2] = np.clip(arr[y, :, 2].astype(np.int16) + strength, 0, 255).astype(np.uint8)
            arr[y, :, 1] = np.clip(arr[y, :, 1].astype(np.int16) + strength // 3, 0, 255).astype(np.uint8)

    # Vertical lines via columns
    vp_x = w // 2
    for i in range(30):
        x_bot = int(w * i / 29)
        for s in range(0, floor_h, 2):
            frac = s / max(floor_h - 1, 1)
            y = h - 1 - s
            x = int(x_bot + (vp_x - x_bot) * frac)
            if 0 <= y < h and 0 <= x < w:
                strength = int(18 * max(0.1, 1.0 - frac))
                arr[y, x, 2] = min(255, arr[y, x, 2] + strength)


def render_frame(fi: int, total: int, metrics: dict, rng: random.Random,
                 prev_frames: list[np.ndarray]) -> np.ndarray:
    """Render a single frame. prev_frames stores last 6 for stutter reuse."""
    t = fi / FPS

    # Find current cut
    cut = None
    for c in CUTS:
        if c[0] <= fi < c[1]:
            cut = c
            break
    if cut is None:
        return np.zeros((H, W, 3), dtype=np.uint8)

    start, end, kind, col_key, data = cut
    local = (fi - start) / max(end - start, 1)
    color = _col(col_key, fi)
    sx, sy = _shake(rng, 0.6)

    # ── black
    if kind == "black":
        return np.full((H, W, 3), BG, dtype=np.uint8)

    # ── flash (full screen color blast 2-3 frames)
    if kind == "flash":
        arr = np.full((H, W, 3), color, dtype=np.uint8)
        # add noise
        noise = rng.randint(0, 60)
        arr = np.clip(arr.astype(np.int16) - noise, 0, 255).astype(np.uint8)
        return arr

    # ── invert (negate previous frame)
    if kind == "invert":
        if prev_frames:
            return 255 - prev_frames[-1]
        return np.full((H, W, 3), (255, 255, 255), dtype=np.uint8)

    # ── stutter (replay last 3 frames rapidly)
    if kind == "stutter":
        if prev_frames and len(prev_frames) >= 3:
            idx = fi % 3
            return prev_frames[-(3 - idx)].copy()
        elif prev_frames:
            return prev_frames[-1].copy()
        return np.zeros((H, W, 3), dtype=np.uint8)

    # ── base canvas for content frames
    arr = np.full((H, W, 3), BG, dtype=np.uint8)
    _perspective_grid(arr, t)
    _matrix_rain(arr, rng, t, color)

    img = Image.fromarray(arr, "RGB")
    d = ImageDraw.Draw(img, "RGBA")

    # ── text_slam: huge text centered, shaking
    if kind == "text_slam":
        text = str(data)
        bbox = d.textbbox((0, 0), text, font=FNT_MEGA)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (W - tw) // 2 + sx * 2
        y = (H - th) // 2 + sy * 2
        # glow
        d.text((x + 3, y + 3), text, fill=tuple(c // 3 for c in color), font=FNT_MEGA)
        d.text((x, y), text, fill=color, font=FNT_MEGA)
        arr = np.asarray(img).copy()

    # ── big_stat: large centered stat
    elif kind == "big_stat":
        text = str(data)
        bbox = d.textbbox((0, 0), text, font=FNT_BIG)
        tw = bbox[2] - bbox[0]
        x = (W - tw) // 2 + sx
        y = H // 2 - 50 + sy
        d.text((x + 2, y + 2), text, fill=tuple(c // 4 for c in color), font=FNT_BIG)
        d.text((x, y), text, fill=color, font=FNT_BIG)
        arr = np.asarray(img).copy()

    # ── terminal: monospace text block
    elif kind == "terminal":
        lines = str(data).split("\n")
        y = 200 + sy
        # draw a dark box
        d.rectangle((80, 160, W - 80, 160 + len(lines) * 42 + 60), fill=(3, 6, 12, 220))
        d.rectangle((80, 160, W - 80, 160 + len(lines) * 42 + 60), outline=color + (120,), width=2)
        # cursor blink
        cursor = "█" if (fi // 3) % 2 == 0 else " "
        for i, line in enumerate(lines):
            # type-in effect
            chars = int(len(line) * min(1.0, local * 2.5 + i * 0.1))
            visible = line[:chars]
            if i == len(lines) - 1 and chars < len(line):
                visible += cursor
            c = color if i == 0 else DIM if i > 1 else WHITE
            d.text((110 + sx, y), visible, fill=c, font=FNT_TERM)
            y += 42
        arr = np.asarray(img).copy()

    # ── ascii: render ASCII art centered
    elif kind == "ascii":
        lines = data if isinstance(data, list) else str(data).split("\n")
        total_h = len(lines) * 24
        base_y = (H - total_h) // 2 + sy
        for i, line in enumerate(lines):
            # scramble reveal
            chars = int(len(line) * min(1.0, local * 3.0))
            visible = line[:chars]
            # cycle remaining chars
            remaining = len(line) - chars
            if remaining > 0:
                glyphs = "/@#$%^&*|\\<>{}[]~!?"
                visible += "".join(rng.choice(glyphs) for _ in range(remaining))
            bbox = d.textbbox((0, 0), visible, font=FNT_TERM)
            tw = bbox[2] - bbox[0]
            x = (W - tw) // 2 + sx
            fade = max(0.4, 1.0 - abs(i - len(lines) / 2) / (len(lines) / 2 + 1))
            c = tuple(int(cc * fade) for cc in color)
            d.text((x, base_y + i * 24), visible, fill=c, font=FNT_TERM)
        arr = np.asarray(img).copy()

    # ── ascii_big: ASCII logo drawn bigger
    elif kind == "ascii_big":
        lines = data if isinstance(data, list) else str(data).split("\n")
        total_h = len(lines) * 30
        base_y = (H - total_h) // 2 + sy
        for i, line in enumerate(lines):
            chars = int(len(line) * min(1.0, local * 2.0))
            visible = line[:chars]
            bbox = d.textbbox((0, 0), visible, font=FNT_MED)
            tw = bbox[2] - bbox[0]
            x = (W - tw) // 2 + sx
            d.text((x + 2, base_y + i * 30 + 2), visible, fill=tuple(c // 4 for c in color), font=FNT_MED)
            d.text((x, base_y + i * 30), visible, fill=color, font=FNT_MED)
        arr = np.asarray(img).copy()

    # ── countup: big number counting up
    elif kind == "countup":
        target = int(data)
        current = int(target * min(1.0, local * 1.5))
        text = str(current)
        bbox = d.textbbox((0, 0), text, font=FNT_MEGA)
        tw = bbox[2] - bbox[0]
        x = (W - tw) // 2 + sx
        y = H // 2 - 80 + sy
        d.text((x + 3, y + 3), text, fill=tuple(c // 3 for c in color), font=FNT_MEGA)
        d.text((x, y), text, fill=color, font=FNT_MEGA)
        d.text(((W - 200) // 2, H // 2 + 60), "MODULES ONLINE", fill=DIM, font=FNT_MED)
        arr = np.asarray(img).copy()

    # ── round_spin: spinning round counter
    elif kind == "round_spin":
        max_r = int(data)
        current = int(max_r * min(1.0, local * 1.8))
        text = f"ROUND {current:02d}"
        bbox = d.textbbox((0, 0), text, font=FNT_BIG)
        tw = bbox[2] - bbox[0]
        x = (W - tw) // 2 + sx * 2
        y = H // 2 - 50 + sy * 2
        d.text((x, y), text, fill=color, font=FNT_BIG)
        d.text(((W - 300) // 2, H // 2 + 50), "SIMULATION ACTIVE", fill=DIM, font=FNT_MED)
        arr = np.asarray(img).copy()

    # ── grid_zoom: just the grid zooming with speed lines
    elif kind == "grid_zoom":
        # grid is already drawn, add speed lines
        cx, cy = W // 2, H // 3
        for i in range(40):
            angle = (i / 40) * 2 * math.pi + t * 3
            r1 = 50 + int(200 * local)
            r2 = r1 + 100 + int(300 * local)
            x1 = int(cx + r1 * math.cos(angle))
            y1 = int(cy + r1 * math.sin(angle))
            x2 = int(cx + r2 * math.cos(angle))
            y2 = int(cy + r2 * math.sin(angle))
            d.line((x1, y1, x2, y2), fill=color + (60,), width=1)
        arr = np.asarray(img).copy()

    # ── endcard
    elif kind == "endcard":
        # ASCII logo
        lines = ASCII_LOGO
        total_h = len(lines) * 26
        base_y = H // 2 - total_h // 2 - 80 + sy
        for i, line in enumerate(lines):
            bbox = d.textbbox((0, 0), line, font=FNT_TERM)
            tw = bbox[2] - bbox[0]
            x = (W - tw) // 2 + sx
            d.text((x, base_y + i * 26), line, fill=CYAN, font=FNT_TERM)
        # taglines
        tags = [
            "OSINT > MARKETS > SIMULATION > BRANCH DIFF",
            "terminal-native geopolitical forecasting",
            "github.com/nativ3ai",
        ]
        ty = H // 2 + 80
        for i, tag in enumerate(tags):
            bbox = d.textbbox((0, 0), tag, font=FNT_TERM)
            tw = bbox[2] - bbox[0]
            c = ORANGE if i == 0 else DIM
            d.text(((W - tw) // 2, ty + i * 32), tag, fill=c, font=FNT_TERM)
        arr = np.asarray(img).copy()

    # ── fadeout
    elif kind == "fadeout":
        # endcard content fading
        lines = ASCII_LOGO
        total_h = len(lines) * 26
        base_y = H // 2 - total_h // 2 - 80
        for i, line in enumerate(lines):
            bbox = d.textbbox((0, 0), line, font=FNT_TERM)
            tw = bbox[2] - bbox[0]
            x = (W - tw) // 2
            fade = max(0, int(CYAN[1] * (1 - local)))
            d.text((x, base_y + i * 26), line, fill=(0, fade, int(fade * 1.1)), font=FNT_TERM)
        arr = np.asarray(img).copy()
        # darken
        arr = (arr.astype(np.float32) * max(0, 1 - local)).clip(0, 255).astype(np.uint8)

    else:
        arr = np.asarray(img).copy()

    # ── post-processing ────────────────────────────────────────────────────
    # Chromatic aberration — always on, heavier on cuts
    aberr = 3 + (rng.randint(0, 5) if rng.random() < 0.3 else 0)
    r = np.roll(arr[:, :, 0], aberr, axis=1)
    b = np.roll(arr[:, :, 2], -aberr, axis=1)
    arr[:, :, 0] = r
    arr[:, :, 2] = b

    # Horizontal glitch tears — frequent
    if rng.random() < 0.4:
        for _ in range(rng.randint(1, 5)):
            y = rng.randint(0, H - 6)
            band = rng.randint(1, 8)
            shift = rng.randint(-40, 40)
            end_y = min(H, y + band)
            arr[y:end_y] = np.roll(arr[y:end_y], shift, axis=1)

    # Scanlines (every 2 rows darken)
    arr[::2] = (arr[::2].astype(np.int16) * 80 // 100).clip(0, 255).astype(np.uint8)

    # Noise
    noise = np.random.default_rng(fi * 7 + 3).integers(-8, 9, (H, W, 1), dtype=np.int16)
    arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    # CRT barrel warp (subtle — shift edge columns inward)
    warp_strength = 12
    for col_offset in range(warp_strength):
        shift = int((warp_strength - col_offset) * 0.4)
        if shift > 0 and col_offset < W:
            arr[:, col_offset] = np.roll(arr[:, col_offset], shift, axis=0)
            arr[:, W - 1 - col_offset] = np.roll(arr[:, W - 1 - col_offset], -shift, axis=0)

    # Vignette
    yy = np.linspace(-1, 1, H)[:, None]
    xx = np.linspace(-1, 1, W)[None, :]
    vig = np.clip(1.15 - np.sqrt(xx * xx + yy * yy) * 0.4, 0.5, 1.0).astype(np.float32)
    arr = (arr.astype(np.float32) * vig[:, :, None]).clip(0, 255).astype(np.uint8)

    return arr


# ── audio: heavy 808 bass + low synth ─────────────────────────────────────

def make_audio(path: Path, duration: float) -> None:
    sr = 44100
    n = int(sr * duration)
    t = np.arange(n, dtype=np.float64) / sr
    beat = 60.0 / BPM
    audio = np.zeros(n, dtype=np.float64)

    # ── gentle sidechain pulse — musical pump, not hard duck ──
    sc = np.ones(n, dtype=np.float64)
    duck = int(0.18 * sr)
    for bt in np.arange(0, duration, beat):
        i = int(bt * sr)
        j = min(n, i + duck)
        sc[i:j] *= 0.35 + 0.65 * (1 - np.exp(-np.linspace(0, 4, j - i)))

    # ══════════════════════════════════════════════════════════════
    #  TRON BASS SYNTH — cinematic soundtrack feel
    #  Three layers + chord progression that evolves over time
    # ══════════════════════════════════════════════════════════════

    # Chord progression (2 bars per chord, Am → Em → Dm → Am)
    # Each chord = 8 beats at 140bpm = ~3.43s
    chord_prog = [
        (27.5, 55.0, 82.41),   # Am: A0, A1, E2
        (32.7, 49.0, 65.41),   # Em: E1(low), G1, E2(approx)
        (29.14, 43.65, 73.42), # Dm: D1, F1, D2
        (27.5, 55.0, 82.41),   # Am: A0, A1, E2
    ]
    chord_len = 8 * beat  # 8 beats per chord
    # Build per-sample root/third/fifth frequencies
    root_f = np.zeros(n, dtype=np.float64)
    mid_f = np.zeros(n, dtype=np.float64)
    top_f = np.zeros(n, dtype=np.float64)
    for ci, (r, m, tp) in enumerate(chord_prog):
        for rep in range(int(duration / (chord_len * len(chord_prog))) + 2):
            start_s = (rep * len(chord_prog) + ci) * chord_len
            i = int(start_s * sr)
            j = min(n, int((start_s + chord_len) * sr))
            if i >= n:
                break
            root_f[i:j] = r
            mid_f[i:j] = m
            top_f[i:j] = tp
    # Fill any remaining zeros with Am
    root_f[root_f == 0] = 27.5
    mid_f[mid_f == 0] = 55.0
    top_f[top_f == 0] = 82.41

    # Layer 1: Sub-fundamental — follows root, pure sine weight
    phase_root = np.cumsum(root_f / sr) * 2 * np.pi
    sub = np.sin(phase_root) * 0.35

    # Layer 2: Main bass body — follows mid note, fat detuned sawtooth
    phase_mid = np.cumsum(mid_f / sr) * 2 * np.pi
    phase_mid_d = np.cumsum(mid_f * 1.005 / sr) * 2 * np.pi
    bass_main = np.zeros(n, dtype=np.float64)
    bass_det = np.zeros(n, dtype=np.float64)
    for k in range(1, 8):
        bass_main += np.sin(phase_mid * k) / k * 0.28
        bass_det += np.sin(phase_mid_d * k) / k * 0.28
    bass_body = (bass_main + bass_det) * 0.5

    # Layer 3: Upper harmonic — follows top note, gentle sine
    phase_top = np.cumsum(top_f / sr) * 2 * np.pi
    upper = np.sin(phase_top) * 0.12

    # Slow breathing LFO on bass body — cinematic swell
    lfo = 0.5 + 0.5 * np.sin(2 * np.pi * 0.18 * t)  # ~5.5s cycle
    bass_total = (sub + bass_body * lfo + upper) * sc
    audio += bass_total

    # ── Kick — subdued, felt not heard ──
    kick_len = int(0.3 * sr)
    for bt in np.arange(0, duration, beat):
        i = int(bt * sr)
        j = min(n, i + kick_len)
        lt = np.arange(j - i, dtype=np.float64) / sr
        env = np.exp(-lt * 10)
        freq = 55 - 25 * (lt / max(lt[-1], 1e-6))
        kick = np.sin(2 * np.pi * freq * lt) * env * 0.18  # way quieter
        audio[i:j] += kick

    # ── Snare — barely there, just a soft thud for groove ──
    snare_rng = np.random.default_rng(77)
    snare_len = int(0.08 * sr)
    for idx, bt in enumerate(np.arange(beat, duration, beat)):
        if idx % 2 != 0:
            continue
        i = int(bt * sr)
        j = min(n, i + snare_len)
        lt = np.arange(j - i, dtype=np.float64) / sr
        env = np.exp(-lt * 25)
        body = np.sin(2 * np.pi * 90 * lt) * env * 0.03
        audio[i:j] += body

    # ── Cinematic bass melody — slow evolving notes over the chords ──
    # A simple 4-note melody that plays every 2 beats, long sustained tones
    melody_notes = [55.0, 49.0, 43.65, 55.0, 65.41, 55.0, 49.0, 43.65]
    melody_step = beat * 2  # half-note feel
    for idx, mel_at in enumerate(np.arange(0, duration, melody_step)):
        freq = melody_notes[idx % len(melody_notes)]
        length = melody_step * 0.95  # almost legato
        i = int(mel_at * sr)
        j = min(n, i + int(length * sr))
        if j <= i:
            continue
        lt = np.arange(j - i, dtype=np.float64) / sr
        # Slow attack + slow release — cinematic pad-like envelope
        attack = np.clip(lt / 0.15, 0, 1)  # 150ms attack
        release = np.clip((length - lt * sr / sr) / 0.3, 0, 1)
        env = attack * release
        # Sawtooth with fewer harmonics — smoother, more pad-like
        mel = np.zeros(j - i, dtype=np.float64)
        for k in range(1, 5):
            mel += np.sin(2 * np.pi * freq * k * lt) / (k * k)  # 1/k^2 rolloff = softer
        # Detuned layer
        mel2 = np.zeros(j - i, dtype=np.float64)
        for k in range(1, 5):
            mel2 += np.sin(2 * np.pi * freq * 1.003 * k * lt) / (k * k)
        tone = (mel + mel2) * 0.5 * env * 0.10
        audio[i:j] += tone * sc[i:j]

    # ── Dark drone pad — follows root chord, with slow tremolo ──
    pad_env = np.clip(t / 5.0, 0, 1) * np.clip((duration - t) / 3.0, 0, 1)
    drone = np.sin(phase_root) * 0.06
    drone += np.sin(phase_root * 1.498) * 0.04  # ~fifth relative
    drone += np.sin(phase_root * 2.0) * 0.02    # octave
    tremolo = 0.75 + 0.25 * np.sin(2 * np.pi * 0.12 * t)
    audio += drone * pad_env * tremolo * sc

    # ── Subtle transition thumps at cuts (quiet, low) ──
    cut_times = set()
    for c in CUTS:
        cut_times.add(c[0] / FPS)
        cut_times.add(c[1] / FPS)
    for ct in sorted(cut_times):
        burst_len = int(0.05 * sr)
        i = max(0, int(ct * sr) - burst_len // 4)
        j = min(n, i + burst_len)
        if j <= i:
            continue
        lt = np.arange(j - i, dtype=np.float64) / sr
        env = np.exp(-lt * 45)
        burst = np.sin(2 * np.pi * 40 * lt) * env * 0.12
        audio[i:j] += burst

    # ── Sub-bass swells before transitions ──
    major_cuts = [3.0, 5.5, 8.5, 12.0, 16.0, 20.0, 24.0, 28.0]
    for mc in major_cuts:
        riser_len = int(0.8 * sr)
        i = max(0, int(mc * sr) - riser_len)
        j = min(n, i + riser_len)
        lt = np.linspace(0, 1, j - i)
        freq_sweep = 22 + 33 * lt ** 2  # very low sweep
        phase_sw = np.cumsum(freq_sweep / sr) * 2 * np.pi
        sweep = np.sin(phase_sw) * lt ** 2 * 0.12
        audio[i:j] += sweep

    # ── Master: warm saturation ──
    audio = np.tanh(audio * 1.6)  # gentler saturation — more headroom for bass
    peak = np.max(np.abs(audio)) + 1e-8
    audio *= 0.94 / peak

    pcm = (audio * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


# ── render pipeline ────────────────────────────────────────────────────────

def render(output: Path) -> None:
    metrics = load_metrics()
    _build_cuts(metrics)

    total = int(FPS * DUR)
    output.parent.mkdir(parents=True, exist_ok=True)
    work = output.parent / ".render_tron_tmp"
    work.mkdir(parents=True, exist_ok=True)
    tmp_vid = work / "tron_silent.mp4"
    tmp_aud = work / "tron_audio.wav"
    log_f = work / "ffmpeg.log"

    print(f"Audio ({DUR:.0f}s @ {BPM}bpm)...")
    make_audio(tmp_aud, DUR)

    print(f"Video ({total} frames, {W}x{H} @ {FPS}fps)...")
    cmd = [
        "ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "18",
        str(tmp_vid),
    ]
    rng = random.Random(42)
    np.random.seed(42)

    prev_frames: list[np.ndarray] = []

    with open(log_f, "w") as lf:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=lf)
        try:
            for i in range(total):
                frame = render_frame(i, total, metrics, rng, prev_frames)
                proc.stdin.write(frame.tobytes())
                # keep last 6 frames for stutter
                prev_frames.append(frame)
                if len(prev_frames) > 6:
                    prev_frames.pop(0)
                if (i + 1) % (FPS * 5) == 0:
                    print(f"  {i+1}/{total}")
        finally:
            if proc.stdin:
                proc.stdin.close()
            rc = proc.wait()
            if rc != 0:
                raise RuntimeError(f"ffmpeg failed ({rc}); see {log_f}")

    print("Mux...")
    subprocess.run([
        "ffmpeg", "-y", "-i", str(tmp_vid), "-i", str(tmp_aud),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(output),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"=> {output}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default=str(ROOT / "seed_reports" / "predihermes_tron_ytp.mp4"))
    args = ap.parse_args()
    out = Path(args.output).expanduser().resolve()
    render(out)
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size:stream=width,height,codec_name",
         "-of", "default=noprint_wrappers=1", str(out)],
        check=True, text=True, capture_output=True,
    )
    print(r.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
