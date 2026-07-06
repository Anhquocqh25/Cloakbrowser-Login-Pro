from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


REPOSITORY = "https://github.com/Anhquocqh25/Cloakbrowser-Login-Pro"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--notes", default="Stability and user experience improvements.")
    args = parser.parse_args()
    version = args.version.strip().lstrip("v")
    root = args.release_root.resolve()
    portable = root / f"CloakBrowser-Login-{version}-Windows.zip"
    installer = root / f"CloakBrowser-Login-Pro-Setup-{version}-Windows.exe"
    if not portable.is_file() or not installer.is_file():
        raise SystemExit("Portable or installer artifact is missing.")
    base = f"{REPOSITORY}/releases/download/v{version}"
    payload = {
        "version": version,
        "notes": args.notes,
        "portable_url": f"{base}/{portable.name}",
        "portable_sha256": sha256(portable),
        "installer_url": f"{base}/{installer.name}",
        "installer_sha256": sha256(installer),
    }
    manifest = root / "latest.json"
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    notes = root / f"CHANGELOG-{version}.md"
    notes.write_text(f"# CloakBrowser Login Pro {version}\n\n{args.notes}\n", encoding="utf-8")
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
