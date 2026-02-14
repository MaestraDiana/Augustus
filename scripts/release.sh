#!/usr/bin/env bash
# Release script for Augustus
# Usage: ./scripts/release.sh 0.6.0
#
# Bumps electron/package.json version, commits, tags, and pushes.
# The CI workflow triggers on the v* tag and builds all platforms.

set -euo pipefail

VERSION="${1:-}"

if [ -z "$VERSION" ]; then
  echo "Usage: ./scripts/release.sh <version>"
  echo "Example: ./scripts/release.sh 0.6.0"
  exit 1
fi

# Strip leading 'v' if provided
VERSION="${VERSION#v}"
TAG="v${VERSION}"

# Validate semver-ish format
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+'; then
  echo "Error: Version must be semver format (e.g., 0.6.0)"
  exit 1
fi

# Check for clean working tree
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Error: Working tree is not clean. Commit or stash changes first."
  exit 1
fi

# Check tag doesn't already exist
if git tag -l "$TAG" | grep -q "$TAG"; then
  echo "Error: Tag $TAG already exists."
  exit 1
fi

# Read current version
CURRENT=$(node -p "require('./electron/package.json').version")
echo "Current version: $CURRENT"
echo "New version:     $VERSION"
echo "Tag:             $TAG"
echo ""

# Bump version in electron/package.json
node -e "
const fs = require('fs');
const pkg = JSON.parse(fs.readFileSync('./electron/package.json', 'utf8'));
pkg.version = '${VERSION}';
fs.writeFileSync('./electron/package.json', JSON.stringify(pkg, null, 4) + '\n');
"

# Commit, tag, push
git add electron/package.json
git commit -m "Bump version to ${VERSION} for release"
git tag "$TAG"
git push origin main "$TAG"

echo ""
echo "Release $TAG pushed. CI build will start automatically."
echo "Monitor at: https://github.com/TheFeloniousMonk/Augustus/actions"
