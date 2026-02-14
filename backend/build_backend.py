"""Build script for PyInstaller backend bundling."""
import subprocess
import sys
from pathlib import Path


def build():
    """Run PyInstaller to bundle the Augustus backend."""
    backend_dir = Path(__file__).parent
    spec_file = backend_dir / "augustus.spec"

    if not spec_file.exists():
        print(f"Error: spec file not found at {spec_file}")
        sys.exit(1)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(spec_file),
        "--clean",
        "--noconfirm",
    ]

    print(f"Building Augustus backend with PyInstaller...")
    print(f"Working directory: {backend_dir}")
    result = subprocess.run(cmd, cwd=str(backend_dir))

    if result.returncode != 0:
        print("PyInstaller build failed!")
        sys.exit(result.returncode)

    # Verify output exists
    import platform
    exe_name = "augustus.exe" if platform.system() == "Windows" else "augustus"
    output = backend_dir / "dist" / "augustus" / exe_name
    if output.exists():
        print(f"Build successful! Output: {output}")
    else:
        print(f"Warning: Expected output not found at {output}")
        print("Check the dist/ directory for output.")


if __name__ == "__main__":
    build()
