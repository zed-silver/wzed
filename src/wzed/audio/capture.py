"""Microphone capture: shared WASAPI (never exclusive), ring buffer, PTT."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)


_SILENCE_PEAK = 1e-3  # below this it's not a quiet room, it's absence of signal


def _resolve_device(device: str | int | None) -> int | None:
    """Resolve the input device to a stable INDEX.

    device None/"" → index of the system default mic (avoids the
    "Multiple input devices found for ''" error when there are several mics).
    device str → matches by name (first one containing the substring).
    device int → used as is.
    """
    if isinstance(device, int):
        return device
    if device is None or device == "":
        default_in = sd.default.device[0]
        if isinstance(default_in, int) and default_in >= 0:
            return default_in
        # no explicit default: first device with input channels
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
    """Records while `start()` is active; `stop()` returns the whole utterance.

    Simple model for PTT (Phase 1). Continuous mode (VAD) comes in Phase 2
    consuming the same blocks via callback.
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
        # receives the RMS of each block (30 ms) to feed the HUD; must not raise
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
            except Exception:  # noqa: BLE001 - HUD never brings down the capture
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
            blocksize=int(self.sample_rate * 0.03),  # 30 ms blocks
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
            # teto de segurança (tecla PTT presa). Mantém o INÍCIO da fala —
            # descartar o começo em silêncio é o que fazia sumir o texto ditado.
            log.warning(
                "fala de %.0fs excedeu o teto de %.0fs (tecla PTT presa?); "
                "mantendo o início e descartando o excedente",
                len(audio) / self.sample_rate,
                self.max_samples / self.sample_rate,
            )
            audio = audio[: self.max_samples]
        self._warn_if_silent(audio)
        return audio

    def _warn_if_silent(self, audio: np.ndarray) -> None:
        """Warns when the mic opens but delivers no signal.

        It's the most treacherous failure in wzed: the device opens, the PTT fires, the engine runs
        and nothing shows up, without a single line of error. It happens with the mic muted, with volume
        at zero or taken in exclusive mode by another app (DaVinci Resolve does this).
        A live mic in a quiet room still registers background noise on the order of 1e-3;
        below _SILENCE_PEAK it's digital silence, meaning no audio is arriving.
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
        """Validates the mic and detects the Bluetooth handsfree trap (8/16 kHz native)."""
        idx = _resolve_device(device)
        if idx is None:
            return "AVISO: nenhum dispositivo de entrada encontrado"
        info = sd.query_devices(idx, kind="input")
        native = int(info["default_samplerate"])
        msg = f"mic[{idx}]: {info['name']} @ {native} Hz"
        if native < sample_rate:
            msg += " [AVISO: sample rate baixo; headset BT em modo handsfree degrada o STT]"
        return msg
