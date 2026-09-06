#!/usr/bin/env python3
"""Prove the two refusals that stand between this repository and the wrong application.

The failure this guards against is silent. If the eros document is accepted, or if bytes nobody
stated in advance are accepted, the result is a client that compiles, produces no warnings, passes a
build and targets a different application. That defect surfaces long after generation, packaging and
documentation have all been built on the wrong document.

Standard library only. No framework, no requirements file and no configuration file. A bare assert
and a non-zero exit are what this needs.

    python generator/selftest.py
    python generator/selftest.py --network
"""

import argparse
import contextlib
import io
import json
import os
import tempfile

import fetch_spec
from _common import git_blob_sha1, resolve_repo_path, sha256_file

# The thirteen spec fields fetch_spec.py owns. verify_image.py owns the image block, and this list
# deliberately does not name it, so a missing image field cannot implicate the fetch.
SPEC_KEYS = (
    "fetchedAt",
    "fetchedFrom",
    "specRepo",
    "specRefName",
    "specCommit",
    "specPath",
    "specBlobSha1",
    "specSha256",
    "specBytes",
    "specOpenApiVersion",
    "specPathCount",
    "specOperationCount",
    "specSchemaCount",
)

HEX = set("0123456789abcdef")

# Git's well-known hash of the empty blob. Reproducible with `git hash-object -t blob /dev/null`.
EMPTY_BLOB_SHA1 = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


def document(openapi, version, paths):
    """A synthetic OpenAPI document carrying only what the checks read.

    Roughly 200 bytes rather than a 337 KB committed fixture. Both real documents declare openapi
    3.0.1 and info.version 3.0.0, so the passing dict carries those values and the non-discriminator
    assertion tests the real condition rather than an invented one.
    """
    return {
        "openapi": openapi,
        "info": {"title": "Whisparr", "version": version},
        "paths": {path: {"get": {"operationId": "stub"}} for path in paths},
    }


WHISPARR2_PATHS = ("/", "/api/v3/series", "/api/v3/episode")
EROS_PATHS = ("/", "/api/v3/movie", "/api/v3/alttitle")


def read_committed_spec():
    return resolve_repo_path(fetch_spec.DEFAULT_OUT_FILE)


def read_provenance():
    with open(resolve_repo_path(fetch_spec.PROVENANCE_PATH), encoding="utf-8") as handle:
        return json.load(handle)


def check_discriminator():
    """An eros-shaped document is refused, and the refusal names both paths in words."""
    problems = fetch_spec.check_tier2(document("3.0.1", "3.0.0", EROS_PATHS))
    assert len(problems) == 1, problems
    assert "/api/v3/movie" in problems[0], problems[0]
    assert "/api/v3/series" in problems[0], problems[0]
    assert "eros" in problems[0], problems[0]

    assert fetch_spec.check_tier2(document("3.0.1", "3.0.0", WHISPARR2_PATHS)) == []
    print("ok  discriminator: eros refused naming /api/v3/movie and /api/v3/series, v2 accepted")


def check_non_discriminator():
    """openapi and info.version do not affect the verdict, in either direction."""
    accepted = fetch_spec.check_tier2(document("3.0.1", "3.0.0", WHISPARR2_PATHS))
    assert fetch_spec.check_tier2(document("3.1.4", "9.9.9", WHISPARR2_PATHS)) == accepted

    refused = fetch_spec.check_tier2(document("3.0.1", "3.0.0", EROS_PATHS))
    assert fetch_spec.check_tier2(document("3.1.4", "9.9.9", EROS_PATHS)) == refused
    print("ok  non-discriminator: openapi and info.version do not change the verdict")


def check_tier1_boundaries():
    """The pin holds at one byte either side and at zero length."""
    with open(read_committed_spec(), "rb") as handle:
        body = handle.read()
    expected = (
        fetch_spec.EXPECTED_BYTES,
        fetch_spec.EXPECTED_SHA256,
        fetch_spec.EXPECTED_BLOB_SHA1,
    )

    assert fetch_spec.check_tier1(body, *expected) == []
    assert fetch_spec.check_tier1(body[:-1], *expected) != []
    assert fetch_spec.check_tier1(body + b"x", *expected) != []

    empty = fetch_spec.check_tier1(b"", *expected)
    assert len(empty) == 1 and "empty" in empty[0], empty
    print("ok  tier 1: the committed body passes, one byte either side and zero length refuse")


def check_blob_identity():
    """git_blob_sha1 reproduces git's own object identity."""
    assert git_blob_sha1(b"") == EMPTY_BLOB_SHA1
    print("ok  blob identity: git_blob_sha1 of the empty input is git's empty-blob hash")


def check_atomic_write():
    """A write that raises leaves the previous file byte-identical and no temp file behind."""
    known = b"the previous contents\n"
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "pinned.bin")
        with open(path, "wb") as handle:
            handle.write(known)

        # Not a bytes-like object, so handle.write raises before os.replace is reached.
        try:
            fetch_spec.write_bytes_atomic(path, object())
        except TypeError:
            pass
        else:
            raise AssertionError("write_bytes_atomic accepted a payload that cannot be written")

        with open(path, "rb") as handle:
            assert handle.read() == known
        assert os.listdir(directory) == ["pinned.bin"], os.listdir(directory)
    print("ok  atomic write: a failed write leaves the target intact and no temp file behind")


def check_committed_spec():
    """The file on disk still matches its own recorded byte count, sha256 and blob sha1.

    This is the assertion that catches a CRLF-mangled checkout. With core.autocrlf=true and no
    .gitattributes rule the checked-out spec carries injected CR bytes and none of the three match.
    """
    provenance = read_provenance()
    path = read_committed_spec()
    with open(path, "rb") as handle:
        body = handle.read()

    assert len(body) == provenance["specBytes"], (len(body), provenance["specBytes"])
    assert sha256_file(path) == provenance["specSha256"]
    assert git_blob_sha1(body) == provenance["specBlobSha1"]
    print("ok  committed spec: bytes, sha256 and blob sha1 on disk match provenance")


def check_provenance_complete():
    """Every spec field is present and observed, and the patched-spec field is absent."""
    provenance = read_provenance()

    for key in SPEC_KEYS:
        assert key in provenance, key
        value = provenance[key]
        assert value is not None, key
        assert not (isinstance(value, str) and not value.strip()), key

    assert type(provenance["specBytes"]) is int, type(provenance["specBytes"])

    sha256 = provenance["specSha256"]
    assert len(sha256) == 64 and set(sha256) <= HEX, sha256
    blob = provenance["specBlobSha1"]
    assert len(blob) == 40 and set(blob) <= HEX, blob

    assert "generatedSpecSha256" not in provenance
    print("ok  provenance: thirteen spec fields present and observed, no patched-spec field")


def parse_and_check(argv):
    """Run the flag contract over one argv vector. Returns (exit code, stderr text).

    argparse writes usage and the message to stderr and raises SystemExit, so the buffer is what
    carries the message text the assertions read. No subprocess and no network.
    """
    parser = fetch_spec.build_parser()
    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer):
        try:
            args = parser.parse_args(argv)
            fetch_spec.check_flag_contract(parser, args)
        except SystemExit as stop:
            return stop.code, buffer.getvalue()
    return 0, buffer.getvalue()


def check_flag_vectors():
    """The six flag vectors of D-04, and the three constants-drift vectors of the move path."""
    destinations = sorted(vars(fetch_spec.build_parser().parse_args([])))
    assert destinations == ["commit", "expect_bytes", "expect_sha256", "out_file", "propose"], (
        destinations
    )

    code, _ = parse_and_check([])
    assert code == 0, code

    code, message = parse_and_check(["--commit", "abc"])
    assert code == 2, code
    assert "--expect-sha256" in message and "--expect-bytes" in message, message
    assert message.rstrip().endswith("Run --propose abc to observe the values first."), message

    code, message = parse_and_check(["--commit", "abc", "--expect-sha256", "d"])
    assert code == 2, code
    assert "--expect-bytes" in message, message
    assert "--expect-sha256" not in message.split("missing", 1)[1], message

    code, _ = parse_and_check(["--commit", "abc", "--expect-sha256", "d", "--expect-bytes", "5"])
    assert code == 0, code

    code, _ = parse_and_check(["--propose", "abc"])
    assert code == 0, code

    code, message = parse_and_check(["--propose", "abc", "--commit", "abc"])
    assert code == 2, code
    assert "--commit" in message and "writes nothing" in message, message

    assert (
        fetch_spec.constants_drift(
            fetch_spec.SPEC_COMMIT, fetch_spec.EXPECTED_BYTES, fetch_spec.EXPECTED_SHA256
        )
        == []
    )
    drift = fetch_spec.constants_drift(
        "0" * 40, fetch_spec.EXPECTED_BYTES, fetch_spec.EXPECTED_SHA256
    )
    assert len(drift) == 1 and "SPEC_COMMIT" in drift[0], drift
    assert len(fetch_spec.constants_drift("0" * 40, 1, "x")) == 3

    print("ok  flag contract: six flag vectors refuse or accept as D-04 states, three drift vectors")


OFFLINE_CHECKS = (
    check_discriminator,
    check_non_discriminator,
    check_tier1_boundaries,
    check_blob_identity,
    check_atomic_write,
    check_committed_spec,
    check_provenance_complete,
    check_flag_vectors,
)

# The network group lands with the proposal mode.
NETWORK_CHECKS = ()


def main():
    parser = argparse.ArgumentParser(description="Self-test the Whisparr 2 pipeline scripts.")
    parser.add_argument(
        "--network",
        action="store_true",
        help="Also run the checks that fetch real commits from raw.githubusercontent.com.",
    )
    args = parser.parse_args()

    checks = list(OFFLINE_CHECKS)
    if args.network:
        checks.extend(NETWORK_CHECKS)
    for check in checks:
        check()

    print("{} checks passed.".format(len(checks)))


if __name__ == "__main__":
    main()
