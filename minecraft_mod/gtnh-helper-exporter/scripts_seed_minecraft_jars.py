#!/usr/bin/env python3
"""Seed local Gradle cache with Minecraft 1.7.10 client/server jars.

ForgeGradle 1.2 tries to download from retired S3 URLs. This script pulls the
current Mojang-hosted artifacts from launchermeta and writes them to the paths
ForgeGradle expects so legacy builds can proceed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.request import urlopen

MANIFEST_URL = "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
TARGET_VERSION = "1.7.10"


def fetch_json(url: str) -> dict:
    with urlopen(url) as r:  # nosec B310 - controlled Mojang URL
        return json.loads(r.read().decode("utf-8"))


def download_bytes(url: str) -> bytes:
    with urlopen(url) as r:  # nosec B310 - controlled Mojang URL
        return r.read()


def sha1_hex(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def resolve_version_metadata() -> dict:
    manifest = fetch_json(MANIFEST_URL)
    for entry in manifest.get("versions", []):
        if entry.get("id") == TARGET_VERSION:
            return fetch_json(entry["url"])
    raise RuntimeError(f"Could not find Minecraft version {TARGET_VERSION} in manifest")


def artifact_targets(home: Path) -> dict[str, Path]:
    return {
        "client": home
        / ".gradle/caches/minecraft/net/minecraft/minecraft/1.7.10/minecraft-1.7.10.jar",
        "server": home
        / ".gradle/caches/minecraft/net/minecraft/server/minecraft_server/1.7.10/minecraft_server-1.7.10.jar",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--home",
        default=str(Path.home()),
        help="Home directory where .gradle cache exists (default: current user home)",
    )
    args = parser.parse_args()

    home = Path(os.path.expanduser(args.home)).resolve()
    version_meta = resolve_version_metadata()
    downloads = version_meta.get("downloads", {})
    targets = artifact_targets(home)

    for kind in ("client", "server"):
        if kind not in downloads:
            raise RuntimeError(f"Missing {kind} download metadata for {TARGET_VERSION}")
        info = downloads[kind]
        payload = download_bytes(info["url"])
        actual_sha = sha1_hex(payload)
        expected_sha = info.get("sha1")
        if expected_sha and actual_sha != expected_sha:
            raise RuntimeError(
                f"SHA1 mismatch for {kind}: expected {expected_sha}, got {actual_sha}"
            )

        out = targets[kind]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(payload)
        print(f"Wrote {kind} jar: {out}")

    print("Done. Re-run: gradle clean build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
