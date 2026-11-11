#!/usr/bin/env bash
# Build both plugin packages into dist/ with the Dify plugin CLI (`dify` on PATH, or DIFY_CLI=/path/to/dify).
set -euo pipefail
cd "$(dirname "$0")/.."
DIFY="${DIFY_CLI:-dify}"
mkdir -p dist
for plugin in models/wiro tools/wiro_media; do
  name="$(awk '/^name:/ {print $2; exit}' "$plugin/manifest.yaml")"
  version="$(awk '/^version:/ {print $2; exit}' "$plugin/manifest.yaml")"
  "$DIFY" plugin package "$plugin" -o "dist/${name}-${version}.difypkg"
done
ls -l dist
