#!/usr/bin/env python3
"""Fetch the Whisparr 2 OpenAPI document from a pinned commit in Whisparr/Whisparr.

Whisparr 2 serves no spec endpoint, so there is nothing to capture from a running instance. The
document is a git blob in the upstream repository, addressed by commit. This script fetches it,
verifies it three ways before writing anything, and records what it observed in
spec/PROVENANCE.json.

The fetch URL carries a commit SHA and never a ref name. A commit is content-addressed, so the URL
names exactly one tree.

    python generator/fetch_spec.py
"""

import argparse
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone

from _common import USER_AGENT, die, git_blob_sha1, resolve_repo_path, write_json_lf

SPEC_REPO = "Whisparr/Whisparr"  # measured 2026-09-05
# Recorded in provenance only, and never used to build a URL. A ref name moves, and the whole point
# of the pin is that it does not.  measured 2026-09-05
SPEC_REF_NAME = "v2"
SPEC_COMMIT = "face3be8956e4c3798a9364a0f2ea95948e34c1c"  # measured 2026-09-05
SPEC_PATH = "src/Whisparr.Api.V3/openapi.json"  # measured 2026-09-05
EXPECTED_BYTES = 282862  # measured 2026-09-05
EXPECTED_SHA256 = "e16d5052c6da3fdb9c54739890412c340c4b485c0a1b53af15f5a6ac837bb0a2"  # measured 2026-09-05
EXPECTED_BLOB_SHA1 = "a3037cf379826505dc4557e74bf0798f43f2d4b8"  # measured 2026-09-05

DEFAULT_OUT_FILE = "spec/openapi.raw.json"
PROVENANCE_PATH = "spec/PROVENANCE.json"

RAW_HOST = "https://raw.githubusercontent.com/"

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def spec_url(commit):
    """The commit-addressed raw URL for the pinned path.

    It takes a commit and nothing else, so no ref name can reach a URL. It is a function so the
    normal path and any candidate-proposal path cannot build different URLs.
    """
    return RAW_HOST + SPEC_REPO + "/" + commit + "/" + SPEC_PATH


def http_get_bytes(url, timeout=60):
    """Return (status, body bytes). A refused connection is status 0, not an exception.

    The status is returned rather than raised so a 404 on a wrong commit is a refusal message and
    not a traceback.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except (urllib.error.URLError, OSError):
        return 0, b""


def check_tier1(body, expected_bytes, expected_sha256, expected_blob):
    """Pin the bytes. Returns refusal lines, and an empty list means pass.

    Compares an exact integer and lowercase hex strings. It never rounds and never converts.
    """
    problems = []
    if len(body) == 0:
        problems.append(
            "ERROR: REFUSED - the response body is empty. A zero-length document is not a spec. "
            "Nothing was written."
        )
        return problems
    if len(body) != expected_bytes:
        problems.append(
            "ERROR: REFUSED - the body is {} bytes, expected exactly {}. Nothing was "
            "written.".format(len(body), expected_bytes)
        )
    observed_sha256 = hashlib.sha256(body).hexdigest()
    if observed_sha256 != expected_sha256:
        problems.append(
            "ERROR: REFUSED - sha256 is {}, expected {}. Nothing was written.".format(
                observed_sha256, expected_sha256
            )
        )
    observed_blob = git_blob_sha1(body)
    if observed_blob != expected_blob:
        problems.append(
            "ERROR: REFUSED - git blob sha1 is {}, expected {}. Nothing was written.".format(
                observed_blob, expected_blob
            )
        )
    return problems


def check_tier2(document):
    """The eros discriminator. Path presence only, never openapi or info.version.

    Measured 2026-09-05: both documents declare openapi 3.0.1 and info.version 3.0.0, and both
    declare info.title Whisparr. Path presence is the only thing that separates them.
    """
    paths = document.get("paths") or {}
    required = [p for p in ("/api/v3/series", "/api/v3/episode") if p not in paths]
    forbidden = [p for p in ("/api/v3/movie", "/api/v3/alttitle") if p in paths]
    if not required and not forbidden:
        return []
    return [
        "ERROR: REFUSED - this document declares {} and not {}. That is the eros branch of "
        "Whisparr/Whisparr, which is Whisparr 3, not Whisparr 2. Nothing was written.".format(
            ", ".join(forbidden) or "none of /api/v3/movie or /api/v3/alttitle",
            ", ".join(required) or "the expected paths /api/v3/series and /api/v3/episode",
        )
    ]


def check_tier3(document):
    """The precondition pre-processing needs. Derived from the document rather than pinned."""
    problems = []
    version = document.get("openapi")
    if not (isinstance(version, str) and version.startswith("3.0.")):
        problems.append(
            "ERROR: REFUSED - the document declares openapi {!r}, expected a 3.0.x document. "
            "Nothing was written.".format(version)
        )
    paths = document.get("paths") or {}
    if "/" not in paths:
        problems.append(
            "ERROR: REFUSED - the document does not declare the malformed root path. "
            "Pre-processing removes it, and its absence means this is not the document the "
            "pipeline was measured against. Nothing was written."
        )
    return problems


def describe(body, document):
    """The four recorded-not-gated observations.

    They are recorded because a reader wants to see them. They are not gates because tier 1 already
    fixes the content exactly.
    """
    paths = document.get("paths") or {}
    operations = 0
    for methods in paths.values():
        if isinstance(methods, dict):
            operations += sum(1 for key in methods if key.lower() in HTTP_METHODS)
    schemas = (document.get("components") or {}).get("schemas") or {}
    return {
        "specOpenApiVersion": document.get("openapi"),
        "specPathCount": len(paths),
        "specOperationCount": operations,
        "specSchemaCount": len(schemas),
    }


def write_bytes_atomic(path, data):
    """Write data to path so an interrupted run never leaves a truncated file.

    The temporary file is created in the same directory as path, because os.replace is atomic only
    within one filesystem. Either the complete new bytes land or the previous file is unchanged.
    """
    directory = os.path.dirname(os.path.abspath(path))
    handle = tempfile.NamedTemporaryFile(dir=directory, prefix=".tmp-", delete=False)
    try:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
    except BaseException:
        handle.close()
        os.remove(handle.name)
        raise
    os.replace(handle.name, path)


def build_spec_provenance(commit, url, body, document):
    """The thirteen fields this script owns, in recorded order."""
    observed = describe(body, document)
    return {
        "fetchedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "fetchedFrom": url,
        "specRepo": SPEC_REPO,
        "specRefName": SPEC_REF_NAME,
        "specCommit": commit,
        "specPath": SPEC_PATH,
        "specBlobSha1": git_blob_sha1(body),
        "specSha256": hashlib.sha256(body).hexdigest(),
        "specBytes": len(body),
        "specOpenApiVersion": observed["specOpenApiVersion"],
        "specPathCount": observed["specPathCount"],
        "specOperationCount": observed["specOperationCount"],
        "specSchemaCount": observed["specSchemaCount"],
    }


def write_provenance(path, spec_fields):
    """Merge the spec block into provenance, preserving the fields this script does not own.

    Re-assigning an existing key keeps its position, so the image block verify_image.py writes stays
    where it was and a re-run of either script does not reorder the file.
    """
    document = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    for key, value in spec_fields.items():
        document[key] = value
    # A new fetch invalidates the patched spec, and preprocess_spec.py is what puts this field back.
    document.pop("generatedSpecSha256", None)
    # A null is not an observation. Checked over the thirteen keys this script wrote and not over the
    # merged document, so a field owned by another script cannot implicate this one.
    unobserved = [
        key
        for key, value in spec_fields.items()
        if value is None or (isinstance(value, str) and not value.strip())
    ]
    if unobserved:
        die(
            "ERROR: REFUSED - provenance would record no observed value for: {}. {} is "
            "untouched.".format(", ".join(unobserved), path)
        )
    write_json_lf(path, document)


def build_parser():
    parser = argparse.ArgumentParser(description="Fetch the pinned Whisparr 2 OpenAPI document.")
    parser.add_argument("--out-file", default=DEFAULT_OUT_FILE)
    return parser


def main():
    args = build_parser().parse_args()
    out_path = resolve_repo_path(args.out_file)
    provenance_path = resolve_repo_path(PROVENANCE_PATH)

    url = spec_url(SPEC_COMMIT)
    print("Fetching " + url)
    status, body = http_get_bytes(url)
    if status != 200:
        die("ERROR: REFUSED - {} answered HTTP {}. Nothing was written.".format(url, status))

    try:
        document = json.loads(body)
    except json.JSONDecodeError as error:
        die(
            "ERROR: REFUSED - the response body is not valid JSON: {}. Nothing was "
            "written.".format(error)
        )

    problems = (
        check_tier1(body, EXPECTED_BYTES, EXPECTED_SHA256, EXPECTED_BLOB_SHA1)
        + check_tier2(document)
        + check_tier3(document)
    )
    if problems:
        die(*problems)

    provenance = build_spec_provenance(SPEC_COMMIT, url, body, document)

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    write_bytes_atomic(out_path, body)
    write_provenance(provenance_path, provenance)

    print("  + {} bytes".format(provenance["specBytes"]))
    print("  + sha256 " + provenance["specSha256"])
    print("  + blob   " + provenance["specBlobSha1"])
    print("Done. " + out_path)


if __name__ == "__main__":
    main()
