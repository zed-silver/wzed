"""wzed configuration: TOML at %APPDATA%\\wzed\\config.toml, validated by pydantic."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "wzed"
CONFIG_PATH = APP_DIR / "config.toml"
DB_PATH = APP_DIR / "history.db"


class HotkeysCfg(BaseModel):
    push_to_talk: str = "<ctrl>+<win>"  # hold = record; release = transcribe
    toggle_continuous: str = "<ctrl>+<alt>+d"


class SttCfg(BaseModel):
    engine: str = "fwhisper"  # fwhisper | parakeet (fwhisper locks the language; parakeet auto-detects and ignores `language`)
    device: str = "cuda"  # cuda | cpu
    language: str = "pt"  # pt | en (automatic detection is Phase 3)


class InjectCfg(BaseModel):
    default_strategy: str = "clipboard"  # clipboard | sendinput
    restore_clipboard_delay_ms: int = 400
    # profiles per executable (lowercase process name)
    per_app: dict[str, str] = Field(
        default_factory=lambda: {
            "windowsterminal.exe": "sendinput",
            "openconsole.exe": "sendinput",
        }
    )


class AudioCfg(BaseModel):
    sample_rate: int = 16000
    device: str | None = None  # None = system default
    vad_silence_ms: int = 300  # end-of-speech window in continuous mode
    max_utterance_s: int = 60

    @field_validator("device", mode="before")
    @classmethod
    def _empty_to_none(cls, v: object) -> object:
        # TOML has no null: None is saved as "" and must return to None on load,
        # otherwise sounddevice treats "" as a name filter and matches several mics.
        return None if v in ("", None) else v


class Config(BaseModel):
    hotkeys: HotkeysCfg = Field(default_factory=HotkeysCfg)
    stt: SttCfg = Field(default_factory=SttCfg)
    inject: InjectCfg = Field(default_factory=InjectCfg)
    audio: AudioCfg = Field(default_factory=AudioCfg)
    improved_mode: bool = False  # "AI-improved text" mode (Phase 2)
    show_hud: bool = True  # recording bar with waveform at the bottom of the screen


def load() -> Config:
    if CONFIG_PATH.is_file():
        data = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return Config.model_validate(data)
    APP_DIR.mkdir(parents=True, exist_ok=True)
    cfg = Config()
    save(cfg)
    return cfg


def save(cfg: Config) -> None:
    """Minimal TOML serialization (2 levels, simple types), enough for the config."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    data = cfg.model_dump()
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    for k, v in scalars.items():
        lines.append(f"{k} = {_toml_value(v)}")
    for section, values in data.items():
        if not isinstance(values, dict):
            continue
        lines.append(f"\n[{section}]")
        for k, v in values.items():
            if isinstance(v, dict):
                lines.append(f"[{section}.{k}]")
                for kk, vv in v.items():
                    lines.append(f'"{kk}" = {_toml_value(vv)}')
            else:
                lines.append(f"{k} = {_toml_value(v)}")
    CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _toml_value(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if v is None:
        return '""'
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
