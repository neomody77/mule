#!/bin/bash
# Deploy Mule to server
# Usage: ./scripts/deploy.sh
#
# This script:
# 1. Pulls latest code from git
# 2. Generates build info (version, commit, timestamp)
# 3. Builds Flutter web client
# 4. Copies build output to static/ directory
# 5. Generates version.json for API endpoint (after copy to avoid Flutter overwrite)
# 6. Restarts the mule service via pm2

set -e

cd "$(dirname "$0")/.."

echo "=== Mule Deployment ==="
echo ""

# Step 1: Pull latest code
echo "[1/5] Pulling latest code..."
git pull

# Step 2: Generate build info for Flutter
echo "[2/5] Generating build info..."
./scripts/update_build_info.sh

# Step 3: Build Flutter web
echo "[3/5] Building Flutter web client..."
cd client
flutter build web --no-wasm-dry-run
cd ..

# Step 4: Copy to static directory
echo "[4/5] Copying build to static/..."
cp -r client/build/web/* static/

# Step 5: Generate version.json (after copy to avoid Flutter overwrite)
echo "[5/5] Generating version.json..."
VERSION="1.0.0"
BUILD_TIME=$(date "+%Y-%m-%d %H:%M:00")
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
cat > "static/version.json" << JSON
{"version":"$VERSION","buildTime":"$BUILD_TIME","gitCommit":"$GIT_COMMIT"}
JSON

# Step 6: Restart service
echo ""
echo "Restarting mule service..."
pm2 restart mule

echo ""
echo "=== Deployment Complete ==="
echo "Version: v$VERSION ($GIT_COMMIT)"
echo "Build time: $BUILD_TIME"
