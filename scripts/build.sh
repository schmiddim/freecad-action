#!/usr/bin/env bash
# Central build script used by both Makefile and GitHub Action.
# Usage: scripts/build.sh [export|gallery|build]
#
# Environment variables:
#   DOCKER_IMAGE  - Docker image for FreeCAD export (default: ghcr.io/schmiddim/freecad-action:latest)
#   WORKSPACE     - Working directory mounted into Docker (default: current directory)
#   ACTION_PATH   - Path to the action repo (set automatically in GitHub Actions)

set -euo pipefail

DOCKER_IMAGE="${DOCKER_IMAGE:-ghcr.io/schmiddim/freecad-action:latest}"
WORKSPACE="${WORKSPACE:-$(pwd)}"

# Resolve script directory (for local dev) and ACTION_PATH (for CI)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ACTION_PATH="${ACTION_PATH:-$(dirname "$SCRIPT_DIR")}"

step_export() {
    echo "==> Pulling Docker image ${DOCKER_IMAGE}..."
    if ! docker pull "${DOCKER_IMAGE}" 2>/dev/null; then
        echo "==> Pull failed, building image locally..."
        docker build -t "${DOCKER_IMAGE}" "${ACTION_PATH}"
    fi

    echo "==> Exporting FCStd files to STL/STEP via Docker..."
    docker run --rm \
        -v "${WORKSPACE}:/workspace" \
        -v "${ACTION_PATH}/scripts:/action/scripts:ro" \
        "${DOCKER_IMAGE}" \
        /action/scripts/export.py
}

step_css() {
    # Find the scripts directory containing package.json
    local scripts_dir
    if [ -f "${WORKSPACE}/scripts/package.json" ]; then
        scripts_dir="${WORKSPACE}/scripts"
    elif [ -f "${ACTION_PATH}/scripts/package.json" ]; then
        scripts_dir="${ACTION_PATH}/scripts"
    else
        echo "==> No package.json found, skipping CSS build"
        return 0
    fi

    echo "==> Building Tailwind CSS via node:22-slim..."
    docker run --rm \
        -v "${scripts_dir}:/scripts" \
        -w /scripts \
        node:22-slim \
        sh -c "npm ci --no-audit --no-fund && npm run build:css"
}

step_gallery() {
    step_css

    echo "==> Building gallery HTML via ${DOCKER_IMAGE}..."
    docker run --rm \
        --entrypoint python \
        -v "${WORKSPACE}:/workspace" \
        -v "${ACTION_PATH}:/action:ro" \
        -e ACTION_PATH=/action \
        -e SEND_PING="${SEND_PING:-false}" \
        -e ACTION_REF="${ACTION_REF:-}" \
        -e GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}" \
        -e GITHUB_SERVER_URL="${GITHUB_SERVER_URL:-}" \
        -w /workspace \
        "${DOCKER_IMAGE}" \
        /action/scripts/build_gallery.py
}

case "${1:-build}" in
    export)
        step_export
        ;;
    gallery)
        step_gallery
        ;;
    build)
        step_export
        step_gallery
        ;;
    *)
        echo "Usage: $0 [export|gallery|build]"
        exit 1
        ;;
esac
