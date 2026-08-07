"""Pós-processamento determinístico (sem LLM): dicionário pessoal e limpeza leve.

O dicionário vive em %APPDATA%\\wzed\\dictionary.txt, uma linha por regra:
    errado -> certo        (substituição, case-insensitive, por palavra)
    TermoExato             (proteção: força a grafia exata quando o STT acertar foneticamente)
"""

from __future__ import annotations

import re
from pathlib import Path

from wzed.config import APP_DIR

DICT_PATH = APP_DIR / "dictionary.txt"

# hesitações comuns pt/en no INÍCIO de frase (remoção conservadora; o resto é papel do LLM)
_HESITACAO = re.compile(
    r"^(?:hum+|uh+m*|ah+n?|é+h?|eh+|hm+m*)[,.\s]+", re.IGNORECASE
)


class Rules:
    def __init__(self) -> None:
        self._subs: list[tuple[re.Pattern[str], str]] = []
        self._protected: list[tuple[re.Pattern[str], str]] = []
        self.reload()

    def reload(self) -> None:
        self._subs.clear()
        self._protected.clear()
        if not DICT_PATH.is_file():
            return
        for line in DICT_PATH.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "->" in line:
                wrong, right = (p.strip() for p in line.split("->", 1))
                if wrong:
                    self._subs.append(
                        (re.compile(rf"\b{re.escape(wrong)}\b", re.IGNORECASE), right)
                    )
            else:
                self._protected.append(
                    (re.compile(rf"\b{re.escape(line)}\b", re.IGNORECASE), line)
                )

    def apply(self, text: str) -> str:
        text = text.strip()
        text = _HESITACAO.sub("", text)
        for pat, right in self._subs:
            text = pat.sub(right, text)
        for pat, exact in self._protected:
            text = pat.sub(exact, text)
        # espaço duplicado e espaço antes de pontuação (sobras de substituição)
        text = re.sub(r"\s{2,}", " ", text)
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        return text.strip()
