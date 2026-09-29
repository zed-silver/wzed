"""STT engines with a single interface: Parakeet (default) and faster-whisper (fallback)."""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from collections.abc import Sequence
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)


def setup_cuda_dlls() -> None:
    """Exposes the DLLs from the nvidia-* pip packages and uses onnxruntime's preload (Windows)."""
    spec = importlib.util.find_spec("nvidia")
    if spec and spec.submodule_search_locations:
        for loc in spec.submodule_search_locations:
            for bin_dir in Path(loc).glob("*/bin"):
                if bin_dir.is_dir():
                    os.add_dll_directory(str(bin_dir))
                    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]
    try:  # onnxruntime >= 1.21
        import onnxruntime as ort

        ort.preload_dlls()
    except Exception:  # noqa: BLE001 - preload is an optimization, not a requirement
        pass


class SttEngine(Protocol):
    def transcribe(
        self, audio: np.ndarray, language: str, hints: Sequence[str] = ()
    ) -> str:
        """audio: float32 mono 16 kHz in [-1, 1] → text (with punctuation).

        hints: terms the engine should favor (the personal dictionary's correct spellings);
        engines without a biasing mechanism ignore them.
        """
        ...


class ParakeetEngine:
    """NVIDIA Parakeet-TDT-0.6B-v3 via onnx-asr. Native punctuation/capitalization."""

    def __init__(self, device: str = "cuda") -> None:
        import onnx_asr

        setup_cuda_dlls()
        providers = (
            ["CUDAExecutionProvider", "CPUExecutionProvider"]
            if device == "cuda"
            else ["CPUExecutionProvider"]
        )
        self._model = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", providers=providers)
        self.warmup()

    def warmup(self) -> None:
        self._model.recognize(np.zeros(16000, dtype=np.float32), sample_rate=16000)

    def transcribe(
        self, audio: np.ndarray, language: str, hints: Sequence[str] = ()
    ) -> str:
        # onnx-asr has no hotword biasing for this model: hints are ignored
        return (self._model.recognize(audio, sample_rate=16000, language=language) or "").strip()


class FasterWhisperEngine:
    """faster-whisper large-v3-turbo int8 (fallback; robust PT-BR)."""

    def __init__(self, device: str = "cuda") -> None:
        from faster_whisper import WhisperModel

        setup_cuda_dlls()
        compute = "int8_float16" if device == "cuda" else "int8"
        self._model = WhisperModel(
            "deepdml/faster-whisper-large-v3-turbo-ct2", device=device, compute_type=compute
        )
        self.warmup()

    def warmup(self) -> None:
        segs, _ = self._model.transcribe(np.zeros(16000, dtype=np.float32), language="pt")
        list(segs)

    def transcribe(
        self, audio: np.ndarray, language: str, hints: Sequence[str] = ()
    ) -> str:
        # hotwords (not initial_prompt): re-applied on every 30 s window; faster-whisper
        # truncates it to ~223 tokens, so the tail of a huge dictionary is dropped
        segs, _ = self._model.transcribe(
            audio,
            language=language,
            beam_size=1,
            vad_filter=False,
            hotwords=", ".join(hints) or None,
        )
        return " ".join(s.text.strip() for s in segs).strip()


def create_engine(name: str, device: str) -> SttEngine:
    try:
        if name == "parakeet":
            return ParakeetEngine(device)
        return FasterWhisperEngine(device)
    except Exception as e:
        if device == "cuda":
            log.warning("engine %s falhou em CUDA (%s); caindo para CPU", name, e)
            return create_engine(name, "cpu")
        raise
