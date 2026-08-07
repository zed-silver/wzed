"""Engines STT com interface única: Parakeet (padrão) e faster-whisper (fallback)."""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)


def setup_cuda_dlls() -> None:
    """Expõe as DLLs dos pacotes pip nvidia-* e usa o preload do onnxruntime (Windows)."""
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
    except Exception:  # noqa: BLE001 - preload é otimização, não requisito
        pass


class SttEngine(Protocol):
    def transcribe(self, audio: np.ndarray, language: str) -> str:
        """audio: float32 mono 16 kHz em [-1, 1] → texto (com pontuação)."""
        ...


class ParakeetEngine:
    """NVIDIA Parakeet-TDT-0.6B-v3 via onnx-asr. Pontuação/capitalização nativas."""

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

    def transcribe(self, audio: np.ndarray, language: str) -> str:
        return (self._model.recognize(audio, sample_rate=16000, language=language) or "").strip()


class FasterWhisperEngine:
    """faster-whisper large-v3-turbo int8 (fallback; PT-BR robusto)."""

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

    def transcribe(self, audio: np.ndarray, language: str) -> str:
        segs, _ = self._model.transcribe(
            audio, language=language, beam_size=1, vad_filter=False
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
