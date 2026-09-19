#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diff_images.py -- re-runnable provenance check for the re-tagged train-ticket images in Harbor.

Question answered
-----------------
Five train-ticket services run in the cluster with a tag other than 1.0.0 (1.0.1 / 1.0.2).
What exactly differs between those images and the 1.0.0 image of the same repository
(application classes, resources, dependency jars, image config), and was a fault injected?

Method (read-only; anonymous pull tokens are kept in memory only and never written anywhere)
---------------------------------------------------------------------------------------------
 1. inventory : list every ts-* repository / tag of the Harbor project with push time and digest.
 2. resolve   : tag -> OCI image index -> linux/amd64 manifest (buildx attestation entries skipped);
                fetch the image config and the buildx SLSA provenance attestation, if present.
 3. layers    : compare the ordered layer digest lists; download only layers above the common prefix
                (sha256-verified cache) and build a file-level view (path -> sha256/size/mode) of them.
 4. jars      : compare the application fat jar entry by entry (CRC32 + size); classify changes into
                classes / resources / dependency jars / Spring Boot loader / META-INF / other, and
                recurse one level into dependency jars whose bytes changed (e.g. ts-common).
 5. javap     : for every changed / added / removed class run `javap -c -p -constants -l` on both sides,
                strip constant-pool indices, split into members and report added / removed / changed
                members, plus an offset-independent instruction diff of each changed method annotated
                with source line numbers (e.g. "+ invokestatic # // Method java/lang/Thread.sleep:(J)V").
 6. upstream  : (--upstream-compile) compile the upstream sources (commit 313886e9) of ts-common and of
                the service with the local javac 8, using the image's own BOOT-INF/lib as classpath,
                and compare every class of the image with the compiled upstream class
                (byte-identical, identical after javap normalisation, or different -> member diff).

Outputs (under --workdir)
-------------------------
  blobs/sha256/<hex>                                verified blob cache (layers, configs, attestations)
  inventory/harbor_ts_tags.json | .txt              ts-* repository / tag / push time / digest table
  images/<repo>/<tag>/meta.json                     index / manifest / config / attestation summary
  images/<repo>/<tag>/files/L<i>/<path>             regular files extracted from layers above the prefix
  pairs/<repo>/<old>__<new>/summary.json            structured diff of one pair
  pairs/<repo>/<old>__<new>/report.txt              human-readable diff of one pair
  pairs/<repo>/<old>__<new>/javap/<class>.diff      full normalised javap diff per changed class
  upstream/<repo>/<tag>/report.txt | summary.json   upstream-source vs image comparison
  summary.txt                                       roll-up of all pairs (and upstream checks)

Usage
-----
  python3 diff_images.py                          # default pairs, no upstream compile
  python3 diff_images.py --upstream-compile       # additionally compare every image with upstream source
  python3 diff_images.py --pair ts-preserve-service:1.0.0-fix2:1.0.0 --skip-inventory
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import difflib
import hashlib
import io
import json
import posixpath
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------------------------------

HARBOR_BASE_URL: str = "http://1.94.151.57:85"
HARBOR_PROJECT: str = "train-ticket"

DEFAULT_WORKDIR: Path = Path(
    "/private/tmp/claude-501/-Users-mymz-work---------------benchmark/"
    "f5792d23-0738-4486-bf81-4963e2a42d30/scratchpad/rebuilt-images"
)
DEFAULT_UPSTREAM_DIR: Path = Path(
    "/Users/mymz/work/国家重点研发/韧性测试工具 benchmark/benchmark-sources/train-ticket-upstream"
)

# (repository, old tag, new tag).  The first pair of each repository is what the cluster runs.
DEFAULT_COMPARISON_PAIRS: List[Tuple[str, str, str]] = [
    ("ts-order-service", "1.0.0", "1.0.1"),
    ("ts-payment-service", "1.0.0", "1.0.2"),
    ("ts-payment-service", "1.0.0", "1.0.1"),
    ("ts-payment-service", "1.0.1", "1.0.2"),
    ("ts-order-other-service", "1.0.0", "1.0.2"),
    ("ts-order-other-service", "1.0.0", "1.0.1"),
    ("ts-order-other-service", "1.0.1", "1.0.2"),
    ("ts-consign-price-service", "1.0.0", "1.0.1"),
    ("ts-station-food-service", "1.0.0", "1.0.1"),
]

# ts-travel-service: every 2026 push in Harbor, oldest first (tags move, so untagged pushes are pinned by
# digest; the tagged ones are listed by tag and their digest is recorded in meta.json at run time).
TRAVEL_SERVICE_LINEAGE: List[str] = [
    "sha256:a7917c2637c3b4fe1b8276dcd5a73883c5a05cad09757a03b87ebc9e6cda2a3a",  # 2026-03-15T10:02 untagged
    "sha256:0c34a311d5fc7358ae05b5be7a29056c857bd67a7c05128eb8a99169643ffca3",  # 2026-03-16T02:55 untagged
    "sha256:eaecd65e92fe1ab47e20eaa303731d8f5057ea1f7be3024784386cc65be581d2",  # 2026-03-16T03:09 untagged
    "sha256:5b4f04a2192ab9aea6c19a806285dc7f74b16cec3d09adfed33d0b4d65bcfc45",  # 2026-03-16T03:20 untagged
    "sha256:561a808a5b3fe867ef4b910ee7b09674e24c86c6d8b0518654db5e1d41ef2b6c",  # 2026-03-16T04:08 untagged
    "1.0.1",  # 2026-03-16T04:09  sha256:9db2dbbdb6c3…
    "1.0.2",  # 2026-03-16T07:12  sha256:f2895a4570b3…
    "sha256:9264562df0bccf3249c26460c189f899e6f406e74427ad4b88d835500ba48c28",  # 2026-03-17T14:57 untagged
    "sha256:10b918e0062c4994ee5c6ff19786957d28ba98d70391ef80541a1cf2dde7e63a",  # 2026-03-23T08:13 untagged
    "1.0.0",  # 2026-03-23T08:16  sha256:7d4a3481466e… (what the cluster runs)
]
DEFAULT_COMPARISON_PAIRS += [
    ("ts-travel-service", TRAVEL_SERVICE_LINEAGE[0], "1.0.0"),  # earliest 03-15 push vs current 1.0.0
    ("ts-travel-service", "1.0.2", "1.0.0"),
] + [
    ("ts-travel-service", older, newer)  # every consecutive push, to date each change
    for older, newer in zip(TRAVEL_SERVICE_LINEAGE, TRAVEL_SERVICE_LINEAGE[1:])
]

MANIFEST_ACCEPT_HEADER: str = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    ]
)
INDEX_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}

# Image-config keys whose change could alter runtime behaviour.
RUNTIME_CONFIG_KEYS: Tuple[str, ...] = (
    "Env", "Entrypoint", "Cmd", "ExposedPorts", "WorkingDir", "User", "Volumes",
    "Labels", "StopSignal", "Healthcheck", "OnBuild", "Shell",
)

JAVAP_FLAGS: Tuple[str, ...] = ("-c", "-p", "-constants", "-l")
TEXT_RESOURCE_SUFFIXES: Tuple[str, ...] = (
    ".yml", ".yaml", ".properties", ".xml", ".json", ".txt", ".sql", ".conf", ".MF", ".factories",
    ".imports", ".html", ".js", ".css", ".sh", ".list", ".idx",
)
SECRET_KEY_PATTERN = re.compile(r"pass|secret|token|cred|auth|key", re.IGNORECASE)

# Report size caps, so that a pathological pair cannot produce megabytes of text.
MAX_LISTED_PATHS: int = 200
MAX_INSTRUCTION_DIFF_LINES: int = 80
MAX_RESOURCE_DIFF_LINES: int = 200


# --------------------------------------------------------------------------------------------------
# Registry / Harbor access (read-only)
# --------------------------------------------------------------------------------------------------

RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


def with_retries(operation, description: str, attempts: int = 6):
    """Run operation(); retry transient network / 5xx failures with exponential backoff (Harbor
    occasionally answers 502 on the token endpoint)."""
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except urllib.error.HTTPError as error:
            if error.code not in RETRYABLE_HTTP_CODES or attempt == attempts:
                raise
            reason = f"HTTP {error.code}"
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as error:
            if attempt == attempts:
                raise
            reason = type(error).__name__
        wait_seconds = 2 ** attempt
        print(f"  retry {attempt}/{attempts - 1} for {description} after {reason}; waiting {wait_seconds}s", flush=True)
        time.sleep(wait_seconds)
    raise RuntimeError("unreachable")

class RegistryClient:
    """Minimal read-only Docker Registry v2 client for a public Harbor project.

    Anonymous pull tokens are fetched per repository and held in memory only.
    Blobs are cached on disk by digest and verified against their sha256 on download.
    """

    def __init__(self, base_url: str, project: str, blob_cache_dir: Path) -> None:
        self.base_url: str = base_url.rstrip("/")
        self.project: str = project
        self.blob_cache_dir: Path = blob_cache_dir
        self.blob_cache_dir.mkdir(parents=True, exist_ok=True)
        self._pull_tokens: Dict[str, str] = {}

    def _fetch_pull_token(self, repository: str) -> str:
        """Obtain an anonymous pull token for one repository (kept in memory only)."""
        query = urllib.parse.urlencode(
            {"service": "harbor-registry", "scope": f"repository:{self.project}/{repository}:pull"}
        )

        def fetch() -> str:
            with urllib.request.urlopen(f"{self.base_url}/service/token?{query}", timeout=30) as response:
                return json.load(response)["token"]

        token: str = with_retries(fetch, f"pull token {repository}")
        self._pull_tokens[repository] = token
        return token

    def _open(self, repository: str, path: str, accept: Optional[str] = None):
        """Open a registry v2 URL; refresh the anonymous token once if the registry answers 401."""
        for attempt in range(2):
            token = self._pull_tokens.get(repository) or self._fetch_pull_token(repository)
            headers = {"Authorization": f"Bearer {token}"}
            if accept:
                headers["Accept"] = accept
            request = urllib.request.Request(
                f"{self.base_url}/v2/{self.project}/{repository}/{path}", headers=headers
            )
            try:
                return with_retries(
                    lambda: urllib.request.urlopen(request, timeout=300), f"{repository}/{path[:40]}"
                )
            except urllib.error.HTTPError as error:
                if error.code == 401 and attempt == 0:
                    self._pull_tokens.pop(repository, None)
                    continue
                raise
        raise RuntimeError("unreachable")

    def get_manifest(self, repository: str, reference: str) -> Tuple[Dict[str, Any], str, str]:
        """Return (manifest JSON, sha256 digest of the raw bytes, media type)."""
        with self._open(repository, f"manifests/{reference}", MANIFEST_ACCEPT_HEADER) as response:
            raw_bytes = response.read()
            header_media_type = response.headers.get("Content-Type", "")
        computed_digest = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
        if reference.startswith("sha256:") and computed_digest != reference:
            raise ValueError(f"manifest digest mismatch for {repository}@{reference}")
        manifest = json.loads(raw_bytes)
        return manifest, computed_digest, manifest.get("mediaType") or header_media_type

    def get_blob_path(self, repository: str, digest: str) -> Path:
        """Download a blob into the verified cache (if not cached yet) and return its path."""
        algorithm, hex_digest = digest.split(":", 1)
        cached_path = self.blob_cache_dir / algorithm / hex_digest
        if cached_path.exists():
            return cached_path
        cached_path.parent.mkdir(parents=True, exist_ok=True)
        partial_path = cached_path.with_name(hex_digest + ".partial")

        def download() -> None:
            hasher = hashlib.sha256()
            with self._open(repository, f"blobs/{digest}") as response, open(partial_path, "wb") as output:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    hasher.update(chunk)
                    output.write(chunk)
            if hasher.hexdigest() != hex_digest:  # truncated transfer -> retried as a network error
                partial_path.unlink()
                raise ConnectionError(f"blob digest mismatch for {repository}@{digest}")

        with_retries(download, f"blob {digest[:19]}", attempts=4)
        partial_path.rename(cached_path)
        return cached_path

    def get_blob_json(self, repository: str, digest: str) -> Any:
        return json.loads(self.get_blob_path(repository, digest).read_bytes())


def harbor_api_paginated(base_url: str, api_path: str, page_size: int = 100) -> List[Dict[str, Any]]:
    """GET a paginated Harbor v2.0 API collection (anonymous; public project)."""
    collected: List[Dict[str, Any]] = []
    page_number = 1
    while True:
        separator = "&" if "?" in api_path else "?"
        url = f"{base_url}/api/v2.0/{api_path}{separator}page_size={page_size}&page={page_number}"

        def fetch_page() -> Tuple[List[Dict[str, Any]], int]:
            with urllib.request.urlopen(url, timeout=60) as response:
                return json.load(response), int(response.headers.get("X-Total-Count") or 0)

        batch, total_count = with_retries(fetch_page, f"harbor api {api_path[:60]}")
        collected.extend(batch)
        if not batch or len(collected) >= total_count:
            return collected
        page_number += 1


# --------------------------------------------------------------------------------------------------
# Step 1: inventory
# --------------------------------------------------------------------------------------------------

def build_inventory(workdir: Path) -> List[Dict[str, Any]]:
    """List every ts-* repository and its tags (push time, digest) and save json + txt tables."""
    repositories = harbor_api_paginated(HARBOR_BASE_URL, f"projects/{HARBOR_PROJECT}/repositories")
    rows: List[Dict[str, Any]] = []
    for repository in sorted(repositories, key=lambda item: item["name"]):
        short_name = repository["name"].split("/", 1)[1]
        if not short_name.startswith("ts-"):
            continue
        artifacts = harbor_api_paginated(
            HARBOR_BASE_URL,
            f"projects/{HARBOR_PROJECT}/repositories/{urllib.parse.quote(short_name, safe='')}"
            f"/artifacts?with_tag=true",
        )
        for artifact in artifacts:
            # Untagged artifacts (earlier pushes whose tag moved away) are kept with tag "<untagged>".
            for tag in artifact.get("tags") or [{"name": "<untagged>", "push_time": None}]:
                rows.append(
                    {
                        "repository": short_name,
                        "tag": tag["name"],
                        "tag_push_time": tag.get("push_time"),
                        "artifact_push_time": artifact.get("push_time"),
                        "digest": artifact.get("digest"),
                        "media_type": artifact.get("manifest_media_type"),
                        "size": artifact.get("size"),
                    }
                )
    inventory_dir = workdir / "inventory"
    inventory_dir.mkdir(parents=True, exist_ok=True)
    (inventory_dir / "harbor_ts_tags.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    lines = [f"{'repository':42s} {'tag':14s} {'artifact_push_time':20s} {'tag_push_time':20s} digest"]
    for row in sorted(rows, key=lambda item: (item["repository"], item["artifact_push_time"] or "")):
        lines.append(
            f"{row['repository']:42s} {row['tag']:14s} {(row['artifact_push_time'] or '')[:19]:20s} "
            f"{(row['tag_push_time'] or '')[:19]:20s} {row['digest']}"
        )
    (inventory_dir / "harbor_ts_tags.txt").write_text("\n".join(lines) + "\n")
    return rows


# --------------------------------------------------------------------------------------------------
# Step 2: resolve a tag into manifest / config / attestation
# --------------------------------------------------------------------------------------------------

def redact_secrets(value: Any) -> Any:
    """Recursively replace values whose key looks like a credential (defensive; build args may carry them)."""
    if isinstance(value, dict):
        return {
            key: ("<redacted>" if SECRET_KEY_PATTERN.search(str(key)) and isinstance(item, str) else redact_secrets(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def summarize_attestation(statement: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the parts of an in-toto statement that matter for provenance (no LLB dump)."""
    predicate = statement.get("predicate") or {}
    metadata = dict(predicate.get("metadata") or {})
    buildkit_metadata = metadata.pop("https://mobyproject.org/buildkit@v1#metadata", None)
    summary: Dict[str, Any] = {
        "predicateType": statement.get("predicateType"),
        "subject": statement.get("subject"),
        "buildType": predicate.get("buildType"),
        "builder": predicate.get("builder"),
        "invocation": redact_secrets(predicate.get("invocation")),
        "materials": predicate.get("materials"),
        "metadata": metadata,
        "has_buildConfig": "buildConfig" in predicate,
    }
    if isinstance(buildkit_metadata, dict):
        summary["buildkit_metadata_keys"] = sorted(buildkit_metadata.keys())
        summary["buildkit_vcs"] = buildkit_metadata.get("vcs")
    return summary


def safe_reference(reference: str) -> str:
    """Tag or digest -> directory-name-safe string ('sha256:abcd…' -> 'sha256_abcd…')."""
    return reference.replace(":", "_")


def parse_pair_argument(text: str) -> Tuple[str, str, str]:
    """'repo:old:new' where old/new are tags or full 'sha256:<64 hex>' digests."""
    reference = r"(?:sha256:[0-9a-f]{64}|[^:]+)"
    match = re.fullmatch(rf"(?P<repo>[^:]+):(?P<old>{reference}):(?P<new>{reference})", text)
    if not match:
        raise argparse.ArgumentTypeError(f"--pair must be repo:old:new, got {text!r}")
    return match.group("repo"), match.group("old"), match.group("new")


def resolve_image(client: RegistryClient, repository: str, tag: str, workdir: Path) -> Dict[str, Any]:
    """Resolve repository:tag to its linux/amd64 image manifest, config and provenance; save meta.json."""
    top_manifest, top_digest, top_media_type = client.get_manifest(repository, tag)
    image: Dict[str, Any] = {
        "repository": repository,
        "tag": tag,
        "top_digest": top_digest,
        "top_media_type": top_media_type,
        "index_entries": [],
    }
    attestation_entries: List[Dict[str, Any]] = []
    image["platform"] = "linux/amd64"
    if top_media_type in INDEX_MEDIA_TYPES:
        platform_manifest_digest: Optional[str] = None
        fallback_entry: Optional[Dict[str, Any]] = None
        for entry in top_manifest.get("manifests", []):
            platform = entry.get("platform") or {}
            annotations = entry.get("annotations") or {}
            image["index_entries"].append(
                {
                    "digest": entry["digest"],
                    "platform": f"{platform.get('os')}/{platform.get('architecture')}",
                    "reference_type": annotations.get("vnd.docker.reference.type"),
                }
            )
            if annotations.get("vnd.docker.reference.type") == "attestation-manifest":
                attestation_entries.append(entry)
                continue
            fallback_entry = fallback_entry or entry
            if platform.get("os") == "linux" and platform.get("architecture") == "amd64":
                platform_manifest_digest = platform_manifest_digest or entry["digest"]
        if platform_manifest_digest is None:
            # Some ts-travel-service pushes of 2026-03-16 are arm64-only.  The application jar is
            # platform independent, so it is still compared; base layers then differ by construction.
            if fallback_entry is None:
                raise RuntimeError(f"{repository}:{tag} has no image manifest")
            platform = fallback_entry.get("platform") or {}
            image["platform"] = f"{platform.get('os')}/{platform.get('architecture')}"
            platform_manifest_digest = fallback_entry["digest"]
        image_manifest, image_manifest_digest, _ = client.get_manifest(repository, platform_manifest_digest)
    else:
        image_manifest, image_manifest_digest = top_manifest, top_digest

    config_digest = image_manifest["config"]["digest"]
    config = client.get_blob_json(repository, config_digest)
    layer_history = [item for item in config.get("history", []) if not item.get("empty_layer")]
    layers: List[Dict[str, Any]] = []
    for index, layer in enumerate(image_manifest["layers"]):
        history_item = layer_history[index] if index < len(layer_history) else {}
        layers.append(
            {
                "index": index,
                "digest": layer["digest"],
                "size": layer["size"],
                "media_type": layer["mediaType"],
                "created": history_item.get("created"),
                "created_by": history_item.get("created_by"),
            }
        )

    attestations: List[Dict[str, Any]] = []
    for entry in attestation_entries:
        if (entry.get("annotations") or {}).get("vnd.docker.reference.digest") != image_manifest_digest:
            continue
        attestation_manifest, attestation_digest, _ = client.get_manifest(repository, entry["digest"])
        for layer in attestation_manifest.get("layers", []):
            statement = client.get_blob_json(repository, layer["digest"])
            attestations.append(
                {
                    "attestation_manifest": attestation_digest,
                    "blob": layer["digest"],
                    "predicate_type": (layer.get("annotations") or {}).get("in-toto.io/predicate-type"),
                    "summary": summarize_attestation(statement),
                }
            )

    image.update(
        {
            "manifest_digest": image_manifest_digest,
            "config_digest": config_digest,
            "config": config,
            "layers": layers,
            "attestations": attestations,
        }
    )
    image_dir = workdir / "images" / repository / safe_reference(tag)
    image_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / "meta.json").write_text(json.dumps(image, indent=1, ensure_ascii=False))
    return image


# --------------------------------------------------------------------------------------------------
# Step 3: layer comparison and file-level view
# --------------------------------------------------------------------------------------------------

def compare_layer_lists(old_image: Dict[str, Any], new_image: Dict[str, Any]) -> Dict[str, Any]:
    """Compare ordered layer digests; everything above the common prefix is 'differing'."""
    old_digests = [layer["digest"] for layer in old_image["layers"]]
    new_digests = [layer["digest"] for layer in new_image["layers"]]
    common_prefix = 0
    while (
        common_prefix < min(len(old_digests), len(new_digests))
        and old_digests[common_prefix] == new_digests[common_prefix]
    ):
        common_prefix += 1
    return {
        "identical": old_digests == new_digests,
        "old_layer_count": len(old_digests),
        "new_layer_count": len(new_digests),
        "common_prefix_length": common_prefix,
        "old_above_prefix": old_image["layers"][common_prefix:],
        "new_above_prefix": new_image["layers"][common_prefix:],
    }


def normalize_tar_path(member_name: str) -> str:
    """'./app/x.jar' -> '/app/x.jar' (keeps leading dots of real file names such as '.bashrc')."""
    name = member_name
    while name.startswith("./"):
        name = name[2:]
    name = name.lstrip("/").rstrip("/")
    return "/" + name if name else "/"


def is_safe_relative_path(path: str) -> bool:
    return ".." not in Path(path.lstrip("/")).parts


def build_layer_view(layer_blob: Path, extract_root: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    """Read one gzip'd layer tar sequentially; return path -> metadata and optionally extract regular files."""
    view: Dict[str, Dict[str, Any]] = {}
    with tarfile.open(layer_blob, mode="r:*") as archive:
        for member in archive:
            path = normalize_tar_path(member.name)
            directory, base_name = posixpath.split(path)
            if base_name == ".wh..wh..opq":
                view[posixpath.join(directory, "<opaque-whiteout>")] = {"type": "opaque-whiteout"}
                continue
            if base_name.startswith(".wh."):
                view[posixpath.join(directory, base_name[4:])] = {"type": "whiteout"}
                continue
            entry: Dict[str, Any] = {
                "type": (
                    "file" if member.isfile() else "dir" if member.isdir() else "symlink" if member.issym()
                    else "hardlink" if member.islnk() else "other"
                ),
                "mode": oct(member.mode & 0o7777),
                "uid": member.uid,
                "gid": member.gid,
                "mtime": member.mtime,
            }
            if member.isfile():
                hasher = hashlib.sha256()
                data_stream = archive.extractfile(member)
                output_handle = None
                if extract_root is not None and is_safe_relative_path(path):
                    target_path = extract_root / path.lstrip("/")
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    output_handle = open(target_path, "wb")
                    entry["extracted_to"] = str(target_path)
                try:
                    while data_stream is not None:
                        chunk = data_stream.read(1 << 20)
                        if not chunk:
                            break
                        hasher.update(chunk)
                        if output_handle is not None:
                            output_handle.write(chunk)
                finally:
                    if output_handle is not None:
                        output_handle.close()
                entry["size"] = member.size
                entry["sha256"] = hasher.hexdigest()
            elif member.issym() or member.islnk():
                entry["link"] = member.linkname
            view[path] = entry
    return view


def build_side_view(
    client: RegistryClient, repository: str, tag: str, layers: Sequence[Dict[str, Any]], workdir: Path
) -> Dict[str, Dict[str, Any]]:
    """Merge the views of the layers above the common prefix (upper layers override lower ones)."""
    merged: Dict[str, Dict[str, Any]] = {}
    for layer in layers:
        blob_path = client.get_blob_path(repository, layer["digest"])
        extract_root = workdir / "images" / repository / safe_reference(tag) / "files" / f"L{layer['index']}"
        layer_view = build_layer_view(blob_path, extract_root)
        for path, entry in layer_view.items():
            if path.endswith("/<opaque-whiteout>"):
                directory = path[: -len("/<opaque-whiteout>")]
                for existing in [key for key in merged if key.startswith(directory + "/")]:
                    del merged[existing]
            entry = dict(entry, layer_index=layer["index"])
            merged[path] = entry
    return merged


def compare_views(old_view: Dict[str, Dict[str, Any]], new_view: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """File-level comparison of two merged layer views (mtime-only changes are counted, not listed)."""
    compared_fields = ("type", "sha256", "size", "link", "mode", "uid", "gid")
    added = sorted(set(new_view) - set(old_view))
    removed = sorted(set(old_view) - set(new_view))
    changed: List[Dict[str, Any]] = []
    mtime_only = 0
    for path in sorted(set(old_view) & set(new_view)):
        old_entry, new_entry = old_view[path], new_view[path]
        differing_fields = [name for name in compared_fields if old_entry.get(name) != new_entry.get(name)]
        if differing_fields:
            changed.append(
                {
                    "path": path,
                    "fields": differing_fields,
                    "old": {name: old_entry.get(name) for name in compared_fields + ("mtime",)},
                    "new": {name: new_entry.get(name) for name in compared_fields + ("mtime",)},
                }
            )
        elif old_entry.get("mtime") != new_entry.get("mtime"):
            mtime_only += 1
    return {
        "added": [{"path": path, **new_view[path]} for path in added],
        "removed": [{"path": path, **old_view[path]} for path in removed],
        "changed": changed,
        "unchanged_except_mtime": mtime_only,
    }


# --------------------------------------------------------------------------------------------------
# Step 5 helpers (a): annotations, which `javap -c` does not print
# --------------------------------------------------------------------------------------------------

class ClassFileReader:
    """Tiny class-file parser that renders annotations with resolved constant-pool values.

    `javap -c -p` omits annotations, so a change such as @Value("${timeout:5000}") -> "...:50"
    or a new @GetMapping path would otherwise be invisible in the member comparison.
    """

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0
        self.constant_pool: List[Any] = [None]

    def _u1(self) -> int:
        value = self.data[self.position]
        self.position += 1
        return value

    def _u2(self) -> int:
        value = int.from_bytes(self.data[self.position:self.position + 2], "big")
        self.position += 2
        return value

    def _u4(self) -> int:
        value = int.from_bytes(self.data[self.position:self.position + 4], "big")
        self.position += 4
        return value

    def _read_constant_pool(self) -> None:
        count = self._u2()
        index = 1
        while index < count:
            tag = self._u1()
            if tag == 1:
                length = self._u2()
                raw = self.data[self.position:self.position + length]
                self.position += length
                self.constant_pool.append(("utf8", raw.decode("utf-8", errors="replace")))
            elif tag in (3, 4):
                raw_value = self._u4()
                if tag == 3 and raw_value >= 1 << 31:
                    raw_value -= 1 << 32
                self.constant_pool.append(("int" if tag == 3 else "float_bits", raw_value))
            elif tag in (5, 6):
                high, low = self._u4(), self._u4()
                raw_value = (high << 32) | low
                if tag == 5 and raw_value >= 1 << 63:
                    raw_value -= 1 << 64
                self.constant_pool.append(("long" if tag == 5 else "double_bits", raw_value))
                self.constant_pool.append(None)  # 8-byte constants take two slots
                index += 1
            elif tag in (7, 8, 16, 19, 20):
                self.constant_pool.append(("ref1", self._u2()))
            elif tag in (9, 10, 11, 12, 17, 18):
                self.constant_pool.append(("ref2", self._u2(), self._u2()))
            elif tag == 15:
                self.constant_pool.append(("handle", self._u1(), self._u2()))
            else:
                raise ValueError(f"unknown constant pool tag {tag}")
            index += 1

    def _utf8(self, index: int) -> str:
        entry = self.constant_pool[index]
        return entry[1] if entry and entry[0] == "utf8" else f"#{index}"

    def _constant(self, index: int) -> str:
        entry = self.constant_pool[index]
        if entry is None:
            return f"#{index}"
        if entry[0] == "utf8":
            return json.dumps(entry[1], ensure_ascii=False)
        if entry[0] == "float_bits":
            return repr(struct.unpack(">f", entry[1].to_bytes(4, "big"))[0])
        if entry[0] == "double_bits":
            return repr(struct.unpack(">d", (entry[1] & ((1 << 64) - 1)).to_bytes(8, "big"))[0])
        return str(entry[1])

    def _element_value(self) -> str:
        tag = chr(self._u1())
        if tag in "BCDFIJSZs":
            return self._constant(self._u2())
        if tag == "e":
            type_name, constant_name = self._u2(), self._u2()
            return f"{self._utf8(type_name)}.{self._utf8(constant_name)}"
        if tag == "c":
            return f"class {self._utf8(self._u2())}"
        if tag == "@":
            return self._annotation()
        if tag == "[":
            return "[" + ", ".join(self._element_value() for _ in range(self._u2())) + "]"
        raise ValueError(f"unknown element_value tag {tag}")

    def _annotation(self) -> str:
        type_name = self._utf8(self._u2())
        pairs = [f"{self._utf8(self._u2())}={self._element_value()}" for _ in range(self._u2())]
        return f"@{type_name}({', '.join(pairs)})"

    def _attributes(self) -> List[str]:
        rendered: List[str] = []
        for _ in range(self._u2()):
            name = self._utf8(self._u2())
            length = self._u4()
            end = self.position + length
            if name in ("RuntimeVisibleAnnotations", "RuntimeInvisibleAnnotations"):
                rendered.extend(self._annotation() for _ in range(self._u2()))
            elif name in ("RuntimeVisibleParameterAnnotations", "RuntimeInvisibleParameterAnnotations"):
                for parameter_index in range(self._u1()):
                    for _ in range(self._u2()):
                        rendered.append(f"param{parameter_index} {self._annotation()}")
            elif name == "ConstantValue":
                rendered.append(f"ConstantValue={self._constant(self._u2())}")
            elif name == "Signature":
                rendered.append(f"Signature={self._utf8(self._u2())}")
            self.position = end
        return rendered

    def annotations(self) -> Dict[str, List[str]]:
        """Return {'<class>' | 'field name:desc' | 'method name:desc': [rendered annotations...]}."""
        self.position = 8
        self._read_constant_pool()
        self.position += 6  # access_flags, this_class, super_class
        interface_count = self._u2()  # read first: `position += 2 * self._u2()` would lose the u2 advance
        self.position += 2 * interface_count
        result: Dict[str, List[str]] = {}
        for kind in ("field", "method"):
            for _ in range(self._u2()):
                self._u2()  # access flags (already visible in javap output)
                name, descriptor = self._utf8(self._u2()), self._utf8(self._u2())
                rendered = self._attributes()
                if rendered:
                    result[f"{kind} {name}:{descriptor}"] = rendered
        class_attributes = self._attributes()
        if class_attributes:
            result["<class>"] = class_attributes
        return result


def class_annotations(class_bytes: Optional[bytes]) -> Dict[str, List[str]]:
    if class_bytes is None:
        return {}
    try:
        return ClassFileReader(class_bytes).annotations()
    except (ValueError, IndexError) as error:  # never let the helper hide a real diff
        return {"<parse-error>": [str(error)]}


def compare_annotations(old_bytes: Optional[bytes], new_bytes: Optional[bytes]) -> List[str]:
    """Human-readable list of annotation / ConstantValue / Signature differences between two classes."""
    old_annotations, new_annotations = class_annotations(old_bytes), class_annotations(new_bytes)
    differences: List[str] = []
    for member in sorted(set(old_annotations) | set(new_annotations)):
        old_items, new_items = old_annotations.get(member, []), new_annotations.get(member, [])
        if old_items != new_items:
            for item in old_items:
                if item not in new_items:
                    differences.append(f"- {member}: {item}")
            for item in new_items:
                if item not in old_items:
                    differences.append(f"+ {member}: {item}")
    return differences


# --------------------------------------------------------------------------------------------------
# Step 5 helpers (b): javap normalisation and member-level comparison
# --------------------------------------------------------------------------------------------------

def run_javap_batch(class_files: Sequence[Path], parallelism: int = 8) -> Dict[Path, str]:
    """Run javap on many class files in parallel; return path -> stdout (stderr appended on failure)."""

    def run_one(class_file: Path) -> Tuple[Path, str]:
        completed = subprocess.run(
            ["javap", *JAVAP_FLAGS, str(class_file)], capture_output=True, text=True, check=False
        )
        output = completed.stdout
        if completed.returncode != 0:
            output += "\n[javap error] " + completed.stderr
        return class_file, output

    results: Dict[Path, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as executor:
        for class_file, output in executor.map(run_one, class_files):
            results[class_file] = output
    return results


CONSTANT_POOL_OPERAND = re.compile(r"(\s)#\d+(?:,\s*\d+)?(\s+//)")
INVOKEDYNAMIC_BOOTSTRAP = re.compile(r"InvokeDynamic #\d+:")


def strip_constant_pool_indices(text: str) -> str:
    """'invokevirtual #23   // Method x' -> 'invokevirtual #   // Method x' (pool order is build noise)."""
    text = CONSTANT_POOL_OPERAND.sub(r"\1#\2", text)
    return INVOKEDYNAMIC_BOOTSTRAP.sub("InvokeDynamic #:", text)


def parse_javap_members(javap_text: str) -> Tuple[str, Dict[str, List[str]]]:
    """Split `javap -c -p` output into (class header, {member declaration: body lines})."""
    class_header = ""
    members: Dict[str, List[str]] = collections.OrderedDict()
    current_member: Optional[str] = None
    for line in javap_text.splitlines():
        if not class_header and line.rstrip().endswith("{") and not line.startswith(" "):
            class_header = line.strip()
            continue
        if line.startswith("  ") and not line.startswith("   ") and line.strip():
            current_member = line.strip()
            members[current_member] = []
        elif line.startswith("    ") and current_member is not None:
            members[current_member].append(line)
        elif line.strip() == "}":
            current_member = None
    return class_header, members


def parse_member_body(body_lines: Sequence[str]) -> Dict[str, Any]:
    """Turn one member's javap body into offset-independent instructions annotated with source lines."""
    instructions: List[Tuple[int, str]] = []  # (bytecode offset, normalised instruction text)
    line_number_table: List[Tuple[int, int]] = []  # (start offset, source line)
    local_variables: List[str] = []
    exception_handlers: List[str] = []
    section = "code"
    inside_switch = False
    switch_offset = -1
    for raw_line in body_lines:
        stripped = raw_line.strip()
        if stripped in ("Code:",):
            section = "code"
            continue
        if stripped == "LineNumberTable:":
            section = "lines"
            continue
        if stripped in ("LocalVariableTable:", "LocalVariableTypeTable:"):
            section = "locals"
            continue
        if stripped == "Exception table:":
            section = "exceptions"
            continue
        if section == "lines":
            match = re.match(r"line (\d+): (\d+)", stripped)
            if match:
                line_number_table.append((int(match.group(2)), int(match.group(1))))
            continue
        if section == "locals":
            parts = stripped.split()
            if len(parts) >= 5 and parts[0] != "Start":
                local_variables.append(f"{parts[3]} {parts[4]}")
            continue
        if section == "exceptions":
            parts = stripped.split()
            if parts and parts[0] != "from":
                exception_handlers.append("catch " + " ".join(parts[3:]))
            continue
        # section == "code"
        if inside_switch:
            if stripped == "}":
                inside_switch = False
                instructions.append((switch_offset, "}"))
            else:
                case_key = stripped.split(":", 1)[0]
                instructions.append((switch_offset, f"case {case_key}: L"))
            continue
        match = re.match(r"(\d+): (.*)$", stripped)
        if not match:
            continue
        offset, instruction = int(match.group(1)), match.group(2)
        instruction = strip_constant_pool_indices(" " + instruction).strip()
        # ldc vs ldc_w (and goto vs goto_w) only reflect constant-pool size / method length, not semantics.
        instruction = re.sub(r"^(ldc|goto|jsr)_w\b", r"\1", instruction)
        instruction = re.sub(r"^(if\w*|goto|jsr)\s+\d+", r"\1 L", instruction)
        instruction = re.sub(r"\s{2,}", " ", instruction)
        if instruction.startswith(("tableswitch", "lookupswitch")):
            inside_switch = True
            switch_offset = offset
        instructions.append((offset, instruction))
    line_number_table.sort()

    def source_line_for(offset: int) -> Optional[int]:
        best: Optional[int] = None
        for start_offset, source_line in line_number_table:
            if start_offset <= offset:
                best = source_line
            else:
                break
        return best

    return {
        "instructions": [text for _, text in instructions],
        "source_lines": [source_line_for(offset) for offset, _ in instructions],
        "local_variables": sorted(local_variables),
        "exception_handlers": exception_handlers,
        "source_line_range": (
            (min(line for _, line in line_number_table), max(line for _, line in line_number_table))
            if line_number_table else None
        ),
    }


def member_equality_key(parsed_body: Dict[str, Any]) -> Tuple:
    return (
        tuple(parsed_body["instructions"]),
        tuple(parsed_body["local_variables"]),
        tuple(parsed_body["exception_handlers"]),
    )


def instruction_diff_lines(old_body: Dict[str, Any], new_body: Dict[str, Any], context: int = 2) -> List[str]:
    """Offset-independent diff of two method bodies; '+'/'-' lines carry the source line number."""
    old_instructions, new_instructions = old_body["instructions"], new_body["instructions"]
    matcher = difflib.SequenceMatcher(a=old_instructions, b=new_instructions, autojunk=False)
    output: List[str] = []
    for group in matcher.get_grouped_opcodes(context):
        output.append("  @@")
        for tag, old_start, old_end, new_start, new_end in group:
            if tag == "equal":
                for index in range(new_start, new_end):
                    output.append(f"    {new_instructions[index]}")
                continue
            for index in range(old_start, old_end):
                output.append(f"  - {old_instructions[index]}    (old src line {old_body['source_lines'][index]})")
            for index in range(new_start, new_end):
                output.append(f"  + {new_instructions[index]}    (new src line {new_body['source_lines'][index]})")
    if len(output) > MAX_INSTRUCTION_DIFF_LINES:
        output = output[:MAX_INSTRUCTION_DIFF_LINES] + [f"  ... ({len(output) - MAX_INSTRUCTION_DIFF_LINES} more lines)"]
    return output


def instruction_multiset_delta(old_body: Dict[str, Any], new_body: Dict[str, Any]) -> Dict[str, List[str]]:
    """Which normalised instructions appear more often in new than old (and vice versa)."""
    old_counter = collections.Counter(old_body["instructions"])
    new_counter = collections.Counter(new_body["instructions"])
    return {
        "added": sorted((new_counter - old_counter).elements()),
        "removed": sorted((old_counter - new_counter).elements()),
    }


def compare_class_javap(
    old_text: Optional[str],
    new_text: Optional[str],
    old_bytes: Optional[bytes] = None,
    new_bytes: Optional[bytes] = None,
) -> Dict[str, Any]:
    """Member-level comparison of two javap outputs (either side may be None for added/removed classes),
    plus annotation / ConstantValue / Signature differences taken from the raw class bytes."""
    old_header, old_members = parse_javap_members(old_text or "")
    new_header, new_members = parse_javap_members(new_text or "")
    result: Dict[str, Any] = {
        "old_class_header": old_header,
        "new_class_header": new_header,
        "members_added": [],
        "members_removed": [],
        "members_changed": [],
        "annotation_differences": compare_annotations(old_bytes, new_bytes),
        "identical_after_normalisation": False,
    }
    for declaration in new_members:
        if declaration not in old_members:
            parsed = parse_member_body(new_members[declaration])
            result["members_added"].append(
                {
                    "member": declaration,
                    "source_line_range": parsed["source_line_range"],
                    "instructions": parsed["instructions"][:MAX_INSTRUCTION_DIFF_LINES],
                }
            )
    for declaration in old_members:
        if declaration not in new_members:
            parsed = parse_member_body(old_members[declaration])
            result["members_removed"].append(
                {"member": declaration, "source_line_range": parsed["source_line_range"]}
            )
    for declaration in old_members:
        if declaration in new_members:
            old_parsed = parse_member_body(old_members[declaration])
            new_parsed = parse_member_body(new_members[declaration])
            if member_equality_key(old_parsed) != member_equality_key(new_parsed):
                result["members_changed"].append(
                    {
                        "member": declaration,
                        "old_source_line_range": old_parsed["source_line_range"],
                        "new_source_line_range": new_parsed["source_line_range"],
                        "instruction_delta": instruction_multiset_delta(old_parsed, new_parsed),
                        "local_variables_added": sorted(
                            set(new_parsed["local_variables"]) - set(old_parsed["local_variables"])
                        ),
                        "local_variables_removed": sorted(
                            set(old_parsed["local_variables"]) - set(new_parsed["local_variables"])
                        ),
                        "diff": instruction_diff_lines(old_parsed, new_parsed),
                    }
                )
    result["identical_after_normalisation"] = (
        old_text is not None
        and new_text is not None
        and old_header == new_header
        and not result["members_added"]
        and not result["members_removed"]
        and not result["members_changed"]
        and not result["annotation_differences"]
    )
    return result


# --------------------------------------------------------------------------------------------------
# Step 4: jar comparison
# --------------------------------------------------------------------------------------------------

LIB_NAME_PATTERN = re.compile(r"^(?P<artifact>.+?)-(?P<version>\d[\w.\-]*?)(?:\.RELEASE|\.Final)?\.jar$")


def classify_jar_entry(entry_name: str) -> str:
    if entry_name.startswith("BOOT-INF/classes/"):
        return "classes" if entry_name.endswith(".class") else "resources"
    if entry_name.startswith("BOOT-INF/lib/"):
        return "libs"
    if entry_name.startswith("org/springframework/boot/loader/"):
        return "boot_loader"
    if entry_name.startswith("META-INF/") or entry_name.startswith("BOOT-INF/") and entry_name.endswith(".idx"):
        return "meta"
    if entry_name.endswith(".class"):
        return "classes"  # thin jar (e.g. nested ts-common): classes at the root
    return "other"


def jar_entry_table(jar_path: Path) -> Dict[str, zipfile.ZipInfo]:
    with zipfile.ZipFile(jar_path) as archive:
        return {info.filename: info for info in archive.infolist() if not info.is_dir()}


def jar_timestamp_profile(entries: Dict[str, zipfile.ZipInfo]) -> Dict[str, Any]:
    """Most common zip entry timestamps (≈ when the jar was packaged / classes were compiled)."""
    counter = collections.Counter(
        "%04d-%02d-%02d %02d:%02d" % info.date_time[:5] for info in entries.values()
    )
    return {"most_common": counter.most_common(3), "distinct": len(counter)}


def is_text_resource(entry_name: str) -> bool:
    return entry_name.endswith(TEXT_RESOURCE_SUFFIXES) or "/" not in entry_name.strip("/")


def text_diff(old_bytes: bytes, new_bytes: bytes, label: str) -> List[str]:
    old_lines = old_bytes.decode("utf-8", errors="replace").splitlines()
    new_lines = new_bytes.decode("utf-8", errors="replace").splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, f"old/{label}", f"new/{label}", lineterm="", n=2))
    if len(diff) > MAX_RESOURCE_DIFF_LINES:
        diff = diff[:MAX_RESOURCE_DIFF_LINES] + [f"... ({len(diff) - MAX_RESOURCE_DIFF_LINES} more lines)"]
    return diff


def compare_jars(
    old_jar: Path, new_jar: Path, javap_dir: Path, label: str, recurse_into_libs: bool = True
) -> Dict[str, Any]:
    """Compare two jars entry by entry; javap-diff changed classes; recurse into changed nested jars."""
    old_entries, new_entries = jar_entry_table(old_jar), jar_entry_table(new_jar)
    added = sorted(set(new_entries) - set(old_entries))
    removed = sorted(set(old_entries) - set(new_entries))
    changed = sorted(
        name
        for name in set(old_entries) & set(new_entries)
        if (old_entries[name].CRC, old_entries[name].file_size)
        != (new_entries[name].CRC, new_entries[name].file_size)
    )
    identical_count = len(set(old_entries) & set(new_entries)) - len(changed)
    result: Dict[str, Any] = {
        "label": label,
        "old_jar": str(old_jar),
        "new_jar": str(new_jar),
        "old_sha256": hashlib.sha256(old_jar.read_bytes()).hexdigest(),
        "new_sha256": hashlib.sha256(new_jar.read_bytes()).hexdigest(),
        "old_entry_count": len(old_entries),
        "new_entry_count": len(new_entries),
        "identical_entry_count": identical_count,
        "old_timestamps": jar_timestamp_profile(old_entries),
        "new_timestamps": jar_timestamp_profile(new_entries),
        "by_category": {},
        "class_diffs": {},
        "text_diffs": {},
        "nested_jar_diffs": {},
        "lib_version_changes": [],
    }
    for status, names in (("added", added), ("removed", removed), ("changed", changed)):
        for name in names:
            category = classify_jar_entry(name)
            result["by_category"].setdefault(category, {}).setdefault(status, []).append(name)

    # Dependency jars: detect version bumps (same artifact name, different version).
    old_libs = {name for name in old_entries if name.startswith("BOOT-INF/lib/")}
    new_libs = {name for name in new_entries if name.startswith("BOOT-INF/lib/")}

    def artifact_name(entry_name: str) -> str:
        match = LIB_NAME_PATTERN.match(posixpath.basename(entry_name))
        return match.group("artifact") if match else posixpath.basename(entry_name)

    old_by_artifact = {artifact_name(name): name for name in old_libs - new_libs}
    new_by_artifact = {artifact_name(name): name for name in new_libs - old_libs}
    for artifact in sorted(set(old_by_artifact) & set(new_by_artifact)):
        result["lib_version_changes"].append({"old": old_by_artifact[artifact], "new": new_by_artifact[artifact]})

    with zipfile.ZipFile(old_jar) as old_archive, zipfile.ZipFile(new_jar) as new_archive, \
            tempfile.TemporaryDirectory(prefix="jarcmp-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        # Classes: javap both sides (changed), or the one side (added / removed).
        class_names = [name for name in added + removed + changed if name.endswith(".class")]
        side_files: Dict[Tuple[str, str], Path] = {}
        for name in class_names:
            for side, archive, entries in (("old", old_archive, old_entries), ("new", new_archive, new_entries)):
                if name in entries:
                    target = temp_dir / side / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(name))
                    side_files[(side, name)] = target
        javap_outputs = run_javap_batch(list(side_files.values()))
        javap_dir.mkdir(parents=True, exist_ok=True)
        for name in class_names:
            old_text = javap_outputs.get(side_files.get(("old", name)))
            new_text = javap_outputs.get(side_files.get(("new", name)))
            comparison = compare_class_javap(
                old_text,
                new_text,
                old_archive.read(name) if name in old_entries else None,
                new_archive.read(name) if name in new_entries else None,
            )
            result["class_diffs"][name] = comparison
            diff_lines = difflib.unified_diff(
                strip_constant_pool_indices(old_text or "").splitlines(),
                strip_constant_pool_indices(new_text or "").splitlines(),
                f"old/{name}", f"new/{name}", lineterm="", n=3,
            )
            safe_name = re.sub(r"[^\w.$-]", "_", f"{label}__{name}")
            (javap_dir / f"{safe_name}.diff").write_text("\n".join(diff_lines) + "\n")
            comparison["full_diff_file"] = str(javap_dir / f"{safe_name}.diff")
        # Text resources and META-INF: unified diff.
        for name in added + removed + changed:
            if name.endswith((".class", ".jar")) or not is_text_resource(name):
                continue
            old_bytes = old_archive.read(name) if name in old_entries else b""
            new_bytes = new_archive.read(name) if name in new_entries else b""
            result["text_diffs"][name] = text_diff(old_bytes, new_bytes, name)
        # Nested jars with the same name but different bytes (e.g. ts-common built from source).
        if recurse_into_libs:
            for name in changed:
                if not name.endswith(".jar"):
                    continue
                old_nested, new_nested = temp_dir / "old" / name, temp_dir / "new" / name
                old_nested.parent.mkdir(parents=True, exist_ok=True)
                new_nested.parent.mkdir(parents=True, exist_ok=True)
                old_nested.write_bytes(old_archive.read(name))
                new_nested.write_bytes(new_archive.read(name))
                result["nested_jar_diffs"][name] = compare_jars(
                    old_nested, new_nested, javap_dir, f"{label}!{posixpath.basename(name)}", recurse_into_libs=False
                )
    return result


# --------------------------------------------------------------------------------------------------
# Pair comparison and report
# --------------------------------------------------------------------------------------------------

def diff_image_config(old_config: Dict[str, Any], new_config: Dict[str, Any]) -> Dict[str, Any]:
    """Compare runtime-relevant config keys, the build history and the creation time."""
    differences: Dict[str, Any] = {}
    old_runtime, new_runtime = old_config.get("config") or {}, new_config.get("config") or {}
    for key in RUNTIME_CONFIG_KEYS:
        if old_runtime.get(key) != new_runtime.get(key):
            differences[key] = {"old": old_runtime.get(key), "new": new_runtime.get(key)}
    old_history = [
        (item.get("created_by"), bool(item.get("empty_layer"))) for item in old_config.get("history", [])
    ]
    new_history = [
        (item.get("created_by"), bool(item.get("empty_layer"))) for item in new_config.get("history", [])
    ]
    return {
        "runtime_config_differences": differences,
        "history_commands_identical": old_history == new_history,
        "history_command_diff": list(
            difflib.unified_diff(
                [f"{'E' if empty else 'L'} {command}" for command, empty in old_history],
                [f"{'E' if empty else 'L'} {command}" for command, empty in new_history],
                "old", "new", lineterm="", n=0,
            )
        ),
        "old_created": old_config.get("created"),
        "new_created": new_config.get("created"),
        "old_history_created": [
            (item.get("created"), (item.get("created_by") or "")[:100]) for item in old_config.get("history", [])[-5:]
        ],
        "new_history_created": [
            (item.get("created"), (item.get("created_by") or "")[:100]) for item in new_config.get("history", [])[-5:]
        ],
    }


def find_application_jar(view: Dict[str, Dict[str, Any]]) -> Optional[str]:
    candidates = [path for path, entry in view.items() if path.endswith(".jar") and entry.get("type") == "file"]
    application = [path for path in candidates if path.startswith("/app/")]
    return (application or candidates or [None])[0]


def compare_pair(
    client: RegistryClient, repository: str, old_tag: str, new_tag: str, workdir: Path
) -> Dict[str, Any]:
    old_image = resolve_image(client, repository, old_tag, workdir)
    new_image = resolve_image(client, repository, new_tag, workdir)
    layer_comparison = compare_layer_lists(old_image, new_image)
    if old_image["platform"] != new_image["platform"]:
        # Different CPU architectures share no base layers; compare only the layers that add the jar.
        layer_comparison["cross_platform"] = True
        for side in ("old_above_prefix", "new_above_prefix"):
            layer_comparison[side] = [
                layer for layer in layer_comparison[side]
                if JAR_COPY_PATTERN.match((layer.get("created_by") or "").strip())
            ]
    summary: Dict[str, Any] = {
        "repository": repository,
        "old_tag": old_tag,
        "new_tag": new_tag,
        "old_identity": {
            key: old_image[key] for key in ("top_digest", "manifest_digest", "config_digest", "platform")
        },
        "new_identity": {
            key: new_image[key] for key in ("top_digest", "manifest_digest", "config_digest", "platform")
        },
        "config": diff_image_config(old_image["config"], new_image["config"]),
        "layers": layer_comparison,
        "attestations": {"old": old_image["attestations"], "new": new_image["attestations"]},
    }
    pair_dir = workdir / "pairs" / repository / f"{safe_reference(old_tag)}__{safe_reference(new_tag)}"
    pair_dir.mkdir(parents=True, exist_ok=True)
    if not layer_comparison["identical"]:
        old_view = build_side_view(client, repository, old_tag, layer_comparison["old_above_prefix"], workdir)
        new_view = build_side_view(client, repository, new_tag, layer_comparison["new_above_prefix"], workdir)
        summary["files"] = compare_views(old_view, new_view)
        old_jar_path, new_jar_path = find_application_jar(old_view), find_application_jar(new_view)
        summary["application_jar"] = {"old_path": old_jar_path, "new_path": new_jar_path}
        if old_jar_path and new_jar_path:
            summary["jar"] = compare_jars(
                Path(old_view[old_jar_path]["extracted_to"]),
                Path(new_view[new_jar_path]["extracted_to"]),
                pair_dir / "javap",
                posixpath.basename(new_jar_path),
            )
        # Non-jar files that changed: text diff for small ones (e.g. /etc/timezone).
        summary["small_file_diffs"] = {}
        for change in summary["files"]["changed"]:
            path = change["path"]
            if path.endswith(".jar") or (change["new"].get("size") or 0) > 65536:
                continue
            if "extracted_to" in old_view[path] and "extracted_to" in new_view[path]:
                summary["small_file_diffs"][path] = text_diff(
                    Path(old_view[path]["extracted_to"]).read_bytes(),
                    Path(new_view[path]["extracted_to"]).read_bytes(),
                    path,
                )
    (pair_dir / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False, default=str))
    (pair_dir / "report.txt").write_text(render_pair_report(summary))
    return summary


def render_listing(title: str, items: Sequence[str], indent: str = "    ") -> List[str]:
    lines = [f"{indent}{title} ({len(items)}):"]
    for item in items[:MAX_LISTED_PATHS]:
        lines.append(f"{indent}  {item}")
    if len(items) > MAX_LISTED_PATHS:
        lines.append(f"{indent}  ... {len(items) - MAX_LISTED_PATHS} more")
    return lines


def render_jar_section(jar: Dict[str, Any], indent: str = "") -> List[str]:
    lines = [
        f"{indent}jar {jar['label']}: old sha256={jar['old_sha256'][:16]}… new sha256={jar['new_sha256'][:16]}…",
        f"{indent}  entries old={jar['old_entry_count']} new={jar['new_entry_count']} "
        f"identical={jar['identical_entry_count']}",
        f"{indent}  zip timestamps old={jar['old_timestamps']['most_common']} new={jar['new_timestamps']['most_common']}",
    ]
    for category in ("classes", "resources", "libs", "boot_loader", "meta", "other"):
        statuses = jar["by_category"].get(category)
        if not statuses:
            lines.append(f"{indent}  [{category}] no differences")
            continue
        lines.append(f"{indent}  [{category}]")
        for status in ("added", "removed", "changed"):
            if statuses.get(status):
                lines.extend(render_listing(status, statuses[status], indent + "    "))
    if jar["lib_version_changes"]:
        lines.append(f"{indent}  dependency version changes:")
        for change in jar["lib_version_changes"]:
            lines.append(f"{indent}    {change['old']} -> {change['new']}")
    for name, comparison in jar["class_diffs"].items():
        lines.append(f"{indent}  class {name}:")
        if comparison["identical_after_normalisation"]:
            lines.append(f"{indent}    identical after javap normalisation (byte-level noise only)")
            continue
        if comparison["old_class_header"] != comparison["new_class_header"]:
            lines.append(f"{indent}    header old: {comparison['old_class_header']}")
            lines.append(f"{indent}    header new: {comparison['new_class_header']}")
        for difference in comparison.get("annotation_differences", []):
            lines.append(f"{indent}    annotation {difference}")
        for member in comparison["members_added"]:
            lines.append(f"{indent}    + member {member['member']}  (src lines {member['source_line_range']})")
        for member in comparison["members_removed"]:
            lines.append(f"{indent}    - member {member['member']}  (src lines {member['source_line_range']})")
        for member in comparison["members_changed"]:
            lines.append(
                f"{indent}    ~ member {member['member']}  (src lines old {member['old_source_line_range']}"
                f" -> new {member['new_source_line_range']})"
            )
            if member["local_variables_added"] or member["local_variables_removed"]:
                lines.append(
                    f"{indent}      locals +{member['local_variables_added']} -{member['local_variables_removed']}"
                )
            lines.extend(f"{indent}    {line}" for line in member["diff"])
        lines.append(f"{indent}    full diff: {comparison.get('full_diff_file')}")
    for name, diff in jar["text_diffs"].items():
        lines.append(f"{indent}  text diff {name}:")
        lines.extend(f"{indent}    {line}" for line in diff)
    for name, nested in jar["nested_jar_diffs"].items():
        lines.append(f"{indent}  nested jar {name}:")
        lines.extend(render_jar_section(nested, indent + "    "))
    return lines


def render_pair_report(summary: Dict[str, Any]) -> str:
    lines = [
        f"=== {summary['repository']}  {summary['old_tag']} -> {summary['new_tag']}",
        f"old index {summary['old_identity']['top_digest']}  {summary['old_identity']['platform']} "
        f"{summary['old_identity']['manifest_digest']}",
        f"new index {summary['new_identity']['top_digest']}  {summary['new_identity']['platform']} "
        f"{summary['new_identity']['manifest_digest']}",
        f"created old={summary['config']['old_created']} new={summary['config']['new_created']}",
        "",
        "[image config]",
    ]
    runtime_differences = summary["config"]["runtime_config_differences"]
    if not runtime_differences:
        lines.append("  Env/Entrypoint/Cmd/ExposedPorts/WorkingDir/User/Volumes/Labels/...: identical")
    for key, values in runtime_differences.items():
        lines.append(f"  {key}: old={values['old']} new={values['new']}")
    lines.append(f"  build history commands identical: {summary['config']['history_commands_identical']}")
    lines.extend(f"  {line}" for line in summary["config"]["history_command_diff"])
    lines.append("")
    layers = summary["layers"]
    lines.append("[layers]")
    lines.append(
        f"  old={layers['old_layer_count']} new={layers['new_layer_count']} "
        f"common prefix={layers['common_prefix_length']} identical={layers['identical']}"
    )
    if layers.get("cross_platform"):
        lines.append("  cross-platform pair (amd64 vs arm64): only the layers that ADD the jar are compared below")
    for side in ("old", "new"):
        for layer in layers[f"{side}_above_prefix"]:
            lines.append(
                f"  {side} L{layer['index']} {layer['digest'][:19]} {layer['size']:>10} B  "
                f"{(layer['created'] or '')[:19]}  {(layer['created_by'] or '')[:90]}"
            )
    for side in ("old", "new"):
        for attestation in summary["attestations"][side]:
            attestation_summary = attestation["summary"]
            lines.append(
                f"  {side} provenance: buildStarted={attestation_summary['metadata'].get('buildStartedOn')} "
                f"finished={attestation_summary['metadata'].get('buildFinishedOn')} "
                f"materials={[item.get('uri') for item in attestation_summary.get('materials') or []]}"
            )
    if "files" in summary:
        files = summary["files"]
        lines.append("")
        lines.append("[files in layers above the common prefix]")
        lines.extend(render_listing("added", [item["path"] for item in files["added"]], "  "))
        lines.extend(render_listing("removed", [item["path"] for item in files["removed"]], "  "))
        lines.append(f"  changed ({len(files['changed'])}):")
        for change in files["changed"][:MAX_LISTED_PATHS]:
            lines.append(
                f"    {change['path']}  fields={change['fields']}  "
                f"size {change['old'].get('size')} -> {change['new'].get('size')}"
            )
        lines.append(f"  identical except mtime: {files['unchanged_except_mtime']}")
        for path, diff in summary.get("small_file_diffs", {}).items():
            lines.append(f"  small file diff {path}:")
            lines.extend(f"    {line}" for line in diff)
    if "jar" in summary:
        lines.append("")
        lines.append("[application jar]")
        lines.extend(render_jar_section(summary["jar"], "  "))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------------------
# Step 6: compile upstream sources and compare with an image jar
# --------------------------------------------------------------------------------------------------

def compile_java_sources(
    source_root: Path, output_dir: Path, classpath: Sequence[Path], log_path: Path
) -> bool:
    """javac 8 with the flags Maven + spring-boot-starter-parent 2.3.x use (-g, -parameters, UTF-8, 1.8)."""
    sources = sorted(str(path) for path in source_root.rglob("*.java"))
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    argument_file = output_dir.parent / f"{output_dir.name}.sources.txt"
    argument_file.write_text("\n".join(f'"{source}"' for source in sources) + "\n")
    command = [
        "javac", "-nowarn", "-g", "-parameters", "-encoding", "UTF-8", "-source", "1.8", "-target", "1.8",
        "-d", str(output_dir), "-cp", ":".join(str(path) for path in classpath), f"@{argument_file}",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    log_path.write_text(
        f"$ javac ... ({len(sources)} sources)\nexit={completed.returncode}\n{completed.stdout}\n{completed.stderr}"
    )
    return completed.returncode == 0


def compare_class_trees(
    compiled: Dict[str, bytes], image: Dict[str, bytes], javap_dir: Path, label: str
) -> Dict[str, Any]:
    """Compare class name -> bytes maps: byte-identical / identical after javap normalisation / different."""
    only_compiled = sorted(set(compiled) - set(image))
    only_image = sorted(set(image) - set(compiled))
    byte_identical: List[str] = []
    to_javap: List[str] = []
    for name in sorted(set(compiled) & set(image)):
        (byte_identical if compiled[name] == image[name] else to_javap).append(name)
    normalised_identical: List[str] = []
    different: Dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="upcmp-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        files: Dict[Tuple[str, str], Path] = {}
        for name in to_javap + only_image + only_compiled:
            for side, table in (("upstream", compiled), ("image", image)):
                if name in table:
                    target = temp_dir / side / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(table[name])
                    files[(side, name)] = target
        outputs = run_javap_batch(list(files.values()))
        javap_dir.mkdir(parents=True, exist_ok=True)
        for name in to_javap + only_image + only_compiled:
            upstream_text = outputs.get(files.get(("upstream", name)))
            image_text = outputs.get(files.get(("image", name)))
            comparison = compare_class_javap(upstream_text, image_text, compiled.get(name), image.get(name))
            if comparison["identical_after_normalisation"]:
                normalised_identical.append(name)
                continue
            safe_name = re.sub(r"[^\w.$-]", "_", f"{label}__{name}")
            (javap_dir / f"{safe_name}.diff").write_text(
                "\n".join(
                    difflib.unified_diff(
                        strip_constant_pool_indices(upstream_text or "").splitlines(),
                        strip_constant_pool_indices(image_text or "").splitlines(),
                        f"upstream/{name}", f"image/{name}", lineterm="", n=3,
                    )
                )
                + "\n"
            )
            comparison["full_diff_file"] = str(javap_dir / f"{safe_name}.diff")
            different[name] = comparison
    return {
        "compiled_class_count": len(compiled),
        "image_class_count": len(image),
        "byte_identical": len(byte_identical),
        "identical_after_javap_normalisation": normalised_identical,
        "different": different,
        "only_in_upstream_compile": only_compiled,
        "only_in_image": only_image,
    }


def compare_image_with_upstream(
    repository: str, tag: str, application_jar: Path, upstream_dir: Path, workdir: Path, keep_libs: bool = True
) -> Dict[str, Any]:
    """Compile upstream ts-common + service sources against the image's libs and compare with the image."""
    output_root = workdir / "upstream" / repository / safe_reference(tag)
    if output_root.exists():
        shutil.rmtree(output_root)
    lib_dir = output_root / "lib"
    lib_dir.mkdir(parents=True)
    image_service_classes: Dict[str, bytes] = {}
    image_service_resources: Dict[str, bytes] = {}
    image_common_classes: Dict[str, bytes] = {}
    common_jar_name: Optional[str] = None
    with zipfile.ZipFile(application_jar) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if info.filename.startswith("BOOT-INF/lib/") and info.filename.endswith(".jar"):
                target = lib_dir / posixpath.basename(info.filename)
                target.write_bytes(archive.read(info.filename))
                if posixpath.basename(info.filename).startswith("ts-common"):
                    common_jar_name = target.name
            elif info.filename.startswith("BOOT-INF/classes/"):
                relative = info.filename[len("BOOT-INF/classes/"):]
                (image_service_classes if relative.endswith(".class") else image_service_resources)[relative] = (
                    archive.read(info.filename)
                )
    third_party_libs = sorted(path for path in lib_dir.glob("*.jar") if not path.name.startswith("ts-common"))
    if common_jar_name:
        with zipfile.ZipFile(lib_dir / common_jar_name) as common_archive:
            for info in common_archive.infolist():
                if info.filename.endswith(".class"):
                    image_common_classes[info.filename] = common_archive.read(info.filename)

    common_output = output_root / "compiled-ts-common"
    common_ok = compile_java_sources(
        upstream_dir / "ts-common" / "src" / "main" / "java", common_output, third_party_libs,
        output_root / "javac-ts-common.log",
    )
    service_output = output_root / "compiled-service"
    service_ok = compile_java_sources(
        upstream_dir / repository / "src" / "main" / "java", service_output,
        [common_output, *third_party_libs], output_root / "javac-service.log",
    )

    def read_tree(root: Path) -> Dict[str, bytes]:
        return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*.class")}

    result: Dict[str, Any] = {
        "repository": repository,
        "tag": tag,
        "application_jar": str(application_jar),
        "javac_version": subprocess.run(["javac", "-version"], capture_output=True, text=True).stderr.strip(),
        "ts_common_jar": common_jar_name,
        "compile_ok": {"ts-common": common_ok, "service": service_ok},
        "service_classes": compare_class_trees(
            read_tree(service_output), image_service_classes, output_root / "javap", "service"
        ),
        "ts_common_classes": compare_class_trees(
            read_tree(common_output), image_common_classes, output_root / "javap", "ts-common"
        ),
        "resources": {},
    }
    resource_root = upstream_dir / repository / "src" / "main" / "resources"
    upstream_resources = {
        str(path.relative_to(resource_root)): path.read_bytes() for path in resource_root.rglob("*") if path.is_file()
    } if resource_root.exists() else {}
    for name in sorted(set(upstream_resources) | set(image_service_resources)):
        upstream_bytes, image_bytes = upstream_resources.get(name), image_service_resources.get(name)
        if upstream_bytes == image_bytes:
            result["resources"][name] = "identical"
        elif upstream_bytes is None:
            result["resources"][name] = "only in image"
        elif image_bytes is None:
            result["resources"][name] = "only in upstream"
        else:
            result["resources"][name] = text_diff(upstream_bytes, image_bytes, name)
    result["libs"] = sorted(path.name for path in lib_dir.glob("*.jar"))
    if not keep_libs:
        shutil.rmtree(lib_dir)  # ~80 MB per image; the names are kept in result["libs"]
    (output_root / "summary.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str))
    (output_root / "report.txt").write_text(render_upstream_report(result))
    return result


def render_upstream_report(result: Dict[str, Any]) -> str:
    lines = [
        f"=== upstream source (313886e9) vs image {result['repository']}:{result['tag']}",
        f"javac: {result['javac_version']}   compile ok: {result['compile_ok']}   ts-common jar: {result['ts_common_jar']}",
    ]
    for key in ("service_classes", "ts_common_classes"):
        tree = result[key]
        lines.append(
            f"[{key}] compiled={tree['compiled_class_count']} image={tree['image_class_count']} "
            f"byte-identical={tree['byte_identical']} "
            f"identical-after-javap-normalisation={len(tree['identical_after_javap_normalisation'])} "
            f"different={len(tree['different'])} only-upstream={len(tree['only_in_upstream_compile'])} "
            f"only-image={len(tree['only_in_image'])}"
        )
        lines.extend(render_listing("only in upstream compile", tree["only_in_upstream_compile"], "  "))
        lines.extend(render_listing("only in image", tree["only_in_image"], "  "))
        for name, comparison in tree["different"].items():
            lines.append(f"  different: {name}")
            if comparison["old_class_header"] != comparison["new_class_header"]:
                lines.append(f"    header upstream: {comparison['old_class_header']}")
                lines.append(f"    header image   : {comparison['new_class_header']}")
            for difference in comparison.get("annotation_differences", []):
                lines.append(f"    annotation {difference}  ('-' = upstream, '+' = image)")
            for member in comparison["members_added"]:
                lines.append(f"    + (image only) {member['member']}")
            for member in comparison["members_removed"]:
                lines.append(f"    - (upstream only) {member['member']}")
            for member in comparison["members_changed"]:
                lines.append(f"    ~ {member['member']}")
                lines.extend(f"    {line}" for line in member["diff"])
    lines.append("[resources]")
    for name, status in result["resources"].items():
        if isinstance(status, str):
            lines.append(f"  {name}: {status}")
        else:
            lines.append(f"  {name}: DIFFERENT")
            lines.extend(f"    {line}" for line in status)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------------------
# Step 7: scan every image the cluster runs (tags taken from the exported deployments.json)
# --------------------------------------------------------------------------------------------------

DEFAULT_DEPLOYMENTS_JSON: Path = Path(
    "/Users/mymz/work/国家重点研发/韧性测试工具 benchmark/multisystem-audit-20260918/"
    "manifests/train-ticket/deployments.json"
)
SOURCE_COPY_PATTERN = re.compile(r"^(?:ADD|COPY)\s+(?:--\S+\s+)*(?P<source>\S+)\s+(?P<destination>\S+)$")
JAR_COPY_PATTERN = re.compile(r"^(?:ADD|COPY)\s.*\.jar\s")


def load_deployed_images(deployments_json: Path) -> List[Tuple[str, str]]:
    """(repository, tag) of every train-ticket/ts-* container image in an exported Deployment list."""
    document = json.loads(deployments_json.read_text())
    items = document.get("items", []) if isinstance(document, dict) else document
    images: List[Tuple[str, str]] = []
    for item in items:
        pod_spec = item["spec"]["template"]["spec"]
        for container in pod_spec.get("containers", []) + (pod_spec.get("initContainers") or []):
            match = re.search(rf"/{HARBOR_PROJECT}/(?P<repo>ts-[^:@/]+):(?P<tag>[^@]+)$", container["image"])
            if match:
                images.append((match.group("repo"), match.group("tag")))
    return sorted(set(images))


def parse_dockerfile_instructions(dockerfile: Path) -> List[str]:
    """Instructions of a Dockerfile (line continuations joined, comments dropped, whitespace collapsed)."""
    instructions: List[str] = []
    pending = ""
    for raw_line in dockerfile.read_text(errors="replace").splitlines():
        line = raw_line.strip()
        if not pending and (not line or line.startswith("#")):
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        instructions.append(" ".join((pending + line).split()))
        pending = ""
    if pending.strip():
        instructions.append(" ".join(pending.split()))
    return instructions


def normalize_instruction(text: str, from_dockerfile: bool = False) -> str:
    """Make a Dockerfile instruction and an image-history 'created_by' string comparable."""
    text = text.replace("# buildkit", "").strip()
    text = re.sub(r"^/bin/sh -c #\(nop\)\s+", "", text)  # classic (non-buildkit) builder
    keyword, _, argument = text.partition(" ")
    keyword, argument = keyword.upper(), argument.strip()
    if keyword == "RUN":
        argument = re.sub(r"^/bin/sh -c ", "", argument)
    elif keyword in ("CMD", "ENTRYPOINT"):
        if argument.startswith("["):
            try:
                tokens = json.loads(argument)  # Dockerfile exec form: ["java", "-jar", ...]
            except ValueError:
                tokens = re.findall(r'"((?:[^"\\]|\\.)*)"', argument)  # buildkit history: ["java" "-jar" ...]
        else:
            tokens = ["/bin/sh", "-c", argument] if from_dockerfile else argument.split()
        argument = json.dumps(tokens)
    elif keyword == "EXPOSE":
        argument = " ".join(sorted(re.findall(r"\d+", argument)))
    elif keyword in ("ADD", "COPY"):
        argument = re.sub(r"--\S+\s+", "", argument)  # --chown / --chmod flags
    return f"{keyword} {' '.join(argument.split())}"


def compare_history_with_dockerfile(image: Dict[str, Any], dockerfile: Path) -> Dict[str, Any]:
    """Align the image build history with the upstream Dockerfile (FROM excluded; it is not in history)."""
    if not dockerfile.exists():
        return {"dockerfile": str(dockerfile), "error": "no upstream Dockerfile"}
    upstream = [
        normalize_instruction(line, from_dockerfile=True)
        for line in parse_dockerfile_instructions(dockerfile)
        if not line.upper().startswith("FROM ")
    ]
    history = [normalize_instruction(item.get("created_by") or "") for item in image["config"].get("history", [])]
    matcher = difflib.SequenceMatcher(a=upstream, b=history, autojunk=False)
    matched_upstream: set = set()
    matched_history: List[int] = []
    for block in matcher.get_matching_blocks():
        matched_upstream.update(range(block.a, block.a + block.size))
        matched_history.extend(range(block.b, block.b + block.size))
    first_own_step = min(matched_history) if matched_history else len(history)
    return {
        "dockerfile": str(dockerfile),
        "first_own_history_index": first_own_step,
        "upstream_steps_not_in_image": [upstream[index] for index in range(len(upstream)) if index not in matched_upstream],
        "image_steps_not_in_upstream": [
            history[index] for index in range(first_own_step, len(history)) if index not in matched_history
        ],
    }


def compare_source_layers_with_upstream(
    client: RegistryClient, image: Dict[str, Any], workdir: Path, upstream_dir: Path
) -> Dict[str, Any]:
    """Non-Java images: compare each file added by the image's own ADD/COPY steps with the upstream
    build context (the service directory of the upstream repository)."""
    repository = image["repository"]
    service_dir = upstream_dir / repository
    alignment = compare_history_with_dockerfile(image, service_dir / "Dockerfile")
    first_own_step = alignment.get("first_own_history_index", 0)
    files: Dict[str, Any] = {}
    current_workdir = "/"
    layer_index = -1
    for history_index, item in enumerate(image["config"].get("history", [])):
        instruction = normalize_instruction(item.get("created_by") or "")
        if not item.get("empty_layer"):
            layer_index += 1
        if instruction.startswith("WORKDIR "):
            current_workdir = posixpath.join(current_workdir, instruction[len("WORKDIR "):])
        match = SOURCE_COPY_PATTERN.match(instruction)
        if history_index < first_own_step or item.get("empty_layer") or not match:
            continue
        layer = image["layers"][layer_index]
        source, destination = match.group("source"), match.group("destination")
        destination_is_directory = destination.endswith("/") or destination in (".", "./")
        destination = posixpath.normpath(posixpath.join(current_workdir, destination))
        source_path = service_dir / source
        extract_root = workdir / "images" / repository / safe_reference(image["tag"]) / "files" / f"L{layer_index}"
        view = build_layer_view(client.get_blob_path(repository, layer["digest"]), extract_root)
        image_entries = {path: entry for path, entry in view.items() if entry.get("type") in ("file", "symlink")}
        expected: Dict[str, Path] = {}
        if source_path.is_dir():
            for upstream_file in source_path.rglob("*"):
                if upstream_file.is_symlink() or upstream_file.is_file():
                    expected[posixpath.join(destination, str(upstream_file.relative_to(source_path)))] = upstream_file
        else:
            target = posixpath.join(destination, source_path.name) if destination_is_directory else destination
            expected[target] = source_path
        for path in sorted(set(image_entries) | set(expected)):
            upstream_file, image_entry = expected.get(path), image_entries.get(path)
            label = f"L{layer_index} {path}"
            if image_entry is None:
                files[label] = "only in upstream"
            elif upstream_file is None or not (upstream_file.is_symlink() or upstream_file.exists()):
                files[label] = "only in image"
            elif upstream_file.is_symlink() or image_entry["type"] == "symlink":
                same_link = upstream_file.is_symlink() and image_entry.get("link") == str(upstream_file.readlink())
                files[label] = "identical" if same_link else (
                    f"symlink differs: upstream={'-> ' + str(upstream_file.readlink()) if upstream_file.is_symlink() else 'file'}"
                    f" image={'-> ' + str(image_entry.get('link')) if image_entry['type'] == 'symlink' else 'file'}"
                )
            elif hashlib.sha256(upstream_file.read_bytes()).hexdigest() == image_entry["sha256"]:
                files[label] = "identical"
            else:
                files[label] = text_diff(upstream_file.read_bytes(), Path(image_entry["extracted_to"]).read_bytes(), path)
    return {"history_vs_dockerfile": alignment, "files": files}


def scan_deployed_images(
    client: RegistryClient,
    deployed: Sequence[Tuple[str, str]],
    workdir: Path,
    upstream_dir: Path,
    needles: Sequence[str],
    keep_downloads: bool,
) -> List[str]:
    """Compare every deployed image with upstream source; return one roll-up line per image."""
    lines: List[str] = []
    rows: List[Dict[str, Any]] = []
    for repository, tag in deployed:
        print(f"scanning deployed {repository}:{tag}", flush=True)
        image = resolve_image(client, repository, tag, workdir)
        jar_layers = [
            layer for layer in image["layers"]
            if JAR_COPY_PATTERN.match((layer.get("created_by") or "").strip())
        ]
        row: Dict[str, Any] = {
            "repository": repository,
            "tag": tag,
            "index_digest": image["top_digest"],
            "created": image["config"].get("created"),
        }
        if not jar_layers:
            comparison = compare_source_layers_with_upstream(client, image, workdir, upstream_dir)
            row.update(kind="non-java", files=comparison["files"], history_vs_dockerfile=comparison["history_vs_dockerfile"])
            not_identical = [name for name, status in row["files"].items() if status != "identical"]
            alignment = row["history_vs_dockerfile"]
            lines.append(
                f"[deployed {repository}:{tag}] non-java; {len(row['files'])} source files compared; "
                f"not identical ({len(not_identical)}): {not_identical[:12] or 'none'}; "
                f"Dockerfile steps missing={alignment.get('upstream_steps_not_in_image')} "
                f"extra={alignment.get('image_steps_not_in_upstream')}"
            )
            rows.append(row)
            continue
        row["history_vs_dockerfile"] = compare_history_with_dockerfile(image, upstream_dir / repository / "Dockerfile")
        jar_layer = jar_layers[-1]
        blob_path = client.blob_cache_dir / "sha256" / jar_layer["digest"].split(":", 1)[1]
        blob_was_cached = blob_path.exists()
        extract_root = workdir / "images" / repository / safe_reference(tag) / "files" / f"L{jar_layer['index']}"
        extract_existed = extract_root.exists()
        view = build_layer_view(client.get_blob_path(repository, jar_layer["digest"]), extract_root)
        jar_path_in_image = find_application_jar(view)
        application_jar = Path(view[jar_path_in_image]["extracted_to"])
        result = compare_image_with_upstream(
            repository, tag, application_jar, upstream_dir, workdir, keep_libs=keep_downloads
        )
        hits = grep_jar(application_jar, [needle.encode("utf-8") for needle in needles]) if needles else {}
        service, common = result["service_classes"], result["ts_common_classes"]
        differing_resources = [name for name, status in result["resources"].items() if status != "identical"]
        row.update(
            {
                "kind": "java",
                "jar": jar_path_in_image,
                "jar_sha256": view[jar_path_in_image]["sha256"],
                "compile_ok": result["compile_ok"],
                "service_classes": {
                    "image": service["image_class_count"],
                    "byte_identical": service["byte_identical"],
                    "identical_after_normalisation": len(service["identical_after_javap_normalisation"]),
                    "different": sorted(service["different"]),
                    "only_in_image": service["only_in_image"],
                    "only_in_upstream": service["only_in_upstream_compile"],
                },
                "ts_common": {
                    "image": common["image_class_count"],
                    "byte_identical": common["byte_identical"],
                    "different": sorted(common["different"]),
                },
                "resources_not_identical": differing_resources,
                "grep": hits,
                "libs": result["libs"],
            }
        )
        rows.append(row)
        lines.append(
            f"[deployed {repository}:{tag}] compile_ok={result['compile_ok']} service classes: "
            f"{service['byte_identical']}/{service['image_class_count']} byte-identical, "
            f"{len(service['identical_after_javap_normalisation'])} normalised-identical, "
            f"different={sorted(service['different'])}, only-image={service['only_in_image']}, "
            f"only-upstream={service['only_in_upstream_compile']}; ts-common "
            f"{common['byte_identical']}/{common['image_class_count']} byte-identical; "
            f"resources not identical={differing_resources}; grep={ {k: len(v) for k, v in hits.items()} }; "
            f"Dockerfile steps missing={row['history_vs_dockerfile'].get('upstream_steps_not_in_image')} "
            f"extra={row['history_vs_dockerfile'].get('image_steps_not_in_upstream')}"
        )
        if not keep_downloads:  # the jar layer of an image that is not part of a pair: ~70 MB + ~80 MB
            if not blob_was_cached:
                blob_path.unlink()
            if not extract_existed:
                shutil.rmtree(extract_root)
    scan_dir = workdir / "deployed-scan"
    scan_dir.mkdir(parents=True, exist_ok=True)
    (scan_dir / "summary.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False, default=str))
    (scan_dir / "report.txt").write_text("\n".join(lines) + "\n")
    return lines


def grep_jar(jar_path: Path, needles: Sequence[bytes]) -> Dict[str, List[str]]:
    """For each needle, the 'entry' / 'nested.jar!entry' names whose uncompressed bytes contain it."""
    hits: Dict[str, List[str]] = {needle.decode("utf-8"): [] for needle in needles}

    def check(label: str, data: bytes) -> None:
        for needle in needles:
            if needle in data:
                hits[needle.decode("utf-8")].append(label)

    with zipfile.ZipFile(jar_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            data = archive.read(info.filename)
            check(info.filename, data)
            if info.filename.endswith(".jar"):
                with zipfile.ZipFile(io.BytesIO(data)) as nested:
                    for nested_info in nested.infolist():
                        if not nested_info.is_dir():
                            check(f"{info.filename}!{nested_info.filename}", nested.read(nested_info.filename))
    return hits


# --------------------------------------------------------------------------------------------------
# Roll-up
# --------------------------------------------------------------------------------------------------

def one_line_verdict(summary: Dict[str, Any]) -> str:
    """Mechanical classification only; the human judgement lives in README.md."""
    if summary["layers"]["identical"]:
        return "identical layers"
    jar = summary.get("jar")
    if not jar:
        return "layers differ, no application jar pair found"
    counts = {
        category: sum(len(names) for names in statuses.values())
        for category, statuses in jar["by_category"].items()
    }
    semantic_class_changes = [
        name for name, comparison in jar["class_diffs"].items() if not comparison["identical_after_normalisation"]
    ]
    nested = {
        name: [
            class_name for class_name, comparison in nested_jar["class_diffs"].items()
            if not comparison["identical_after_normalisation"]
        ]
        for name, nested_jar in jar["nested_jar_diffs"].items()
    }
    return (
        f"jar entries changed by category={counts}; classes with semantic bytecode change={semantic_class_changes}; "
        f"nested jar class changes={nested}; runtime config diffs={list(summary['config']['runtime_config_differences'])}"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workdir", type=Path, default=DEFAULT_WORKDIR)
    parser.add_argument("--upstream-dir", type=Path, default=DEFAULT_UPSTREAM_DIR)
    parser.add_argument(
        "--pair", action="append", default=[], type=parse_pair_argument,
        help="repo:old:new, old/new = tag or sha256:<digest> (repeatable; replaces the default pairs)",
    )
    parser.add_argument("--skip-inventory", action="store_true")
    parser.add_argument("--upstream-compile", action="store_true", help="compare every image jar with upstream")
    parser.add_argument(
        "--grep", action="append", default=[],
        help="byte string to look for in every entry (and nested-jar entry) of each application jar",
    )
    parser.add_argument(
        "--scan-deployed", action="store_true",
        help="also compare every ts-* image named in --deployments-json with upstream source",
    )
    parser.add_argument("--deployments-json", type=Path, default=DEFAULT_DEPLOYMENTS_JSON)
    parser.add_argument(
        "--keep-downloads", action="store_true",
        help="keep jar layers / extracted libs downloaded only for --scan-deployed (default: delete after use)",
    )
    parser.add_argument("--no-pairs", action="store_true", help="skip the pair comparisons")
    arguments = parser.parse_args(argv)

    if shutil.which("javap") is None:
        print("javap not found on PATH", file=sys.stderr)
        return 2
    workdir: Path = arguments.workdir
    workdir.mkdir(parents=True, exist_ok=True)
    client = RegistryClient(HARBOR_BASE_URL, HARBOR_PROJECT, workdir / "blobs")
    pairs = arguments.pair or DEFAULT_COMPARISON_PAIRS

    roll_up: List[str] = []
    if not arguments.skip_inventory:
        rows = build_inventory(workdir)
        roll_up.append(f"[inventory] {len(rows)} ts-* tags -> {workdir / 'inventory' / 'harbor_ts_tags.txt'}")

    application_jars: Dict[Tuple[str, str], Path] = {}
    for repository, old_tag, new_tag in ([] if arguments.no_pairs else pairs):
        print(f"comparing {repository} {old_tag} -> {new_tag}", flush=True)
        summary = compare_pair(client, repository, old_tag, new_tag, workdir)
        roll_up.append(f"[{repository} {old_tag} -> {new_tag}] {one_line_verdict(summary)}")
        if "jar" in summary:
            application_jars[(repository, old_tag)] = Path(summary["jar"]["old_jar"])
            application_jars[(repository, new_tag)] = Path(summary["jar"]["new_jar"])

    if arguments.grep:
        for (repository, tag), jar_path in sorted(application_jars.items()):
            hits = grep_jar(jar_path, [needle.encode("utf-8") for needle in arguments.grep])
            roll_up.append(f"[grep in {repository}:{tag}] {hits}")

    if arguments.upstream_compile:
        for (repository, tag), jar_path in sorted(application_jars.items()):
            print(f"upstream compile check {repository}:{tag}", flush=True)
            result = compare_image_with_upstream(repository, tag, jar_path, arguments.upstream_dir, workdir)
            service, common = result["service_classes"], result["ts_common_classes"]
            differing_resources = [name for name, status in result["resources"].items() if status != "identical"]
            roll_up.append(
                f"[upstream vs {repository}:{tag}] compile_ok={result['compile_ok']} "
                f"service: byte-identical {service['byte_identical']}/{service['image_class_count']}, "
                f"normalised-identical {len(service['identical_after_javap_normalisation'])}, "
                f"different {sorted(service['different'])}, only-image {service['only_in_image']}, "
                f"only-upstream {service['only_in_upstream_compile']}; "
                f"ts-common: byte-identical {common['byte_identical']}/{common['image_class_count']}, "
                f"different {sorted(common['different'])}; resources not identical: {differing_resources}"
            )
    if arguments.scan_deployed:
        deployed = load_deployed_images(arguments.deployments_json)
        roll_up.append(f"[deployed] {len(deployed)} ts-* images from {arguments.deployments_json}")
        roll_up.extend(
            scan_deployed_images(
                client, deployed, workdir, arguments.upstream_dir, arguments.grep, arguments.keep_downloads
            )
        )

    summary_name = "summary-deployed-scan.txt" if arguments.no_pairs else "summary.txt"
    (workdir / summary_name).write_text("\n".join(roll_up) + "\n")
    print("\n".join(roll_up))
    return 0


if __name__ == "__main__":
    sys.exit(main())
