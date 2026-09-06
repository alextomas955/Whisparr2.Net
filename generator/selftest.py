#!/usr/bin/env python3
"""Prove the refusals that stand between this repository and the wrong application, and prove that
the transformations the pinned document needs still change it.

The failure the refusals guard against is silent. If the eros document is accepted, or if bytes
nobody stated in advance are accepted, the result is a client that compiles, produces no warnings,
passes a build and targets a different application. That defect surfaces long after generation,
packaging and documentation have all been built on the wrong document.

The failure the pre-processing checks guard against is quieter still. Whisparr fixes something
upstream, a rewrite that was patching it has nothing left to patch, and it keeps running over a
document it no longer describes with nothing to say so. Each of the four is driven over a document
where its own zero-condition holds, and each is driven over the pin and made to report the number it
was measured at. Three further checks judge the deliverable rather than the functions: the
committed patched document, a run of the script that must reproduce it byte for byte, and a run
over a document with nothing left to change, which must exit non-zero and write nothing.

Standard library only. No framework, no requirements file and no configuration file. A bare assert
and a non-zero exit are what this needs.

This script is run by hand today. Wiring it into a workflow lands with the phase that adds one.

    python generator/selftest.py
    python generator/selftest.py --network
    python generator/selftest.py --docker
"""

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import conformance
import fetch_spec
import generate
import preprocess_spec
import verify_image
from _common import REPO_ROOT, git_blob_sha1, resolve_repo_path, sha256_file

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
    """Both committed specs on disk still match their own recorded values.

    This is the assertion that catches a CRLF-mangled checkout. With core.autocrlf=true and no
    .gitattributes rule the checked-out spec carries injected CR bytes and none of the values match.
    """
    provenance = read_provenance()
    path = read_committed_spec()
    with open(path, "rb") as handle:
        body = handle.read()

    assert len(body) == provenance["specBytes"], (len(body), provenance["specBytes"])
    assert sha256_file(path) == provenance["specSha256"]
    assert git_blob_sha1(body) == provenance["specBlobSha1"]

    patched = resolve_repo_path(preprocess_spec.DEFAULT_OUT_FILE)
    assert sha256_file(patched) == provenance["generatedSpecSha256"], patched
    print("ok  committed specs: two files judged, bytes, sha256 and blob sha1 on disk match "
          "provenance")


def check_provenance_complete():
    """Every spec field is present and observed, and the patched-spec hash is recorded."""
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

    patched = provenance["generatedSpecSha256"]
    assert len(patched) == 64 and set(patched) <= HEX, patched
    print("ok  provenance: thirteen spec fields present and observed, patched-spec hash recorded")


def check_url_is_commit_addressed():
    """The fetch URL carries the commit it was given, and the recorded URL carries the recorded one.

    The refusal at the argparse boundary only decides which values may be spoken. This decides
    where the value goes. A spec_url that substituted SPEC_REF_NAME for its argument would fetch a
    moving branch head while provenance still recorded a commit, and every other offline check here
    passes with that substitution in place.
    """
    prefix = fetch_spec.RAW_HOST + fetch_spec.SPEC_REPO + "/"
    url = fetch_spec.spec_url(fetch_spec.SPEC_COMMIT)
    assert url.startswith(prefix), url
    assert url[len(prefix):].split("/", 1)[0] == fetch_spec.SPEC_COMMIT, url
    assert url.endswith("/" + fetch_spec.SPEC_PATH), url

    other = "0" * 40
    assert fetch_spec.spec_url(other)[len(prefix):].split("/", 1)[0] == other

    provenance = read_provenance()
    assert provenance["fetchedFrom"] == fetch_spec.spec_url(provenance["specCommit"]), provenance[
        "fetchedFrom"
    ]
    print("ok  fetch url: the commit argument addresses the URL, and fetchedFrom matches specCommit")


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


# Every refusal line in the pre-processing module opens with the first and closes with the second,
# so one grep finds them all. docs/REGENERATION.md keys its refusal table on the same strings.
REFUSAL_PREFIX = "ERROR: REFUSED - "
REFUSAL_TAIL = "Nothing was written."


def zero_condition_documents():
    """One synthetic document per transformation, each satisfying that transformation's zero-condition.

    A few lines each, in the spirit of document() above, rather than committed fixtures that would
    each need reviewing whenever the pin moves. Returned from module level so the set of
    transformations covered can be compared against the set the pre-processing module declares.
    """
    return {
        # Root security already narrows to the header scheme alone.
        "T1": {"security": [dict(scheme) for scheme in preprocess_spec.SECURITY], "paths": {}},
        # No malformed root path to delete.
        "T2": {"paths": {"/api/v3/series": {"get": {}}}},
        # Every operation already annotated. It carries an operation on purpose: a document with
        # none must not read as already annotated.
        "T3": {"paths": {"/api/v3/series": {"get": {"operationId": "ListSeries"}}}},
        # None of the five CLR-shaped schemas declared.
        "T4": {"components": {"schemas": {}}},
    }


def check_preprocess_zero_conditions():
    """Each transformation refuses, in its own words, over a document it has nothing to do to.

    Per transformation rather than over the run as a whole. A run-level test that something changed
    passes while three of the four are dead, which is the redundant rewrite this exists to catch.
    The walk is over the transformation tuple, so a fifth transformation added later cannot be
    silently uncovered: it would have no document here and the first assertion would say so.
    """
    documents = zero_condition_documents()
    declared = {name for name, _ in preprocess_spec.TRANSFORMATIONS}
    assert set(documents) == declared, sorted(set(documents) ^ declared)

    lines = {}
    for name, transform in preprocess_spec.TRANSFORMATIONS:
        count, refusals = transform(documents[name])
        assert count == 0, (name, count)
        assert len(refusals) == 1, (name, refusals)
        assert refusals[0].startswith(REFUSAL_PREFIX), refusals[0]
        assert refusals[0].endswith(REFUSAL_TAIL), refusals[0]
        lines[name] = refusals[0]

    # Four transformations refusing with one sentence would pass every assertion above and tell a
    # reader nothing about which of them found nothing.
    assert len(set(lines.values())) == len(lines), lines
    print("ok  zero conditions: {} transformations refuse over their own zero-condition, each "
          "changing nothing and naming itself".format(len(lines)))


def check_operation_id_shape():
    """The identifier pattern accepts a PascalCase name and refuses the two shapes that matter."""
    shape = preprocess_spec.OPERATION_ID_PATTERN
    assert shape.fullmatch("GetCalendarFeed")

    # The derivation the one non-cosmetic override entry exists to replace. A dot is not a C#
    # identifier character.
    assert not shape.fullmatch("GetFeedV3CalendarWhisparr.ics")

    # The vector that matters. A pattern that grew an IGNORECASE flag, or a call that became search
    # rather than fullmatch, still passes the two above and hands the generator a name it sanitises
    # into one of its own choosing.
    assert not shape.fullmatch("listMovie")
    print("ok  operationId shape: three names judged, PascalCase accepted, a dotted name and a "
          "camelCase name refused")


def parsed_raw_spec():
    """The committed raw document, freshly parsed, so a caller can mutate it without affecting another.

    The path comes from the pre-processing module's own constant rather than being restated here.
    """
    with open(resolve_repo_path(preprocess_spec.DEFAULT_RAW_SPEC), encoding="utf-8") as handle:
        return json.load(handle)


def operations_of(document):
    """(key, method, path, operation) for every operation in the document, in document order."""
    return [
        (method.upper() + " " + path, method, path, operation)
        for path, item in document["paths"].items()
        for method, operation in item.items()
        if method in preprocess_spec.HTTP_METHODS
    ]


def check_preprocess_transformations_apply():
    """The four transformations still change the pinned document, by the amounts measured.

    This fails the day the pin moves in a way that changes those numbers, and that is the intended
    behaviour rather than brittleness to design around. The repair is to re-measure the new document
    and state its numbers here, never to loosen the assertion into "something changed".
    """
    document = parsed_raw_spec()
    counts = []
    for name, transform in preprocess_spec.TRANSFORMATIONS:
        count, refusals = transform(document)
        assert refusals == [], (name, refusals)
        counts.append(count)
    assert counts == [1, 1, 227, 10], counts

    paths = document["paths"]
    schemas = document["components"]["schemas"]
    measured = (len(paths), len(operations_of(document)), len(schemas))
    assert measured == (156, 227, 129), measured
    assert [name for name in preprocess_spec.CLR_SCHEMAS if name in schemas] == []
    print("ok  transformations: the four report {}, {}, {} and {} over the pin, leaving {} path "
          "items, {} operations and {} schemas".format(*(tuple(counts) + measured)))


def check_override_table():
    """Every override entry matches an operation, and a ninth that matches none is refused."""
    overrides = preprocess_spec.OPERATION_ID_OVERRIDES
    assert len(overrides) == 8, len(overrides)

    document = parsed_raw_spec()
    preprocess_spec.delete_root_path(document)
    count, refusals = preprocess_spec.assign_operation_ids(document)
    # An unused key is the stale-override refusal, so a clean run is the assertion that all 8 matched.
    assert refusals == [], refusals
    assert count == 227, count

    stale = "GET /api/v3/nowhere"
    assert stale not in overrides, stale
    # A plain dict copy on the module attribute, restored in the finally so a failed assertion
    # cannot leave the mutation behind for the checks that follow.
    preprocess_spec.OPERATION_ID_OVERRIDES = dict(overrides, **{stale: "GetNowhere"})
    try:
        count, refusals = preprocess_spec.assign_operation_ids(parsed_raw_spec())
        assert count == 0, count
        assert len(refusals) == 2, refusals
        assert refusals[0].startswith(REFUSAL_PREFIX), refusals[0]
        assert "1 override entries match no operation" in refusals[0], refusals[0]
        assert stale in refusals[1], refusals[1]
    finally:
        preprocess_spec.OPERATION_ID_OVERRIDES = overrides
    print("ok  override table: {} entries, every one matching an operation, and an injected ninth "
          "refused by name".format(len(overrides)))


def check_operation_id_derivation():
    """227 distinct names over the pin, no collisions, and the readability claim checked.

    The global collision assertion is strictly stricter than the per-class collision the generator
    would suffer. The per-tag count is measured anyway, because it is the collision that would
    actually break a build, and reporting it is what makes the stricter assertion legible.
    """
    document = parsed_raw_spec()
    preprocess_spec.delete_root_path(document)
    count, refusals = preprocess_spec.assign_operation_ids(document)
    assert refusals == [], refusals

    named = [
        (operation["operationId"], (operation.get("tags") or [""])[0])
        for _, _, _, operation in operations_of(document)
    ]
    assert len(named) == count == 227, (len(named), count)
    assert len({identifier for identifier, _ in named}) == 227
    assert len(set(named)) == 227

    # Every override key derived naively, which is what D-11 claims is safe for seven of the eight.
    naive = {}
    for key, method, path, operation in operations_of(parsed_raw_spec()):
        if key in preprocess_spec.OPERATION_ID_OVERRIDES:
            naive[key] = preprocess_spec.derive_operation_id(
                method, path, (operation.get("tags") or [""])[0],
                preprocess_spec.returns_json_array(operation),
            )
    assert len(naive) == len(preprocess_spec.OPERATION_ID_OVERRIDES), sorted(naive)
    invalid = sorted(
        key for key, identifier in naive.items()
        if not preprocess_spec.OPERATION_ID_PATTERN.fullmatch(identifier)
    )
    assert len(invalid) == 1, invalid

    # And the transformation agrees, with the table emptied: one name fails the shape assertion,
    # and it is the same one. The other seven entries are readability choices.
    overrides = preprocess_spec.OPERATION_ID_OVERRIDES
    preprocess_spec.OPERATION_ID_OVERRIDES = {}
    try:
        bare = parsed_raw_spec()
        preprocess_spec.delete_root_path(bare)
        count, refusals = preprocess_spec.assign_operation_ids(bare)
        assert count == 0, count
        assert len(refusals) == 2, refusals
        assert "shape assertion failed: 1 names" in refusals[0], refusals[0]
        assert refusals[1].strip().startswith(invalid[0] + " "), refusals[1]
    finally:
        preprocess_spec.OPERATION_ID_OVERRIDES = overrides
    print("ok  operationId derivation: {} distinct names over {} operations, no collision globally "
          "or within a tag, and {} is the one override the build needs".format(
              len({identifier for identifier, _ in named}), len(named), invalid[0]))


def clr_reference_sites(document):
    """Every reference to the five CLR-shaped schemas, partitioned by whether it lives inside one.

    Walked here rather than read back out of the rewrite, so the partition the rewrite relies on is
    measured a second time by something that does not share its code. An outside site is returned as
    the parent node and the key, so the replacement it received can be read after the rewrite runs.
    That is what keeps the ten from being restated as a list of paths.
    """
    schemas = document["components"]["schemas"]
    targets = set(preprocess_spec.CLR_SCHEMAS)
    owner_of = {id(schemas[name]): name for name in targets if name in schemas}
    inside = []
    outside = []

    def walk(node, owner):
        if isinstance(node, dict):
            for key, value in node.items():
                name = None
                if isinstance(value, dict):
                    reference = value.get("$ref")
                    if isinstance(reference, str) and reference.startswith(
                        preprocess_spec.REF_PREFIX
                    ):
                        name = reference[len(preprocess_spec.REF_PREFIX):]
                if name in targets:
                    if owner is None:
                        outside.append((node, key, name))
                    else:
                        inside.append((owner, key, name))
                    continue
                walk(value, owner_of.get(id(value), owner))
        elif isinstance(node, list):
            for item in node:
                walk(item, owner)

    walk(document, None)
    return inside, outside


def check_clr_schema_partition():
    """Eleven references, ten outside the five and one inside, and the two witness shapes."""
    document = parsed_raw_spec()
    inside, outside = clr_reference_sites(document)
    assert len(inside) + len(outside) == 11, (len(inside), len(outside))
    assert len(outside) == 10, len(outside)
    assert sorted(inside) == [preprocess_spec.INTERNAL_REFERENCE], inside

    count, refusals = preprocess_spec.rewrite_clr_schemas(document)
    assert refusals == [], refusals
    assert count == len(outside), (count, len(outside))

    def replacement(name):
        return preprocess_spec.OBJECT_SHAPED.get(name, preprocess_spec.STRING)

    dated = [(node, key) for node, key, name in outside if replacement(name) == preprocess_spec.DATE]
    plain = [(node, key) for node, key, name in outside if replacement(name) != preprocess_spec.DATE]
    assert len(dated) == 1, len(dated)
    assert dated[0][0][dated[0][1]] == preprocess_spec.DATE, dated[0][0][dated[0][1]]
    assert all(node[key] == preprocess_spec.STRING for node, key in plain), plain
    assert [name for name in preprocess_spec.CLR_SCHEMAS if name in document["components"]["schemas"]] == []
    print("ok  CLR schemas: {} references, {} outside rewritten to strings of which {} carries a "
          "date format, and the one inside is {}.{} -> {}".format(
              len(inside) + len(outside), len(outside), len(dated), *inside[0]))


def run_preprocess_spec(*arguments):
    """Invoke the real pre-processing script and capture its output.

    Mirrors run_fetch_spec below, including the encoding and errors pair, which is set because a
    non-ASCII byte in captured output otherwise raises UnicodeDecodeError on a Windows console.
    """
    completed = subprocess.run(
        [
            sys.executable,
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "preprocess_spec.py"),
        ]
        + list(arguments),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.returncode, completed.stdout + completed.stderr


def check_preprocess_refuses_scratch_input():
    """A scratch input aimed at the committed output path is refused, and that output does not move.

    The only pre-processing check that runs a subprocess. The refusal lives in main(), ahead of the
    parse, so there is no function to drive it through.
    """
    committed = resolve_repo_path(preprocess_spec.DEFAULT_OUT_FILE)
    before = (os.path.getsize(committed), sha256_file(committed))

    with tempfile.TemporaryDirectory() as directory:
        scratch = resolve_repo_path(os.path.join(directory, "scratch.json"))
        with open(scratch, "w", encoding="utf-8") as handle:
            json.dump(document("3.0.1", "3.0.0", WHISPARR2_PATHS), handle)
        code, output = run_preprocess_spec("--raw-spec", scratch)

    assert code == 1, (code, output)
    assert scratch in output, output
    assert committed in output, output
    # The assertion that makes this a test of the control rather than of the message.
    assert (os.path.getsize(committed), sha256_file(committed)) == before
    print("ok  scratch input: a non-default input aimed at the committed output exits 1, and that "
          "output is byte-identical afterwards")


def clr_reference_pointers(document):
    """Every reference to the five CLR-shaped schemas that lives outside those five, as a pointer.

    clr_reference_sites above returns parent nodes, which can only be read in the document they came
    from. A pointer can be resolved in a second document, which is what lets the sites measured over
    the raw pin be read back out of the committed patched file.
    """
    schemas = document["components"]["schemas"]
    targets = set(preprocess_spec.CLR_SCHEMAS)
    owner_of = {id(schemas[name]): name for name in targets if name in schemas}
    outside = []

    def walk(node, owner, trail):
        if isinstance(node, dict):
            items = node.items()
        elif isinstance(node, list):
            items = enumerate(node)
        else:
            return
        for key, value in items:
            name = None
            if isinstance(value, dict):
                reference = value.get("$ref")
                if isinstance(reference, str) and reference.startswith(preprocess_spec.REF_PREFIX):
                    name = reference[len(preprocess_spec.REF_PREFIX):]
            if name in targets:
                if owner is None:
                    outside.append((trail + (key,), name))
                continue
            walk(value, owner_of.get(id(value), owner), trail + (key,))

    walk(document, None, ())
    return sorted(outside)


def resolve_pointer(document, trail):
    node = document
    for key in trail:
        node = node[key]
    return node


def check_patched_document_on_disk():
    """The committed patched document carries the four results, read out of the file itself.

    Every other pre-processing check drives a transformation over a document it parsed itself. This
    one judges the deliverable. The ten reference sites are located in the raw pin and then read at
    those same positions in the patched file, so the assertion cannot drift into counting nullable
    strings the document already carried.
    """
    with open(resolve_repo_path(preprocess_spec.DEFAULT_OUT_FILE), encoding="utf-8") as handle:
        patched = json.load(handle)

    assert patched["security"] == preprocess_spec.SECURITY, patched["security"]
    assert "/" not in patched["paths"], sorted(patched["paths"])[:3]

    operations = operations_of(patched)
    assert len(operations) == 227, len(operations)
    identifiers = [operation["operationId"] for _, _, _, operation in operations]
    assert len(set(identifiers)) == 227, len(set(identifiers))
    invalid = [i for i in identifiers if not preprocess_spec.OPERATION_ID_PATTERN.fullmatch(i)]
    assert invalid == [], invalid

    schemas = patched["components"]["schemas"]
    assert [name for name in preprocess_spec.CLR_SCHEMAS if name in schemas] == []
    assert len(schemas) == 129, len(schemas)

    pointers = clr_reference_pointers(parsed_raw_spec())
    assert len(pointers) == 10, len(pointers)
    dated = [t for t, name in pointers if name == "DateOnly"]
    assert len(dated) == 1, dated
    for trail, name in pointers:
        expected = preprocess_spec.DATE if name == "DateOnly" else preprocess_spec.STRING
        assert resolve_pointer(patched, trail) == expected, (trail, name)

    print("ok  patched document: the committed file carries {} operations with distinct valid "
          "names, no root path, {} schemas and {} rewritten sites of which {} is a date".format(
              len(operations), len(schemas), len(pointers), len(dated)))


def check_preprocess_reproduces_committed_output():
    """The shipped script, run over the pin, writes the committed patched file byte for byte.

    Nothing else here judges main(). Every transformation assertion above drives the four functions
    directly, so a main() that ran three of them, or a writer that changed its indent or its line
    ending, leaves the whole suite green while the committed deliverable is no longer what the code
    produces. The output goes outside the repository, which is also what makes the provenance
    assertion below meaningful: the record must follow the output file, not the repository default.
    """
    committed = resolve_repo_path(preprocess_spec.DEFAULT_OUT_FILE)
    provenance_path = resolve_repo_path(fetch_spec.PROVENANCE_PATH)
    before = (os.path.getsize(provenance_path), sha256_file(provenance_path))

    with tempfile.TemporaryDirectory() as directory:
        scratch = os.path.join(directory, "openapi.generated.json")
        code, output = run_preprocess_spec("--out-file", scratch)
        assert code == 0, (code, output)
        with open(scratch, "rb") as handle:
            produced = handle.read()
        assert os.listdir(directory) == ["openapi.generated.json"], os.listdir(directory)

    with open(committed, "rb") as handle:
        assert produced == handle.read(), len(produced)
    assert sha256_file(committed) == read_provenance()["generatedSpecSha256"]
    assert (os.path.getsize(provenance_path), sha256_file(provenance_path)) == before

    print("ok  reproducible: a run over the pin writes {} bytes identical to the committed patched "
          "spec, and no provenance outside the output directory".format(len(produced)))


def check_preprocess_refusal_gate_exits():
    """A document with nothing left to change exits 1 and writes no output document.

    The zero-condition check above proves the four functions return a refusal line. This proves the
    refusal reaches the exit code and stops the write, which is the half a caller and a build see.
    The committed patched document is the input, because all four zero-conditions hold over it at
    once: security is already narrowed, the root path is already gone, every operation already
    carries an operationId and the five CLR-shaped schemas are already deleted.
    """
    with tempfile.TemporaryDirectory() as directory:
        scratch = os.path.join(directory, "openapi.generated.json")
        code, output = run_preprocess_spec(
            "--raw-spec", preprocess_spec.DEFAULT_OUT_FILE, "--out-file", scratch
        )
        assert code == 1, (code, output)
        assert os.listdir(directory) == [], os.listdir(directory)

    refusals = [line for line in output.splitlines() if line.startswith(REFUSAL_PREFIX)]
    assert len(refusals) == len(preprocess_spec.TRANSFORMATIONS), refusals
    assert len(set(refusals)) == len(refusals), refusals
    assert "wrote" not in output, output

    print("ok  refusal gate: a document with nothing left to change exits 1 with {} refusals and "
          "writes no output".format(len(refusals)))


def check_preprocess_refuses_committed_write_targets():
    """The pin and the committed provenance record are not write targets for a scratch run.

    Both refusals live at the argument boundary, before the document is parsed, so this drives
    main() through a patched argv and needs no document on disk. The two cases are separate
    because they fail for different reasons: the first names an output, the second names a
    directory the caller never wrote down.
    """
    default_raw = resolve_repo_path(preprocess_spec.DEFAULT_RAW_SPEC)
    default_out = resolve_repo_path(preprocess_spec.DEFAULT_OUT_FILE)
    committed = [
        (default_raw, sha256_file(default_raw)),
        (default_out, sha256_file(default_out)),
        (resolve_repo_path(fetch_spec.PROVENANCE_PATH), sha256_file(resolve_repo_path(fetch_spec.PROVENANCE_PATH))),
    ]

    with tempfile.TemporaryDirectory() as directory:
        scratch_in = os.path.join(directory, "in.json")
        with open(default_raw, "rb") as source, open(scratch_in, "wb") as target:
            target.write(source.read())

        # Writing the patched document over the pin destroys the identity every other check is
        # measured against.
        code, output = run_preprocess_spec("--out-file", preprocess_spec.DEFAULT_RAW_SPEC)
        assert code == 1, (code, output)
        assert "the pinned input document is not a write target" in output, output

        # An output beside the committed provenance rewrites a file the caller never named.
        code, output = run_preprocess_spec(
            "--raw-spec", scratch_in, "--out-file", "spec/scratch.json"
        )
        assert code == 1, (code, output)
        assert "may not write beside the committed provenance record" in output, output

    for path, digest in committed:
        assert sha256_file(path) == digest, path
    print("ok  write targets: the pin and the committed provenance are refused, all three intact")


def check_generated_tree_digest():
    """The committed tree still hashes to the digest the last generation recorded.

    What this pins is a hand edit under the generated tree that has been committed. Git reports
    such an edit as clean, and no other mechanism in this repository sees it without Docker. The
    recorded value is read out of spec/PROVENANCE.json rather than carried here, so this check
    cannot become a second authority that drifts from the record.

    The member count is asserted as a literal on purpose. It is the size of the set the digest is
    defined over, and a tree_members that quietly started walking the whole package root would
    still produce a self-consistent digest.
    """
    recorded = generate.read_provenance().get("generatedTreeSha256")
    assert recorded, "spec/PROVENANCE.json carries no generatedTreeSha256"

    members = generate.tree_members(REPO_ROOT)
    assert len(members) == 224, len(members)

    on_disk = generate.tree_sha256(REPO_ROOT)
    assert on_disk == recorded, (on_disk, recorded)
    print("ok  generated tree: {} files hash to the generatedTreeSha256 the last generation "
          "recorded".format(len(members)))


def check_generated_tree_matches_spec():
    """The committed tree carries exactly the file names and the method names the spec implies.

    What this pins is the census gate itself. The gate in generator/generate.py runs against a
    staged tree that exists only during a Docker run, so without this check nothing in the suite a
    developer actually runs exercises expected_from_spec or api_method_names.

    The numbers in the printed line are derived from the sets rather than typed, because the
    assertion is the emptiness of the four difference sets and not any particular count.
    """
    package_root = os.path.join(REPO_ROOT, "src", "Whisparr2.Net")
    expected_files, expected_methods = generate.expected_from_spec(
        os.path.join(REPO_ROOT, "spec", "openapi.generated.json"))

    for subdir, want in sorted(expected_files.items()):
        have = {f for f in os.listdir(os.path.join(package_root, subdir)) if f.endswith(".cs")}
        assert want - have == set(), (subdir, sorted(want - have))
        assert have - want == set(), (subdir, sorted(have - want))

    stems = generate.api_method_names(package_root)
    assert expected_methods - stems == set(), sorted(expected_methods - stems)
    assert stems - expected_methods == set(), sorted(stems - expected_methods)
    print("ok  census: {} Model and {} Api file names and {} method names match the committed "
          "spec exactly".format(
              len(expected_files["Model"]), len(expected_files["Api"]), len(expected_methods)))


def check_tree_digest_moves():
    """An edit, an addition, a deletion and a rename each move the digest, over synthetic trees.

    What this pins is the digest definition, not the deliverable. Every other check here stays
    green against a tree_sha256 that ignored paths, and the rename case is the one a digest over
    concatenated file bytes alone fails.

    An unmutated copy is asserted to reproduce the baseline as well. Without it a tree_sha256 that
    returned a fresh value on every call would satisfy all four inequalities.

    Nothing here touches the repository. Every tree is built and destroyed under a temporary
    directory.
    """
    def put(path, text):
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)

    def build(root):
        """A minimal tree in the shape tree_members walks: the five subdirectories and the three
        meta members."""
        package_root = os.path.join(root, "src", "Whisparr2.Net")
        for subdir in generate.GENERATED_SUBDIRS:
            os.makedirs(os.path.join(package_root, subdir))
            put(os.path.join(package_root, subdir, subdir + "Thing.cs"), "// " + subdir + "\n")
        os.makedirs(os.path.join(root, ".openapi-generator"))
        put(os.path.join(root, ".openapi-generator", "FILES"),
            "src/Whisparr2.Net/Api/ApiThing.cs\n")
        put(os.path.join(root, ".openapi-generator", "VERSION"), "7.25.0\n")
        put(os.path.join(root, ".openapi-generator-ignore"), "# nothing\n")

    def digest_after(mutate):
        with tempfile.TemporaryDirectory() as root:
            build(root)
            mutate(root)
            return generate.tree_sha256(root)

    def target(root, name="ModelThing.cs"):
        return os.path.join(root, "src", "Whisparr2.Net", "Model", name)

    def unchanged(root):
        pass

    baseline = digest_after(unchanged)
    assert digest_after(unchanged) == baseline, "the digest is not a function of the tree"

    moved = {
        "an edit": digest_after(lambda root: put(target(root), "// ModelThing, edited\n")),
        "an addition": digest_after(lambda root: put(target(root, "ModelExtra.cs"), "// extra\n")),
        "a deletion": digest_after(lambda root: os.remove(target(root))),
        "a rename": digest_after(
            lambda root: os.rename(target(root), target(root, "ModelRenamed.cs"))),
    }
    for mutation, digest in sorted(moved.items()):
        assert digest != baseline, mutation
    assert len(set(moved.values())) == len(moved), moved
    print("ok  tree digest: an edit, an addition, a deletion and a rename each move the digest")


def check_generated_files_manifest():
    """.openapi-generator/FILES lists exactly the committed .cs sources, compared both ways.

    What this pins is the manifest against the tree, and its limit is worth stating plainly: it
    catches an added or a deleted file and no edit, which is why check_generated_tree_digest sits
    beside it. It is asserted anyway because it costs one set comparison and it names the exact
    files a single digest cannot.
    """
    with open(os.path.join(REPO_ROOT, ".openapi-generator", "FILES"), encoding="utf-8") as handle:
        listed = [line.strip() for line in handle if line.strip()]

    for line in listed:
        assert "\\" not in line, line
        assert ":" not in line, line
        assert not line.startswith("/"), line
        assert line.startswith("src/Whisparr2.Net/"), line

    manifest = set(listed)
    assert len(manifest) == len(listed), "the manifest lists a path twice"

    on_disk = {r for r, _ in generate.tree_members(REPO_ROOT) if r.endswith(".cs")}
    assert manifest - on_disk == set(), sorted(manifest - on_disk)
    assert on_disk - manifest == set(), sorted(on_disk - manifest)
    print("ok  manifest: .openapi-generator/FILES lists exactly the {} committed source "
          "files".format(len(manifest)))


def put_text(path, text):
    """Write LF-terminated text, creating the parent directory."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


# A document in the shape generate.expected_from_spec reads, carrying one schema, one tag and two
# operations. Roughly 300 bytes rather than the 337 KB pin, and small enough that a reader can hold
# the whole expectation in their head: Model/Thing.cs, Api/ThingApi.cs, Api/IApi.cs, and the two
# method stems ListThing and CreateThing.
SYNTHETIC_SPEC = {
    "openapi": "3.0.1",
    "info": {"title": "Whisparr", "version": "3.0.0"},
    "components": {"schemas": {"Thing": {"type": "object"}}},
    "paths": {
        "/api/v3/thing": {
            "get": {"operationId": "ListThing", "tags": ["Thing"]},
            "post": {"operationId": "CreateThing", "tags": ["Thing"]},
        }
    },
}

# The two operations as generichost writes them, each with the OrDefault twin beside it, so the
# stem filter in api_method_names is exercised rather than assumed away.
THING_API_CS = """namespace Whisparr2.Net.Api
{{
    public partial class ThingApi
    {{
        public async Task<I{0}ApiResponse> {0}Async(CancellationToken token)
        public async Task<I{0}ApiResponse?> {0}OrDefaultAsync(CancellationToken token)
        public async Task<ICreateThingApiResponse> CreateThingAsync(CancellationToken token)
        public async Task<ICreateThingApiResponse?> CreateThingOrDefaultAsync(CancellationToken token)
    }}
}}
"""


def build_synthetic_tree(root, list_stem="ListThing"):
    """A repository-shaped tree the gates accept, under root.

    It carries the staged input generate.py reads, the five generated subdirectories, the three
    meta members and a provenance record, which is everything gate_staged_tree and
    verify_committed_tree touch. list_stem renames the first operation's implementation without
    renaming what the spec declares, which is the generator-rename case D-07 names.

    Two files that are not generator output sit in the tree on purpose: a stray .cs beside the
    csproj and one under obj/, which is what a build leaves behind. Both must be invisible to
    generated_cs_files and to tree_members.
    """
    package_root = os.path.join(root, "src", "Whisparr2.Net")
    put_text(os.path.join(root, "spec", "openapi.generated.json"),
             json.dumps(SYNTHETIC_SPEC, indent=2) + "\n")
    put_text(os.path.join(package_root, "Model", "Thing.cs"), "// Thing\n")
    put_text(os.path.join(package_root, "Api", "ThingApi.cs"), THING_API_CS.format(list_stem))
    put_text(os.path.join(package_root, "Api", "IApi.cs"), "// IApi\n")
    put_text(os.path.join(package_root, "Client", "ClientUtils.cs"), "// ClientUtils\n")
    put_text(os.path.join(package_root, "Extensions", "ServiceCollection.cs"), "// Extensions\n")
    put_text(os.path.join(package_root, "Logging", "Logging.cs"), "// Logging\n")
    put_text(os.path.join(package_root, "Stray.cs"), "// hand-written, beside the csproj\n")
    put_text(os.path.join(package_root, "obj", "Debug", "net8.0", "AssemblyInfo.cs"), "// build\n")

    members = [relative for relative, _ in generate.tree_members(root) if relative.endswith(".cs")]
    put_text(os.path.join(root, ".openapi-generator", "FILES"), "".join(m + "\n" for m in members))
    put_text(os.path.join(root, ".openapi-generator", "VERSION"), "7.25.0\n")
    put_text(os.path.join(root, ".openapi-generator-ignore"), "# nothing\n")
    put_text(os.path.join(root, "spec", "PROVENANCE.json"),
             json.dumps({"specSha256": "0" * 64, "generatedTreeSha256": generate.tree_sha256(root)},
                        indent=2) + "\n")
    return package_root


@contextlib.contextmanager
def repo_root_at(root):
    """Point generate.py's repository root at a synthetic tree for the duration of a block.

    verify_committed_tree and write_tree_digest read the module constant rather than a parameter,
    so this is what lets them be driven without a Docker run and without touching the repository.
    """
    original = generate.REPO_ROOT
    generate.REPO_ROOT = root
    try:
        yield
    finally:
        generate.REPO_ROOT = original


def call_gate(function, *arguments):
    """Call a gate and return (exit code or None, everything it printed).

    None means the gate returned. generate.die prints to stdout and raises SystemExit, so a gate
    that printed a refusal and carried on is distinguishable here from one that refused.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        try:
            function(*arguments)
        except SystemExit as stop:
            return stop.code, buffer.getvalue()
    return None, buffer.getvalue()


def check_staged_tree_gate_refuses():
    """gate_staged_tree accepts a tree that matches its spec and refuses six mutations of it.

    What this pins is the census gate as a gate. check_generated_tree_matches_spec drives
    expected_from_spec and api_method_names over the committed tree, so the derivation is covered,
    but nothing offline made gate_staged_tree refuse anything: every refusal in it could be deleted
    and the suite stayed green. It runs against a staged tree that exists only during a Docker run,
    which is why the tree here is synthetic.

    The control is asserted first. Without it a gate that refused everything would satisfy all six
    mutations.
    """
    def gated(mutate, list_stem="ListThing"):
        with tempfile.TemporaryDirectory() as root:
            package_root = build_synthetic_tree(root, list_stem)
            mutate(package_root)
            return call_gate(generate.gate_staged_tree, root, package_root, "PKG")

    def unchanged(package_root):
        pass

    code, output = gated(unchanged)
    assert code is None, (code, output)
    # Six, not eight: the stray beside the csproj and the one under obj/ are not generator output.
    assert "staged 6 .cs files" in output, output
    assert "every one of the 2 method names the spec declares is implemented" in output, output

    refusals = [
        ("a missing subdirectory",
         lambda pkg: shutil.rmtree(os.path.join(pkg, "Api")),
         "is missing 1 of the five generated subdirectories: Api"),
        ("a missing manifest",
         lambda pkg: os.remove(os.path.join(pkg, "..", "..", ".openapi-generator", "FILES")),
         "the staged tree is missing .openapi-generator/FILES"),
        ("a missing ignore file",
         lambda pkg: os.remove(os.path.join(pkg, "..", "..", ".openapi-generator-ignore")),
         "the staged tree is missing .openapi-generator-ignore"),
        ("a file the spec does not imply",
         lambda pkg: put_text(os.path.join(pkg, "Model", "Ghost.cs"), "// ghost\n"),
         "Model/Ghost.cs was generated and the spec implies no such file"),
        ("a file the spec implies and the generator did not write",
         lambda pkg: os.remove(os.path.join(pkg, "Model", "Thing.cs")),
         "Model/Thing.cs is implied by the spec and was not generated"),
        ("a subdirectory holding no .cs",
         lambda pkg: os.remove(os.path.join(pkg, "Client", "ClientUtils.cs")),
         "Client/ holds no .cs file"),
    ]
    for name, mutate, expected in refusals:
        code, output = gated(mutate)
        assert code == 1, (name, code, output)
        assert "REFUSED" in output, (name, output)
        assert expected in output, (name, output)
        assert "Nothing in PKG was touched" in output, (name, output)

    # The generator renaming an operationId is its own refusal, because the file names still match.
    code, output = gated(unchanged, list_stem="ListThings")
    assert code == 1, (code, output)
    assert "does not carry the method names the spec declares, in 2 case(s)" in output, output
    assert "ListThing is declared by the spec and no Api/*.cs implements ListThingAsync" \
        in output, output
    assert "ListThings is implemented as ListThingsAsync and the spec declares no such " \
        "operationId" in output, output
    assert "generator/preprocess_spec.py" in output, output
    print("ok  staged gate: a matching staged tree passes and seven mutations of it each refuse")


def check_preflight_refuses_a_damaged_tree():
    """verify_committed_tree refuses on three states and bootstraps on exactly one.

    What this pins is the pre-flight that stands between a hand edit and the delete in step 3. It
    was unasserted: the refusal on a recorded digest that no longer matches could be turned into a
    print, and the suite stayed green.

    The fourth state is the one the bootstrap belongs to, a genuinely absent digest over a tree
    that was never generated. It is asserted here as well, because a pre-flight that refused it
    would make the first generation impossible and no other check would say so.
    """
    def preflight(mutate):
        with tempfile.TemporaryDirectory() as root:
            package_root = build_synthetic_tree(root)
            mutate(root, package_root)
            with repo_root_at(root):
                return call_gate(generate.verify_committed_tree, package_root)

    def drop_digest(root):
        path = os.path.join(root, "spec", "PROVENANCE.json")
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
        record.pop("generatedTreeSha256")
        put_text(path, json.dumps(record, indent=2) + "\n")

    def unchanged(root, package_root):
        pass

    code, output = preflight(unchanged)
    assert code is None, (code, output)
    assert "the committed tree matches generatedTreeSha256" in output, output

    # A recorded digest over a tree missing one subdirectory. This is the state that used to take
    # the bootstrap branch, print that no digest was recorded and delete a co-located hand edit.
    def missing_subdir(root, package_root):
        shutil.rmtree(os.path.join(package_root, "Extensions"))
        put_text(os.path.join(package_root, "Model", "Thing.cs"), "// Thing, edited by hand\n")

    code, output = preflight(missing_subdir)
    assert code == 1, (code, output)
    assert "generatedTreeSha256 is recorded but the tree is incomplete" in output, output
    assert "missing    Extensions" in output, output
    assert "no generatedTreeSha256 recorded yet" not in output, output

    # A recorded digest over a complete tree that no longer hashes to it. The added and the deleted
    # file are named from the manifest; the edit is not localisable from one hash and is not named.
    def hand_edited(root, package_root):
        put_text(os.path.join(package_root, "Model", "Thing.cs"), "// Thing, edited by hand\n")
        put_text(os.path.join(package_root, "Model", "Ghost.cs"), "// ghost\n")
        os.remove(os.path.join(package_root, "Logging", "Logging.cs"))

    code, output = preflight(hand_edited)
    assert code == 1, (code, output)
    assert "does not match generatedTreeSha256 in spec/PROVENANCE.json" in output, output
    assert "src/Whisparr2.Net/Model/Ghost.cs is on disk and is not in .openapi-generator/FILES" \
        in output, output
    assert "src/Whisparr2.Net/Logging/Logging.cs is in .openapi-generator/FILES and is not on " \
        "disk" in output, output
    assert "generator/generate.py --check" in output, output

    # No digest recorded over a tree that still holds four of the five subdirectories. A first
    # generation never looks like this.
    def partial_bootstrap(root, package_root):
        drop_digest(root)
        shutil.rmtree(os.path.join(package_root, "Extensions"))

    code, output = preflight(partial_bootstrap)
    assert code == 1, (code, output)
    assert "no generatedTreeSha256 is recorded and the tree is partial" in output, output
    assert "missing    Extensions" in output, output

    # The one state the bootstrap belongs to.
    def first_run(root, package_root):
        drop_digest(root)
        for subdir in generate.GENERATED_SUBDIRS:
            shutil.rmtree(os.path.join(package_root, subdir))

    code, output = preflight(first_run)
    assert code is None, (code, output)
    assert "no generatedTreeSha256 recorded yet, establishing it" in output, output
    print("ok  pre-flight: a damaged tree refuses on three states and only an absent tree "
          "bootstraps")


def check_write_tree_digest_keeps_the_record():
    """write_tree_digest replaces one field, keeps every other, and writes the pipeline's bytes.

    What this pins is the only writer of generatedTreeSha256. It runs at the end of a generation,
    after the tree has already been replaced, so a version of it that dropped the thirteen fetch
    fields or the six image fields would destroy the provenance record and the run would still
    print Done. Nothing offline saw that.

    The record is a copy of the committed one, so the field list is the real one rather than an
    invented one, and it is written under a temporary directory.
    """
    committed = read_provenance()
    assert "generatedTreeSha256" in committed, sorted(committed)
    replacement = "b" * 64

    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "spec", "PROVENANCE.json")
        put_text(path, json.dumps(committed, indent=2, ensure_ascii=False) + "\n")
        with repo_root_at(root):
            generate.write_tree_digest(replacement)
        with open(path, "rb") as handle:
            raw = handle.read()

    written = json.loads(raw.decode("utf-8"))
    assert written["generatedTreeSha256"] == replacement, written["generatedTreeSha256"]
    assert list(written) == list(committed), (list(written), list(committed))
    for key, value in committed.items():
        if key != "generatedTreeSha256":
            assert written[key] == value, key
    assert b"\r" not in raw, "the record was written with CRLF"
    assert raw.endswith(b"\n"), "the record has no trailing newline"
    print("ok  provenance write: generatedTreeSha256 is replaced and the other {} fields "
          "survive".format(len(committed) - 1))


# The gate over what the live suite is allowed to address. Its refusals carry their own tail: the
# module's REFUSAL_TAIL belongs to the pre-processing refusals and says something else, and one
# constant carrying two sentences would rewrite every one of them.
ADDRESSING_REFUSAL_TAIL = "The integration suite may address only the container this run started."

# The port the image listens on inside the container, and its one declaration in the suite.
CONTAINER_PORT = "6969"
CONTAINER_PORT_DECLARATION = "public const ushort ContainerPort = " + CONTAINER_PORT + ";"

# The two real Whisparr libraries on this machine are published on the container port plus ten
# thousand and on the port after it. Derived rather than written out. The rule cannot refuse a
# number it does not hold, and a public repository has no reason to carry the address of somebody's
# personal instance in plain digits.
FORBIDDEN_HOST_PORTS = tuple(str(int(CONTAINER_PORT) + 10000 + step) for step in (0, 1))

# The one derivation an address may come from, and the one docker call the suite may make.
ADDRESS_DERIVATION = "GetMappedPublicPort"
DOCKER_SUBCOMMAND = "port"
DOCKER_CONTAINER_ARGUMENT = "fixture.ContainerId"

# The sweep script boots a container and issues a real delete against it, so two of the same rules
# hold over it: it may not name either forbidden port, and the name it addresses carries a suffix
# unique to the run rather than being a fixed literal that a second run would destroy.
CONTAINER_NAME_ASSIGNMENT = "CONTAINER_NAME = "
PER_RUN_ELEMENT = "uuid.uuid4()"

URL_LITERAL = re.compile(r"https?://")
DOCKER_ARGUMENT = re.compile(r"start\.ArgumentList\.Add\(([^)]*)\)")
DOCKER_PROCESS = re.compile(r'(?:ProcessStartInfo|Process\.Start)[^;]*?"docker"')

INTEGRATION_PROJECT = os.path.join("test", "Whisparr2.Net.IntegrationTests")
SWEEP_SCRIPT = os.path.join("generator", "conformance.py")


def addressing_refusal(text):
    """One refusal line, opening with the shared prefix and closing with the addressing tail."""
    return REFUSAL_PREFIX + text + " " + ADDRESSING_REFUSAL_TAIL


def statements(text):
    """(first line number, collapsed text) for every ;-terminated statement in a source file.

    The unit of the address rule is the statement, not the line. A base URL built from the mapped
    port does not fit on one line at this repository's width, so a line-scoped rule refuses the
    correct expression. Widening the rule to accept that would be the carve-out this gate must not
    have; reading the whole statement states the same rule over its real unit, and it still refuses
    a literal address written on one line.
    """
    number = 1
    buffer = []
    start = 1
    for line in text.split("\n"):
        if not buffer:
            start = number
        buffer.append(line.strip())
        if ";" in line:
            yield start, " ".join(part for part in buffer if part)
            buffer = []
        number += 1
    if buffer:
        yield start, " ".join(part for part in buffer if part)


def audit_source(relative, text):
    """Return the refusal lines for one C# source. An empty list means the four rules hold."""
    refusals = []

    # R1. An address is built through the mapped port of this run's own container, or not at all.
    for number, statement in statements(text):
        if URL_LITERAL.search(statement) and ADDRESS_DERIVATION not in statement:
            refusals.append(addressing_refusal(
                "{}:{} builds an address that does not come from {}: {}".format(
                    relative, number, ADDRESS_DERIVATION, statement)))

    refusals.extend(audit_lines(relative, text))

    # R4. One docker subcommand, one argument shape.
    if DOCKER_PROCESS.search(text):
        arguments = [argument.strip() for argument in DOCKER_ARGUMENT.findall(text)]
        first = arguments[0] if arguments else None
        if first is None:
            # A call that adds no argument runs whatever the client defaults to, and a gate that
            # cannot read the subcommand refuses rather than passes.
            refusals.append(addressing_refusal(
                "{} starts the docker client and adds no argument, so the subcommand it runs "
                "cannot be read.".format(relative)))
        elif first != '"' + DOCKER_SUBCOMMAND + '"':
            refusals.append(addressing_refusal(
                "{} runs the docker subcommand {} rather than {}.".format(
                    relative, first, DOCKER_SUBCOMMAND)))
        elif len(arguments) < 2 or DOCKER_CONTAINER_ARGUMENT not in arguments[1]:
            second = arguments[1] if len(arguments) > 1 else "no container"
            refusals.append(addressing_refusal(
                "{} runs docker {} against {} rather than against the fixture's own container "
                "id.".format(relative, DOCKER_SUBCOMMAND, second)))

    return refusals


def audit_lines(relative, text):
    """The two port rules, which are line-scoped because a port literal sits on one line.

    Shared by the C# sources and the sweep script, because naming a real instance is the same
    mistake in either language.
    """
    refusals = []
    for number, line in enumerate(text.split("\n"), start=1):
        stripped = line.strip()

        # R2. The owner's real instances are never named, in any context, comments included.
        for port in FORBIDDEN_HOST_PORTS:
            if port in line:
                refusals.append(addressing_refusal(
                    "{}:{} names host port {}, which is a real Whisparr library on this "
                    "machine: {}".format(relative, number, port, stripped)))

        # R3. The container port appears in its declaration and nowhere else. One forbidden host
        # port contains the container port as a substring, and R2 has already reported it by name,
        # so one mistake produces one refusal.
        if CONTAINER_PORT in line and CONTAINER_PORT_DECLARATION not in line:
            if not any(port in line for port in FORBIDDEN_HOST_PORTS):
                refusals.append(addressing_refusal(
                    "{}:{} carries {} outside the container-port declaration: {}".format(
                        relative, number, CONTAINER_PORT, stripped)))
    return refusals


def audit_script(relative, text):
    """Return the refusal lines for the sweep script. An empty list means both rules hold.

    The address rule is not applied here. The script reads its host port back from the container it
    created and builds a loopback URL from it, which is the correct shape in Python and carries no
    mapped-port accessor to name.
    """
    refusals = list(audit_lines(relative, text))

    names = [(number, line.strip()) for number, line in enumerate(text.split("\n"), start=1)
             if CONTAINER_NAME_ASSIGNMENT in line]
    if not names:
        refusals.append(addressing_refusal(
            "{} declares no container name, so the container it addresses cannot be "
            "read.".format(relative)))
    for number, line in names:
        if PER_RUN_ELEMENT not in line:
            refusals.append(addressing_refusal(
                "{}:{} names a container without a suffix unique to the run: {}".format(
                    relative, number, line)))
    return refusals


def integration_sources():
    """(relative path, absolute path) for every C# source in the integration project.

    bin and obj are skipped. The build writes generated C# under both, and the gate has nothing to
    say about generator output that no contributor edits.
    """
    found = []
    root = os.path.join(REPO_ROOT, INTEGRATION_PROJECT)
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = [name for name in subdirectories if name not in ("bin", "obj")]
        for name in sorted(files):
            if name.endswith(".cs"):
                full = os.path.join(directory, name)
                found.append((os.path.relpath(full, REPO_ROOT).replace(os.sep, "/"), full))
    return sorted(found)


def refuse_no_integration_sources(count):
    """Refuse when the gate found nothing to read, rather than passing.

    A suite that was deleted, or a project that moved, would otherwise satisfy every rule by having
    no source to break one.
    """
    if count <= 0:
        return addressing_refusal(
            "the gate read no C# source under {}, so a deleted suite would satisfy every "
            "rule.".format(INTEGRATION_PROJECT.replace(os.sep, "/")))
    return None


# One forbidden C# shape per branch. A branch with no synthetic source is a branch nobody knows
# works. The forbidden host port is derived rather than written, for the same reason the constant
# above is, and the container name is a placeholder that exists nowhere.
SYNTHETIC_SOURCES = {
    # R1: an address written into source rather than read back from this run's container.
    "R1": 'string baseUrl = "http://127.0.0.1:22451";\n',
    # R2: a real instance on this machine, named without building a URL, so R1 does not fire first.
    "R2": "private const int OwnerInstancePort = {};\n".format(FORBIDDEN_HOST_PORTS[1]),
    # R3: the container port restated outside its declaration.
    "R3": "private const ushort AlsoTheContainerPort = {};\n".format(CONTAINER_PORT),
    # R4a: the docker client started with no argument, so the subcommand cannot be read.
    "R4a": 'ProcessStartInfo start = new("docker");\n',
    # R4b: a docker subcommand that is not port.
    "R4b": ('ProcessStartInfo start = new("docker");\n'
            'start.ArgumentList.Add("rm");\n'
            "start.ArgumentList.Add(fixture.ContainerId);\n"),
    # R4c: docker port against something other than this run's container.
    "R4c": ('ProcessStartInfo start = new("docker");\n'
            'start.ArgumentList.Add("port");\n'
            'start.ArgumentList.Add("example-instance");\n'),
}

# The C# control. Without it a gate that refused everything would satisfy all six shapes above.
CONTROL_SOURCE = (
    "public const ushort ContainerPort = 6969;\n"
    'BaseUrl = "http://" + _container.Hostname + ":"\n'
    "    + _container.GetMappedPublicPort(ContainerPort).ToString(CultureInfo.InvariantCulture);\n"
    'ProcessStartInfo start = new("docker");\n'
    'start.ArgumentList.Add("port");\n'
    "start.ArgumentList.Add(fixture.ContainerId);\n"
)

# One forbidden Python shape per branch of the script rules.
SYNTHETIC_SCRIPTS = {
    # P1: a real instance on this machine, named in the script that issues a delete.
    "P1": 'BASE = "http://127.0.0.1:{}"\nCONTAINER_NAME = "x-" + uuid.uuid4().hex\n'.format(
        FORBIDDEN_HOST_PORTS[0]),
    # P2: a fixed container name, which a second run would force-remove mid-sweep.
    "P2": 'CONTAINER_NAME = "example-instance"\n',
    # P3: no container name declared at all, so the name the run addresses cannot be read.
    "P3": 'container = "example-instance"\n',
}

# The Python control, in the shape the sweep script is written in.
CONTROL_SCRIPT = (
    'CONTAINER_NAME = "whisparr2-conformance-" + uuid.uuid4().hex[:12]\n'
    'base = "http://127.0.0.1:{}".format(port)\n'
)


def check_integration_suite_addresses_only_its_own_container():
    """The gate accepts the committed sources and refuses nine forbidden shapes in nine sentences.

    What this pins is the one property whose failure is irreversible. Every source in the
    integration project can build an address, the sweep script boots a container and issues a real
    delete against it, and any address that is not the container the run started is somebody's live
    library. A suite that wrote into one would pass, print green and have destroyed real data.

    The controls are asserted first. Without them a gate that refused everything would satisfy
    every forbidden shape below and prove nothing.
    """
    assert audit_source("control.cs", CONTROL_SOURCE) == [], \
        audit_source("control.cs", CONTROL_SOURCE)
    assert audit_script("control.py", CONTROL_SCRIPT) == [], \
        audit_script("control.py", CONTROL_SCRIPT)

    fired = {}
    for auditor, shapes, suffix in ((audit_source, SYNTHETIC_SOURCES, ".cs"),
                                    (audit_script, SYNTHETIC_SCRIPTS, ".py")):
        for name, text in sorted(shapes.items()):
            refusals = auditor(name + suffix, text)
            assert len(refusals) >= 1, (name, refusals)
            assert all(line.startswith(REFUSAL_PREFIX) for line in refusals), refusals
            assert all(line.endswith(ADDRESSING_REFUSAL_TAIL) for line in refusals), refusals
            fired[name] = refusals[0]

    # Nine branches refusing with one sentence would pass every assertion above and tell a reader
    # nothing about which of them fired.
    assert len(set(fired.values())) == len(fired), fired

    sources = integration_sources()
    empty = refuse_no_integration_sources(len(sources))
    assert empty is None, empty
    assert refuse_no_integration_sources(0) is not None

    real = []
    for relative, path in sources:
        with open(path, encoding="utf-8") as handle:
            real.extend(audit_source(relative, handle.read()))
    with open(os.path.join(REPO_ROOT, SWEEP_SCRIPT), encoding="utf-8") as handle:
        real.extend(audit_script(SWEEP_SCRIPT.replace(os.sep, "/"), handle.read()))
    assert real == [], real

    print("ok  suite addressing: {} committed sources and the sweep script hold the rules, and {} "
          "forbidden shapes are each refused in their own words".format(len(sources), len(fired)))


# Two schemas and five properties, in the spirit of zero_condition_documents() above: an integer, a
# nullable string, a boolean, a reference to a string enum, and a nullable map of nullable strings.
# Small enough that a reader can hold the whole expectation in their head, and enough to reach every
# branch of the walker that reports a failure.
CONFORMANCE_PAIR_DOCUMENT = {
    "components": {
        "schemas": {
            "Thing": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "integer", "format": "int32"},
                    "label": {"type": "string", "nullable": True},
                    "enabled": {"type": "boolean"},
                    "kind": {"$ref": "#/components/schemas/ThingKind"},
                    "strings": {
                        "type": "object",
                        "additionalProperties": {"type": "string", "nullable": True},
                        "nullable": True,
                    },
                },
            },
            "ThingKind": {"enum": ["standard", "special"], "type": "string"},
        }
    }
}

CONFORMANCE_PAIR_ROOT = {"$ref": "#/components/schemas/Thing"}

# Six pairs. Four produce a finding and two must not, because a walker that flagged everything would
# satisfy the first four and be useless. The expectation carries the owning schema name: a finding
# that could not name its schema could not be keyed by schema and property, which is the whole shape
# of the patch list, and the two pairs that reach an inline subschema are where that is lost.
CONFORMANCE_PAIRS = (
    ("an undeclared property",
     {"id": 1, "javEpisodeFormat": "x"},
     ("undeclared", "Thing", "$.javEpisodeFormat")),
    ("a wrong JSON type", {"id": "1"}, ("type", "Thing", "$.id")),
    ("a null on a property that does not declare nullable", {"id": None},
     ("null", "Thing", "$.id")),
    ("an enum value outside the declared set", {"kind": "premium"},
     ("enum", "ThingKind", "$.kind")),
    ("a map-shaped site", {"strings": {"a": "b", "c": None}}, None),
    ("a fully conformant body",
     {"id": 1, "label": None, "enabled": True, "kind": "standard", "strings": {"a": "b"}},
     None),
)

# The seventh case is not a walker case. The content type is classified before a body is parsed, so
# the assertion is over the classifier, and handing the walker a body it never sees would state the
# wrong rule. Four that must not be read as JSON, two that must.
NON_JSON_CONTENT_TYPES = (
    "text/html",
    "text/html; charset=utf-8",
    "text/calendar",
    "text/plain",
)
JSON_CONTENT_TYPES = ("application/json", "application/json; charset=utf-8")


def conformance_findings(body):
    """Every finding the shipped walker records for one body against the pair document."""
    findings = []
    conformance.walk(CONFORMANCE_PAIR_DOCUMENT, CONFORMANCE_PAIR_ROOT, body, findings, set())
    return findings


def check_conformance_failure_branches():
    """The four failing verdicts fire over synthetic pairs, and the three script refusals fire too.

    What this pins is every branch of the sweep that a run against this pin never reaches. The type,
    null and enum verdicts occur zero times against the pinned image, so this is the only place they
    are ever seen firing: all three could be deleted and the Docker run stayed green. The shipped
    module is imported rather than restated, because a copy would pass while the walker was broken.

    Nothing here opens a socket or starts a container.
    """
    for name, body, expected in CONFORMANCE_PAIRS:
        findings = conformance_findings(body)
        if expected is None:
            assert findings == [], (name, findings)
            continue
        assert len(findings) == 1, (name, findings)
        verdict, schema, path, _detail = findings[0]
        assert (verdict, schema, path) == expected, (name, findings[0])

    # The four verdict sentences, from the findings the pairs just produced. Each is a line
    # docs/REGENERATION.md keys a row on, and a verdict with no sentence would print nothing.
    lines = conformance.refuse_findings([finding for _name, body, expected in CONFORMANCE_PAIRS
                                         if expected for finding in conformance_findings(body)])
    assert len(lines) == 4, lines
    assert len(set(lines)) == 4, lines
    assert all(line.startswith(conformance.REFUSAL_PREFIX) for line in lines), lines

    assert not any(conformance.classify_json(entry) for entry in NON_JSON_CONTENT_TYPES)
    assert all(conformance.classify_json(entry) for entry in JSON_CONTENT_TYPES)

    # The bodiless map names a schema, and against a document that no longer declares it the sweep
    # would validate a payload against the wrong schema and report every difference as a finding.
    named = {schema for schema, _shape, _query in conformance.BODILESS_SCHEMA_MAP.values()}
    declares = {"components": {"schemas": {schema: {"type": "object"} for schema in named}}}
    refusals = (
        (conformance.refuse_bodiless_map({"components": {"schemas": {}}},
                                         conformance.BODILESS_SCHEMA_MAP),
         conformance.refuse_bodiless_map(declares, conformance.BODILESS_SCHEMA_MAP)),
        (conformance.refuse_empty_selection(0), conformance.refuse_empty_selection(90)),
        # 80 answered, 4 non-JSON and 6 bodiless with data leave 70 to schema-check.
        (conformance.refuse_invariant(70, 80, 4, 8), conformance.refuse_invariant(70, 80, 4, 6)),
    )
    for fires, quiet in refusals:
        assert (fires or "").startswith(conformance.REFUSAL_PREFIX), fires
        assert fires.endswith(REFUSAL_TAIL), fires
        assert quiet is None, quiet
    assert len({fires for fires, _quiet in refusals}) == len(refusals), refusals

    produced = sum(1 for _name, _body, expected in CONFORMANCE_PAIRS if expected)
    print("ok  conformance branches: {} synthetic pairs, {} of them producing a finding, {} "
          "content types classified without parsing, {} script refusals fired".format(
              len(CONFORMANCE_PAIRS), produced,
              len(NON_JSON_CONTENT_TYPES) + len(JSON_CONTENT_TYPES), len(refusals)))


OFFLINE_CHECKS = (
    check_discriminator,
    check_non_discriminator,
    check_tier1_boundaries,
    check_blob_identity,
    check_atomic_write,
    check_committed_spec,
    check_provenance_complete,
    check_url_is_commit_addressed,
    check_flag_vectors,
    check_propose_is_fail_closed,
    check_image_identity,
    check_preprocess_zero_conditions,
    check_preprocess_transformations_apply,
    check_override_table,
    check_operation_id_shape,
    check_operation_id_derivation,
    check_clr_schema_partition,
    check_preprocess_refuses_scratch_input,
    check_preprocess_refuses_committed_write_targets,
    check_patched_document_on_disk,
    check_preprocess_reproduces_committed_output,
    check_preprocess_refusal_gate_exits,
    check_generated_tree_digest,
    check_generated_tree_matches_spec,
    check_tree_digest_moves,
    check_generated_files_manifest,
    check_staged_tree_gate_refuses,
    check_preflight_refuses_a_damaged_tree,
    check_write_tree_digest_keeps_the_record,
    check_integration_suite_addresses_only_its_own_container,
    check_conformance_failure_branches,
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


def run_generate(*arguments):
    """Invoke the real generation script and capture its output.

    Mirrors run_preprocess_spec above, including the encoding and errors pair, which is set
    because a non-ASCII byte in captured output otherwise raises UnicodeDecodeError on a Windows
    console.
    """
    completed = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "generate.py")]
        + list(arguments),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return completed.returncode, completed.stdout + completed.stderr


def check_generate_check_is_clean():
    """A fresh generation reproduces the committed tree byte for byte, and writes nothing.

    What this pins is the reproduction itself, and the write-nothing contract of
    generator/generate.py --check. Recording sizes and digests before the run and asserting them
    afterwards is what makes this a test of the control rather than of the message: a --check that
    printed the right sentence while writing into the repository would satisfy the first two
    assertions and fail the last two. check_preprocess_refuses_scratch_input states the same rule.

    This check is not in OFFLINE_CHECKS. It runs the pinned generator image and takes roughly 30 to
    60 seconds, and a machine without Docker must still get a green default suite.

    The three sampled sources are the first, the middle and the last of the sorted member list, so
    a failure names the same files on every run.
    """
    sources = [full for relative, full in generate.tree_members(REPO_ROOT)
               if relative.endswith(".cs")]
    watched = [
        os.path.join(REPO_ROOT, "spec", "PROVENANCE.json"),
        os.path.join(REPO_ROOT, ".openapi-generator", "FILES"),
        os.path.join(REPO_ROOT, ".openapi-generator-ignore"),
        sources[0],
        sources[len(sources) // 2],
        sources[-1],
    ]
    before = {path: (os.path.getsize(path), sha256_file(path)) for path in watched}
    digest_before = generate.tree_sha256(REPO_ROOT)

    code, output = run_generate("--check")

    assert code == 0, (code, output)
    assert "match the committed tree byte for byte" in output, output
    for path in watched:
        assert (os.path.getsize(path), sha256_file(path)) == before[path], path
    assert generate.tree_sha256(REPO_ROOT) == digest_before, "the check run changed the tree"
    print("ok  docker: a fresh generation reproduces the committed tree byte for byte and wrote "
          "nothing")


DOCKER_CHECKS = (check_generate_check_is_clean,)


def main():
    parser = argparse.ArgumentParser(description="Self-test the Whisparr 2 pipeline scripts.")
    parser.add_argument(
        "--network",
        action="store_true",
        help="Also run the checks that fetch real commits from raw.githubusercontent.com.",
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Also run the checks that regenerate the client through the pinned image.",
    )
    args = parser.parse_args()

    checks = list(OFFLINE_CHECKS)
    if args.network:
        checks.extend(NETWORK_CHECKS)
    if args.docker:
        checks.extend(DOCKER_CHECKS)
    for check in checks:
        check()

    print("{} checks passed.".format(len(checks)))


if __name__ == "__main__":
    main()
