"""Verifies the audio device fix: config roundtrip + real mic open.

Does not bring up the app (does not arm the PTT hook). Usage: uv run python scripts/check_audio.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import sounddevice as sd

from wzed import config as cfg_mod
from wzed.audio.capture import Recorder, _resolve_device

cfg = cfg_mod.load()
print(f"config.audio.device carregado = {cfg.audio.device!r} (esperado: None)")
assert cfg.audio.device is None, "validator não normalizou '' -> None"

idx = _resolve_device(cfg.audio.device)
print(f"device resolvido = índice {idx}")
print(Recorder.check_device(cfg.audio.device, cfg.audio.sample_rate))

# actually record 1 s to prove the stream opens without the ValueError
rec = Recorder(cfg.audio.sample_rate, cfg.audio.device, cfg.audio.max_utterance_s)
rec.start()
time.sleep(1.0)
audio = rec.stop()
rms = float(np.sqrt(np.mean(audio**2))) if len(audio) else 0.0
print(f"capturados {len(audio)} samples ({len(audio) / cfg.audio.sample_rate:.2f}s), RMS={rms:.4f}")
print("OK: mic abre e captura sem erro." if len(audio) > 0 else "FALHOU: nada capturado")
