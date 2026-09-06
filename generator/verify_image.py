#!/usr/bin/env python3
"""Identity-check the pinned Whisparr 2 container image and record what it reported.

The same image name carries tags for a different application. A digest that turned out to be
Whisparr 3 would make every later integration test prove the client against the wrong application,
and the API prefix and the application name are identical on both, so neither discriminates.

Boots the pinned digest with a seeded config.xml, reads GET /api/v3/system/status with the seeded
key, refuses unless the instance reports branch v2 and major version 2, then merges six image
fields into spec/PROVENANCE.json. The container is removed whether the run succeeded or failed.

Requires Docker. Run it when the pin moves, not per change.

    python generator/verify_image.py
"""

import argparse
import json
import os
import xml.etree.ElementTree as ElementTree

from _common import die, resolve_repo_path, write_json_lf

IMAGE_TAG = "ghcr.io/hotio/whisparr:v2-2.2.0-release.231"  # measured 2026-09-05
IMAGE_DIGEST = "sha256:c6dae7dc99b52c3f73b64c9eca9bb38db0f646c98a3ea5829c57b1ebdce0d170"  # measured 2026-09-05
# Only the digest is ever used to run. The tag is recorded beside it so a reader can tell which
# release line the digest belongs to, and the repository name is taken from the tag rather than
# written twice.  measured 2026-09-05
IMAGE_REF = IMAGE_TAG.rsplit(":", 1)[0] + "@" + IMAGE_DIGEST
CONTAINER_NAME = "whisparr2-verify"  # measured 2026-09-05

SEED_FILE = "generator/config.seed.xml"  # measured 2026-09-05
# One committed seed, read once. The key comes out of the same document that is copied into the
# container, so the script cannot hold a key the container was never given.  measured 2026-09-05
with open(resolve_repo_path(SEED_FILE), "rb") as _seed_handle:
    SEED_BYTES = _seed_handle.read()
API_KEY = ElementTree.fromstring(SEED_BYTES).findtext("ApiKey")  # measured 2026-09-05

CONTAINER_PORT = 6969  # measured 2026-09-05
READY_TIMEOUT_SEC = 120  # measured 2026-09-05
PROVENANCE_PATH = "spec/PROVENANCE.json"  # measured 2026-09-05
EXPECTED_BRANCH = "v2"  # measured 2026-09-05
EXPECTED_MAJOR = 2  # measured 2026-09-05
# At a root-owned 0755 seed the identity read still succeeds and this is the only trace of the
# failure. Grepping the log for it is what stops that defect reaching the integration suite.
FORBIDDEN_LOG_MARKER = "UnauthorizedAccessException"  # measured 2026-09-05


def assert_identity(status):
    """Return refusal lines for a status document. An empty list means the identity holds.

    Pure, and takes a dict, which is what lets every identity assertion run with no Docker daemon.
    It reads branch and the major component of version and nothing else: appName is Whisparr on
    both applications and the API prefix is /api/v3 on both, so neither discriminates.
    """
    branch = status.get("branch")
    version = status.get("version")
    # An absent or unparseable version is a failed assertion, not a raise.
    major = None
    if isinstance(version, str):
        head = version.split(".")[0]
        if head.isdigit():
            major = int(head)
    if branch != EXPECTED_BRANCH or major != EXPECTED_MAJOR:
        return [
            "ERROR: REFUSED - the instance reports branch '{}' version '{}'. Required: branch "
            "'{}' and major version {}.".format(branch, version, EXPECTED_BRANCH, EXPECTED_MAJOR)
        ]
    return []


def image_provenance(status):
    """The six provenance fields this script owns, and no others."""
    return {
        "imageTag": IMAGE_TAG,
        "imageDigest": IMAGE_REF,
        "whisparrVersion": status.get("version"),
        "whisparrBranch": status.get("branch"),
        "whisparrBuildTime": status.get("buildTime"),
        "whisparrPackageVersion": status.get("packageVersion"),
    }


def merge_image_provenance(path, updates):
    """Merge the image block into a provenance document this script does not create.

    Refuses when the file is absent rather than creating one with an image block and no spec block,
    which keeps the ordering between the two scripts explicit rather than implicit in the file's
    contents.
    """
    provenance_path = resolve_repo_path(path)
    if not os.path.exists(provenance_path):
        die(
            "ERROR: REFUSED - {} does not exist. Run generator/fetch_spec.py first: it writes the "
            "spec block this script merges into.".format(provenance_path)
        )

    # A null is not an observation. The comprehension runs over the six keys this script owns,
    # before the merge, so a pre-existing key it does not own cannot implicate it.
    unobserved = [
        key
        for key, value in updates.items()
        if value is None or (isinstance(value, str) and not value.strip())
    ]
    if unobserved:
        die(
            "ERROR: REFUSED - provenance would record no observed value for: {}. {} is "
            "untouched.".format(", ".join(unobserved), provenance_path)
        )

    with open(provenance_path, encoding="utf-8") as handle:
        provenance = json.load(handle)
    # Python dicts preserve insertion order and re-assigning an existing key keeps its position, so
    # these land after the spec block on a first run and stay put on a re-run.
    for key, value in updates.items():
        provenance[key] = value
    write_json_lf(provenance_path, provenance)
    return provenance_path
