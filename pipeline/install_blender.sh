#!/usr/bin/env bash
# Instala o Blender (cache em ~/blender) e exporta BLENDER_BIN para os próximos passos.
set -euo pipefail
V="${BLENDER_VERSION:-4.2.3}"; MM="${V%.*}"; DIR="$HOME/blender"
sudo apt-get update -y >/dev/null
sudo apt-get install -y libxi6 libxkbcommon0 libgl1 libxxf86vm1 libxfixes3 libxrender1 libsm6 libegl1 >/dev/null
if [ ! -x "$DIR/blender" ]; then
  mkdir -p "$DIR"
  if curl -fL --retry 3 -o /tmp/blender.tar.xz "https://download.blender.org/release/Blender${MM}/blender-${V}-linux-x64.tar.xz"; then
    tar -xf /tmp/blender.tar.xz -C "$DIR" --strip-components=1; rm -f /tmp/blender.tar.xz
  fi
fi
if [ -x "$DIR/blender" ]; then
  echo "BLENDER_BIN=$DIR/blender" >> "$GITHUB_ENV"; "$DIR/blender" --version | head -1
else
  sudo apt-get install -y blender >/dev/null
  echo "BLENDER_BIN=$(command -v blender)" >> "$GITHUB_ENV"; blender --version | head -1
fi
