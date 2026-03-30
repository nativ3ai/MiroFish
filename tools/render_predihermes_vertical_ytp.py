#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import random
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
W = 1080
H = 1920
FPS = 24
DURATION = 24.0
FONT_PATH = "/System/Library/Fonts/Menlo.ttc"

PALETTE = {
    "bg0": (2, 8, 12),
    "bg1": (6, 18, 22),
    "grid": (18, 56, 64),
    "fg": (210, 255, 245),
    "muted": (108, 160, 154),
    "cyan": (66, 232, 255),
    "green": (74, 255, 184),
    "amber": (255, 206, 96),
    "red": (255, 96, 112),
}

SCENES = [
    {
        "name": "BOOTSTRAP",
        "start": 0.0,
        "end": 4.5,
        "accent": "cyan",
        "subtitle": "INSTALL + WIRE DEPENDENCIES",
        "command": "$ git clone https://github.com/nativ3ai/hermes-geopolitical-market-sim && cd hermes-geopolitical-market-sim && ./install.sh",
        "lines": [
            "skill path -> ~/.hermes/skills/research/geopolitical-market-sim",
            "deps -> requests + pipeline helper",
            "source nodes -> worldosint-headless + mirofish fork",
        ],
    },
    {
        "name": "MODEL SWITCH",
        "start": 4.5,
        "end": 8.5,
        "accent": "green",
        "subtitle": "CONFIGURE OPENAI-CODEX BRAIN",
        "command": "$ hermes config set model.provider openai-codex && hermes config set model.default gpt-5.3-codex-medium",
        "lines": [
            "api key -> ~/.hermes/.env :: OPENAI_API_KEY=...",
            "mode -> strict reconcile for status conflicts",
            "target -> lower hallucination under mixed artifacts",
        ],
    },
    {
        "name": "MODULE SURFACE",
        "start": 8.5,
        "end": 13.2,
        "accent": "amber",
        "subtitle": "OSINT MODULE CONTROL",
        "command": "$ predihermes list-worldosint-modules && predihermes update-topic iran-conflict --add-module maritime_snapshot --set-max-rounds 28",
        "lines": [
            "63 modules discovered via worldosint headless",
            "topic controls -> add/remove modules, params, rounds",
            "narrative inputs -> rss + risk + military + maritime",
        ],
    },
    {
        "name": "SIM PIPELINE",
        "start": 13.2,
        "end": 18.6,
        "accent": "red",
        "subtitle": "RUN TRACKED TOPIC + COUNTERFACTUAL",
        "command": "$ predihermes run-tracked iran-conflict --simulate",
        "lines": [
            "market match -> US-Iran nuclear deal by March 31?",
            "branch actor -> SHADOW HORMUZ UNDERWRITER @ round 10",
            "diff frame -> economic chokehold signal amplification",
        ],
    },
    {
        "name": "OUTPUT",
        "start": 18.6,
        "end": 24.0,
        "accent": "green",
        "subtitle": "DASHBOARD + OPERATOR CALL",
        "command": "$ predihermes dashboard iran-conflict",
        "lines": [
            "bid/ask drift + headline pressure + risk rows",
            "branch vs base actions and actor impact trace",
            "call -> compare implied % vs simulation probability",
        ],
    },
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    idx = 1 if bold else 0
    try:
        return ImageFont.truetype(FONT_PATH, size=size, index=idx)
    except Exception:
        return ImageFont.load_default()


def wrap_to_width(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    out = []
    cur = words[0]
    for w in words[1:]:
        nxt = cur + " " + w
        if draw.textlength(nxt, font=fnt) <= max_w:
            cur = nxt
        else:
            out.append(cur)
            cur = w
    out.append(cur)
    return out


def scene_at(t: float) -> dict:
    for s in SCENES:
        if s["start"] <= t < s["end"]:
            return s
    return SCENES[-1]


def typed_portion(text: str, progress: float) -> str:
    n = max(0, min(len(text), int(len(text) * progress)))
    return text[:n]


def base_canvas(t: float) -> Image.Image:
    arr = np.zeros((H, W, 3), dtype=np.uint8)
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    x = np.linspace(0, 1, W, dtype=np.float32)[None, :]
    pulse = 0.5 + 0.5 * math.sin(2 * math.pi * (0.08 * t))
    arr[..., 0] = (PALETTE["bg0"][0] * (1 - y) + PALETTE["bg1"][0] * y).astype(np.uint8)
    arr[..., 1] = (PALETTE["bg0"][1] * (1 - y) + (PALETTE["bg1"][1] + 6 * pulse) * y).astype(np.uint8)
    arr[..., 2] = (PALETTE["bg0"][2] * (1 - y) + (PALETTE["bg1"][2] + 10 * pulse) * y).astype(np.uint8)

    grid_x = ((x * W + 10 * t) % 64) < 1
    grid_y = ((y * H + 22 * t) % 56) < 1
    grid = np.logical_or(grid_x, grid_y)
    arr[grid] = np.clip(arr[grid] + np.array(PALETTE["grid"], dtype=np.uint8), 0, 255)

    return Image.fromarray(arr, mode="RGB")


def glitch_image(img: Image.Image, t: float, strength: float) -> Image.Image:
    if strength <= 0:
        return img
    a = np.array(img).astype(np.float32)
    h, w = a.shape[:2]

    # scanline jitter
    for _ in range(int(6 + 18 * strength)):
        y = random.randint(0, h - 8)
        band = random.randint(2, 10)
        shift = random.randint(-14, 14)
        a[y:y+band] = np.roll(a[y:y+band], shift, axis=1)

    # RGB split
    r = np.roll(a[..., 0], int(2 + 8 * strength), axis=1)
    g = a[..., 1]
    b = np.roll(a[..., 2], int(-(2 + 8 * strength)), axis=1)
    out = np.stack([r, g, b], axis=-1)

    # digital noise bursts
    noise = (np.random.rand(h, w, 1) - 0.5) * (25 + 120 * strength)
    out += noise

    # vignetting
    yy = np.linspace(-1, 1, h)[:, None]
    xx = np.linspace(-1, 1, w)[None, :]
    dist = np.sqrt(xx * xx + yy * yy)
    vignette = np.clip(1.08 - dist * 0.35, 0.7, 1.0)
    out *= vignette[..., None]

    out = np.clip(out, 0, 255).astype(np.uint8)
    return Image.fromarray(out, mode="RGB")


def draw_panel(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, edge: tuple[int, int, int]) -> None:
    draw.rounded_rectangle((x, y, x + w, y + h), radius=24, outline=edge, width=2, fill=(3, 10, 14, 188))


def render_frame(frame_idx: int, total_frames: int) -> Image.Image:
    t = frame_idx / FPS
    sc = scene_at(t)
    local = (t - sc["start"]) / max(sc["end"] - sc["start"], 1e-6)

    img = base_canvas(t)
    d = ImageDraw.Draw(img, "RGBA")

    f_title = font(74, bold=True)
    f_sub = font(38, bold=False)
    f_cmd = font(29, bold=False)
    f_body = font(34, bold=False)
    f_small = font(24, bold=False)

    edge = PALETTE[sc["accent"]]

    # Outer HUD
    draw_panel(d, 34, 42, W - 68, H - 84, edge)
    draw_panel(d, 64, 102, W - 128, 108, edge)
    d.text((88, 136), "root@operator:~/#", fill=PALETTE["muted"], font=f_small)
    d.text((W - 286, 136), "REC  LIVE  YTP", fill=PALETTE["red"], font=f_small)

    # Header
    d.text((88, 270), sc["name"], fill=edge, font=f_title)
    d.text((88, 352), sc["subtitle"], fill=PALETTE["fg"], font=f_sub)

    # Command box
    draw_panel(d, 82, 430, W - 164, 126, edge)
    cmd_prog = min(1.0, local * 1.35)
    cmd = typed_portion(sc["command"], cmd_prog)
    d.text((106, 474), cmd + ("_" if (frame_idx % 8) < 4 else ""), fill=PALETTE["green"], font=f_cmd)

    # Body + metrics cards
    draw_panel(d, 82, 600, W - 164, 920, edge)
    y = 650
    max_w = W - 220
    for line in sc["lines"]:
        for row in wrap_to_width(d, line, f_body, max_w):
            reveal = 1.0 if local > 0.2 else local / 0.2
            text = typed_portion(row, min(1.0, reveal + (y - 650) / 700.0))
            d.text((110, y), text, fill=PALETTE["fg"], font=f_body)
            y += 52
        y += 12

    # Arc indicator
    d.text((86, H - 170), "NARRATIVE ARC", fill=PALETTE["muted"], font=f_small)
    bar_w = W - 172
    d.rectangle((86, H - 126, 86 + bar_w, H - 106), outline=edge, width=2)
    fill_w = int(bar_w * (frame_idx / max(total_frames - 1, 1)))
    d.rectangle((88, H - 124, 88 + fill_w, H - 108), fill=edge)

    # rapid phase strobe at scene boundaries
    burst = 0.0
    for s in SCENES:
        dt = abs(t - s["start"])
        if dt < 0.16:
            burst = max(burst, 1 - dt / 0.16)
    micro = 0.35 * max(0.0, math.sin(2 * math.pi * 7.5 * t))
    strength = min(1.0, 0.18 + 0.38 * micro + 0.66 * burst)

    if frame_idx % 2 == 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=0.2 + 0.8 * burst))
    return glitch_image(img, t, strength)


def make_audio(path: Path, duration: float) -> None:
    sr = 44100
    n = int(sr * duration)
    t = np.arange(n, dtype=np.float32) / sr
    bpm = 148.0
    beat = 60.0 / bpm

    # TRON-ish arpeggio with FM flavor
    notes = np.array([55.0, 82.41, 110.0, 164.81], dtype=np.float32)
    step = int(beat * sr / 2)
    idx = (np.arange(n) // step) % len(notes)
    f = notes[idx]
    mod = np.sin(2 * np.pi * (f * 2.01) * t) * 1.7
    arp = np.sin(2 * np.pi * (f + mod) * t)

    # sidechained bass
    bass = np.sin(2 * np.pi * 41.2 * t + 0.5 * np.sin(2 * np.pi * 2.0 * t))

    # kick/hat
    sig = np.zeros(n, dtype=np.float32)
    kick_len = int(0.16 * sr)
    hat_len = int(0.04 * sr)
    for bt in np.arange(0, duration, beat):
        i = int(bt * sr)
        j = min(n, i + kick_len)
        lt = np.arange(j - i, dtype=np.float32) / sr
        env = np.exp(-lt * 34)
        kf = 66 - 28 * (lt / max(lt[-1], 1e-6))
        sig[i:j] += 0.9 * np.sin(2 * np.pi * kf * lt) * env

        i2 = int((bt + beat * 0.5) * sr)
        j2 = min(n, i2 + hat_len)
        if i2 < n and j2 > i2:
            lt2 = np.arange(j2 - i2, dtype=np.float32) / sr
            env2 = np.exp(-lt2 * 90)
            noise = (np.random.rand(j2 - i2).astype(np.float32) * 2 - 1)
            sig[i2:j2] += 0.22 * noise * env2

    # rhythmic gate for cyber pulse
    gate = 0.5 + 0.5 * np.sign(np.sin(2 * np.pi * (1 / beat) * t))
    synth = 0.42 * arp + 0.30 * bass
    audio = synth * (0.52 + 0.48 * gate) + sig

    # mild saturation + limiter
    audio = np.tanh(audio * 1.4)
    audio *= 0.88 / (np.max(np.abs(audio)) + 1e-6)

    pcm = (audio * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def render(output: Path, fps: int = FPS, duration: float = DURATION) -> None:
    total = int(fps * duration)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="predihermes_v_ytp_") as td:
        td_path = Path(td)
        frames_dir = td_path / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        audio_path = td_path / "audio.wav"

        random.seed(42)
        np.random.seed(42)
        for i in range(total):
            frame = render_frame(i, total)
            frame.save(frames_dir / f"frame_{i:05d}.png")

        make_audio(audio_path, duration)

        cmd = [
            "ffmpeg",
            "-y",
            "-framerate", str(fps),
            "-i", str(frames_dir / "frame_%05d.png"),
            "-i", str(audio_path),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(output),
        ]
        subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render PrediHermes vertical YTP teaser")
    parser.add_argument("--output", default=str(ROOT / "seed_reports" / "predihermes_vertical_ytp.mp4"))
    parser.add_argument("--duration", type=float, default=DURATION)
    parser.add_argument("--fps", type=int, default=FPS)
    args = parser.parse_args()

    out = Path(args.output).expanduser().resolve()
    render(out, fps=args.fps, duration=args.duration)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
