#!/usr/bin/env python3
"""
Ljudexempel till webbsidan: klipper ut korta MP3-klipp och spektrogram ur inspelningarna i audio/.

  python scripts/clips.py            # efter build.py; nya klipp skapas, befintliga återanvänds
  python scripts/clips.py --antal 5  # fler klipp per art och natt (standard 3)
  python scripts/clips.py --tid 150  # sluta efter 150 s (kör igen för att fortsätta)

Urval: för varje art och natt de detektioner med högst sannolikhet (olika filer). Oidentifierade
signaler och "Aves sp." tas inte med. Inspelningar som saknas i audio/ hoppas över.

  Ultraljud (fladdermöss, vårtbitare, näbbmöss m.fl., inspelade i 384 kHz): det starkaste avsnittet
  på 1,5 s över 12 kHz väljs, högpassfiltreras och saktas ner 10 gånger så att det blir hörbart.
  Fåglar (BirdNET): BirdNETs bästa 3 s-segment för arten i filen, ±1 s, i normal hastighet.

Skriver docs/audio/<natt>/<fil>_<start>.mp3 och .png samt docs/data/clips.json.
Kräver ffmpeg samt numpy, scipy och matplotlib.
"""
import csv, glob, json, os, subprocess, sys, time, warnings
from datetime import datetime

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfiltfilt

from PIL import Image
import matplotlib
matplotlib.use("Agg")
warnings.filterwarnings("ignore", message="Chunk")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO = os.path.join(ROOT, "audio")
OUT = os.path.join(ROOT, "docs", "audio")
DATA = os.path.join(ROOT, "docs", "data", "data.json")
MANIFEST = os.path.join(ROOT, "docs", "data", "clips.json")
BIRDNET = os.path.join(ROOT, "data", "birdnet")
SKIP = {"Oidentifierad", "Aves sp."}
SLOW = 10          # nedsaktning för ultraljud
US_WIN = 1.5       # sekunder ultraljud (blir 15 s nedsaktat)
US_HP = 12000      # högpass för ultraljud (Hz)


def file_time(name):
    """DEV_001_20261007_192046.wav -> datetime"""
    p = os.path.splitext(name)[0].split("_")
    return datetime.strptime(p[-2] + p[-1], "%Y%m%d%H%M%S")


def birdnet_segments():
    best = {}
    for f in sorted(glob.glob(os.path.join(BIRDNET, "*.csv"))):
        with open(f, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                sci, p = r.get("Vetenskapligt namn", "").strip(), (r.get("Sannolikhet") or "").replace(",", ".")
                if sci and p and float(p) > best.get((r["Fil"], sci), (0,))[0]:
                    best[(r["Fil"], sci)] = (float(p), float(r["Start s"] or 0))
    return best


def read_mono(path):
    sr, x = wavfile.read(path)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if x.dtype.kind == "i":
        x = x.astype(np.float32) / np.iinfo(x.dtype).max
    return sr, x.astype(np.float32)


def loudest_window(x, sr, win):
    n = int(win * sr)
    if len(x) <= n:
        return 0
    c = np.cumsum(np.concatenate([[0.0], x.astype(np.float64) ** 2]))
    s = c[n:] - c[:-n]          # energi i varje fönster av längden win
    return int(np.argmax(s))


def to_mp3(x, rate, path):
    peak = float(np.max(np.abs(x))) or 1.0
    pcm = (x / peak * 0.89 * 32767).astype("<i2").tobytes()
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "s16le", "-ar", str(rate), "-ac", "1",
                    "-i", "pipe:0", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "48k", path],
                   input=pcm, check=True)


def spectrogram(x, sr, fmax, path, t0=0.0):
    """Spektrogram med kontrast per klipp: bruset (medianen) blir mörkt, de starkaste lätena ljusa."""
    from scipy.signal import spectrogram as spg
    nfft = 1024 if sr > 100000 else 512
    f, t, S = spg(x, fs=sr, nperseg=nfft, noverlap=nfft * 3 // 4, window="hann")
    keep = f <= fmax
    db = 10 * np.log10(S[keep] + 1e-20)
    from scipy.ndimage import uniform_filter
    db = uniform_filter(db, size=(3, 3))          # dämpa brusprickar
    db -= np.median(db, axis=1, keepdims=True)    # jämna ut bakgrundsbrus per frekvens
    lo, hi = 2.0, max(8.0, float(np.percentile(db, 99.9)))
    fig = plt.figure(figsize=(6.4, 2.0), dpi=80)
    ax = fig.add_axes([0.08, 0.2, 0.9, 0.75])
    ax.imshow(db, origin="lower", aspect="auto", cmap="magma", vmin=lo, vmax=hi, interpolation="nearest",
              extent=(t0, t0 + len(x) / sr, 0, f[keep][-1]))
    ax.set_ylim(0, fmax)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v / 1000:g}"))
    ax.set_ylabel("kHz", fontsize=8)
    ax.set_xlabel("s i filen", fontsize=8, labelpad=1)
    ax.tick_params(labelsize=7)
    fig.canvas.draw()
    img = Image.fromarray(np.asarray(fig.canvas.buffer_rgba())[..., :3])
    plt.close(fig)
    img.quantize(48).save(path, optimize=True)


def main(per_night=3, budget=None):
    t_start = time.time()
    D = json.load(open(DATA, encoding="utf-8"))
    sp = D["species"]
    wavs = {}
    for dirpath, _, files in os.walk(AUDIO):
        for f in files:
            if f.lower().endswith(".wav"):
                wavs.setdefault(f, os.path.join(dirpath, f))
    bn = birdnet_segments()

    groups = {}
    for d in D["detections"]:
        if sp[d[0]]["sci"] not in SKIP:
            groups.setdefault((d[0], d[5]), []).append(d)
    jobs = []
    for (si, night), dets in sorted(groups.items(), key=lambda kv: (kv[0][1], sp[kv[0][0]]["sci"])):
        files = set()
        for d in sorted(dets, key=lambda d: -d[3]):
            if d[6] in files or d[6] not in wavs:
                continue
            files.add(d[6])
            jobs.append((si, night, d))
            if len(files) >= per_night:
                break

    clips, made, keep = [], 0, set()
    for si, night, d in jobs:
        if budget and time.time() - t_start > budget:
            print(f"Tiden slut: {made} nya klipp – kör igen för att fortsätta.")
            return False
        s, f = sp[si], d[6]
        bird = s.get("group") == "bird"
        try:
            sr, x = read_mono(wavs[f])
        except Exception as e:
            print("  ! kan inte läsa", f, e)
            continue
        if bird:
            start = bn.get((f, s["sci"]), (0, (datetime.fromisoformat(d[2]) - file_time(f)).total_seconds()))[1]
            a = max(0.0, start - 1)
            seg = x[int(a * sr): int((start + 4) * sr)]
            slow, fmax = 1, 11000
        else:
            if sr < 96000:
                continue
            seg_x = sosfiltfilt(butter(6, US_HP, "highpass", fs=sr, output="sos"), x)
            i0 = loudest_window(seg_x, sr, US_WIN)
            a = i0 / sr
            seg = seg_x[i0: i0 + int(US_WIN * sr)]
            slow, fmax = SLOW, min(130000, sr // 2)
        if len(seg) < sr * 0.2:
            continue
        stem = f"{os.path.splitext(f)[0]}_{int(round(a * 1000)):05d}"
        rel = f"audio/{night}/{stem}"
        mp3, png = os.path.join(ROOT, "docs", rel + ".mp3"), os.path.join(ROOT, "docs", rel + ".png")
        keep.update({mp3, png})
        if not (os.path.exists(mp3) and os.path.exists(png)):
            os.makedirs(os.path.dirname(mp3), exist_ok=True)
            to_mp3(seg, sr // slow, mp3)
            spectrogram(seg, sr, fmax, png, t0=a)
            made += 1
        clips.append([s["sci"], night, f, round(a, 2), round(len(seg) / sr, 2), d[3], d[2], rel, slow])

    # klipp som inte längre väljs tas bort
    removed, keep = 0, {os.path.abspath(k) for k in keep}
    for p in glob.glob(os.path.join(OUT, "**", "*.*"), recursive=True):
        if os.path.abspath(p) not in keep:
            os.remove(p)
            removed += 1
    json.dump({"fields": ["sci", "night", "file", "start", "dur", "prob", "time", "path", "slow"], "clips": clips},
              open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    size = sum(os.path.getsize(p) for p in glob.glob(os.path.join(OUT, "**", "*.*"), recursive=True))
    print(f"{len(clips)} ljudexempel ({made} nya, {removed} borttagna), {size / 1e6:.1f} MB i docs/audio")
    return True


if __name__ == "__main__":
    a = sys.argv
    done = main(int(a[a.index("--antal") + 1]) if "--antal" in a else 3,
                float(a[a.index("--tid") + 1]) if "--tid" in a else None)
    sys.exit(0 if done else 3)
