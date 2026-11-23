#!/usr/bin/env bash
# Fontes pixel/HUD (se falhar, o compose usa DejaVu como reserva).
mkdir -p assets/fonts
B="https://github.com/google/fonts/raw/main/ofl"
curl -fsSL -o assets/fonts/PressStart2P.ttf "$B/pressstart2p/PressStart2P-Regular.ttf" || echo "aviso: fonte pixel indisponivel"
curl -fsSL -o assets/fonts/ShareTechMono.ttf "$B/sharetechmono/ShareTechMono-Regular.ttf" || echo "aviso: fonte HUD indisponivel"
exit 0
