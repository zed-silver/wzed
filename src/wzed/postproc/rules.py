"""Deterministic post-processing (no LLM): personal dictionary and light cleanup.

The dictionary lives at %APPDATA%\\wzed\\dictionary.txt, one rule per line:
    wrong -> right         (substitution, case-insensitive, whole words/phrases only)
    ExactTerm              (protection: forces the exact spelling when the STT gets it phonetically right)

The file is re-read automatically when its modification time changes (checked on every
dictation), so edits apply to the next dictation without restarting the app.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from wzed.config import APP_DIR

log = logging.getLogger(__name__)

DICT_PATH = APP_DIR / "dictionary.txt"

DICT_TEMPLATE = """\
# wzed: personal dictionary (saving the file is enough; applies to the next dictation)
#
#   wrong -> right     fixes a recurring mistranscription (case-insensitive, whole words only)
#   ExactTerm          forces the exact spelling of a term the STT already hears right
#
# Longer phrases win over shorter ones. Lines starting with # are ignored.
#
# confiwide -> ComfyUI
# Supabase
"""

# common pt/en hesitations at the START of a sentence (conservative removal; the rest is the LLM's job).
# A bare "é" is NOT a hesitation: it is the verb ("É importante…"). Only the elongated "éé"/"éh" is.
_HESITACAO = re.compile(
    r"^(?:hum+|uh+m*|ah+n?|éé+h?|éh+|eh+|hm+m*)[,.\s]+", re.IGNORECASE
)


def _norm(phrase: str) -> str:
    """Lookup key: case-folded, internal whitespace collapsed."""
    return " ".join(phrase.split()).casefold()


def _phrase_pattern(phrase: str) -> str:
    # whole word/phrase: no word character glued on either side (works for accents and for
    # terms that start/end with symbols, like "C++", where \b would fail); any run of
    # whitespace between the words, since the STT may emit double spaces
    body = r"\s+".join(re.escape(w) for w in phrase.split())
    return rf"(?<!\w){body}(?!\w)"


class Rules:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else DICT_PATH
        self._map: dict[str, str] = {}
        self._pattern: re.Pattern[str] | None = None
        self._mtime: int | None = None
        self.reload()

    def reload(self) -> None:
        try:
            mtime = self._path.stat().st_mtime_ns
        except OSError:  # no dictionary file: no rules
            self._set({}, None)
            return
        try:
            text = self._path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            # editor mid-save or wrong encoding: keep the rules we already have
            log.warning("não foi possível ler %s; mantendo o dicionário anterior", self._path, exc_info=True)
            return
        self._set(self._parse(text), mtime)
        log.info("dicionário carregado: %d regra(s)", len(self._map))

    @staticmethod
    def _parse(text: str) -> dict[str, str]:
        rules: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "->" in line:
                wrong, right = (p.strip() for p in line.split("->", 1))
            else:
                wrong = right = line
            if wrong:
                rules[_norm(wrong)] = right  # a later line overrides an earlier one
        return rules

    def _set(self, rules: dict[str, str], mtime: int | None) -> None:
        self._map = rules
        self._mtime = mtime
        if not rules:
            self._pattern = None
            return
        # ONE alternation, longest phrase first: "confi wide" wins over "confi", and a
        # replacement is never re-matched by another rule (single pass, no chaining)
        keys = sorted(rules, key=lambda k: (len(k.split()), len(k)), reverse=True)
        self._pattern = re.compile(
            "|".join(_phrase_pattern(k) for k in keys), re.IGNORECASE
        )

    def _reload_if_changed(self) -> None:
        try:
            mtime: int | None = self._path.stat().st_mtime_ns
        except OSError:
            mtime = None
        if mtime != self._mtime:
            self.reload()

    def hint_terms(self) -> list[str]:
        """Correct spellings from the dictionary (deduplicated, file order), used to bias the
        STT before it transcribes. Empty dictionary = no hints = unchanged STT behavior."""
        self._reload_if_changed()
        return list(dict.fromkeys(v for v in self._map.values() if v))

    def apply(self, text: str) -> str:
        self._reload_if_changed()
        text = text.strip()
        text = _HESITACAO.sub("", text)
        if self._pattern is not None:
            text = self._pattern.sub(lambda m: self._map.get(_norm(m.group(0)), m.group(0)), text)
        # doubled spaces and space before punctuation (leftovers from substitution)
        text = re.sub(r"\s{2,}", " ", text)
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        return text.strip()


def ensure_dictionary_file(path: Path | None = None) -> Path:
    """Creates the dictionary with a commented template if it does not exist yet."""
    path = path if path is not None else DICT_PATH
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DICT_TEMPLATE, encoding="utf-8")
    return path
