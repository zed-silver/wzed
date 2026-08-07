"""Phase 0, item 2: A/B of STT engines (Parakeet-TDT-0.6B-v3 vs faster-whisper turbo int8).

Measures per-sentence latency (post-load, model resident) and WER against bench/refs.json.
Usage:
    uv run python scripts/bench_stt.py [--engine parakeet|fwhisper|both] [--device cuda|cpu]
Output: table on stdout + bench/results.json
"""

from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "bench" / "audio"
REFS = ROOT / "bench" / "refs.json"
RESULTS = ROOT / "bench" / "results.json"


def _setup_cuda_dlls() -> None:
    """Exposes ALL DLLs from the nvidia-* pip packages and uses onnxruntime's preload."""
    import importlib.util
    import os

    spec = importlib.util.find_spec("nvidia")
    if spec and spec.submodule_search_locations:
        for loc in spec.submodule_search_locations:
            for bin_dir in Path(loc).glob("*/bin"):
                if bin_dir.is_dir():
                    os.add_dll_directory(str(bin_dir))
                    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ["PATH"]
    try:  # onnxruntime >= 1.21 loads the CUDA DLLs from the pip packages on its own
        import onnxruntime as ort

        ort.preload_dlls()
    except Exception:
        pass


def _norm(text: str) -> str:
    """Normalization for WER: lowercase, no punctuation, no accents, single spaces."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def bench_parakeet(files: list[Path], refs: dict, device: str) -> dict:
    import onnx_asr

    providers = (
        ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if device == "cuda"
        else ["CPUExecutionProvider"]
    )
    t0 = time.perf_counter()
    model = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", providers=providers)
    load_s = time.perf_counter() - t0
    # warmup (discards the first utterance to measure the warm regime)
    model.recognize(str(files[0]))
    rows = []
    for f in files:
        lang = refs[f.stem]["lang"]
        t0 = time.perf_counter()
        text = model.recognize(str(f), language=lang)
        dt = time.perf_counter() - t0
        rows.append({"id": f.stem, "latency_ms": round(dt * 1000, 1), "text": text})
    return {"engine": "parakeet-tdt-0.6b-v3", "device": device, "load_s": round(load_s, 1), "rows": rows}


def bench_fwhisper(files: list[Path], refs: dict, device: str) -> dict:
    from faster_whisper import WhisperModel

    compute = "int8_float16" if device == "cuda" else "int8"
    t0 = time.perf_counter()
    model = WhisperModel("deepdml/faster-whisper-large-v3-turbo-ct2", device=device, compute_type=compute)
    load_s = time.perf_counter() - t0
    segs, _ = model.transcribe(str(files[0]), language=refs[files[0].stem]["lang"])
    list(segs)  # warmup
    rows = []
    for f in files:
        lang = refs[f.stem]["lang"]
        t0 = time.perf_counter()
        segs, _ = model.transcribe(str(f), language=lang, beam_size=1, vad_filter=False)
        text = " ".join(s.text.strip() for s in segs)
        dt = time.perf_counter() - t0
        rows.append({"id": f.stem, "latency_ms": round(dt * 1000, 1), "text": text})
    return {"engine": "faster-whisper large-v3-turbo int8", "device": device, "load_s": round(load_s, 1), "rows": rows}


def add_wer(result: dict, refs: dict) -> None:
    import jiwer

    for row in result["rows"]:
        ref = _norm(refs[row["id"]]["text"])
        hyp = _norm(row["text"])
        row["wer"] = round(jiwer.wer(ref, hyp), 3) if ref else None
    pt = [r["wer"] for r in result["rows"] if r["id"].startswith("pt") and r["wer"] is not None]
    en = [r["wer"] for r in result["rows"] if r["id"].startswith("en") and r["wer"] is not None]
    lat = [r["latency_ms"] for r in result["rows"]]
    result["summary"] = {
        "wer_pt": round(sum(pt) / len(pt), 3) if pt else None,
        "wer_en": round(sum(en) / len(en), 3) if en else None,
        "latency_ms_median": sorted(lat)[len(lat) // 2],
        "latency_ms_max": max(lat),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["parakeet", "fwhisper", "both"], default="both")
    ap.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    ap.add_argument("--audio-dir", default=None, help="folder with the .wav files (default: bench/audio)")
    ap.add_argument("--refs", default=None, help="references json (default: bench/refs.json)")
    ap.add_argument("--out", default=None, help="results json")
    args = ap.parse_args()

    audio_dir = Path(args.audio_dir) if args.audio_dir else AUDIO_DIR
    refs_path = Path(args.refs) if args.refs else REFS
    out_path = Path(args.out) if args.out else (audio_dir.parent / "results.json")

    _setup_cuda_dlls()
    refs = json.loads(refs_path.read_text(encoding="utf-8-sig"))
    files = sorted(p for p in audio_dir.glob("*.wav") if p.stem in refs)
    if not files:
        raise SystemExit(f"Nenhum áudio em {audio_dir}; grave antes (record_test_audio.py).")
    print(f"{len(files)} arquivos | device={args.device} | dataset={audio_dir.name}")

    results = []
    for name, fn in (("parakeet", bench_parakeet), ("fwhisper", bench_fwhisper)):
        if args.engine not in (name, "both"):
            continue
        try:
            r = fn(files, refs, args.device)
            add_wer(r, refs)
            results.append(r)
            s = r["summary"]
            print(
                f"\n== {r['engine']} ({r['device']}) | load {r['load_s']}s | "
                f"WER pt={s['wer_pt']} en={s['wer_en']} | "
                f"latência mediana={s['latency_ms_median']}ms max={s['latency_ms_max']}ms"
            )
            for row in r["rows"]:
                cat = refs[row["id"]].get("cat", "")
                print(
                    f"  {row['id']} {cat:<12} {row['latency_ms']:>7}ms "
                    f"wer={row['wer']:<6} {row['text'][:60]}"
                )
        except Exception as e:  # noqa: BLE001 - bench should report, not die
            print(f"\n== {name} FALHOU: {type(e).__name__}: {e}")
            results.append({"engine": name, "error": f"{type(e).__name__}: {e}"})

    _compare(results, refs)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nresultados em {out_path}")


def _compare(results: list[dict], refs: dict) -> None:
    """Verdict: WER by category (where the pt-BR accent vs pt-PT model shows up)."""
    ok = [r for r in results if "rows" in r]
    if len(ok) < 2:
        return
    cats = sorted({refs[i].get("cat", "?") for i in refs})
    print("\n" + "=" * 74)
    print("  WER por categoria (menor é melhor)")
    print("=" * 74)
    print(f"  {'categoria':<14} " + " ".join(f"{r['engine'][:18]:>20}" for r in ok))
    for c in cats:
        line = f"  {c:<14} "
        for r in ok:
            vals = [
                row["wer"]
                for row in r["rows"]
                if refs[row["id"]].get("cat", "?") == c and row["wer"] is not None
            ]
            line += f"{(sum(vals) / len(vals) if vals else float('nan')):>20.3f} "
        print(line)
    print("  " + "-" * 70)
    for r in ok:
        s = r["summary"]
        print(
            f"  {r['engine']:<38} WER pt {s['wer_pt']:.3f} | "
            f"latência mediana {s['latency_ms_median']:.0f} ms"
        )
    best_wer = min(ok, key=lambda r: r["summary"]["wer_pt"])
    best_lat = min(ok, key=lambda r: r["summary"]["latency_ms_median"])
    print(f"\n  Mais preciso: {best_wer['engine']}")
    print(f"  Mais rápido:  {best_lat['engine']}")
    delta = abs(ok[0]["summary"]["wer_pt"] - ok[1]["summary"]["wer_pt"])
    if delta < 0.02:
        print("  → Empate técnico em WER (<2 pontos): decida pela latência.")
    else:
        print(f"  → Diferença de WER relevante ({delta:.3f}): decida pela precisão.")


if __name__ == "__main__":
    main()
