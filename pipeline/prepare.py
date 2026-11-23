#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Passo 1 do pipeline.
Lê a narração (.mp3), descobre QUANDO cada palavra foi falada (faster-whisper),
casa isso com o roteiro e escreve build/timeline.json (cenas, legendas, eventos de HUD)
+ a matriz de jobs de render para o GitHub Actions.
"""
import argparse
import difflib
import json
import math
import os
import re
import subprocess
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from roteiro import SCENES, FPS  # noqa: E402

CHUNK_FRAMES = int(os.environ.get("CHUNK_FRAMES", "150"))
TAIL = 0.7          # segundos de "respiro" depois da última palavra
CUT_LEAD = 0.12     # a cena troca um pouquinho ANTES da palavra


def norm(w):
    w = unicodedata.normalize("NFD", w.lower())
    w = "".join(c for c in w if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", w)


def audio_duration(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path])
    return float(out.decode().strip())


# ------------------------------------------------------------------ tokens do roteiro
def parse_tokens():
    toks = []
    for si, sc in enumerate(SCENES):
        for pi, part in enumerate(sc["text"].split("*")):
            for w in part.split():
                n = norm(w)
                if n:
                    toks.append({"scene": si, "disp": w, "norm": n, "hl": (pi % 2 == 1)})
    return toks


# ------------------------------------------------------------------ whisper
def expand_word(word, st, en):
    """'49' -> quarenta e nove (3 tokens) para casar com o roteiro escrito por extenso."""
    n = norm(word)
    if not n:
        return []
    if n.isdigit():
        try:
            from num2words import num2words
            parts = [norm(p) for p in num2words(int(n), lang="pt_BR").split()]
            parts = [p for p in parts if p]
            if parts:
                d = (en - st) / len(parts)
                return [(p, st + i * d, st + (i + 1) * d) for i, p in enumerate(parts)]
        except Exception:
            pass
    return [(n, st, en)]


def whisper_words(path, prompt):
    from faster_whisper import WhisperModel
    model = WhisperModel(os.environ.get("WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
    segs, _info = model.transcribe(path, language="pt", word_timestamps=True,
                                   initial_prompt=prompt, beam_size=5)
    out = []
    for s in segs:
        for w in (s.words or []):
            out.extend(expand_word(w.word, float(w.start), float(w.end)))
    return out


# ------------------------------------------------------------------ alinhamento
_RC = {}


def ratio(a, b):
    if a == b:
        return 1.0
    k = (a, b)
    if k not in _RC:
        _RC[k] = difflib.SequenceMatcher(None, a, b).ratio()
    return _RC[k]


def align(S, H):
    """Needleman-Wunsch: devolve, para cada palavra do roteiro, o índice da palavra ouvida (ou None)."""
    n, m = len(S), len(H)
    GAP = -0.5
    sc = [[0.0] * (m + 1) for _ in range(n + 1)]
    bt = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        sc[i][0] = i * GAP
        bt[i][0] = 1
    for j in range(1, m + 1):
        sc[0][j] = j * GAP
        bt[0][j] = 2
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            r = ratio(S[i - 1], H[j - 1])
            s = (2.0 * r - 0.9) if r >= 0.55 else -1.2
            best, b = sc[i - 1][j - 1] + s, 0
            up = sc[i - 1][j] + GAP
            left = sc[i][j - 1] + GAP
            if up > best:
                best, b = up, 1
            if left > best:
                best, b = left, 2
            sc[i][j] = best
            bt[i][j] = b
    mp = [None] * n
    i, j = n, m
    while i > 0 or j > 0:
        b = bt[i][j]
        if i > 0 and j > 0 and b == 0:
            if ratio(S[i - 1], H[j - 1]) >= 0.55:
                mp[i - 1] = j - 1
            i -= 1
            j -= 1
        elif i > 0 and (b == 1 or j == 0):
            i -= 1
        else:
            j -= 1
    return mp


def proportional(tokens, dur):
    t0, t1 = 0.3, max(1.3, dur - 0.4)
    wts = [len(t["norm"]) + 2 for t in tokens]
    tot = float(sum(wts))
    acc, out = t0, []
    for w in wts:
        d = (t1 - t0) * w / tot
        out.append((acc, acc + d * 0.92))
        acc += d
    return out


def token_times(tokens, heard, dur):
    n = len(tokens)
    S = [t["norm"] for t in tokens]
    times = [None] * n
    matched = 0
    if heard:
        H = [h[0] for h in heard]
        mp = align(S, H)
        for i, j in enumerate(mp):
            if j is not None:
                times[i] = (heard[j][1], heard[j][2])
                matched += 1
    frac = matched / float(max(1, n))
    print("alinhamento: %d/%d palavras casadas (%.0f%%)" % (matched, n, frac * 100))
    if frac < 0.35:
        print("::warning::Alinhamento fraco, usando tempo proporcional nas legendas.")
        return proportional(tokens, dur)
    i = 0
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        t0 = times[i - 1][1] if i > 0 else 0.0
        t1 = times[j][0] if j < n else dur
        if t1 < t0:
            t1 = t0 + 0.2 * (j - i)
        wts = [len(S[k]) + 1 for k in range(i, j)]
        tot = float(sum(wts))
        acc = t0
        for k, w in zip(range(i, j), wts):
            d = (t1 - t0) * w / tot
            times[k] = (acc, acc + d * 0.9)
            acc += d
        i = j
    prev = 0.0
    for k in range(n):
        s, e = times[k]
        s = max(s, prev)
        e = max(e, s + 0.05)
        times[k] = (s, e)
        prev = s
    return times


# ------------------------------------------------------------------ legendas / eventos
def make_chunks(toks):
    chunks, cur = [], []

    def flush():
        if cur:
            chunks.append(list(cur))
            del cur[:]

    for tk in toks:
        if cur and len(" ".join([x["disp"] for x in cur] + [tk["disp"]])) > 16:
            flush()
        cur.append(tk)
        if len(cur) >= 3 or tk["disp"][-1] in ".,:;?!":
            flush()
    flush()
    return chunks


def resolve(anchor, sc):
    kind = anchor[0]
    if kind == "s":
        return sc["start"] + float(anchor[1])
    if kind == "f":
        return sc["start"] + float(anchor[1]) * (sc["end"] - sc["start"])
    if kind == "end":
        return sc["end"] + float(anchor[1])
    if kind == "w":
        t = sc["anchors"].get(norm(anchor[1]))
        if t is None:
            print("aviso: palavra-ancora '%s' não achada na cena %s" % (anchor[1], sc["key"]))
            t = sc["start"] + 0.4
        return t + float(anchor[2])
    raise ValueError("ancora invalida: %r" % (anchor,))


def build_timeline(dur, heard):
    toks = parse_tokens()
    times = token_times(toks, heard, dur)
    for tk, (s, e) in zip(toks, times):
        tk["t0"], tk["t1"] = s, e

    scenes = []
    for si, sc in enumerate(SCENES):
        st = [t for t in toks if t["scene"] == si]
        scenes.append({"i": si, "key": sc["key"], "model": sc["model"], "node": sc["node"],
                       "hud": sc["hud"], "toks": st})

    total = dur + TAIL
    for k, sc in enumerate(scenes):
        sc["start"] = 0.0 if k == 0 else max(0.0, sc["toks"][0]["t0"] - CUT_LEAD)
    for k, sc in enumerate(scenes):
        sc["end"] = scenes[k + 1]["start"] if k + 1 < len(scenes) else total

    n_frames = int(math.ceil(total * FPS))
    prev_f = -1
    for k, sc in enumerate(scenes):
        f0 = int(round(sc["start"] * FPS))
        if f0 <= prev_f:
            f0 = prev_f + 1
        sc["f0"] = f0
        prev_f = f0
    for k, sc in enumerate(scenes):
        nxt = scenes[k + 1]["f0"] if k + 1 < len(scenes) else n_frames
        sc["nframes"] = max(1, nxt - sc["f0"])

    out_scenes = []
    for si, sc in enumerate(scenes):
        anchors = {}
        for tk in sc["toks"]:
            anchors.setdefault(tk["norm"], tk["t0"])
        sc["anchors"] = anchors

        chunks = []
        raw = make_chunks(sc["toks"])
        for ci, ch in enumerate(raw):
            t0 = ch[0]["t0"]
            t1 = ch[-1]["t1"]
            if ci + 1 < len(raw):
                t1 = min(raw[ci + 1][0]["t0"], t1 + 0.30)
            else:
                t1 = min(sc["end"], t1 + 0.30)
            chunks.append({"t0": t0, "t1": max(t1, t0 + 0.2),
                           "words": [{"w": x["disp"].upper(), "hl": x["hl"]} for x in ch]})

        events = []
        for ev in SCENES[si]["events"]:
            e = dict(ev)
            a = resolve(ev["a"], sc)
            b = resolve(ev["b"], sc)
            if b < a + 0.4:
                b = a + 0.4
            e["a"], e["b"] = a, b
            events.append(e)
        hud = dict(sc["hud"])
        if "reveal" in hud:
            hud["reveal"] = resolve(hud["reveal"], sc)

        out_scenes.append({"i": si, "key": sc["key"], "model": sc["model"], "node": sc["node"],
                           "start": sc["start"], "end": sc["end"], "f0": sc["f0"],
                           "nframes": sc["nframes"], "hud": hud, "events": events, "chunks": chunks})

    return {"fps": FPS, "duration": total, "audio_duration": dur, "frames": n_frames,
            "scenes": out_scenes}


def proportional_timeline(dur):
    """Linha do tempo sem whisper (usada no teste rápido do HUD)."""
    return build_timeline(dur, None)


def make_matrix(tl):
    inc = []
    for sc in tl["scenes"]:
        s = 0
        while s < sc["nframes"]:
            e = min(sc["nframes"], s + CHUNK_FRAMES)
            inc.append({"scene": sc["i"], "start": s, "end": e, "count": e - s,
                        "tag": "s%02d_%05d" % (sc["i"], s)})
            s = e
    return {"include": inc}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", default="audio/narracao.mp3")
    ap.add_argument("--out", default="build/timeline.json")
    ap.add_argument("--no-whisper", action="store_true")
    a = ap.parse_args()

    dur = audio_duration(a.audio)
    print("duração do áudio: %.2f s" % dur)
    if dur > 62:
        print("::warning::O áudio tem mais de 1 minuto (%.1f s)." % dur)

    heard = None
    if not a.no_whisper:
        prompt = " ".join(s["text"].replace("*", "") for s in SCENES)
        try:
            heard = whisper_words(a.audio, prompt)
            print("whisper ouviu %d palavras" % len(heard))
        except Exception as ex:  # sem whisper: cai no tempo proporcional
            print("::warning::whisper falhou (%r); usando tempo proporcional" % (ex,))

    tl = build_timeline(dur, heard)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(tl, f, ensure_ascii=False, indent=1)

    matrix = make_matrix(tl)
    print("frames totais: %d | jobs de render: %d" % (tl["frames"], len(matrix["include"])))
    for sc in tl["scenes"]:
        print("  cena %d %-13s %6.2fs -> %6.2fs  (%d frames)" %
              (sc["i"], sc["key"], sc["start"], sc["end"], sc["nframes"]))
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a", encoding="utf-8") as f:
            f.write("matrix=" + json.dumps(matrix) + "\n")


if __name__ == "__main__":
    main()
