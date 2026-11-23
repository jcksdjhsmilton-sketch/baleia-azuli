# -*- coding: utf-8 -*-
"""
ROTEIRO DO VIDEO: "Evolução da BALEIA AZUL" (formato build / servidor)

- text   : narração (o que você cola no ElevenLabs). Palavras entre *asteriscos*
           ficam AMARELAS na legenda (os asteriscos não vão para a narração).
- model  : qual cena 3D o Blender monta.
- node   : posição na linha do tempo (0..4 = 50 / 49 / 40 / 28 mi / HOJE).
- hud    : painel do canto (nome, nível, barras, era).
- events : painéis que aparecem no vídeo. Ancoras de tempo:
             ("s", seg)         segundos depois do início da cena
             ("f", fração)      fração da duração da cena (0..1)
             ("w", palavra, s)  quando a narração fala essa palavra (+ s segundos)
             ("end", s)         fim da cena (+ s segundos)
"""

FPS = 30

# (milhões de anos atrás, rótulo)
TIMELINE_NODES = [(50, "50 MI"), (49, "49 MI"), (40, "40 MI"), (28, "28 MI"), (0, "HOJE")]

SCENES = [
    # ------------------------------------------------------------------ 0 GANCHO
    {
        "key": "intro",
        "model": "whale_intro",
        "text": "Você é uma baleia. A maior build do servidor. Até *cento e oitenta* toneladas. Mas ela começou assim.",
        "node": 4,
        "hud": {"name": "BALEIA AZUL", "lv": "LV.MAX", "hp": 1.0, "tam": 1.0, "era": "ATUAL"},
        "events": [
            {"kind": "chat", "a": ("s", 0.15), "b": ("end", 0.0), "title": "CHAT DO SERVIDOR",
             "lines": [("sys", "[SERVIDOR] BUILD NOVA: 180 TON", 0.0),
                       ("p", "ORCA_01: ISSO É UM SUBMARINO??", 1.0),
                       ("p", "TUBARAO_02: NERFA ESSA BUILD", 2.0)]},
        ],
    },
    # ------------------------------------------------------------------ 1 PAKICETUS
    {
        "key": "pakicetus",
        "model": "pakicetus",
        "text": "*Pakicetus:* cinquenta milhões de anos. Tamanho de lobo. "
                "Vive em terra, perto do rio. *Dica um:* vai gostar de água.",
        "node": 0,
        "hud": {"name": "PAKICETUS", "lv": "LV.1", "hp": 0.10, "tam": 0.04, "era": "EOCENO",
                "hidden_name": "??????", "hidden_lv": "LV.??", "reveal": ("w", "pakicetus", 0.0)},
        "events": [
            {"kind": "popup", "a": ("w", "pakicetus", 0.0), "b": ("w", "pakicetus", 2.4),
             "title": "NOVA BUILD REGISTRADA", "name": "PAKICETUS", "sub": "PARENTE ANTIGO DA BALEIA"},
            {"kind": "bubble", "a": ("w", "lobo", 0.0), "b": ("w", "lobo", 1.6), "text": "CACHORRO?"},
            {"kind": "panel", "a": ("w", "vive", -0.1), "b": ("w", "dica", -0.15),
             "title": "CRIAR BUILD // BALEIA",
             "rows": [("kv", "BASE", "MINI-LOBO"), ("bar", "TAMANHO", 0.03, "1 M"),
                      ("toggle", "PATAS", True), ("toggle", "NADADEIRA", False)]},
            {"kind": "hint", "a": ("w", "dica", 0.0), "b": ("end", 0.0), "n": 1,
             "text": "ELE VAI GOSTAR DE ÁGUA"},
        ],
    },
    # ------------------------------------------------------------------ 2 AMBULOCETUS
    {
        "key": "ambulocetus",
        "model": "ambulocetus",
        "text": "*Ambulocetus:* quarenta e nove milhões de anos. *Buff:* nadar. "
                "*Nerf:* lento na terra. Embosca igual jacaré. *Dica dois:* as pernas vão encolher.",
        "node": 1,
        "hud": {"name": "AMBULOCETUS", "lv": "LV.2", "hp": 0.28, "tam": 0.12, "era": "EOCENO"},
        "events": [
            {"kind": "popup", "a": ("w", "ambulocetus", 0.0), "b": ("w", "ambulocetus", 2.4),
             "title": "NOVA BUILD REGISTRADA", "name": "AMBULOCETUS", "sub": "A BALEIA QUE ANDA"},
            {"kind": "panel", "a": ("w", "buff", -0.1), "b": ("w", "embosca", -0.1),
             "title": "PATCH 1.1",
             "rows": [("bul", "+ NADAR", "good"), ("bul", "+ EMBOSCADA", "good"),
                      ("bul", "- LENTO NA TERRA", "bad")]},
            {"kind": "bubble", "a": ("w", "embosca", 0.2), "b": ("w", "embosca", 1.8), "text": "JACARÉ?"},
            {"kind": "hint", "a": ("w", "dica", 0.0), "b": ("end", 0.0), "n": 2,
             "text": "AS PERNAS VÃO ENCOLHER"},
        ],
    },
    # ------------------------------------------------------------------ 3 BASILOSAURUS
    {
        "key": "basilosaurus",
        "model": "basilosaurus",
        "text": "*Basilosaurus:* quarenta milhões de anos. Até *dezoito* metros. "
                "*Buff:* oceano inteiro. *Nerf:* perna inútil. *Dica três:* os dentes vão virar um pente.",
        "node": 2,
        "hud": {"name": "BASILOSAURUS", "lv": "LV.3", "hp": 0.55, "tam": 0.55, "era": "EOCENO"},
        "events": [
            {"kind": "popup", "a": ("w", "basilosaurus", 0.0), "b": ("w", "basilosaurus", 2.4),
             "title": "NOVA BUILD REGISTRADA", "name": "BASILOSAURUS", "sub": "SERPENTE DO OCEANO"},
            {"kind": "bubble", "a": ("w", "dezoito", 0.0), "b": ("w", "dezoito", 1.6), "text": "COBRA?"},
            {"kind": "panel", "a": ("w", "buff", -0.1), "b": ("w", "dica", -0.15),
             "title": "PATCH 1.2",
             "rows": [("bul", "+ OCEANO INTEIRO", "good"), ("bul", "+ ATÉ 18 METROS", "good"),
                      ("bul", "- PERNA INÚTIL", "bad")]},
            {"kind": "hint", "a": ("w", "dica", 0.0), "b": ("end", 0.0), "n": 3,
             "text": "OS DENTES VÃO VIRAR UM PENTE"},
        ],
    },
    # ------------------------------------------------------------------ 4 AETIOCETUS
    {
        "key": "aetiocetus",
        "model": "aetiocetus",
        "text": "*Aetiocetus:* vinte e oito milhões de anos. Dente e começo de barbatana. "
                "Meio caçador, meio filtro.",
        "node": 3,
        "hud": {"name": "AETIOCETUS", "lv": "LV.4", "hp": 0.70, "tam": 0.22, "era": "OLIGOCENO"},
        "events": [
            {"kind": "popup", "a": ("w", "aetiocetus", 0.0), "b": ("w", "aetiocetus", 2.4),
             "title": "NOVA BUILD REGISTRADA", "name": "AETIOCETUS", "sub": "DENTE + PENTE"},
            {"kind": "panel", "a": ("w", "dente", 0.0), "b": ("end", 0.0),
             "title": "PATCH 1.3",
             "rows": [("bul", "+ COMEÇO DE BARBATANA", "good"), ("bul", "+ CAÇA E FILTRA", "good"),
                      ("bul", "- TAMANHO", "bad")]},
        ],
    },
    # ------------------------------------------------------------------ 5 BALEIA AZUL
    {
        "key": "baleia_azul",
        "model": "blue_whale",
        "text": "*Baleia azul:* hoje. Até *trinta* metros. Até *cento e oitenta* toneladas. "
                "Come quatro toneladas de krill por dia. Parente vivo mais próximo: o hipopótamo. Você é a baleia azul.",
        "node": 4,
        "hud": {"name": "BALEIA AZUL", "lv": "LV.5", "hp": 1.0, "tam": 1.0, "era": "ATUAL"},
        "events": [
            {"kind": "popup", "a": ("w", "baleia", 0.0), "b": ("w", "baleia", 2.4),
             "title": "BUILD FINAL", "name": "BALEIA AZUL", "sub": "A MAIOR DE TODAS"},
            {"kind": "panel", "a": ("w", "trinta", -0.1), "b": ("w", "parente", -0.1),
             "title": "STATUS // BALEIA AZUL",
             "rows": [("bar", "TAMANHO", 1.0, "30 M"), ("bar", "PESO", 1.0, "180 TON"),
                      ("bar", "KRILL POR DIA", 0.8, "4 TON")]},
            {"kind": "bubble", "a": ("w", "hipopotamo", 0.0), "b": ("end", 0.0), "text": "HIPOPÓTAMO??"},
        ],
    },
]


def narration_text():
    """Texto limpo para colar no ElevenLabs (sem os asteriscos)."""
    return "\n\n".join(s["text"].replace("*", "") for s in SCENES)


if __name__ == "__main__":
    print(narration_text())
