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

# The argparse destinations for the three flags that move the pin. They are accepted only together.
MOVE_FLAGS = ("commit", "expect_sha256", "expect_bytes")


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


def constants_drift(commit, expected_bytes, expected_sha256):
    """Compare three accepted values against the module constants. Empty means they agree.

    The failure this catches: a move that supplied all three flags but left the constants behind.
    The file on disk then holds the new commit's bytes while SPEC_COMMIT, EXPECTED_BYTES and
    EXPECTED_SHA256 still hold the old ones. The next plain `python generator/fetch_spec.py`
    refetches the old commit, passes tier 1 against the old constants, and rewrites both the spec
    and the provenance back to the old pin. `git status` shows that change, so it is not invisible,
    but the developer believes the pin already moved and has no reason to look. The repository ends
    up on a pin nobody chose, and everything generated after that point is built from the wrong
    document.
    """
    drift = []
    for name, held, accepted in (
        ("SPEC_COMMIT", SPEC_COMMIT, commit),
        ("EXPECTED_BYTES", EXPECTED_BYTES, expected_bytes),
        ("EXPECTED_SHA256", EXPECTED_SHA256, expected_sha256),
    ):
        if held != accepted:
            drift.append(
                "WARNING: {} still holds {}, but this move accepted {}. Update it in the same "
                "commit that moves the pin.".format(name, held, accepted)
            )
    return drift


def build_parser():
    parser = argparse.ArgumentParser(
        prog="fetch_spec.py",
        description="Fetch the pinned Whisparr 2 OpenAPI document from Whisparr/Whisparr by commit.",
    )
    parser.add_argument("--out-file", default=DEFAULT_OUT_FILE)

    move = parser.add_argument_group(
        "moving the pin",
        "All three are required together. Supplying only some of them is a refusal, not a bypass.",
    )
    move.add_argument("--commit", metavar="SHA40")
    move.add_argument("--expect-sha256", metavar="HEX64")
    move.add_argument("--expect-bytes", metavar="N", type=int)

    parser.add_argument(
        "--propose",
        metavar="SHA40",
        help="Fetch this commit read-only, print observed size, sha256 and blob sha1, write nothing.",
    )
    return parser


def flag_name(destination):
    return "--" + destination.replace("_", "-")


def check_flag_contract(parser, args):
    """Refuse a partial move and refuse a proposal combined with a move.

    parser.error exits 2 and die exits 1, and the two stay distinct: 2 means the caller invoked the
    script wrongly, 1 means the bytes are not what the caller said they would be. Both are non-zero,
    so both fail closed in any shell and in any CI step.

    argparse offers only add_mutually_exclusive_group, which enforces the opposite relation, so
    parser.error is the documented mechanism for a condition the application defines.
    """
    supplied = [name for name in MOVE_FLAGS if getattr(args, name) is not None]

    if args.propose and supplied:
        parser.error(
            "--propose writes nothing and cannot be combined with "
            + ", ".join(flag_name(name) for name in supplied)
            + "."
        )

    if supplied and len(supplied) != len(MOVE_FLAGS):
        missing = [name for name in MOVE_FLAGS if getattr(args, name) is None]
        parser.error(
            "moving the pin requires --commit, --expect-sha256 and --expect-bytes together; "
            "missing "
            + ", ".join(flag_name(name) for name in missing)
            + ". Run --propose "
            + (args.commit or "<sha>")
            + " to observe the values first."
        )


def run_propose(commit):
    """Fetch a candidate read-only, print what the write path will demand, and write nothing.

    It runs tier 2 and tier 3 and never tier 1. Tier 1 is the pin, and a proposal has no pin yet,
    while tiers 2 and 3 are properties of the application and must hold for any candidate. So a
    proposal against the wrong application refuses in words rather than printing values that invite
    a paste.

    It is called from main() and returns out of it before the write section, rather than sharing a
    code path with the write and gating the final open. That sharing is how a proposal mode becomes
    the bypass D-04 exists to prevent.
    """
    url = spec_url(commit)
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

    # Exactly the three values the write path will demand, which is the purpose of the mode.
    print("Proposal for commit " + commit)
    print("  --expect-bytes   {}".format(len(body)))
    print("  --expect-sha256  " + hashlib.sha256(body).hexdigest())
    print("  blob sha1        " + git_blob_sha1(body))

    problems = check_tier2(document) + check_tier3(document)
    if problems:
        die(*problems)
    print("Nothing was written.")


def main():
    parser = build_parser()
    args = parser.parse_args()
    check_flag_contract(parser, args)

    if args.propose:
        run_propose(args.propose)
        return

    out_path = resolve_repo_path(args.out_file)
    provenance_path = resolve_repo_path(PROVENANCE_PATH)

    # A move runs tier 1 against the values the caller stated in advance, so there is no path that
    # writes bytes nobody predicted.
    moving = args.commit is not None
    commit = args.commit if moving else SPEC_COMMIT
    expected_bytes = args.expect_bytes if moving else EXPECTED_BYTES
    expected_sha256 = args.expect_sha256 if moving else EXPECTED_SHA256

    url = spec_url(commit)
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

    # The caller states a size and a sha256. The blob sha1 is a function of those same bytes, so on
    # the move path it is recomputed and recorded rather than gated; there is nothing left for it to
    # catch once the length and the sha256 both match.
    expected_blob = git_blob_sha1(body) if moving else EXPECTED_BLOB_SHA1

    problems = (
        check_tier1(body, expected_bytes, expected_sha256, expected_blob)
        + check_tier2(document)
        + check_tier3(document)
    )
    if problems:
        die(*problems)

    provenance = build_spec_provenance(commit, url, body, document)

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    write_bytes_atomic(out_path, body)
    write_provenance(provenance_path, provenance)

    print("  + {} bytes".format(provenance["specBytes"]))
    print("  + sha256 " + provenance["specSha256"])
    print("  + blob   " + provenance["specBlobSha1"])
    print("Done. " + out_path)

    if moving:
        print("Copy the accepted values into the module constants in the same commit:")
        print('  SPEC_COMMIT = "{}"'.format(commit))
        print("  EXPECTED_BYTES = {}".format(provenance["specBytes"]))
        print('  EXPECTED_SHA256 = "{}"'.format(provenance["specSha256"]))
        print('  EXPECTED_BLOB_SHA1 = "{}"'.format(provenance["specBlobSha1"]))
        # The move itself succeeded, so this is a warning about work left undone and not a
        # rejection. Exit stays 0 either way.
        for line in constants_drift(commit, expected_bytes, expected_sha256):
            print(line)


if __name__ == "__main__":
    main()
