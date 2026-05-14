#!/usr/bin/env bash
# Build a distributable tar.gz of the eink_dashboard custom component.
#
# What this script does:
#   1. Build the frontend TypeScript bundle
#   2. Package custom_components/eink_dashboard/ into dist/eink_dashboard-<version>.tar.gz
#   3. Optionally produce dist/eink_dashboard.zip for HACS zip_release
#   4. Clean up the generated frontend JS bundle
#
# Usage:
#   bash scripts/build_dist.sh            # build both tar.gz and zip (default)
#   bash scripts/build_dist.sh --zip      # zip only
#   bash scripts/build_dist.sh --tarball  # tar.gz only

set -euo pipefail

BUILD_TARBALL=true
BUILD_ZIP=true
for arg in "$@"; do
    case "${arg}" in
        --zip)     BUILD_TARBALL=false; BUILD_ZIP=true ;;
        --tarball) BUILD_TARBALL=true;  BUILD_ZIP=false ;;
        *) echo "Unknown argument: ${arg}"; exit 1 ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "${0}")/.." && pwd)"
COMPONENT_DIR="${REPO_ROOT}/custom_components/eink_dashboard"
DIST_DIR="${REPO_ROOT}/dist"

VERSION=$(python3 -c "import json; print(json.load(open('${COMPONENT_DIR}/manifest.json'))['version'])")
ARCHIVE="${DIST_DIR}/eink_dashboard-${VERSION}.tar.gz"

FRONTEND_DIR="${COMPONENT_DIR}/frontend"

cleanup() {
    echo "Cleaning up generated assets..."
    rm -f "${FRONTEND_DIR}/eink-dashboard-card.js" "${FRONTEND_DIR}/eink-dashboard-card.js.map"
    rm -f "${FRONTEND_DIR}/eink-dashboard-editor.js" "${FRONTEND_DIR}/eink-dashboard-editor.js.map"
}
trap cleanup EXIT

echo "==> Building frontend TypeScript..."
(cd "${FRONTEND_DIR}" && pnpm install --frozen-lockfile && pnpm build)

mkdir -p "${DIST_DIR}"

if [ "${BUILD_TARBALL}" = "true" ]; then
    echo "==> Creating ${ARCHIVE}..."
    tar czf "${ARCHIVE}" \
        --exclude="eink_dashboard/__pycache__" \
        --exclude="eink_dashboard/**/__pycache__" \
        --exclude="eink_dashboard/frontend/src" \
        --exclude="eink_dashboard/frontend/test" \
        --exclude="eink_dashboard/frontend/node_modules" \
        --exclude="eink_dashboard/frontend/package.json" \
        --exclude="eink_dashboard/frontend/pnpm-lock.yaml" \
        --exclude="eink_dashboard/frontend/pnpm-workspace.yaml" \
        --exclude="eink_dashboard/frontend/tsconfig.json" \
        --exclude="eink_dashboard/frontend/vitest.config.ts" \
        -C "${REPO_ROOT}/custom_components" eink_dashboard
    echo "Done: ${ARCHIVE}"
fi

if [ "${BUILD_ZIP}" = "true" ]; then
    ZIP="${DIST_DIR}/eink_dashboard.zip"
    echo "==> Creating ${ZIP}..."
    (cd "${COMPONENT_DIR}" && zip -r "${ZIP}" . \
        --exclude "*/__pycache__/*" \
        --exclude "__pycache__/*" \
        --exclude "frontend/src/*" \
        --exclude "frontend/test/*" \
        --exclude "frontend/node_modules/*" \
        --exclude "frontend/package.json" \
        --exclude "frontend/pnpm-lock.yaml" \
        --exclude "frontend/pnpm-workspace.yaml" \
        --exclude "frontend/tsconfig.json" \
        --exclude "frontend/vitest.config.ts")
    echo "Done: ${ZIP}"
fi
