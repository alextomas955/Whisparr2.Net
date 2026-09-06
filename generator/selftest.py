#!/usr/bin/env python3
"""Prove the two refusals that stand between this repository and the wrong application.

The failure this guards against is silent. If the eros document is accepted, or if bytes nobody
stated in advance are accepted, the result is a client that compiles, produces no warnings, passes a
build and targets a different application. That defect surfaces long after generation, packaging and
documentation have all been built on the wrong document.

Standard library only. No framework, no requirements file and no configuration file. A bare assert
and a non-zero exit are what this needs.

This script is run by hand today. Wiring it into a workflow lands with the phase that adds one.

    python generator/selftest.py
    python generator/selftest.py --network
"""

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile

import fetch_spec
import verify_image
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

# The six image fields verify_image.py owns. Separate from SPEC_KEYS because the two blocks have
# two writers, and a reader who finds one block incomplete needs to know which script to re-run.
IMAGE_KEYS = (
    "imageTag",
    "imageDigest",
    "whisparrVersion",
    "whisparrBranch",
    "whisparrBuildTime",
    "whisparrPackageVersion",
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
    commit = provenance["specCommit"]
    assert len(commit) == 40 and set(commit) <= HEX, commit

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
    """The ten flag vectors of D-04, three sha40 shape vectors, and three constants-drift
    vectors of the move path."""
    destinations = sorted(vars(fetch_spec.build_parser().parse_args([])))
    assert destinations == ["commit", "expect_bytes", "expect_sha256", "out_file", "propose"], (
        destinations
    )

    # A real commit-shaped value, because both commit-taking flags now carry a type that refuses
    # anything else. A placeholder here would be refused before the contract is reached.
    commit = "0" * 40

    code, _ = parse_and_check([])
    assert code == 0, code

    code, message = parse_and_check(["--commit", commit])
    assert code == 2, code
    assert "--expect-sha256" in message and "--expect-bytes" in message, message
    assert message.rstrip().endswith(
        "Run --propose {} to observe the values first.".format(commit)
    ), message

    code, message = parse_and_check(["--commit", commit, "--expect-sha256", "d"])
    assert code == 2, code
    assert "--expect-bytes" in message, message
    assert "--expect-sha256" not in message.split("missing", 1)[1], message

    code, _ = parse_and_check(["--commit", commit, "--expect-sha256", "d", "--expect-bytes", "5"])
    assert code == 0, code

    code, _ = parse_and_check(["--propose", commit])
    assert code == 0, code

    code, message = parse_and_check(["--propose", commit, "--commit", commit])
    assert code == 2, code
    assert "--commit" in message and "writes nothing" in message, message

    # A ref name is not a commit. The third of these is the exact invocation that recorded
    # "specCommit": "v2" before both flags carried a type.
    code, message = parse_and_check(["--propose", "v2"])
    assert code == 2, code
    assert "40-character lowercase hex commit SHA" in message, message

    code, _ = parse_and_check(["--commit", "v2"])
    assert code == 2, code

    code, _ = parse_and_check(
        [
            "--commit",
            "v2",
            "--expect-sha256",
            fetch_spec.EXPECTED_SHA256,
            "--expect-bytes",
            str(fetch_spec.EXPECTED_BYTES),
        ]
    )
    assert code == 2, code

    code, _ = parse_and_check(["--propose", "../../Radarr/Radarr/master"])
    assert code == 2, code

    # Three spellings of a commit that sha40 refuses, each aimed at one way it could stop doing so.
    # The uppercase pinned commit is what a case-folding parser would accept. The padded pinned
    # commit is what a stripping parser would accept. A 41-character value is what a length test
    # written with < rather than != would accept. The shipped sha40 refuses all three, and these
    # vectors are here to keep it that way. They go through --propose alone because a value passed
    # to --commit alone also hits the partial-move refusal of D-04, which exits 2 on its own and so
    # would pin nothing. Both commit-taking flags carry the same type callable.
    code, message = parse_and_check(["--propose", fetch_spec.SPEC_COMMIT.upper()])
    assert code == 2, code
    assert "40-character lowercase hex commit SHA" in message, message

    code, message = parse_and_check(["--propose", " " + fetch_spec.SPEC_COMMIT + " "])
    assert code == 2, code
    assert "40-character lowercase hex commit SHA" in message, message

    code, message = parse_and_check(["--propose", commit + "0"])
    assert code == 2, code
    assert "40-character lowercase hex commit SHA" in message, message

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

    print(
        "ok  flag contract: ten flag vectors as D-04 states, three sha40 shape vectors, "
        "three drift vectors"
    )


def check_propose_is_fail_closed():
    """An empty --propose argument never reaches the write path, by either of two independent tests.

    The hand-built namespace carries all three move flags. With a partial set the partial-move branch
    fires and produces exit 2 on its own, so the vector would pass with the defect still present. It
    is built by hand rather than through the parser because the parser now refuses the empty string
    before check_flag_contract is reached, and this assertion is about check_flag_contract.
    """
    code, _ = parse_and_check(["--propose", ""])
    assert code == 2, code

    parser = fetch_spec.build_parser()
    args = argparse.Namespace(
        propose="",
        commit="0" * 40,
        expect_sha256=fetch_spec.EXPECTED_SHA256,
        expect_bytes=fetch_spec.EXPECTED_BYTES,
        out_file=fetch_spec.DEFAULT_OUT_FILE,
    )
    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer):
        try:
            fetch_spec.check_flag_contract(parser, args)
        except SystemExit as stop:
            code = stop.code
        else:
            raise AssertionError("check_flag_contract accepted an empty --propose beside a move")
    message = buffer.getvalue()
    assert code == 2, code
    assert "writes nothing" in message and "--commit" in message, message
    print("ok  propose fail-closed: an empty --propose exits 2 at the parser and in the contract")


def check_image_identity():
    """Every SPEC-06 assertion that does not need a running container.

    assert_identity takes a status dict, so the whole identity contract is asserted here with no
    Docker daemon. The two assertions that do need a daemon, the pinned digest reporting v2 and the
    seed landing at mode 0666, are what `python generator/verify_image.py` is for, and they run when
    the pin moves rather than per change.
    """
    accepted = {"branch": "v2", "version": "2.2.0.231"}
    assert verify_image.assert_identity(accepted) == []

    eros = {"branch": "eros", "version": "3.4.0.1387"}
    refused = verify_image.assert_identity(eros)
    assert len(refused) == 1, refused
    assert "'eros'" in refused[0], refused[0]
    assert "'3.4.0.1387'" in refused[0], refused[0]
    assert "'v2'" in refused[0], refused[0]

    # The right branch name with the wrong application behind it. Neither half discriminates alone.
    assert verify_image.assert_identity({"branch": "v2", "version": "3.4.0.1387"}) != []
    assert verify_image.assert_identity({"version": "2.2.0.231"}) != []
    assert verify_image.assert_identity({"branch": "v2"}) != []
    assert verify_image.assert_identity({"branch": "v2", "version": 2}) != []
    assert verify_image.assert_identity({"branch": "v2", "version": "two.2.0.231"}) != []

    # The verdict must not move when fields that do not discriminate are present. appName is
    # Whisparr on both applications and the API prefix is /api/v3 on both, so an edit that started
    # reading either would pass every assertion above while losing the discrimination this check
    # exists for.
    decoys = {"appName": "Whisparr", "urlBase": "/api/v3", "instanceName": "Whisparr"}
    assert verify_image.assert_identity(dict(accepted, **decoys)) == []
    assert verify_image.assert_identity(dict(eros, **decoys)) == refused

    assert tuple(verify_image.image_provenance(accepted)) == IMAGE_KEYS

    # The recorded values, read from the file rather than from a copy written here.
    provenance = read_provenance()
    for key in IMAGE_KEYS:
        assert key in provenance, key
        value = provenance[key]
        assert value is not None, key
        assert not (isinstance(value, str) and not value.strip()), key

    assert provenance["whisparrBranch"] == verify_image.EXPECTED_BRANCH, provenance["whisparrBranch"]
    major = provenance["whisparrVersion"].split(".")[0]
    assert major.isdigit() and int(major) == verify_image.EXPECTED_MAJOR, provenance[
        "whisparrVersion"
    ]

    print("ok  image identity: nine status dicts judged, six image fields recorded and observed")


OFFLINE_CHECKS = (
    check_discriminator,
    check_non_discriminator,
    check_tier1_boundaries,
    check_blob_identity,
    check_atomic_write,
    check_committed_spec,
    check_provenance_complete,
    check_flag_vectors,
    check_propose_is_fail_closed,
    check_image_identity,
)

# Immutable commits, never branch heads. A branch head moves and a test that fetches one breaks on
# the next upstream commit.  measured 2026-09-05
EROS_COMMIT = "cc3fb2abcf60f7c0048eb0294015d291b82bde08"
SAME_BYTES_COMMIT = "1a6005e594c8e3a30bd6a19d900f60177f68ac10"


def run_fetch_spec(*arguments):
    """Invoke the real script and capture its output.

    encoding and errors are set because a non-ASCII byte in captured output otherwise raises
    UnicodeDecodeError on a Windows console.
    """
    completed = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fetch_spec.py")]
        + list(arguments),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.returncode, completed.stdout + completed.stderr


def check_network_propose():
    """The proposal mode against real commits: it refuses the trap and it writes nothing."""
    path = read_committed_spec()
    before = (os.path.getsize(path), sha256_file(path))

    code, output = run_fetch_spec("--propose", EROS_COMMIT)
    assert code != 0, code
    assert "/api/v3/movie" in output and "/api/v3/series" in output, output
    assert "337327" in output, output
    # Only this one file. spec/PROVENANCE.json is written by a sibling plan in this same wave, so a
    # record over the whole directory would fail here for a reason unrelated to the proposal.
    assert (os.path.getsize(path), sha256_file(path)) == before
    print("ok  network: the eros commit is refused naming both paths, and nothing was written")

    code, output = run_fetch_spec("--propose", SAME_BYTES_COMMIT)
    assert code == 0, (code, output)
    assert "282862" in output, output
    assert "a3037cf379826505dc4557e74bf0798f43f2d4b8" in output, output
    print("ok  network: a different commit carrying the same blob reports the pinned values")

    code, output = run_fetch_spec("--commit", fetch_spec.SPEC_COMMIT)
    assert code == 2, (code, output)
    print("ok  network: --commit with no expectation flags exits 2")


NETWORK_CHECKS = (check_network_propose,)


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
