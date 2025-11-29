#!/usr/bin/env python3
"""
Update PDF.js viewer files from npm.

Usage:
    python scripts/update_pdfjs.py [version]

Examples:
    python scripts/update_pdfjs.py          # Uses default version
    python scripts/update_pdfjs.py 4.2.67   # Specific version

This script downloads pdfjs-dist from npm and extracts only the
essential files needed for the document viewer.
"""

import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

# Default version - update this when upgrading
DEFAULT_VERSION = "4.0.379"

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
PDFJS_DIR = PROJECT_ROOT / "static" / "pdfjs"


def run_command(cmd, cwd=None):
    """Run a shell command and return output."""
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error running: {cmd}")
        print(result.stderr)
        sys.exit(1)
    return result.stdout.strip()


def update_pdfjs(version):
    """Download and install PDF.js files."""
    print(f"Updating PDF.js to version {version}...")

    # Create temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Download from npm
        print("Downloading pdfjs-dist from npm...")
        run_command(f"npm pack pdfjs-dist@{version}", cwd=tmpdir)

        # Find the tarball
        tarballs = list(tmpdir.glob("pdfjs-dist-*.tgz"))
        if not tarballs:
            print("Error: Could not find downloaded package")
            sys.exit(1)

        # Extract
        print("Extracting package...")
        with tarfile.open(tarballs[0], "r:gz") as tar:
            tar.extractall(tmpdir)

        package_dir = tmpdir / "package"

        # Backup custom viewer.html if it exists
        custom_viewer = PDFJS_DIR / "web" / "viewer.html"
        viewer_backup = None
        if custom_viewer.exists():
            print("Backing up custom viewer.html...")
            viewer_backup = tmpdir / "viewer.html.backup"
            shutil.copy2(custom_viewer, viewer_backup)

        # Create fresh pdfjs directory structure
        print("Installing files...")
        for subdir in ["build", "web", "web/images", "cmaps", "standard_fonts"]:
            (PDFJS_DIR / subdir).mkdir(parents=True, exist_ok=True)

        # Copy essential files
        files_to_copy = [
            ("build/pdf.mjs", "build/pdf.js"),
            ("build/pdf.worker.mjs", "build/pdf.worker.js"),
            ("web/pdf_viewer.mjs", "web/pdf_viewer.js"),
            ("web/pdf_viewer.css", "web/pdf_viewer.css"),
        ]

        for src, dst in files_to_copy:
            src_path = package_dir / src
            dst_path = PDFJS_DIR / dst
            if src_path.exists():
                shutil.copy2(src_path, dst_path)
                print(f"  Copied {dst}")
            else:
                print(f"  Warning: {src} not found")

        # Copy images directory
        src_images = package_dir / "web" / "images"
        dst_images = PDFJS_DIR / "web" / "images"
        if src_images.exists():
            shutil.rmtree(dst_images, ignore_errors=True)
            shutil.copytree(src_images, dst_images)
            print("  Copied web/images/")

        # Copy cmaps
        src_cmaps = package_dir / "cmaps"
        dst_cmaps = PDFJS_DIR / "cmaps"
        if src_cmaps.exists():
            shutil.rmtree(dst_cmaps, ignore_errors=True)
            shutil.copytree(src_cmaps, dst_cmaps)
            print("  Copied cmaps/")

        # Copy standard_fonts
        src_fonts = package_dir / "standard_fonts"
        dst_fonts = PDFJS_DIR / "standard_fonts"
        if src_fonts.exists():
            shutil.rmtree(dst_fonts, ignore_errors=True)
            shutil.copytree(src_fonts, dst_fonts)
            print("  Copied standard_fonts/")

        # Restore custom viewer.html
        if viewer_backup and viewer_backup.exists():
            print("Restoring custom viewer.html...")
            shutil.copy2(viewer_backup, custom_viewer)
        else:
            print("Warning: No custom viewer.html found. You may need to create one.")

    print(f"\nPDF.js {version} installed successfully!")
    print(f"Location: {PDFJS_DIR}")

    # Show disk usage
    total_size = sum(f.stat().st_size for f in PDFJS_DIR.rglob("*") if f.is_file())
    print(f"Total size: {total_size / 1024 / 1024:.1f} MB")


def main():
    version = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VERSION
    update_pdfjs(version)


if __name__ == "__main__":
    main()
