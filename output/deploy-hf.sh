#!/bin/bash
# ==========================================
# OpenCrew — Deploy to Hugging Face Spaces
# ==========================================

set -e

echo ""
echo "========================================"
echo "  OpenCrew — Hugging Face Spaces Deploy"
echo "========================================"
echo ""

# Check if HF CLI is installed
if ! command -v huggingface-cli &> /dev/null; then
    echo "[ERROR] Hugging Face CLI not found!"
    echo "Install it with: pip install huggingface_hub"
    exit 1
fi

# Check if logged in
echo "[1/5] Checking HF login..."
if ! huggingface-cli whoami &> /dev/null; then
    echo "[ERROR] Not logged in. Run: huggingface-cli login"
    exit 1
fi

echo ""
echo "[2/5] Preparing files..."

# Create temp directory for HF Space
TEMP_DIR=$(mktemp -d)
rm -rf "$TEMP_DIR"
mkdir -p "$TEMP_DIR"

# Copy necessary files
cp Dockerfile.hf "$TEMP_DIR/Dockerfile"
cp supervisord.conf "$TEMP_DIR/"
cp start.sh "$TEMP_DIR/"
cp README_hf.md "$TEMP_DIR/README.md"
cp .gitignore "$TEMP_DIR/"

# Copy directories
cp -r shared "$TEMP_DIR/"
cp -r agents "$TEMP_DIR/"
cp -r web "$TEMP_DIR/"

echo ""
echo "[3/5] Files prepared in: $TEMP_DIR"
echo ""

# Ask for Space name
read -p "Enter your HF Space name (e.g., Binh151412/opencrew): " SPACE_NAME

echo ""
echo "[4/5] Uploading to HF Space: $SPACE_NAME"
echo ""

# Upload files using huggingface-cli
cd "$TEMP_DIR"

# Initialize git repo
git init
git add .
git commit -m "Initial OpenCrew deployment"

# Add HF remote
git remote add origin "https://huggingface.co/spaces/$SPACE_NAME"

# Push to HF
echo "Pushing to Hugging Face..."
git push --force origin main

echo ""
echo "[5/5] Deploy complete!"
echo ""
echo "========================================"
echo "  Your Space: https://huggingface.co/spaces/$SPACE_NAME"
echo "========================================"
echo ""
echo "IMPORTANT: Set these environment variables in Space Settings:"
echo "  - MIMO_API_KEY (required)"
echo "  - MIMO_BASE_URL (optional)"
echo "  - GITHUB_TOKEN (optional)"
echo ""
