"""Captura de microfone: WASAPI compartilhado (nunca exclusivo), ring buffer, PTT."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)


_SILENCE_PEAK = 1e-3  # abaixo disto não é sala silenciosa, é ausência de sinal


def _resolve_device(device: str | int | None) -> int | None:
    """Resolve o dispositivo de entrada para um ÍNDICE estável.

    device None/"" → índice do mic default do sistema (evita o erro
    "Multiple input devices found for ''" quando há vários mics).
    device str → casa por nome (primeiro que contém a substring).
    device int → usado como está.
    """
    if isinstance(device, int):
        return device
    if device is None or device == "":
        default_in = sd.default.device[0]
        if isinstance(default_in, int) and default_in >= 0:
            return default_in
        # sem default explícito: primeiro dispositivo com canais de entrada
        for idx, info in enumerate(sd.query_devices()):
            if info["max_input_channels"] > 0:
                return idx
        return None
    wanted = device.lower()
    for idx, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] > 0 and wanted in info["name"].lower():
            return idx
    log.warning("mic %r não encontrado; usando o default do sistema", device)
    return _resolve_device(None)


class Recorder:
    """Grava enquanto `start()` estiver ativo; `stop()` devolve o utterance inteiro.

    Modelo simples para PTT (Fase 1). O modo contínuo (VAD) entra na Fase 2
    consumindo os mesmos blocos via callback.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        device: str | None = None,
        max_s: int = 60,
        level_callback: Callable[[float], None] | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.device = _resolve_device(device)
        self.max_samples = sample_rate * max_s
        # recebe o RMS de cada bloco (30 ms) para alimentar o HUD; não pode lançar
        self.level_callback = level_callback
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            log.debug("audio status: %s", status)
        block = indata[:, 0].copy()
        with self._lock:
            self._chunks.append(block)
        if self.level_callback is not None:
            try:
                self.level_callback(float(np.sqrt(np.mean(block**2))))
            except Exception:  # noqa: BLE001 - HUD nunca derruba a captura
                pass

    def start(self) -> None:
        if self._stream is not None:
            return
        with self._lock:
            self._chunks = []
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=int(self.sample_rate * 0.03),  # blocos de 30 ms
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        if self._stream is None:
            return np.zeros(0, dtype=np.float32)
        self._stream.stop()
        self._stream.close()
        self._stream = None
        with self._lock:
            audio = (
                np.concatenate(self._chunks)
                if self._chunks
                else np.zeros(0, dtype=np.float32)
            )
            self._chunks = []
        if len(audio) > self.max_samples:
            audio = audio[-self.max_samples :]
        self._warn_if_silent(audio)
        return audio

    def _warn_if_silent(self, audio: np.ndarray) -> None:
        """Avisa quando o mic abre mas não entrega sinal.

        É a falha mais traiçoeira do wzed: o device abre, o PTT dispara, a engine roda
        e nada aparece, sem uma linha de erro. Acontece com o mic no mudo, com volume
        zerado ou tomado em modo exclusivo por outro app (o DaVinci Resolve faz isso).
        Um mic vivo em sala silenciosa ainda registra ruído de fundo na casa de 1e-3;
        abaixo de _SILENCE_PEAK é silêncio digital, ou seja, não está chegando áudio.
        """
        if audio.size < int(0.3 * self.sample_rate):
            return
        peak = float(np.max(np.abs(audio)))
        if peak < _SILENCE_PEAK:
            log.warning(
                "captura MUDA: pico %.6f em %.1fs de áudio. O microfone está no mudo, "
                "com volume zerado ou tomado por outro app; nada será transcrito.",
                peak,
                audio.size / self.sample_rate,
            )

    @property
    def recording(self) -> bool:
        return self._stream is not None

    @staticmethod
    def check_device(device: str | None, sample_rate: int) -> str:
        """Valida o mic e detecta a armadilha do Bluetooth handsfree (8/16 kHz nativo)."""
        idx = _resolve_device(device)
        if idx is None:
            return "AVISO: nenhum dispositivo de entrada encontrado"
        info = sd.query_devices(idx, kind="input")
        native = int(info["default_samplerate"])
        msg = f"mic[{idx}]: {info['name']} @ {native} Hz"
        if native < sample_rate:
            msg += " [AVISO: sample rate baixo; headset BT em modo handsfree degrada o STT]"
        return msg
