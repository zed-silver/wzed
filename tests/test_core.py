"""Unit tests for the hardware-free modules: config, rules, history, hotkey parse."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest


def test_config_roundtrip(tmp_path, monkeypatch):
    from wzed import config as cfg_mod

    monkeypatch.setattr(cfg_mod, "APP_DIR", tmp_path)
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "config.toml")
    cfg = cfg_mod.load()  # creates default
    assert cfg.stt.engine == "fwhisper"
    cfg.stt.engine = "parakeet"
    cfg_mod.save(cfg)
    cfg2 = cfg_mod.load()
    assert cfg2.stt.engine == "parakeet"
    assert cfg2.inject.per_app["windowsterminal.exe"] == "sendinput"


def test_audio_device_none_roundtrip(tmp_path, monkeypatch):
    """Regression: device None is saved as '' in the TOML and MUST come back as None on load,
    otherwise sounddevice matches multiple mics and the app crashes on boot."""
    from wzed import config as cfg_mod

    monkeypatch.setattr(cfg_mod, "APP_DIR", tmp_path)
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", tmp_path / "config.toml")
    cfg = cfg_mod.load()
    assert cfg.audio.device is None
    cfg_mod.save(cfg)
    assert cfg_mod.load().audio.device is None  # must not become ""


def test_rules_hesitacao_e_dicionario(tmp_path, monkeypatch):
    from wzed.postproc import rules as rules_mod

    dict_file = tmp_path / "dictionary.txt"
    dict_file.write_text(
        "wisper -> wzed\nMagalhães\n# comentário\n", encoding="utf-8"
    )
    monkeypatch.setattr(rules_mod, "DICT_PATH", dict_file)
    r = rules_mod.Rules()
    assert r.apply("Hum, o wisper é rápido.") == "o wzed é rápido."
    assert r.apply("falei com o magalhães ontem") == "falei com o Magalhães ontem"
    assert r.apply("texto  com   espaços .") == "texto com espaços."


def test_history_fts(tmp_path):
    from wzed.history.store import HistoryStore

    h = HistoryStore(tmp_path / "h.db")
    h.add("raw", "O relatório de vendas ficou pronto.", app="code.exe", lang="pt")
    h.add("raw", "Amanhã tem reunião cedo.", app="chrome.exe", lang="pt")
    assert len(h.recent()) == 2
    hits = h.search("relatório")
    assert len(hits) == 1 and "vendas" in hits[0][2]
    h.close()


def test_hotkey_parse():
    from wzed.hotkeys.manager import _parse

    groups = _parse("<ctrl>+<alt>+d")
    assert len(groups) == 3
    with pytest.raises(ValueError):
        _parse("<ctrl>+tecla_inexistente")


def test_single_instance_lock(monkeypatch):
    """Regression: without the lock, autostart + a Start Menu click bring up 2 instances
    and each one injects the text (everything comes out duplicated)."""
    from wzed import app as app_mod

    monkeypatch.setattr(app_mod, "_MUTEX_NAME", "Local\\wzed-test-mutex-xyz")
    assert app_mod._acquire_single_instance() is True  # first: acquires
    assert app_mod._acquire_single_instance() is False  # second: refuses


def test_injector_strategy_por_app(monkeypatch):
    from wzed.config import InjectCfg
    from wzed.inject.injector import Injector

    inj = Injector(InjectCfg())
    chamadas = []
    monkeypatch.setattr(
        "wzed.inject.injector.send_unicode", lambda t: chamadas.append(("sendinput", t))
    )
    monkeypatch.setattr(
        "wzed.inject.injector.active_process_name", lambda: "windowsterminal.exe"
    )
    assert inj.inject("olá") == "sendinput"
    assert chamadas == [("sendinput", "olá")]
