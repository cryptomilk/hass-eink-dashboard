#!/usr/bin/env bash
# Build a distributable tar.gz of the eink_dashboard custom component.
#
# What this script does:
#   1. Generate weather icon PNGs from SVG sources (requires cairosvg)
#   2. Download Roboto-Regular.ttf (Apache 2.0) into the component's fonts/ dir
#   3. Package custom_components/eink_dashboard/ into dist/eink_dashboard-<version>.tar.gz
#   4. Clean up generated icons and font from the working tree
#
# Usage:
#   pip install cairosvg
#   bash scripts/build_dist.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${0}")/.." && pwd)"
COMPONENT_DIR="${REPO_ROOT}/custom_components/eink_dashboard"
ICONS_DIR="${COMPONENT_DIR}/icons"
FONTS_DIR="${COMPONENT_DIR}/fonts"
DIST_DIR="${REPO_ROOT}/dist"

VERSION=$(python3 -c "import json; print(json.load(open('${COMPONENT_DIR}/manifest.json'))['version'])")
ARCHIVE="${DIST_DIR}/eink_dashboard-${VERSION}.tar.gz"

ROBOTO_URL="https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Regular.ttf"

cleanup() {
    echo "Cleaning up generated assets..."
    rm -rf "${ICONS_DIR}"
}
trap cleanup EXIT

echo "==> Building icons..."
python3 "${REPO_ROOT}/scripts/build_icons.py"

mkdir -p "${FONTS_DIR}"
if [ -f "${FONTS_DIR}/Roboto-Regular.ttf" ]; then
    echo "==> Roboto-Regular.ttf already exists, skipping download"
else
    echo "==> Downloading Roboto-Regular.ttf (Apache 2.0)..."
    curl -fsSL "${ROBOTO_URL}" -o "${FONTS_DIR}/Roboto-Regular.ttf"
fi

echo "==> Creating ${ARCHIVE}..."
mkdir -p "${DIST_DIR}"
tar czf "${ARCHIVE}" \
    --exclude="eink_dashboard/__pycache__" \
    --exclude="eink_dashboard/**/__pycache__" \
    -C "${REPO_ROOT}/custom_components" eink_dashboard

echo "Done: ${ARCHIVE}"
