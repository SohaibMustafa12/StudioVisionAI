"""Heavy-engine worker. Studio Vision runs this with a Python install that has PyTorch / F5-TTS /
faster-whisper, so the packaged app stays small. Speaks JSON lines over stdin/stdout.
Standalone on purpose: it must not import anything from the app package."""

import json
import os
import sys
import traceback

_out = sys.stdout
sys.stdout = sys.stderr  # libraries print progress; keep the protocol channel clean

state = {"f5": None, "whisper": None, "whisper_size": None}


def send(obj):
    _out.write(json.dumps(obj) + "\n")
    _out.flush()


def status(msg):
    send({"status": msg})


def f5_load():
    if state["f5"] is None:
        n = os.cpu_count() or 4
        threads = str(max(1, n // 2 if n >= 8 else n))  # one thread per physical core is fastest on CPU
        os.environ.setdefault("OMP_NUM_THREADS", threads)
        os.environ.setdefault("MKL_NUM_THREADS", threads)
        import torch
        import torchaudio
        torch.set_num_threads(int(threads))
        try:
            import soundfile as sf

            def _sf_load(filepath, *args, **kwargs):
                data, sr = sf.read(filepath, dtype="float32", always_2d=True)
                return torch.from_numpy(data.T.copy()), sr
            torchaudio.load = _sf_load
        except ImportError:
            pass
        from f5_tts.api import F5TTS
        state["f5"] = F5TTS()
    return {"device": str(getattr(state["f5"], "device", "cpu"))}


def f5_synth(gen_text, ref_file, ref_text, nfe, speed, out):
    f5_load()
    import numpy as np
    import torch
    import wave
    with torch.inference_mode():
        wav_out, sr, _ = state["f5"].infer(ref_file=ref_file, ref_text=ref_text, gen_text=gen_text,
                                           nfe_step=int(nfe), speed=float(speed), show_info=lambda *a, **k: None)
    data = np.clip(np.asarray(wav_out, dtype=np.float32).reshape(-1), -1, 1)
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes((data * 32767).astype("<i2").tobytes())
    return {"path": out}


def _load_whisper(size):
    if state["whisper"] is None or state["whisper_size"] != size:
        from faster_whisper import WhisperModel
        state["whisper"] = WhisperModel(size, device="cpu", compute_type="int8")
        state["whisper_size"] = size
    return state["whisper"]


def _read_wav16(path):
    import numpy as np
    import wave
    with wave.open(path, "rb") as w:
        sr, ch = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    data = data.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        n = int(len(data) * 16000 / sr)
        data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data).astype(np.float32)
    return data


def whisper_words(path, lang, size):
    segs, _ = _load_whisper(size).transcribe(_read_wav16(path), language=lang or None, word_timestamps=True,
                                             beam_size=1)
    return {"words": [(w.start, max(0.05, w.end - w.start), w.word.strip()) for s in segs for w in (s.words or [])]}


def edge(text, voice, rate, pitch, out):
    import asyncio
    import edge_tts
    words = []

    async def go():
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
        with open(out, "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    words.append((chunk["offset"] / 1e7, chunk["duration"] / 1e7, chunk["text"]))
    asyncio.run(go())
    return {"path": out, "words": words}


def whisper(path, lang, size):
    if state["whisper"] is None or state["whisper_size"] != size:
        status(f"Loading offline speech recogniser ({size})…")
        from faster_whisper import WhisperModel
        state["whisper"] = WhisperModel(size, device="cpu", compute_type="int8")
        state["whisper_size"] = size
    # decode ourselves: faster-whisper's file decoder breaks with PyAV >= 19
    import numpy as np
    import wave
    with wave.open(path, "rb") as w:
        sr, ch = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    data = data.reshape(-1, ch).mean(axis=1)
    if sr != 16000:
        n = int(len(data) * 16000 / sr)
        data = np.interp(np.linspace(0, len(data) - 1, n), np.arange(len(data)), data).astype(np.float32)
    segs, info = state["whisper"].transcribe(data, language=lang or None, vad_filter=True, beam_size=1)
    return {"text": " ".join(s.text.strip() for s in segs).strip(), "lang": info.language}


def main():
    for line in sys.stdin:
        try:
            req = json.loads(line)
        except ValueError:
            continue
        rid, cmd = req.pop("id", 0), req.pop("cmd", "")
        if cmd == "quit":
            break
        try:
            if cmd == "f5_load":
                status("Loading voice-cloning model…")
                result = f5_load()
            elif cmd == "f5_synth":
                result = f5_synth(**req)
            elif cmd == "whisper":
                result = whisper(**req)
            elif cmd == "whisper_words":
                result = whisper_words(**req)
            elif cmd == "edge":
                result = edge(**req)
            else:
                raise ValueError(f"unknown command {cmd}")
            send({"id": rid, "ok": True, "result": result})
        except Exception as e:
            traceback.print_exc()
            send({"id": rid, "ok": False, "error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    main()
