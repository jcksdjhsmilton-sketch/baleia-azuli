# -*- coding: utf-8 -*-
"""
Passo final: pega o vídeo 3D (sem interface), desenha HUD azul + legendas + linha do tempo
em cada frame e junta com a narração.   python compose.py --timeline ... --video ... --audio ... --out ...
Teste rápido do HUD (sem Blender):       python compose.py --selftest
"""
import argparse
import json
import math
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from roteiro import TIMELINE_NODES  # noqa: E402

W, H = 1080, 1920
BLUE = (47, 143, 255)
BLUE_L = (127, 200, 255)
YEL = (255, 204, 51)
RED = (255, 107, 94)
WHITE = (255, 255, 255)
GOOD = (111, 211, 255)
PAD = 6

_FC = {}


def F(kind, size):
    size = int(size)
    key = (kind, size)
    if key in _FC:
        return _FC[key]
    name = {"px": "PressStart2P.ttf", "ui": "ShareTechMono.ttf"}[kind]
    cands = [os.path.join(ROOT, "assets", "fonts", name),
             "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    font = None
    for p in cands:
        if os.path.exists(p):
            try:
                font = ImageFont.truetype(p, size)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()
    _FC[key] = font
    return font


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease(x):
    x = clamp(x)
    return 1.0 - (1.0 - x) ** 3


def put(ov, im, x, y, a=1.0):
    if a <= 0.01:
        return
    if a < 1.0:
        al = im.getchannel("A").point(lambda p: int(p * a))
        im = im.copy()
        im.putalpha(al)
    ov.alpha_composite(im, (max(0, int(x)), max(0, int(y))))


def base_panel(w, h, border=BLUE):
    im = Image.new("RGBA", (w + 2 * PAD, h + 2 * PAD), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([PAD, PAD, PAD + w, PAD + h], fill=(8, 22, 44, 215), outline=border + (255,), width=2)
    for (cx, cy) in ((PAD, PAD), (PAD + w, PAD), (PAD, PAD + h), (PAD + w, PAD + h)):
        d.rectangle([cx - 4, cy - 4, cx + 4, cy + 4], fill=BLUE_L + (255,))
    return im, d


RH = {"kv": 40, "bar": 62, "toggle": 42, "bul": 40, "txt": 36}


def mk_panel(title, rows, w=940, prog=1.0, rtitle=None):
    h = 56 + sum(RH[r[0]] for r in rows) + 14
    im, d = base_panel(w, h)
    x0, y = PAD + 22, PAD + 14
    d.text((x0, y), title, font=F("ui", 22), fill=BLUE_L + (255,))
    d.text((PAD + w - 28, y), rtitle or "x", font=F("ui", 22), fill=BLUE_L + (255,), anchor="ra")
    y = PAD + 56
    xr = PAD + w - 24
    for r in rows:
        k = r[0]
        if k == "kv":
            d.text((x0, y), r[1] + ":", font=F("ui", 26), fill=BLUE_L + (255,))
            d.text((xr, y), r[2], font=F("ui", 26), fill=WHITE + (255,), anchor="ra")
        elif k == "bar":
            d.text((x0, y), r[1], font=F("ui", 24), fill=BLUE_L + (255,))
            d.text((xr, y), r[3], font=F("ui", 24), fill=WHITE + (255,), anchor="ra")
            bx0, bx1, by = x0, xr, y + 34
            d.rectangle([bx0, by, bx1, by + 10], fill=(18, 48, 79, 255))
            fw = int((bx1 - bx0) * clamp(r[2] * ease(prog)))
            if fw > 0:
                d.rectangle([bx0, by, bx0 + fw, by + 10], fill=BLUE + (255,))
        elif k == "toggle":
            d.text((x0, y), r[1], font=F("ui", 26), fill=WHITE + (255,))
            on = bool(r[2])
            d.rectangle([xr - 74, y - 2, xr, y + 32], fill=(BLUE if on else (20, 40, 66)) + (255,),
                        outline=BLUE_L + (255,), width=2)
            d.text((xr - 37, y + 15), "ON" if on else "OFF", font=F("ui", 22),
                   fill=(WHITE if on else (120, 150, 190)) + (255,), anchor="mm")
        elif k == "bul":
            col = {"good": GOOD, "bad": RED}.get(r[2], WHITE)
            d.text((x0, y), r[1], font=F("ui", 28), fill=col + (255,))
        elif k == "txt":
            d.text((x0, y), r[1], font=F("ui", 26), fill=(YEL if len(r) > 2 and r[2] == "yellow" else WHITE) + (255,))
        y += RH[k]
    return im


def mk_chat(title, lines, u):
    w, h = 940, 56 + 3 * 40 + 14
    im, d = base_panel(w, h)
    d.text((PAD + 22, PAD + 14), title, font=F("ui", 22), fill=BLUE_L + (255,))
    d.text((PAD + w - 28, PAD + 14), "x", font=F("ui", 22), fill=BLUE_L + (255,), anchor="ra")
    y = PAD + 56
    for (kind, text, dt) in lines:
        if u >= dt:
            d.text((PAD + 22, y), text, font=F("ui", 26), fill=(RED if kind == "sys" else WHITE) + (255,))
        y += 40
    return im


def mk_hint(n, text):
    w, h = 940, 150
    im, d = base_panel(w, h)
    d.text((PAD + 22, PAD + 14), "O QUE ELE VAI VIRAR?", font=F("ui", 24), fill=BLUE_L + (255,))
    d.text((PAD + w - 24, PAD + 14), "DICA %d/3" % n, font=F("ui", 24), fill=YEL + (255,), anchor="ra")
    for i in range(3):
        x = PAD + 22 + i * 34
        d.rectangle([x, PAD + 54, x + 24, PAD + 74], fill=(BLUE if i < n else (18, 48, 79)) + (255,),
                    outline=BLUE_L + (255,), width=2)
    d.text((PAD + 22, PAD + 96), text, font=F("ui", 32), fill=WHITE + (255,))
    return im


def mk_popup(title, name, sub):
    w, h = 760, 190
    im, d = base_panel(w, h)
    cx = PAD + w // 2
    d.text((cx, PAD + 28), title, font=F("ui", 22), fill=BLUE_L + (255,), anchor="mm")
    size = min(40, int((w - 60) / max(1, len(name))))
    d.text((cx, PAD + 90), name, font=F("px", size), fill=WHITE + (255,), anchor="mm")
    d.text((cx, PAD + 150), sub, font=F("ui", 26), fill=YEL + (255,), anchor="mm")
    return im


def mk_bubble(text):
    size = 30
    tw = int(ImageDraw.Draw(Image.new("RGBA", (4, 4))).textlength(text, font=F("px", size)))
    w, h = tw + 44, 74
    im = Image.new("RGBA", (w + 2 * PAD, h + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([PAD, PAD, PAD + w, PAD + h], fill=YEL + (255,), outline=(20, 20, 20, 255), width=4)
    d.polygon([(PAD + 40, PAD + h), (PAD + 78, PAD + h), (PAD + 44, PAD + h + 30)], fill=YEL + (255,))
    d.text((PAD + w // 2, PAD + h // 2), text, font=F("px", size), fill=(20, 20, 20, 255), anchor="mm")
    return im


def draw_subtitle(ov, chunk, u):
    words = chunk["words"]
    text = " ".join(x["w"] for x in words)
    base = min(64, int(960 / max(1, len(text))))
    size = int(base * (1.0 + 0.14 * (1.0 - clamp(u / 0.09))))
    font = F("px", size)
    d = ImageDraw.Draw(ov)
    widths = [d.textlength(x["w"] + " ", font=font) for x in words]
    total = sum(widths) - d.textlength(" ", font=font)
    x = (W - total) / 2.0
    y = 1235
    for wd, wi in zip(words, widths):
        d.text((x, y), wd["w"], font=font, fill=(YEL if wd["hl"] else WHITE) + (255,),
               stroke_width=8, stroke_fill=(0, 0, 0, 255), anchor="lm")
        x += wi


def node_x(i):
    return 130 + i * (820.0 / (len(TIMELINE_NODES) - 1))


def draw_timeline(ov, tl, sc, t):
    d = ImageDraw.Draw(ov)
    idx = sc["i"]
    prev = tl["scenes"][idx - 1]["node"] if idx > 0 else sc["node"]
    p = ease((t - sc["start"]) / 0.8) if idx > 0 else 1.0
    pos = prev + (sc["node"] - prev) * p
    my = TIMELINE_NODES[prev][0] + (TIMELINE_NODES[sc["node"]][0] - TIMELINE_NODES[prev][0]) * p
    label = "AGORA" if my < 0.5 else "HÁ %d MILHÕES DE ANOS" % int(round(my))
    d.text((W // 2, 1500), label, font=F("ui", 26), fill=BLUE_L + (230,), anchor="mm")
    y = 1565
    d.line([(node_x(0), y), (node_x(len(TIMELINE_NODES) - 1), y)], fill=(30, 70, 120, 255), width=4)
    mx = node_x(0) + (node_x(len(TIMELINE_NODES) - 1) - node_x(0)) * pos / (len(TIMELINE_NODES) - 1)
    d.line([(node_x(0), y), (mx, y)], fill=BLUE + (255,), width=4)
    for i, (_m, lab) in enumerate(TIMELINE_NODES):
        x = node_x(i)
        done = x <= mx + 1
        d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=(BLUE if done else (14, 34, 60)) + (255,),
                  outline=BLUE_L + (255,), width=2)
        d.text((x, y + 34), lab, font=F("ui", 20), fill=BLUE_L + (210,), anchor="mm")
    d.ellipse([mx - 17, y - 17, mx + 17, y + 17], fill=(200, 235, 255, 255), outline=BLUE + (255,), width=4)


def hud_values(tl, sc, t):
    h = sc["hud"]
    name, lv = h["name"], h["lv"]
    if "reveal" in h and t < h["reveal"]:
        name, lv = h.get("hidden_name", name), h.get("hidden_lv", lv)
    idx = sc["i"]
    p = ease((t - sc["start"]) / 0.8) if idx > 0 else 1.0
    ph = tl["scenes"][idx - 1]["hud"] if idx > 0 else h
    hp = ph["hp"] + (h["hp"] - ph["hp"]) * p
    tam = ph["tam"] + (h["tam"] - ph["tam"]) * p
    return name, lv, hp, tam, h["era"]


def draw_top(ov, tl, sc, t):
    name, lv, hp, tam, era = hud_values(tl, sc, t)
    im, d = base_panel(540, 118)
    d.text((PAD + 20, PAD + 12), name, font=F("ui", 32), fill=WHITE + (255,))
    d.text((PAD + 520, PAD + 12), lv, font=F("ui", 30), fill=YEL + (255,), anchor="ra")
    for k, (lab, v) in enumerate((("HP", hp), ("TAM", tam))):
        y = PAD + 62 + k * 26
        d.text((PAD + 20, y - 4), lab, font=F("ui", 18), fill=BLUE_L + (255,))
        d.rectangle([PAD + 84, y, PAD + 520, y + 12], fill=(18, 48, 79, 255))
        fw = int(436 * clamp(v))
        if fw > 0:
            d.rectangle([PAD + 84, y, PAD + 84 + fw, y + 12], fill=BLUE + (255,))
    put(ov, im, 34, 28)
    im2, d2 = base_panel(400, 66)
    d2.text((PAD + 200, PAD + 33), "ERA: " + era, font=F("ui", 30), fill=WHITE + (255,), anchor="mm")
    put(ov, im2, 630, 28)


def draw_events(ov, sc, t):
    for ev in sc["events"]:
        a, b = ev["a"], ev["b"]
        if not (a <= t < b):
            continue
        u = t - a
        al = min(clamp(u / 0.18), clamp((b - t) / 0.18))
        slide = (1.0 - ease(u / 0.25)) * 26
        k = ev["kind"]
        if k == "chat":
            put(ov, mk_chat(ev["title"], ev["lines"], u), 64, 190 + slide, al)
        elif k == "panel":
            put(ov, mk_panel(ev["title"], [tuple(r) for r in ev["rows"]], prog=u / 0.8), 64, 190 + slide, al)
        elif k == "hint":
            put(ov, mk_hint(ev["n"], ev["text"]), 64, 190 + slide, al)
        elif k == "popup":
            put(ov, mk_popup(ev["title"], ev["name"], ev["sub"]), 140, 200 + slide, al)
        elif k == "bubble":
            put(ov, mk_bubble(ev["text"]), 640, 800 - slide, al)


def draw_hud(ov, tl, t):
    sc = tl["scenes"][-1]
    for s in tl["scenes"]:
        if s["start"] <= t < s["end"]:
            sc = s
            break
    draw_top(ov, tl, sc, t)
    draw_events(ov, sc, t)
    draw_timeline(ov, tl, sc, t)
    for ch in sc["chunks"]:
        if ch["t0"] <= t < ch["t1"]:
            draw_subtitle(ov, ch, t - ch["t0"])
            break


def frame_image(base, tl, t):
    img = base.resize((W, H), Image.LANCZOS).convert("RGBA")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_hud(ov, tl, t)
    img.alpha_composite(ov)
    return img


def selftest():
    from prepare import proportional_timeline
    tl = proportional_timeline(58.0)
    base = Image.new("RGB", (720, 1280))
    px = base.load()
    for y in range(1280):
        for x in range(0, 720, 8):
            c = (40 + y // 12, 120 + y // 20, 200 - y // 14)
            for k in range(8):
                px[x + k, y] = c
    os.makedirs("smoke", exist_ok=True)
    times = [sc["start"] + 0.5 * (sc["end"] - sc["start"]) for sc in tl["scenes"]]
    sheet = Image.new("RGB", (270 * len(times), 480))
    for i, t in enumerate(times):
        sheet.paste(frame_image(base, tl, t).convert("RGB").resize((270, 480)), (270 * i, 0))
    sheet.save("smoke/hud_test.png")
    print("HUD OK:", len(times), "cenas desenhadas")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeline", default="build/timeline.json")
    ap.add_argument("--video", default="build/raw3d.mp4")
    ap.add_argument("--audio", default="audio/narracao.mp3")
    ap.add_argument("--out", default="out/baleia_azul.mp4")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return
    with open(a.timeline, "r", encoding="utf-8") as fh:
        tl = json.load(fh)
    fps = tl["fps"]
    n = tl["frames"]
    pr = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                  "stream=width,height", "-of", "csv=p=0", a.video]).decode().strip().split(",")
    rw, rh = int(pr[0]), int(pr[1])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", a.video, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                            "%dx%d" % (W, H), "-r", str(fps), "-i", "-", "-i", a.audio, "-af", "apad",
                            "-shortest", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                            a.out], stdin=subprocess.PIPE)
    size = rw * rh * 3
    last = None
    for i in range(n):
        buf = dec.stdout.read(size)
        if len(buf) == size:
            last = Image.frombytes("RGB", (rw, rh), buf)
        elif last is None:
            raise SystemExit("vídeo 3D vazio")
        enc.stdin.write(frame_image(last, tl, i / float(fps)).convert("RGB").tobytes())
        if i % 150 == 0:
            print("frame %d/%d" % (i, n), flush=True)
    enc.stdin.close()
    enc.wait()
    dec.terminate()
    print("pronto:", a.out)


if __name__ == "__main__":
    main()
