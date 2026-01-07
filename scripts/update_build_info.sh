#!/bin/bash
# Update build info before flutter build
# Usage: ./scripts/update_build_info.sh

cd "$(dirname "$0")/.."

BUILD_INFO_FILE="client/lib/config/build_info.dart"
VERSION="1.0.0"
BUILD_TIME=$(date "+%Y-%m-%d %H:%M:00")
GIT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

cat > "$BUILD_INFO_FILE" << DART
// Auto-generated build info - DO NOT EDIT
// This file is updated by scripts/update_build_info.sh before each build

class BuildInfo {
  static const String version = "$VERSION";
  static const String buildTime = "$BUILD_TIME";
  static const String gitCommit = "$GIT_COMMIT";
}
DART

# Also generate JSON file for API endpoint
BUILD_INFO_JSON="static/version.json"
mkdir -p static
cat > "$BUILD_INFO_JSON" << JSON
{"version":"$VERSION","buildTime":"$BUILD_TIME","gitCommit":"$GIT_COMMIT"}
JSON

echo "Updated build info: v$VERSION ($GIT_COMMIT) @ $BUILD_TIME"
