#!/usr/bin/env bash
# Build a Docker image from Guix declarative configs
# Requires: guix-daemon running locally (sudo systemctl start guix-daemon)
#
# Usage:
#   ./scripts/build-guix-image.sh                    # build from manifest
#   ./scripts/build-guix-image.sh --system            # build full Guix System image
#   ./scripts/build-guix-image.sh --push ghcr.io/user/den  # build and push
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
GUIX_DIR="$PROJECT_DIR/guix"

MODE="pack"
PUSH_TARGET=""
IMAGE_NAME="den-guix"
IMAGE_TAG="latest"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --system) MODE="system"; shift ;;
        --push)   PUSH_TARGET="$2"; shift 2 ;;
        --tag)    IMAGE_TAG="$2"; shift 2 ;;
        *)        echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Check guix-daemon is running
if ! guix describe &>/dev/null 2>&1; then
    echo "Error: guix-daemon not running."
    echo "Start it with: sudo systemctl start guix-daemon"
    exit 1
fi

echo "==> Building den image (mode: $MODE)..."

if [ "$MODE" = "pack" ]; then
    # guix pack creates a relocatable Docker image from a manifest
    # This is faster and produces a minimal image with just your packages
    echo "==> Building with guix pack (manifest-based)..."

    IMAGE_FILE=$(guix time-machine -C "$GUIX_DIR/channels.scm" -- \
        pack -f docker \
        --symlink=/bin=bin \
        --symlink=/sbin=sbin \
        --symlink=/usr/bin=bin \
        --symlink=/etc/ssl=/etc/ssl \
        --manifest="$GUIX_DIR/manifest.scm" \
        --entry-point=bin/fish)

    echo "==> Image built: $IMAGE_FILE"
    echo "==> Loading into Docker..."
    IMAGE_ID=$(docker load < "$IMAGE_FILE" | grep -oP 'Loaded image: \K.*' || \
               docker load < "$IMAGE_FILE" | grep -oP 'sha256:\K[a-f0-9]+' | head -c 12)

    docker tag "$IMAGE_ID" "$IMAGE_NAME:$IMAGE_TAG" 2>/dev/null || \
        echo "==> Tag manually: docker tag <image-id> $IMAGE_NAME:$IMAGE_TAG"

elif [ "$MODE" = "system" ]; then
    # guix system image builds a complete Guix System Docker image
    # More complete but heavier — includes init system, guix-daemon, etc.
    echo "==> Building with guix system image (full OS)..."

    IMAGE_FILE=$(guix time-machine -C "$GUIX_DIR/channels.scm" -- \
        system image \
        --image-type=docker \
        "$GUIX_DIR/system.scm")

    echo "==> Image built: $IMAGE_FILE"
    echo "==> Loading into Docker..."
    docker load < "$IMAGE_FILE"
    docker tag "$(docker images -q | head -1)" "$IMAGE_NAME:$IMAGE_TAG"
fi

echo "==> Image ready: $IMAGE_NAME:$IMAGE_TAG"

# Push if requested
if [ -n "$PUSH_TARGET" ]; then
    FULL_TAG="$PUSH_TARGET:$IMAGE_TAG"
    echo "==> Pushing to $FULL_TAG..."
    docker tag "$IMAGE_NAME:$IMAGE_TAG" "$FULL_TAG"
    docker push "$FULL_TAG"
    echo "==> Pushed: $FULL_TAG"
    echo ""
    echo "Deploy to Railway with:"
    echo "  railway deploy --image $FULL_TAG"
fi
