#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS_DIR="$SCRIPT_DIR/.tools"
GRADLE_VERSION="2.14.1"
GRADLE_DIR="$TOOLS_DIR/gradle-$GRADLE_VERSION"
ZIP_PATH="$TOOLS_DIR/gradle-$GRADLE_VERSION-bin.zip"

mkdir -p "$TOOLS_DIR"

if [[ ! -x "$GRADLE_DIR/bin/gradle" ]]; then
  echo "Downloading Gradle $GRADLE_VERSION..."
  curl -fL "https://services.gradle.org/distributions/gradle-$GRADLE_VERSION-bin.zip" -o "$ZIP_PATH"
  unzip -q -o "$ZIP_PATH" -d "$TOOLS_DIR"
fi

exec "$GRADLE_DIR/bin/gradle" "$@"
