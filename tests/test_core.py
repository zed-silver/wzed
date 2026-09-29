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


def _rules(tmp_path, text):
    from wzed.postproc.rules import Rules

    dict_file = tmp_path / "dictionary.txt"
    dict_file.write_text(text, encoding="utf-8")
    return Rules(dict_file), dict_file


def test_rules_limite_de_palavra(tmp_path):
    """A rule must never corrupt words that merely contain the term."""
    r, _ = _rules(tmp_path, "ia -> IA\nconfi -> Comfy\n")
    assert r.apply("a ia do dia no iate") == "a IA do dia no iate"
    assert r.apply("confiança no confi") == "confiança no Comfy"
    assert r.apply("confi, confi.") == "Comfy, Comfy."


def test_rules_frase_longa_vence_e_sem_encadeamento(tmp_path):
    # the shorter rule comes first in the file on purpose: file order must not matter
    r, _ = _rules(
        tmp_path, "confi -> Comfy\nconfi wide -> ComfyUI\nComfyUI -> NUNCA\n"
    )
    assert r.apply("abre o confi wide agora") == "abre o ComfyUI agora"
    assert r.apply("abre o confi   wide") == "abre o ComfyUI"  # STT whitespace varies
    assert r.apply("só o confi") == "só o Comfy"


def test_rules_maiusculas_minusculas(tmp_path):
    r, _ = _rules(tmp_path, "confiwide -> ComfyUI\nSupabase\nC++\n")
    assert r.apply("Confiwide e CONFIWIDE e confiwide") == "ComfyUI e ComfyUI e ComfyUI"
    assert r.apply("o SUPABASE e o supabase") == "o Supabase e o Supabase"
    assert r.apply("código em c++ hoje") == "código em C++ hoje"


def test_rules_dicionario_vazio_ou_ausente(tmp_path):
    from wzed.postproc.rules import Rules

    r, _ = _rules(tmp_path, "# só comentários\n\n")
    assert r.apply("texto intacto.") == "texto intacto."
    assert Rules(tmp_path / "nao_existe.txt").apply("texto intacto.") == "texto intacto."


def test_rules_nao_remove_verbo_e(tmp_path):
    """Regression: the hesitation filter ate the verb "É" at the start of sentences."""
    r, _ = _rules(tmp_path, "")
    assert r.apply("É importante lembrar disso.") == "É importante lembrar disso."
    assert r.apply("Éé, vamos lá.") == "vamos lá."


def test_rules_recarrega_quando_arquivo_muda(tmp_path):
    import os

    r, dict_file = _rules(tmp_path, "confiwide -> ComfyUI\n")
    assert r.apply("confiwide") == "ComfyUI"
    dict_file.write_text("confiwide -> ComfyUI\nsupa base -> Supabase\n", encoding="utf-8")
    st = dict_file.stat()  # force a distinct mtime (coarse filesystem clocks)
    os.utime(dict_file, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    assert r.apply("supa base") == "Supabase"
    dict_file.unlink()
    assert r.apply("confiwide") == "confiwide"  # file deleted: no rules


def test_rules_ensure_dictionary_file(tmp_path):
    from wzed.postproc.rules import Rules, ensure_dictionary_file

    path = ensure_dictionary_file(tmp_path / "sub" / "dictionary.txt")
    assert path.is_file()
    assert Rules(path).apply("confiwide") == "confiwide"  # template is all comments
    path.write_text("x -> y\n", encoding="utf-8")
    ensure_dictionary_file(path)  # must not overwrite an existing dictionary
    assert path.read_text(encoding="utf-8") == "x -> y\n"


def test_rules_hint_terms(tmp_path):
    r, _ = _rules(tmp_path, "confiwide -> ComfyUI\nSupabase\ncomfy ui -> ComfyUI\nx ->\n")
    assert r.hint_terms() == ["ComfyUI", "Supabase"]  # deduplicated, no empty values
    from wzed.postproc.rules import Rules

    assert Rules(tmp_path / "nao_existe.txt").hint_terms() == []


def test_fwhisper_recebe_hotwords():
    """The dictionary's correct terms reach faster-whisper as hotwords; none = None."""
    from types import SimpleNamespace

    import numpy as np

    from wzed.stt.engines import FasterWhisperEngine

    kwargs = {}

    class FakeModel:
        def transcribe(self, audio, **kw):
            kwargs.update(kw)
            return iter([SimpleNamespace(text=" abre o ComfyUI ")]), None

    eng = FasterWhisperEngine.__new__(FasterWhisperEngine)  # skip loading the real model
    eng._model = FakeModel()
    audio = np.zeros(16000, dtype=np.float32)
    assert eng.transcribe(audio, "pt", ["ComfyUI", "Supabase"]) == "abre o ComfyUI"
    assert kwargs["hotwords"] == "ComfyUI, Supabase"
    eng.transcribe(audio, "pt")
    assert kwargs["hotwords"] is None


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
