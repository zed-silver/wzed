"""Records the 15 reference sentences in Ricardo's REAL voice (pt-BR) for the engine A/B.

The synthetic bench (SAPI) validates the pipeline, not the accent. Parakeet is trained on
European Portuguese: this dataset is the gate that decides the final engine.

Usage (interactive terminal, NOT via Claude):
    cd E:\\dev\\wzed
    uv run python scripts/record_test_audio.py

Output: bench/audio_real/*.wav (16 kHz mono) + bench/refs_real.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from wzed.audio.capture import _resolve_device  # noqa: E402

SR = 16000
OUT_DIR = Path(__file__).parent.parent / "bench" / "audio_real"
REFS = Path(__file__).parent.parent / "bench" / "refs_real.json"

# 15 sentences that stress the real risk: pt-BR accent against a model trained on pt-PT.
FRASES: list[tuple[str, str, str]] = [
    # (id, category, text)
    ("r01", "corriqueira", "Bom dia, tudo bem? Vou revisar o documento e te mando ainda hoje."),
    ("r02", "corriqueira", "Preciso terminar essa tarefa antes do fim da tarde."),
    ("r03", "corriqueira", "Me lembra de ligar para o contador na segunda-feira."),
    ("r04", "nomes-locais", "A Michele vai visitar o imóvel em Portimão amanhã de manhã."),
    ("r05", "nomes-locais", "A Zuleika enviou a proposta para o cliente de Lagoa e Carvoeiro."),
    ("r06", "nomes-locais", "O mercado imobiliário do Algarve aqueceu bastante neste verão."),
    ("r07", "numeros", "O apartamento saiu por trezentos e vinte mil euros, com dez por cento de entrada."),
    ("r08", "numeros", "A reunião ficou marcada para quinze de agosto, às três e meia da tarde."),
    ("r09", "hesitacao", "Então, hum, eu acho que a gente podia, tipo, adiar essa decisão para semana que vem."),
    ("r10", "dev", "Vou fazer o commit e subir o deploy na Vercel depois do build passar."),
    ("r11", "dev", "Abre o Visual Studio Code e roda o script de migração do Supabase."),
    ("r12", "pt-br-lexico", "Fecha o arquivo na tela do computador e me manda pelo celular."),
    ("r13", "pt-br-lexico", "Peguei o ônibus e cheguei atrasado no treino do meu time."),
    ("r14", "pergunta", "Você pode me enviar o relatório de vendas do segundo trimestre?"),
    (
        "r15",
        "longa",
        "A ideia central é reduzir o risco de decisão do comprador, mostrando com clareza "
        "os números, o bairro e o que pode dar errado antes de qualquer visita.",
    ),
]


def _bar(rms: float, width: int = 30) -> str:
    n = min(width, int(rms * 400))
    return "[" + "#" * n + "-" * (width - n) + "]"


def _check(audio: np.ndarray) -> list[str]:
    avisos = []
    dur = len(audio) / SR
    if dur < 1.0:
        avisos.append(f"MUITO CURTA ({dur:.1f}s)")
    rms = float(np.sqrt(np.mean(audio**2))) if len(audio) else 0.0
    if rms < 0.006:
        avisos.append(f"volume baixo (RMS {rms:.4f}) — fale mais perto do mic")
    if len(audio) and float(np.max(np.abs(audio))) > 0.99:
        avisos.append("CLIPPING — fale mais longe do mic")
    return avisos


def _record(idx: int) -> np.ndarray:
    chunks: list[np.ndarray] = []
    peak = {"v": 0.0}

    def cb(indata, frames, t, status):  # noqa: ANN001, ARG001
        block = indata[:, 0].copy()
        chunks.append(block)
        peak["v"] = float(np.sqrt(np.mean(block**2)))

    with sd.InputStream(samplerate=SR, channels=1, dtype="float32", device=idx, callback=cb):
        print("   ● GRAVANDO... fale a frase e pressione ENTER para parar")
        # level feedback while the user speaks
        import threading

        parar = threading.Event()

        def medidor():
            while not parar.is_set():
                print(f"\r   nível {_bar(peak['v'])}   ", end="", flush=True)
                time.sleep(0.08)

        th = threading.Thread(target=medidor, daemon=True)
        th.start()
        input()
        parar.set()
        th.join(timeout=0.3)
    print("\r" + " " * 50 + "\r", end="")
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dev = _resolve_device(None)
    info = sd.query_devices(dev, kind="input")
    print("=" * 74)
    print("  wzed · gravação do dataset REAL (15 frases, ~5 minutos)")
    print("=" * 74)
    print(f"  microfone: {info['name']}")
    print("\n  Como funciona:")
    print("    ENTER  inicia a gravação  →  fale a frase  →  ENTER para parar")
    print("    Depois: ENTER aceita · [r] refaz · [o] ouve de novo · [q] sai e salva")
    print("\n  Dicas: fale NATURAL, no ritmo em que você dita de verdade.")
    print("  Não use Ctrl+Win agora (o wzed está rodando e ia gravar junto).")
    print("=" * 74)

    refs: dict[str, dict] = {}
    if REFS.exists():  # resume: keep what has already been recorded
        refs = json.loads(REFS.read_text(encoding="utf-8-sig"))
        if refs:
            print(f"\n  (retomando: {len(refs)} frases já gravadas)\n")

    for i, (fid, cat, texto) in enumerate(FRASES, 1):
        wav = OUT_DIR / f"{fid}.wav"
        if fid in refs and wav.exists():
            print(f"[{i:2d}/15] {fid} já gravada, pulando (apague o .wav para refazer)")
            continue

        print(f"\n[{i:2d}/15] ({cat})")
        print(f'   "{texto}"')
        try:
            input("   ENTER para começar a gravar... ")
        except (EOFError, KeyboardInterrupt):
            break

        while True:
            audio = _record(dev)
            avisos = _check(audio)
            dur = len(audio) / SR
            print(f"   gravado: {dur:.1f}s", end="")
            for a in avisos:
                print(f"  ⚠ {a}", end="")
            print()

            escolha = input("   [ENTER] aceita · [r] refaz · [o] ouve · [q] sai: ").strip().lower()
            if escolha == "o":
                sd.play(audio, SR)
                sd.wait()
                escolha = input("   [ENTER] aceita · [r] refaz: ").strip().lower()
            if escolha == "r":
                continue
            if escolha == "q":
                _save(refs)
                print("\n  Saiu. Rode de novo para continuar de onde parou.")
                return
            break

        sf.write(str(wav), audio, SR, subtype="PCM_16")
        refs[fid] = {"lang": "pt", "text": texto, "voice": "ricardo-real", "cat": cat}
        _save(refs)
        print(f"   ✓ salvo em {wav.name}")

    _save(refs)
    print("\n" + "=" * 74)
    print(f"  PRONTO: {len(refs)}/15 frases em {OUT_DIR}")
    print("  Agora rode o A/B:")
    print("    uv run python scripts/bench_stt.py --engine both --device cuda \\")
    print("        --audio-dir bench/audio_real --refs bench/refs_real.json")
    print("=" * 74)


def _save(refs: dict) -> None:
    REFS.write_text(json.dumps(refs, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
