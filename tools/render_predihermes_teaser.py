#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import textwrap
import wave
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = Path('/Users/native/.hermes/data/geopolitical-market-sim/runs/iran-conflict/20260316_025815/iran-conflict_snapshot.json')
DEFAULT_BASE_SIM = ROOT / 'backend' / 'uploads' / 'simulations' / 'sim_039c095547c5'
DEFAULT_BRANCH_SIM = ROOT / 'backend' / 'uploads' / 'simulations' / 'sim_b48c23571420'
FONT_REGULAR = '/System/Library/Fonts/Menlo.ttc'
FONT_BOLD = '/System/Library/Fonts/Menlo.ttc'
PALETTE = {
    'bg': (5, 9, 8),
    'bg2': (13, 18, 16),
    'fg': (222, 255, 240),
    'muted': (120, 160, 145),
    'green': (77, 226, 165),
    'amber': (255, 211, 106),
    'red': (255, 110, 110),
    'blue': (90, 208, 255),
}
DEFAULT_BPM = 132


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def compact_id(value: str) -> str:
    return value.replace('sim_', 'SIM_').upper()


def parse_action_logs(sim_dir: Path) -> list[dict[str, Any]]:
    actions = []
    for platform in ('twitter', 'reddit'):
        path = sim_dir / platform / 'actions.jsonl'
        if not path.exists():
            continue
        with path.open('r', encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload.setdefault('platform', platform)
                actions.append(payload)
    actions.sort(key=lambda item: item.get('timestamp', ''))
    return actions


def parse_run_state(sim_dir: Path) -> dict[str, Any]:
    return load_json(sim_dir / 'run_state.json')


def parse_counterfactual(sim_dir: Path) -> dict[str, Any]:
    return load_json(sim_dir / 'simulation_config.json').get('counterfactual', {})


def token_counts(texts: list[str], blocked: set[str], limit: int = 5) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for text in texts:
        for token in ''.join(ch.lower() if ch.isalnum() else ' ' for ch in text).split():
            if len(token) < 4 or token in blocked:
                continue
            counts[token] += 1
    return counts.most_common(limit)


def collect_metrics(snapshot_path: Path, base_sim_dir: Path, branch_sim_dir: Path) -> dict[str, Any]:
    snapshot = load_json(snapshot_path)
    base_state = parse_run_state(base_sim_dir)
    branch_state = parse_run_state(branch_sim_dir)
    branch_cfg = parse_counterfactual(branch_sim_dir)
    branch_actions = parse_action_logs(branch_sim_dir)

    news = snapshot.get('news') or {}
    items = news.get('items') or []
    themes = news.get('themes') or []
    risk_rows = (snapshot.get('context') or {}).get('riskRows') or []
    assets = (snapshot.get('context') or {}).get('theaterAssets') or []
    market = (snapshot.get('markets') or [{}])[0]
    actor_name = branch_cfg.get('actor_name', 'Injected actor')

    amplifiers: Counter[str] = Counter()
    frame_texts = []
    for action in branch_actions:
        if action.get('agent_name') == actor_name:
            frame_texts.append(action_text(action))
            continue
        names = referenced_names(action)
        if actor_name in names:
            amplifiers[action.get('agent_name') or f"Agent {action.get('agent_id', '?')}"] += 1
            frame_texts.append(action_text(action))

    key_terms = token_counts(
        frame_texts,
        blocked={'hormuz', 'iran', 'branch', 'round', 'actor', 'market', 'underwriter', 'shadow', 'deal', 'post', 'comment'}
    )

    return {
        'topic': snapshot.get('topic', 'Iran conflict and nuclear diplomacy'),
        'market': market,
        'headline_count': len(items),
        'feeds_count': len(news.get('feeds') or []),
        'theme_summary': ', '.join(f"{item['theme']} {item['count']}" for item in themes[:4]),
        'risk_rows': risk_rows,
        'asset_count': len(assets),
        'base_state': base_state,
        'branch_state': branch_state,
        'counterfactual': branch_cfg,
        'actor_name': actor_name,
        'amplifiers': amplifiers.most_common(5),
        'key_terms': key_terms,
    }


def action_text(action: dict[str, Any]) -> str:
    args = action.get('action_args') or {}
    for key in ('content', 'quote_content', 'original_content', 'post_content', 'comment_content', 'query'):
        value = args.get(key)
        if value:
            return str(value)
    return ''


def referenced_names(action: dict[str, Any]) -> list[str]:
    args = action.get('action_args') or {}
    values = [args.get('original_author_name'), args.get('post_author_name'), args.get('comment_author_name'), args.get('author_name')]
    return [str(v).strip() for v in values if v]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_REGULAR, size=size)


def load_font_bold(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD, size=size, index=1)


def wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False) or ['']


def fit_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    if font.getlength(text) <= max_width:
        return text
    clipped = text
    while clipped and font.getlength(f"{clipped}...") > max_width:
        clipped = clipped[:-1]
    return f"{clipped}..." if clipped else "..."


def wrap_pixel(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if font.getlength(candidate) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def scene_data(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    market = metrics['market']
    base = metrics['base_state']
    branch = metrics['branch_state']
    counter = metrics['counterfactual']
    risks = {row['region']: row['combinedScore'] for row in metrics['risk_rows']}
    amplifiers = ' / '.join(name for name, _ in metrics['amplifiers'][:4]) or 'No direct amplifiers logged'
    terms = ' / '.join(term for term, _ in metrics['key_terms'][:4]) or 'narrative drift'
    return [
        {
            'start': 0.0,
            'end': 3.6,
            'header': 'HERMES AGENT // PREDIHERMES',
            'sub': 'OSINT -> MARKETS -> SIMULATION -> BRANCH DIFF',
            'command': 'hermes chat -q "Use PrediHermes to run iran-conflict and summarize the market."',
            'lines': [
                'boot sequence: worldosint + polymarket + mirofish',
                'skill alias: PrediHermes',
                'mode: terminal-first geopolitical forecasting',
            ],
            'accent': 'green',
        },
        {
            'start': 3.6,
            'end': 7.4,
            'header': 'WORLDOSINT SNAPSHOT',
            'sub': metrics['topic'].upper(),
            'command': 'python3 ~/.hermes/.../geopolitical_market_pipeline.py run-tracked iran-conflict --simulate',
            'lines': [
                f"feeds queried: {metrics['feeds_count']}  |  headlines ingested: {metrics['headline_count']}",
                f"themes: {metrics['theme_summary']}",
                f"risk scores -> IR {risks.get('IR', 'n/a')} / IL {risks.get('IL', 'n/a')} / SA {risks.get('SA', 'n/a')} / US {risks.get('US', 'n/a')}",
                f"theater posture: {metrics['asset_count']} tracked naval assets",
            ],
            'accent': 'blue',
        },
        {
            'start': 7.4,
            'end': 11.2,
            'header': 'POLYMARKET TARGET',
            'sub': market.get('question', 'US-Iran nuclear deal by March 31?').upper(),
            'command': 'clob live book -> acceptingOrders=true',
            'lines': [
                f"yes bid/ask: {market.get('bestBid', 0)*100:.1f}% / {market.get('bestAsk', 0)*100:.1f}%",
                f"liquidity: ${market.get('liquidityNum', 0)/1000:.1f}K  |  volume: ${market.get('volumeNum', 0)/1_000_000:.1f}M",
                'resolution: official US/Iran agreement before Mar 31 2026',
            ],
            'accent': 'amber',
        },
        {
            'start': 11.2,
            'end': 15.8,
            'header': 'MIROFISH COUNTERFACTUAL',
            'sub': f"{counter.get('actor_name', 'Injected actor').upper()} @ ROUND {counter.get('injection_round', 0)}",
            'command': 'POST /api/simulation/<base>/counterfactual -> start branch',
            'lines': [
                f"base: {compact_id('sim_039c095547c5')}  |  {base.get('total_actions_count', 0)} actions  |  44 agents",
                f"branch: {compact_id('sim_b48c23571420')}  |  {branch.get('total_actions_count', 0)} actions  |  45 agents",
                'opening statement: war-risk premiums for Gulf transits just repriced',
                'pathway shift: diplomacy -> shipping / insurance / premium frame',
            ],
            'accent': 'red',
        },
        {
            'start': 15.8,
            'end': 20.2,
            'header': 'BUTTERFLY EFFECT',
            'sub': 'BRANCH PROPAGATION + FORENSICS',
            'command': 'GET /simulation/<branch>/counterfactual',
            'lines': [
                f"amplifiers: {amplifiers}",
                f"dominant drift terms: {terms}",
                'workbench: read-only step 3 + round scrubber + branch/base diff graph',
                'hermes can inject a new actor, rerun, and compare branch logic headlessly',
            ],
            'accent': 'green',
        },
        {
            'start': 20.2,
            'end': 24.0,
            'header': 'PREDIHERMES',
            'sub': '54+ OSINT MODULES // POLYMARKET // MIROFISH',
            'command': 'predict narratives before markets fully price them',
            'lines': [
                'track topics, fetch open markets, generate seed packets, run sims, branch history',
                'terminal-native workflow for geopolitical monitoring and market calls',
                'hackathon build -> real artifacts, not mock screenshots',
            ],
            'accent': 'amber',
        },
    ]


def ease_in_out(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def beat_pulse(t: float, bpm: int = DEFAULT_BPM, sharpness: float = 7.5) -> float:
    beat = (t * bpm / 60.0) % 1.0
    return math.exp(-beat * sharpness)


def visible_chars(text: str, progress: float) -> str:
    if progress >= 1:
        return text
    count = max(0, min(len(text), int(len(text) * progress)))
    return text[:count]


def draw_box(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], outline: tuple[int, int, int], fill=None, width: int = 2) -> None:
    draw.rounded_rectangle(box, radius=14, outline=outline, fill=fill, width=width)


def render_frame(t: float, scenes: list[dict[str, Any]], metrics: dict[str, Any], size: tuple[int, int], fonts: dict[str, ImageFont.FreeTypeFont], rng: random.Random) -> np.ndarray:
    w, h = size
    scene = next((item for item in scenes if item['start'] <= t < item['end']), scenes[-1])
    local_t = t - scene['start']
    scene_len = scene['end'] - scene['start']
    progress = ease_in_out(local_t / max(scene_len, 0.001))
    beat = beat_pulse(t)
    panel_lift = int(beat * 4)

    bg = Image.new('RGB', size, PALETTE['bg'])
    draw = ImageDraw.Draw(bg)

    for y in range(h):
        blend = y / max(1, h - 1)
        line_color = tuple(int(PALETTE['bg'][i] * (1 - blend) + PALETTE['bg2'][i] * blend) for i in range(3))
        draw.line((0, y, w, y), fill=line_color)

    for x in range(0, w, 80):
        draw.line((x, 0, x, h), fill=(15, 30, 24), width=1)
    for y in range(0, h, 54):
        draw.line((0, y, w, y), fill=(12, 24, 20), width=1)

    outer_outline = tuple(min(255, int(c + beat * 18)) for c in (32, 78, 60))
    draw_box(draw, (42, 36, w - 42, h - 36), outer_outline, width=2)
    draw_box(draw, (64, 64, w - 64, h - 64), (18, 50, 38), width=1)

    # Top terminal chrome
    draw_box(draw, (88, 84, w - 88, 142), (58, 122, 97), fill=(10, 17, 15), width=1)
    draw.text((112, 101), 'native@NATIVEs-Mini  ~/hermes', font=fonts['mono_small'], fill=PALETTE['muted'])
    draw.text((w - 260, 101), 'REC  LIVE  LOCAL', font=fonts['mono_small'], fill=PALETTE['red'])

    accent = PALETTE.get(scene['accent'], PALETTE['green'])
    title_progress = min(1.0, local_t / 0.3)
    draw.text((110, 182 - panel_lift), visible_chars(scene['header'], title_progress), font=fonts['title'], fill=accent)
    draw.text((112, 236 - panel_lift), visible_chars(fit_text(scene['sub'], fonts['mono_medium'], w - 240), min(1.0, max(0.0, local_t - 0.08) / 0.38)), font=fonts['mono_medium'], fill=PALETTE['fg'])

    # Command line block
    cmd_box = (110, 284 - panel_lift, w - 110, 336 - panel_lift)
    draw_box(draw, cmd_box, (64, 129, 103), fill=(8, 13, 12), width=1)
    cmd = '$ ' + fit_text(scene['command'], fonts['mono_medium'], cmd_box[2] - cmd_box[0] - 40)
    cmd_visible = visible_chars(cmd, min(1.0, max(0.0, local_t - 0.16) / 0.48))
    if (int(t * 2) % 2) == 0 and len(cmd_visible) < len(cmd):
        cmd_visible += '▌'
    draw.text((128, 299 - panel_lift), cmd_visible, font=fonts['mono_medium'], fill=PALETTE['green'])

    # Left content terminal feed
    feed_box = (110, 366 - panel_lift, 760, h - 112 - panel_lift)
    draw_box(draw, feed_box, (41, 96, 75), fill=(7, 11, 10), width=1)
    lines: list[str] = []
    for raw in scene['lines']:
        lines.extend(wrap_pixel(raw, fonts['mono_feed'], feed_box[2] - feed_box[0] - 40))
    base_y = 392 - panel_lift
    for index, line in enumerate(lines):
        line_progress = max(0.0, min(1.0, (local_t - 0.22 - index * 0.08) / 0.18))
        text = visible_chars(line, line_progress)
        if not text:
            continue
        color = PALETTE['fg'] if index < 2 else PALETTE['muted']
        y = base_y + index * 29
        if y > feed_box[3] - 30:
            break
        draw.text((132, y), text, font=fonts['mono_feed'], fill=color)

    # Right metrics / mini-hud
    hud_box = (800, 366 - panel_lift, w - 110, h - 112 - panel_lift)
    draw_box(draw, hud_box, (95, 82, 35), fill=(11, 11, 8), width=1)
    hud_lines = [
        ('TOPIC', metrics['topic']),
        ('MARKET YES', f"{metrics['market'].get('bestBid', 0)*100:.1f}% -> {metrics['market'].get('bestAsk', 0)*100:.1f}%"),
        ('HEADLINES', str(metrics['headline_count'])),
        ('BASE', f"{metrics['base_state'].get('total_actions_count', 0)} acts"),
        ('BRANCH', f"{metrics['branch_state'].get('total_actions_count', 0)} acts"),
        ('ACTOR', metrics['actor_name']),
    ]
    draw.text((824, 388 - panel_lift), ':: SIGNAL BOARD ::', font=fonts['mono_medium'], fill=PALETTE['amber'])
    for i, (label, value) in enumerate(hud_lines):
        y = 430 - panel_lift + i * 40
        draw.text((826, y), label, font=fonts['hud_small'], fill=PALETTE['muted'])
        draw.text((948, y), fit_text(value, fonts['hud_small'], hud_box[2] - 962), font=fonts['hud_small'], fill=PALETTE['fg'])

    # Scene progress and lower badges
    total_progress = t / scenes[-1]['end']
    draw.rectangle((112, h - 84, w - 112, h - 72), fill=(20, 30, 26))
    draw.rectangle((112, h - 84, int(112 + (w - 224) * total_progress), h - 72), fill=accent)
    draw.text((114, h - 108), 'PREDIHERMES TEASER // REAL RUN ARTIFACTS', font=fonts['mono_small'], fill=PALETTE['muted'])

    arr = np.asarray(bg).astype(np.uint8)
    return apply_glitch(arr, t, scene, rng)


def apply_glitch(arr: np.ndarray, t: float, scene: dict[str, Any], rng: random.Random) -> np.ndarray:
    h, w, _ = arr.shape
    out = arr.astype(np.int16)

    # Scanlines
    out[::3] = (out[::3] * 0.82).astype(np.int16)

    # Ambient noise
    noise = rng.normalvariate(0, 1)
    ambient = np.random.default_rng(int(t * 1000) + 77).integers(-7, 8, size=(h, w, 1), endpoint=False)
    out += ambient

    # Scene cut flashes and periodic glitch windows
    cut_proximity = min(abs(t - scene['start']), abs(scene['end'] - t))
    intensity = 0.0
    if cut_proximity < 0.25:
        intensity += 0.72 * (1.0 - (cut_proximity / 0.25))
    if math.sin(t * 6.4) > 0.88:
        intensity += 0.55
    intensity += beat_pulse(t) * 0.22

    if intensity > 0.05:
        max_slices = 2 + int(intensity * 6)
        for _ in range(max_slices):
            y = rng.randint(0, h - 12)
            band_h = rng.randint(6, 42)
            shift = rng.randint(-42, 42)
            out[y:y + band_h] = np.roll(out[y:y + band_h], shift, axis=1)

        red = np.roll(out[:, :, 0], int(3 + intensity * 7), axis=1)
        blue = np.roll(out[:, :, 2], int(-3 - intensity * 7), axis=1)
        out[:, :, 0] = ((out[:, :, 0] * 0.6) + (red * 0.4)).astype(np.int16)
        out[:, :, 2] = ((out[:, :, 2] * 0.6) + (blue * 0.4)).astype(np.int16)

        if intensity > 0.4:
            flash = int(35 * intensity)
            out += flash

    # Subtle horizontal jitter
    if int(t * 14) % 5 == 0:
        out = np.roll(out, rng.randint(-3, 3), axis=1)

    # Vignette
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = w / 2, h / 2
    dist = np.sqrt(((xx - cx) / (w / 2)) ** 2 + ((yy - cy) / (h / 2)) ** 2)
    vignette = np.clip(1.12 - dist * 0.42, 0.65, 1.0)
    out = (out * vignette[..., None]).astype(np.int16)

    return np.clip(out, 0, 255).astype(np.uint8)


def synth_audio(duration: float, out_path: Path) -> None:
    sr = 44100
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    beat_len = 60 / DEFAULT_BPM
    pulse = np.zeros_like(t)

    def add_signal(start_s: float, length_s: float, signal: np.ndarray) -> None:
        start = int(start_s * sr)
        length = min(len(signal), len(t) - start, int(length_s * sr))
        if start < 0 or start >= len(t) or length <= 0:
            return
        pulse[start:start + length] += signal[:length]

    # Kick on every beat
    for beat_at in np.arange(0, duration, beat_len):
        length = 0.16
        local = np.linspace(0, length, int(sr * length), endpoint=False)
        env = np.exp(-local * 18)
        freq = 92 - 54 * (local / length)
        kick = np.sin(2 * np.pi * freq * local) * env * 0.56
        click = np.sin(2 * np.pi * 2200 * local) * np.exp(-local * 48) * 0.05
        add_signal(beat_at, length, kick + click)

    # Offbeat hats
    noise_rng = np.random.default_rng(17)
    for hat_at in np.arange(beat_len / 2, duration, beat_len / 2):
        length = 0.045
        local = np.linspace(0, length, int(sr * length), endpoint=False)
        env = np.exp(-local * 70)
        hat = noise_rng.standard_normal(len(local)) * env * 0.06
        add_signal(hat_at, length, hat)

    # Clap on beats 2 and 4
    for idx, clap_at in enumerate(np.arange(beat_len, duration, beat_len)):
        if idx % 2 == 0:
            continue
        length = 0.11
        local = np.linspace(0, length, int(sr * length), endpoint=False)
        env = np.exp(-local * 30)
        noise = noise_rng.standard_normal(len(local)) * env * 0.12
        body = np.sin(2 * np.pi * 420 * local) * np.exp(-local * 20) * 0.04
        add_signal(clap_at, length, noise + body)

    # Rolling bassline
    bass_notes = [55, 55, 65.4, 49, 55, 73.4, 65.4, 49]
    for idx, note_at in enumerate(np.arange(0, duration, beat_len / 2)):
        length = beat_len / 2
        local = np.linspace(0, length, int(sr * length), endpoint=False)
        freq = bass_notes[idx % len(bass_notes)]
        env = np.exp(-local * 4.6)
        bass = (np.sin(2 * np.pi * freq * local) + 0.35 * np.sin(2 * np.pi * freq * 2 * local)) * env * 0.17
        add_signal(note_at, length, bass)

    # Techno arp and scene sweeps
    scene_boundaries = [scene['start'] for scene in scene_data(collect_metrics(DEFAULT_SNAPSHOT, DEFAULT_BASE_SIM, DEFAULT_BRANCH_SIM))[1:]]
    arp_notes = [220, 246.94, 293.66, 329.63, 369.99, 329.63, 293.66, 246.94]
    for idx, arp_at in enumerate(np.arange(0, duration, beat_len / 4)):
        length = beat_len / 4
        local = np.linspace(0, length, int(sr * length), endpoint=False)
        freq = arp_notes[idx % len(arp_notes)]
        env = np.exp(-local * 7.5)
        tone = np.sin(2 * np.pi * freq * local) + 0.3 * np.sin(2 * np.pi * freq * 0.5 * local)
        gate = 0.05 + 0.05 * math.sin(2 * math.pi * (idx / 16))
        add_signal(arp_at, length, tone * env * gate)

    for sweep_at in scene_boundaries:
        length = 0.32
        local = np.linspace(0, 1, int(sr * length), endpoint=False)
        freqs = 180 + 1100 * local
        sweep = np.sin(2 * np.pi * freqs * local) * np.exp(-local * 2.7) * 0.12
        add_signal(sweep_at, length, sweep)

    # Gentle sidechain pump
    kick_env = np.ones_like(t)
    for beat_at in np.arange(0, duration, beat_len):
        start = int(beat_at * sr)
        length = int(sr * 0.22)
        if start + length >= len(kick_env):
            break
        env = 0.7 + 0.3 * (1 - np.exp(-np.linspace(0, 4, length)))
        kick_env[start:start + length] *= env

    hiss = 0.005 * noise_rng.standard_normal(len(t))
    audio = np.clip((pulse / np.maximum(kick_env, 0.7)) + hiss, -0.95, 0.95)
    pcm = (audio * 32767).astype(np.int16)
    with wave.open(str(out_path), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sr)
        wav.writeframes(pcm.tobytes())


def encode_video(temp_video: Path, audio_path: Path, final_output: Path) -> None:
    cmd = [
        'ffmpeg', '-y', '-i', str(temp_video), '-i', str(audio_path),
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', str(final_output)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def render(output: Path, width: int, height: int, fps: int) -> None:
    metrics = collect_metrics(DEFAULT_SNAPSHOT, DEFAULT_BASE_SIM, DEFAULT_BRANCH_SIM)
    scenes = scene_data(metrics)
    duration = scenes[-1]['end']
    output.parent.mkdir(parents=True, exist_ok=True)
    work_dir = output.parent / '.render_tmp'
    work_dir.mkdir(parents=True, exist_ok=True)
    temp_video = work_dir / 'teaser_silent.mp4'
    temp_audio = work_dir / 'teaser_audio.wav'
    ffmpeg_log = work_dir / 'ffmpeg_render.log'

    fonts = {
        'title': load_font_bold(38),
        'mono_medium': load_font(23),
        'mono_feed': load_font(20),
        'hud_small': load_font(14),
        'mono_small': load_font(16),
    }

    synth_audio(duration, temp_audio)

    cmd = [
        'ffmpeg', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{width}x{height}', '-r', str(fps),
        '-i', '-', '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'medium', '-crf', '18', str(temp_video)
    ]
    rng = random.Random(42)
    with ffmpeg_log.open('w', encoding='utf-8') as log_handle:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log_handle)
        total_frames = int(duration * fps)
        try:
            for frame_idx in range(total_frames):
                t = frame_idx / fps
                frame = render_frame(t, scenes, metrics, (width, height), fonts, rng)
                proc.stdin.write(frame.tobytes())
        finally:
            if proc.stdin:
                proc.stdin.close()
            rc = proc.wait()
            if rc != 0:
                raise RuntimeError(f'ffmpeg raw encode failed with exit code {rc}; see {ffmpeg_log}')

    encode_video(temp_video, temp_audio, output)


def verify(output: Path) -> str:
    if not output.exists() or output.stat().st_size == 0:
        raise FileNotFoundError(f'Missing or empty output: {output}')
    probe = subprocess.run(
        [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration,size',
            '-of', 'default=noprint_wrappers=1:nokey=0', str(output)
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return probe.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description='Render a glitchy PrediHermes teaser video')
    parser.add_argument('--output', type=Path, default=Path('/Users/native/Desktop/demovideo/demovideo.mp4'))
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--height', type=int, default=720)
    parser.add_argument('--fps', type=int, default=24)
    args = parser.parse_args()

    render(args.output, args.width, args.height, args.fps)
    print(verify(args.output))


if __name__ == '__main__':
    main()
