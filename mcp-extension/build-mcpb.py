"""Build script for Augustus .mcpb Desktop Extension.

Produces a platform-specific .mcpb file (zip archive) containing:
  - manifest.json
  - icon.png
  - server/augustus/  (PyInstaller frozen binary)

Usage:
    python mcp-extension/build-mcpb.py          # build from project root
    python build-mcpb.py                        # build from mcp-extension/

Requires the PyInstaller backend to be built first (backend/dist/augustus/).
Pass --build-backend to run PyInstaller automatically.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def get_platform_tag() -> str:
    """Return platform tag for the .mcpb filename."""
    system = platform.system().lower()
    if system == "windows":
        return "win32"
    elif system == "darwin":
        return "darwin"
    else:
        return "linux"


def build_backend(project_root: Path) -> None:
    """Run the existing PyInstaller build for the backend."""
    build_script = project_root / "backend" / "build_backend.py"
    if not build_script.exists():
        print(f"Error: backend build script not found at {build_script}")
        sys.exit(1)

    print("Building backend with PyInstaller...")
    result = subprocess.run(
        [sys.executable, str(build_script)],
        cwd=str(project_root / "backend"),
    )
    if result.returncode != 0:
        print("Backend build failed!")
        sys.exit(result.returncode)


def build_mcpb(project_root: Path, run_backend_build: bool = False) -> Path:
    """Build the .mcpb Desktop Extension archive."""
    ext_dir = project_root / "mcp-extension"
    manifest_path = ext_dir / "manifest.json"
    icon_src = project_root / "icons" / "augustus-icon-512.png"
    backend_dist = project_root / "backend" / "dist" / "augustus"

    # Validate inputs
    if not manifest_path.exists():
        print(f"Error: manifest.json not found at {manifest_path}")
        sys.exit(1)

    if run_backend_build:
        build_backend(project_root)

    if not backend_dist.exists():
        print(f"Error: PyInstaller output not found at {backend_dist}")
        print("Run 'python backend/build_backend.py' first, or pass --build-backend.")
        sys.exit(1)

    # Verify the binary exists
    exe_name = "augustus.exe" if platform.system() == "Windows" else "augustus"
    binary_path = backend_dist / exe_name
    if not binary_path.exists():
        print(f"Error: Binary not found at {binary_path}")
        sys.exit(1)

    # Read manifest for version
    with open(manifest_path) as f:
        manifest = json.load(f)
    version = manifest.get("version", "0.0.0")

    # Staging directory
    staging = ext_dir / "staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()

    # Copy manifest
    shutil.copy2(manifest_path, staging / "manifest.json")

    # Copy icon
    if icon_src.exists():
        shutil.copy2(icon_src, staging / "icon.png")
    else:
        print(f"Warning: Icon not found at {icon_src}, skipping.")

    # Copy server binary (entire PyInstaller output directory)
    server_dest = staging / "server" / "augustus"
    print(f"Copying PyInstaller output to staging ({backend_dist})...")
    shutil.copytree(backend_dist, server_dest)

    # Create .mcpb archive
    plat = get_platform_tag()
    mcpb_name = f"augustus-mcp-{version}-{plat}.mcpb"
    mcpb_path = ext_dir / mcpb_name

    print(f"Creating {mcpb_name}...")
    with zipfile.ZipFile(mcpb_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in staging.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(staging)
                zf.write(file_path, arcname)

    # Clean up staging
    shutil.rmtree(staging)

    # Report
    size_mb = mcpb_path.stat().st_size / (1024 * 1024)
    print(f"Built: {mcpb_path}")
    print(f"Size:  {size_mb:.1f} MB")
    return mcpb_path


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Build Augustus .mcpb Desktop Extension")
    parser.add_argument(
        "--build-backend",
        action="store_true",
        help="Run PyInstaller backend build before packaging",
    )
    args = parser.parse_args()

    # Resolve project root (works from project root or mcp-extension/)
    cwd = Path.cwd()
    if (cwd / "mcp-extension" / "manifest.json").exists():
        project_root = cwd
    elif (cwd / "manifest.json").exists():
        project_root = cwd.parent
    else:
        print("Error: Run from project root or mcp-extension/ directory.")
        sys.exit(1)

    build_mcpb(project_root, run_backend_build=args.build_backend)


if __name__ == "__main__":
    main()
