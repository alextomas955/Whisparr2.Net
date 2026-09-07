#!/usr/bin/env python3
"""Prove the refusals that stand between this repository and the wrong application, and prove that
the transformations the pinned document needs still change it.

The failure the refusals guard against is silent. If the eros document is accepted, or if bytes
nobody stated in advance are accepted, the result is a client that compiles, produces no warnings,
passes a build and targets a different application. That defect surfaces long after generation,
packaging and documentation have all been built on the wrong document.

The failure the pre-processing checks guard against is quieter still. Whisparr fixes something
upstream, a rewrite that was patching it has nothing left to patch, and it keeps running over a
document it no longer describes with nothing to say so. Each of the five is driven over a document
where its own zero-condition holds, and each is driven over the pin and made to report what it
changed. Three further checks judge the deliverable rather than the functions: the
committed patched document, a run of the script that must reproduce it byte for byte, and a run
over a document with nothing left to change, which must exit non-zero and write nothing.

Standard library only. No framework, no requirements file and no configuration file. A bare assert
and a non-zero exit are what this needs.

This script is run by hand today. Wiring it into a workflow lands with the phase that adds one.

    python generator/selftest.py
    python generator/selftest.py --docker
"""

import argparse
import ast
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import build_spec
import conformance
import container
import generate
import preprocess_spec
from _common import (
    REPO_ROOT,
    resolve_repo_path,
    sha256_file,
    write_bytes_atomic,
)

# The twelve spec fields build_spec.py owns, in the order the provenance record carries them. The
# two image constants are asserted in check_provenance_complete rather than listed here: they are
# module constants of the container harness, not a block with a writer of its own.
SPEC_KEYS = (
    "builtAt",
    "specRepo",
    "specRefName",
    "specCommit",
    "specSha256",
    "specBytes",
    "specOpenApiVersion",
    "specPathCount",
    "specOperationCount",
    "specSchemaCount",
    "sdkImageDigest",
    "swashbuckleCliVersion",
)

HEX = set("0123456789abcdef")


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
    return resolve_repo_path(build_spec.DEFAULT_OUT_FILE)


def read_provenance():
    with open(resolve_repo_path(build_spec.PROVENANCE_PATH), encoding="utf-8") as handle:
        return json.load(handle)


def read_conformance():
    with open(resolve_repo_path(preprocess_spec.CONFORMANCE_FILE), encoding="utf-8") as handle:
        return json.load(handle)


def check_discriminator():
    """An eros-shaped document is refused, and the refusal names both paths in words."""
    problems = build_spec.check_tier2(document("3.0.1", "3.0.0", EROS_PATHS))
    assert len(problems) == 1, problems
    assert "/api/v3/movie" in problems[0], problems[0]
    assert "/api/v3/series" in problems[0], problems[0]
    assert "eros" in problems[0], problems[0]

    assert build_spec.check_tier2(document("3.0.1", "3.0.0", WHISPARR2_PATHS)) == []
    print("ok  discriminator: eros refused naming /api/v3/movie and /api/v3/series, v2 accepted")


def check_non_discriminator():
    """openapi and info.version do not affect the verdict, in either direction."""
    accepted = build_spec.check_tier2(document("3.0.1", "3.0.0", WHISPARR2_PATHS))
    assert build_spec.check_tier2(document("3.1.4", "9.9.9", WHISPARR2_PATHS)) == accepted

    refused = build_spec.check_tier2(document("3.0.1", "3.0.0", EROS_PATHS))
    assert build_spec.check_tier2(document("3.1.4", "9.9.9", EROS_PATHS)) == refused
    print("ok  non-discriminator: openapi and info.version do not change the verdict")


def check_atomic_write():
    """A write that raises leaves the previous file byte-identical and no temp file behind."""
    known = b"the previous contents\n"
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "pinned.bin")
        with open(path, "wb") as handle:
            handle.write(known)

        # Not a bytes-like object, so handle.write raises before os.replace is reached.
        try:
            write_bytes_atomic(path, object())
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

    The byte count and the sha256 are what a developer with no network, no Docker and no build
    re-verifies the committed document with, so both are kept and neither is a lower bound.

    This is also the assertion that catches a CRLF-mangled checkout. With core.autocrlf=true and no
    .gitattributes rule the checked-out spec carries injected CR bytes and neither value matches.
    """
    provenance = read_provenance()
    path = read_committed_spec()
    with open(path, "rb") as handle:
        body = handle.read()

    assert len(body) == provenance["specBytes"], (len(body), provenance["specBytes"])
    assert sha256_file(path) == provenance["specSha256"]

    patched = resolve_repo_path(preprocess_spec.DEFAULT_OUT_FILE)
    assert sha256_file(patched) == provenance["generatedSpecSha256"], patched
    print("ok  committed specs: two files judged, bytes and sha256 on disk match provenance")


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
    commit = provenance["specCommit"]
    assert len(commit) == 40 and set(commit) <= HEX, commit

    patched = provenance["generatedSpecSha256"]
    assert len(patched) == 64 and set(patched) <= HEX, patched

    # Both image keys are asserted here rather than through a list of their own. They are constants
    # of the container harness, so there is no writer whose absence a missing key could implicate.
    for key in ("imageTag", "imageDigest"):
        value = provenance.get(key)
        assert isinstance(value, str) and value.strip(), key

    # The C# fixture builds its container from this recorded key while the Python sweep runs the
    # module constant. The two are written independently, and a disagreement puts the suite and the
    # sweep on different images without either of them noticing.
    assert provenance["imageDigest"] == container.IMAGE_REF, provenance["imageDigest"]

    print("ok  provenance: {} spec fields present and observed, both image constants recorded, "
          "patched-spec hash recorded, recorded image digest matches the harness "
          "constant".format(len(SPEC_KEYS)))


# Every refusal line in the pre-processing module opens with the first and closes with the second,
# so one grep finds them all. docs/REGENERATION.md keys its refusal table on the same strings.
REFUSAL_PREFIX = "ERROR: REFUSED - "
REFUSAL_TAIL = "Nothing was written."


def measured_document(status_codes_satisfied, schemas_satisfied):
    """A synthetic document declaring exactly what the committed conformance record measures.

    Derived from the record rather than written out, so no operation key, status code or schema
    name is stated twice. Each half can be handed to the fifth transformation already satisfied or
    still to do, which is what lets a caller drive a composite zero-condition over the three
    combinations that matter.

    The schemas are declared as bare objects. What the transformation asserts about them is that
    the document declares them at all, because a reference it attached to an undeclared schema
    would point at nothing.
    """
    record = read_conformance()
    paths = {}
    named = []

    for operation_key, code in record["writeProbe"].items():
        if str(code) == preprocess_spec.OK:
            continue
        method, path = operation_key.split(" ", 1)
        declared = str(code) if status_codes_satisfied else preprocess_spec.OK
        paths.setdefault(path, {})[method.lower()] = {
            "responses": {declared: {"description": "Success"}}
        }

    for entry in record["bodilessOperationsReturningData"]:
        if "schema" not in entry:
            continue
        method, path = entry["operation"].split(" ", 1)
        response = {"description": "Success"}
        if schemas_satisfied:
            response["content"] = preprocess_spec.attached_schema(
                entry["schema"], entry["shape"]
            )
        paths.setdefault(path, {})[method.lower()] = {"responses": {"200": response}}
        named.append(entry["schema"])

    return {
        "paths": paths,
        "components": {"schemas": {name: {"type": "object"} for name in named}},
    }


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
        # Both measured kinds already applied. Composite on purpose: the fifth transformation
        # refuses only when neither kind has anything left to change, so a document satisfying one
        # of the two must not appear here. The two that satisfy one each are driven in
        # check_preprocess_measured_responses, where a refusal is the failure.
        "T5": measured_document(status_codes_satisfied=True, schemas_satisfied=True),
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
    """The five transformations run over the pinned document without refusing, and report what
    they changed.

    The per-transformation counts and the three totals are printed, not asserted against literals.
    Each is a fact of the committed document, and a hand-written copy of a fact that comes from a
    committed source is what this repository's conventions forbid. What catches a transformation
    that went no-op is check_preprocess_zero_conditions, check_preprocess_refusal_gate_exits and
    the byte-exact reproduction in check_preprocess_reproduces_committed_output, which together
    imply every number below.
    """
    document = parsed_raw_spec()
    counts = []
    for name, transform in preprocess_spec.TRANSFORMATIONS:
        count, refusals = transform(document)
        assert refusals == [], (name, refusals)
        counts.append(count)

    paths = document["paths"]
    schemas = document["components"]["schemas"]
    measured = (len(paths), len(operations_of(document)), len(schemas))
    assert [name for name in preprocess_spec.CLR_SCHEMAS if name in schemas] == []
    print("ok  transformations: {} report {} over the pin, leaving {} path items, {} operations "
          "and {} schemas".format(
              len(counts), ", ".join(str(count) for count in counts), *measured))


def check_override_table():
    """Every override entry matches an operation, and a ninth that matches none is refused."""
    overrides = preprocess_spec.OPERATION_ID_OVERRIDES

    document = parsed_raw_spec()
    preprocess_spec.delete_root_path(document)
    matched, refusals = preprocess_spec.assign_operation_ids(document)
    # An unused key is the stale-override refusal, so a clean run is the assertion that every entry
    # matched. That is the assertion here; the entry count and the operation count are printed.
    assert refusals == [], refusals

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
    print("ok  override table: {} entries, every one matching one of {} operations, and an "
          "injected ninth refused by name".format(len(overrides), matched))


def check_operation_id_derivation():
    """Distinct names over every operation in the pin, no collisions, and the readability claim
    checked.

    The global collision assertion is strictly stricter than the per-class collision the generator
    would suffer. The per-tag count is measured anyway, because it is the collision that would
    actually break a build, and reporting it is what makes the stricter assertion legible.

    Both assertions are against the measured population and not against a copied literal. The
    population is a fact of the committed document; the distinctness is a property of the
    derivation, and it is the property a collision breaks.
    """
    document = parsed_raw_spec()
    preprocess_spec.delete_root_path(document)
    count, refusals = preprocess_spec.assign_operation_ids(document)
    assert refusals == [], refusals

    named = [
        (operation["operationId"], (operation.get("tags") or [""])[0])
        for _, _, _, operation in operations_of(document)
    ]
    # The population is not a count of endpoint groups. Measured 2026-09-06: building the document
    # from source declares both get and head on /ping where the fetched document declared only get,
    # so HeadPing is one of the arrivals alongside the three groups the source added.
    assert len(named) == count, (len(named), count)
    assert len({identifier for identifier, _ in named}) == len(named)
    assert len(set(named)) == len(named)

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


# The three names running T5 ahead of the operationId derivation exists for, spelled out. A
# derived assertion on its own would pass over a record that named three other operations, and a
# change count would pass with the response attached under a media type the array walker cannot
# see. These three are the whole observable effect of the ordering decision.
RENAMED_BY_ATTACHMENT = ("ListAutoTaggingSchema", "ListCustomFormatSchema", "ListSeriesLookup")


def derived_ids(document):
    """The operationId every operation carries after the derivation has run over this document."""
    return {key: operation["operationId"] for key, _m, _p, operation in operations_of(document)}


def check_preprocess_measured_responses():
    """Each kind, each refusal and each rename of the fifth transformation, driven offline.

    The two kinds are asserted separately off the pure plan function, as the set of operations the
    committed record names rather than as a count of them. The composite zero-condition is driven
    over three documents, because a group that drives only the refusing one passes with a per-kind
    condition in place, and a per-kind condition would refuse the whole correct document the day
    upstream annotates one of the two.

    The renames are asserted as operation ids and never as a change count. A response attached
    under text/json produces a non-zero count with no rename at all, which is the silent no-op this
    is here to catch.
    """
    record = read_conformance()
    document = parsed_raw_spec()
    plan = preprocess_spec.measured_patch_plan(document, record)

    # Each kind against what the record itself names. A status code the probe measured at 200 needs
    # no declaration changed, and a bodiless operation the record names no schema for returns an
    # object no schema in the document describes.
    measured_codes = {key for key, code in record["writeProbe"].items()
                      if str(code) != preprocess_spec.OK}
    measured_schemas = {entry["operation"]
                        for entry in record["bodilessOperationsReturningData"]
                        if "schema" in entry}
    assert set(plan[preprocess_spec.STATUS_KIND]) == measured_codes, sorted(measured_codes)
    assert set(plan[preprocess_spec.SCHEMA_KIND]) == measured_schemas, sorted(measured_schemas)
    assert all(entry["code"] == str(record["writeProbe"][key])
               for key, entry in plan[preprocess_spec.STATUS_KIND].items())
    assert all(entry["code"] != preprocess_spec.OK
               for entry in plan[preprocess_spec.STATUS_KIND].values())
    # Pure: the plan describes and never applies.
    assert preprocess_spec.OK in document["paths"]["/api/v3/tag"]["post"]["responses"]

    # The attachment names one media type and no other. returns_json_array walks exactly
    # application/json, so any other key renames nothing.
    attached = preprocess_spec.attached_schema("Thing", "array")
    assert set(attached) == {"application/json"}, sorted(attached)
    assert attached["application/json"]["schema"]["type"] == "array", attached
    assert set(preprocess_spec.attached_schema("Thing", "object")["application/json"]["schema"]) \
        == {"$ref"}

    # The composite zero-condition, over one document that must refuse and two that must not.
    both = measured_document(status_codes_satisfied=True, schemas_satisfied=True)
    count, refusals = preprocess_spec.declare_measured_responses(both)
    assert count == 0, count
    assert len(refusals) == 1 and refusals[0].startswith(REFUSAL_PREFIX), refusals
    assert refusals[0].endswith(REFUSAL_TAIL), refusals[0]

    codes_only = measured_document(status_codes_satisfied=True, schemas_satisfied=False)
    count, refusals = preprocess_spec.declare_measured_responses(codes_only)
    assert refusals == [], refusals
    assert count == len(measured_schemas), (count, len(measured_schemas))

    schemas_only = measured_document(status_codes_satisfied=False, schemas_satisfied=True)
    count, refusals = preprocess_spec.declare_measured_responses(schemas_only)
    assert refusals == [], refusals
    assert count == len(measured_codes), (count, len(measured_codes))

    # The image-digest refusal, over a record whose digest was changed in memory and over the
    # committed one. The patch list is a measurement against a running image, so the image is the
    # identity that has to match.
    real = preprocess_spec.read_json
    tampered = json.loads(json.dumps(record))
    tampered["measuredAgainst"]["imageDigest"] = "sha256:" + "0" * 64
    intact = parsed_raw_spec()
    before = json.dumps(intact)
    try:
        preprocess_spec.read_json = (
            lambda relative: tampered if relative == preprocess_spec.CONFORMANCE_FILE
            else real(relative)
        )
        count, refusals = preprocess_spec.declare_measured_responses(intact)
    finally:
        preprocess_spec.read_json = real
    assert count == 0, count
    assert len(refusals) == 1 and refusals[0].startswith(REFUSAL_PREFIX), refusals
    assert json.dumps(intact) == before, "the document was patched behind a refusal"
    assert preprocess_spec.declare_measured_responses(parsed_raw_spec())[1] == [], \
        "the committed record refuses against the committed provenance"

    # And the refusal it must not become. main() overwrites generatedSpecSha256 with the
    # post-transformation hash on every run, so an equality on it would hold for one run and refuse
    # every run after that. Asserted over the source, because a later edit that reintroduced the
    # comparison would pass every assertion above.
    source_path = resolve_repo_path("generator/preprocess_spec.py")
    with open(source_path, encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source)
    compared = [
        ast.get_source_segment(source, node) for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and "generatedSpecSha256" in (ast.get_source_segment(source, node) or "")
    ]
    assert not compared, compared

    # The three renames, as operation ids over the pin with the attachment in place and without it.
    without = parsed_raw_spec()
    preprocess_spec.delete_root_path(without)
    assert preprocess_spec.assign_operation_ids(without)[1] == []

    attached_document = parsed_raw_spec()
    preprocess_spec.delete_root_path(attached_document)
    assert preprocess_spec.declare_measured_responses(attached_document)[1] == []
    assert preprocess_spec.assign_operation_ids(attached_document)[1] == []

    before_ids = derived_ids(without)
    after_ids = derived_ids(attached_document)
    moved = {key: (before_ids[key], after_ids[key])
             for key in before_ids if before_ids[key] != after_ids[key]}
    arrays = sorted(key for key, entry in plan[preprocess_spec.SCHEMA_KIND].items()
                    if entry["shape"] == "array")
    assert sorted(moved) == arrays, (sorted(moved), arrays)
    assert sorted(new for _old, new in moved.values()) == sorted(RENAMED_BY_ATTACHMENT), moved
    for key, (old, new) in moved.items():
        assert old.startswith("Get") and new == "List" + old[len("Get"):], (key, old, new)
    # A rename cannot introduce a collision unnoticed. Against the measured population, not a
    # copied one.
    assert len(set(after_ids.values())) == len(after_ids), len(after_ids)

    print("ok  measured responses: {} status codes and {} response schemas planned from the "
          "record, three documents drive the composite zero-condition, the digest refusal fires "
          "and stays quiet, and {} of {} distinct operation ids move from Get to List".format(
              len(measured_codes), len(measured_schemas), len(moved), len(after_ids)))


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
            items = node.items()
        elif isinstance(node, list):
            items = enumerate(node)
        else:
            return
        for key, value in items:
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

    walk(document, None)
    return inside, outside


def check_clr_schema_partition():
    """The reference sites partition into the one inside the five and the rest outside, and the
    two witness shapes land where the partition says they do.

    The two reference counts are printed rather than asserted against literals: both are facts of
    the committed document. What is asserted is the partition itself, which is what the rewrite
    relies on, and the shape each outside site received.
    """
    document = parsed_raw_spec()
    inside, outside = clr_reference_sites(document)
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

    The encoding and errors pair is set because a non-ASCII byte in captured output otherwise
    raises UnicodeDecodeError on a Windows console. run_generate below is written the same way.
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


def check_clr_reference_inside_an_array_is_rewritten():
    """A reference sitting as a direct element of an allOf array is rewritten, not left dangling.

    The five schemas are deleted unconditionally, so a site the rewrite does not collect leaves the
    output document referring to a component it no longer declares, and the generator then runs
    against that document. Driven over the pin with one property added, so the ten sites the
    committed document already carries are present at the same time.

    The sites are located with clr_reference_pointers, which walks list elements, and read back at
    those same positions after the rewrite. Nothing else here would report the array shape:
    check_clr_schema_partition asserts the count the rewrite returns against a walk of its own, and
    a site neither of them collects agrees.
    """
    mutated = parsed_raw_spec()
    carrier = mutated["components"]["schemas"]["HealthResource"]["properties"]
    carrier["someNewField"] = {"allOf": [{"$ref": preprocess_spec.REF_PREFIX + "Version"}]}
    added = ("components", "schemas", "HealthResource", "properties", "someNewField", "allOf", 0)

    pointers = clr_reference_pointers(mutated)
    assert added in [trail for trail, _ in pointers], pointers

    count, refusals = preprocess_spec.rewrite_clr_schemas(mutated)
    assert refusals == [], refusals
    assert count == len(pointers), (count, len(pointers))
    for trail, name in pointers:
        expected = preprocess_spec.DATE if name == "DateOnly" else preprocess_spec.STRING
        assert resolve_pointer(mutated, trail) == expected, (trail, name)

    schemas = mutated["components"]["schemas"]
    assert [name for name in preprocess_spec.CLR_SCHEMAS if name in schemas] == []
    print("ok  array reference: a $ref added as an allOf element brings the rewritten sites to {}, "
          "and every one of them reads back as its replacement".format(count))


def check_patched_document_on_disk():
    """The committed patched document carries the four results, read out of the file itself.

    Every other pre-processing check drives a transformation over a document it parsed itself. This
    one judges the deliverable. The reference sites are located in the raw pin and then read at
    those same positions in the patched file, so the assertion cannot drift into counting nullable
    strings the document already carried.

    The operation, schema and reference-site counts are printed rather than asserted against
    literals. Every one of them is implied by check_preprocess_reproduces_committed_output, which
    reproduces this file byte for byte.
    """
    with open(resolve_repo_path(preprocess_spec.DEFAULT_OUT_FILE), encoding="utf-8") as handle:
        patched = json.load(handle)

    assert patched["security"] == preprocess_spec.SECURITY, patched["security"]
    assert "/" not in patched["paths"], sorted(patched["paths"])[:3]

    operations = operations_of(patched)
    identifiers = [operation["operationId"] for _, _, _, operation in operations]
    assert len(set(identifiers)) == len(identifiers), len(identifiers) - len(set(identifiers))
    invalid = [i for i in identifiers if not preprocess_spec.OPERATION_ID_PATTERN.fullmatch(i)]
    assert invalid == [], invalid

    schemas = patched["components"]["schemas"]
    assert [name for name in preprocess_spec.CLR_SCHEMAS if name in schemas] == []

    pointers = clr_reference_pointers(parsed_raw_spec())
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
    provenance_path = resolve_repo_path(build_spec.PROVENANCE_PATH)
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
        (resolve_repo_path(build_spec.PROVENANCE_PATH), sha256_file(resolve_repo_path(build_spec.PROVENANCE_PATH))),
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

    The member count is printed rather than asserted against a literal. A tree_members that
    quietly started walking the whole package root would produce a self-consistent digest, and what
    catches that is check_generated_files_manifest below: it compares the walked .cs member set
    against .openapi-generator/FILES in both directions, so a stray file in the walk fails there.
    """
    recorded = generate.read_provenance().get("generatedTreeSha256")
    assert recorded, "spec/PROVENANCE.json carries no generatedTreeSha256"

    members = generate.tree_members(REPO_ROOT)

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
# Any variable name, not one literally called "start". Keying on a name let a second call
# site under a different name run unread.
DOCKER_ARGUMENT = re.compile(r"\w+\.ArgumentList\.Add\(([^)]*)\)")
# The daemon is also reachable without a process. Testcontainers pulls a Docker client library
# into this project transitively, so the type names are in scope whether or not anyone meant
# them to be, and a call through it never touches ProcessStartInfo.
# The first argument of a docker call in the sweep script, which is the subcommand.
DOCKER_SUBCOMMAND_CALL = re.compile(r"run_docker\(\[\s*([^,\]]+)")
# The whole argument list of a docker call, so every quoted argument in it can be judged.
CONTAINER_NAME_CONSTANT = "CONTAINER_NAME"
DOCKER_CALL_ARGS = re.compile(r"run_docker\(\[([^\]]*)\]")
DOCKER_QUOTED = re.compile(r'"([^"]*)"')
DOCKER_CLIENT_API = re.compile(r"DockerClient|Docker\.DotNet|IDockerClient")
# A shell is a second way to reach the daemon without naming it in an argument list.
DOCKER_VIA_SHELL = re.compile(r'"(?:cmd|powershell|pwsh|sh|bash)"|/c |-Command ')
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

    # R4. One docker call site per file, one subcommand, one argument shape.
    #
    # Counted rather than searched. An earlier form ran one findall over the whole file and keyed
    # on a variable literally named "start", so a file that already held one compliant call
    # absorbed any number of non-compliant ones, and a second call site under a different name was
    # never read at all. Both were demonstrated.
    sites = DOCKER_PROCESS.findall(text)
    if len(sites) > 1:
        refusals.append(addressing_refusal(
            "{} starts the docker client {} times. One call site per file, so every argument list "
            "in it belongs to a call this rule can read.".format(relative, len(sites))))
    elif sites:
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

    # R5. The daemon is reached one way only. A client library and a shell both bypass R4 entirely,
    # and the client library is already on this project's transitive graph.
    for number, statement in statements(text):
        if DOCKER_CLIENT_API.search(statement):
            refusals.append(addressing_refusal(
                "{}:{} reaches the daemon through a client library rather than through the one "
                "read-only call this suite is allowed: {}".format(relative, number, statement)))
        elif DOCKER_VIA_SHELL.search(statement) and "docker" in statement:
            refusals.append(addressing_refusal(
                "{}:{} reaches the daemon through a shell, where no argument rule can read the "
                "subcommand: {}".format(relative, number, statement)))

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

    The C# address rule is not applied here. The script reads its host port back from the container
    it created and builds a loopback URL from it, which is the correct shape in Python and carries
    no mapped-port accessor to name.

    Two rules do apply, and they did not before. This script issues a real create, update and
    delete, so it is the write-capable half of this phase and had the weaker gate of the two.
    """
    refusals = list(audit_lines(relative, text))

    # Every docker subcommand this script may run. It creates and destroys its own container, so
    # the set is wider than the suite's single read-only call, but it is a set rather than
    # anything the script cares to pass.
    allowed = {'"create"', '"start"', '"logs"', '"port"', '"rm"', '"cp"', '"inspect"'}
    for number, statement in statements(text):
        for match in DOCKER_SUBCOMMAND_CALL.finditer(statement):
            argument = match.group(1).strip()
            if argument not in allowed:
                refusals.append(addressing_refusal(
                    "{}:{} runs the docker subcommand {}, which is not one this script may "
                    "run.".format(relative, number, argument)))
        for call in DOCKER_CALL_ARGS.finditer(statement):
            arguments = [a.strip() for a in call.group(1).split(",")]
            if not arguments or arguments[0] not in ('"rm"',):
                continue
            # rm is the destructive one and the only subcommand whose target must be pinned. A
            # broader rule over every quoted argument was written first and refused correct
            # content twice, on a log tail count and on the loopback publish spec. A rule needing
            # carve-outs is measuring the wrong thing, so it was narrowed to the case that matters.
            if CONTAINER_NAME_CONSTANT not in call.group(1):
                refusals.append(addressing_refusal(
                    "{}:{} removes a container that is not the per-run one this script created: "
                    "{}".format(relative, number, statement)))

    names = [(number, line.strip()) for number, line in enumerate(text.splitlines(), start=1)
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


# Two schemas and eight properties, in the spirit of zero_condition_documents() above: an integer, a
# nullable string, a boolean, a reference to a string enum, a nullable map of nullable strings, an
# array of integers, and a single-member allOf wrapper around the enum. Small enough that a reader
# can hold the whole expectation in their head, and enough to reach every branch of the property
# recorder: the map site, the array, the allOf wrapper and the plain reference.
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
                    "tags": {"type": "array", "items": {"type": "integer", "format": "int32"}},
                    "child": {"allOf": [{"$ref": "#/components/schemas/ThingKind"}]},
                    "loose": {"$ref": "#/components/schemas/Loose"},
                },
            },
            "ThingKind": {"enum": ["standard", "special"], "type": "string"},
            "Loose": {"type": "object", "properties": {"note": {"type": "string"}}},
        }
    }
}

CONFORMANCE_PAIR_ROOT = {"$ref": "#/components/schemas/Thing"}

# Every property Thing declares, each carrying a value of the declared type. Used as the body the
# seen-property assertions record from.
CONFORMANCE_DECLARED_PROPS = ("child", "enabled", "id", "kind", "label", "loose", "strings",
                              "tags")

CONFORMANCE_CONFORMANT_BODY = {
    "id": 1,
    "label": None,
    "enabled": True,
    "kind": "standard",
    "strings": {"a": "b"},
    "tags": [1, 2],
    "child": "special",
    "loose": {"note": "n"},
}

# The content type is classified before a body is parsed, so the assertion is over the classifier
# alone. One read answers 184,918 bytes of Graphviz, and a classifier that read it as JSON would
# record a shape for a document that was never JSON. Four that must not be read as JSON, two that
# must.
NON_JSON_CONTENT_TYPES = (
    "text/html",
    "text/html; charset=utf-8",
    "text/calendar",
    "text/plain",
)
JSON_CONTENT_TYPES = ("application/json", "application/json; charset=utf-8")


def conformance_seen(body):
    """The declared properties the shipped recorder finds in one body against the pair document."""
    seen = set()
    conformance.record_seen_properties(CONFORMANCE_PAIR_DOCUMENT, CONFORMANCE_PAIR_ROOT, body, seen)
    return seen


def check_conformance_failure_branches():
    """The four script refusals each fire and each stay quiet, and the sweep's recorders hold.

    What this pins is every branch of the sweep that a run against the pin never reaches. A refusal
    only ever observed passing is not evidenced, so each is driven once over an input that must fire
    it and once over an input that must not. The shipped module is imported rather than restated,
    because a copy would pass while the sweep was broken.

    Nothing here opens a socket or starts a container.
    """
    assert not any(conformance.classify_json(entry) for entry in NON_JSON_CONTENT_TYPES)
    assert all(conformance.classify_json(entry) for entry in JSON_CONTENT_TYPES)

    # shape is read straight off the parsed body, and the fifth transformation attaches an array
    # response or an object response according to that one word. Getting it wrong renames three
    # generated methods. The media type is recorded without its parameters, and the byte count is
    # of the raw body rather than of anything parsed out of it.
    assert [conformance.json_type_of(value)
            for value in (None, True, 1, 1.5, "x", [], {})] == [
                "null", "boolean", "integer", "number", "string", "array", "object"]
    assert conformance.bodiless_entry(
        "GET /example", "application/json; charset=utf-8", b'[{"id":1}]', [{"id": 1}]) == {
            "operation": "GET /example", "contentType": "application/json",
            "bytes": 10, "shape": "array"}
    assert conformance.bodiless_entry("GET /example", "application/json", b"{}", {})["shape"] == \
        "object"

    # An operation the map names carries the schema name into the record, and one it does not name
    # carries none. That key is the whole input the fifth transformation has for what to attach, so
    # an entry without it would leave the transformation with a copy of the map of its own.
    mapped = sorted(conformance.BODILESS_SCHEMA_MAP)[0]
    schema_name, mapped_shape, _query = conformance.BODILESS_SCHEMA_MAP[mapped]
    body = b"[]" if mapped_shape == "array" else b"{}"
    parsed = [] if mapped_shape == "array" else {}
    assert conformance.bodiless_entry(mapped, "application/json", body, parsed)["schema"] == \
        schema_name
    assert "schema" not in conformance.bodiless_entry(
        "GET /example", "application/json", b"{}", {})

    # The bodiless map names the schema the fifth transformation attaches. Against a document that
    # no longer declares it, the transformation would attach a reference to nothing.
    named = {schema for schema, _shape, _query in conformance.BODILESS_SCHEMA_MAP.values()}
    declares = {"components": {"schemas": {schema: {"type": "object"} for schema in named}}}
    # The map states the shape it expects and the sweep measures the shape the instance returned.
    # A disagreement would attach an array where the instance sends an object, or the reverse, and
    # name the generated method for the wrong one.
    disagreeing = {"operation": mapped,
                   "shape": "object" if mapped_shape == "array" else "array"}
    agreeing = {"operation": mapped, "shape": mapped_shape}
    refusals = (
        (conformance.refuse_bodiless_map({"components": {"schemas": {}}},
                                         conformance.BODILESS_SCHEMA_MAP),
         conformance.refuse_bodiless_map(declares, conformance.BODILESS_SCHEMA_MAP)),
        (conformance.refuse_bodiless_shape([disagreeing], conformance.BODILESS_SCHEMA_MAP),
         conformance.refuse_bodiless_shape([agreeing], conformance.BODILESS_SCHEMA_MAP)),
        (conformance.refuse_empty_selection(0), conformance.refuse_empty_selection(1)),
        # The image this run would boot against the image the client is described by. Driven with
        # the real pair, so the quiet side also reports that the pin and the record agree today.
        (conformance.refuse_measured_image(container.IMAGE_REF, "sha256:" + "0" * 64),
         conformance.refuse_measured_image(container.IMAGE_REF, container.IMAGE_REF)),
    )
    for fires, quiet in refusals:
        assert (fires or "").startswith(conformance.REFUSAL_PREFIX), fires
        assert fires.endswith(REFUSAL_TAIL), fires
        assert quiet is None, quiet
    assert len({fires for fires, _quiet in refusals}) == len(refusals), refusals

    # The recorder is the only input to the never-returned list. A recorder that recorded nothing
    # would report every declared property of every touched schema as never returned, and a
    # never-returned list read as a patch list deletes real properties from the generated models.
    seen = conformance_seen(CONFORMANCE_CONFORMANT_BODY)
    assert seen == {("Thing", prop) for prop in CONFORMANCE_DECLARED_PROPS} | {("Loose", "note")}, \
        seen
    assert conformance.declared_never_returned(CONFORMANCE_PAIR_DOCUMENT, seen) == [], seen

    partial = conformance_seen({"id": 1})
    assert partial == {("Thing", "id")}, partial
    assert conformance.declared_never_returned(CONFORMANCE_PAIR_DOCUMENT, partial) == [
        {"schema": "Thing", "property": prop}
        for prop in CONFORMANCE_DECLARED_PROPS if prop != "id"
    ]

    print("ok  conformance branches: {} content types classified without parsing, {} declared "
          "properties recorded from one body and {} of them reported never returned from another, "
          "{} script refusals fired and stayed quiet".format(
              len(NON_JSON_CONTENT_TYPES) + len(JSON_CONTENT_TYPES), len(seen),
              len(CONFORMANCE_DECLARED_PROPS) - 1, len(refusals)))


OFFLINE_CHECKS = (
    check_discriminator,
    check_non_discriminator,
    check_atomic_write,
    check_committed_spec,
    check_provenance_complete,
    check_preprocess_zero_conditions,
    check_preprocess_transformations_apply,
    check_override_table,
    check_operation_id_shape,
    check_operation_id_derivation,
    check_preprocess_measured_responses,
    check_clr_schema_partition,
    check_preprocess_refuses_scratch_input,
    check_preprocess_refuses_committed_write_targets,
    check_clr_reference_inside_an_array_is_rewritten,
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


def run_conformance():
    """Invoke the real sweep and capture its output, with the external probe off.

    Mirrors run_generate above, including the encoding and errors pair. The flag is removed from
    the environment rather than left to whatever the caller exported, because the Docker group must
    not need a route to the public internet and the probe's one read reaches an external metadata
    service.
    """
    environment = dict(os.environ)
    environment.pop(conformance.EXTERNAL_FLAG, None)
    completed = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "conformance.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        check=False,
    )
    return completed.returncode, completed.stdout + completed.stderr


# The one operation the external probe contributes. The committed file was produced with the probe
# on and the check below runs without it, so this entry is the whole of the difference a hermetic
# run is allowed to have. Naming it is what lets every list be compared entry for entry rather than
# loosely.
CONFORMANCE_EXTERNAL_ONLY_OPERATION = "GET /api/v3/series/lookup"

# Every key a hermetic run must reproduce exactly. bodilessOperationsReturningData is compared
# separately, because it is the one list the external probe adds to.
#
# declaredNeverReturned is not among them, and cannot be. Measured across two boots of the same
# digest: one carried LogResource.exception and LogResource.exceptionType because a log row on that
# boot held an exception, and the other carried HealthResource.id because that boot raised a health
# issue and the first returned an empty health collection. The list covers the schemas a run
# touched, so an empty collection removes its schema from the list entirely. It is a record of one
# boot and never a patch list, which is why nothing downstream reads it.
CONFORMANCE_REPRODUCED_KEYS = (
    "measuredAgainst",
    "readsSelected",
    "readsSchemaChecked",
    "nonJsonReads",
    "readsNotAnswering200",
    "writeProbe",
    "writesNotProbed",
)


def check_conformance_sweep_reproduces_the_record():
    """A fresh sweep against the pin reproduces the committed record and exits 0.

    What this pins is the deliverable. The record is what the fifth transformation patches from, so
    a sweep that quietly recorded something else would move the generated client without moving any
    committed file a reader looks at. Every key is compared entry for entry rather than by count:
    a count is a copy of a fact this comparison already fixes.

    The two rules the record must not break are asserted here as well as enforced in the sweep. No
    status the probe observed failing may appear as a success code, and no operation may sit in
    both the probe map and the unreachable list.

    This check is not in OFFLINE_CHECKS. It boots the pinned image, calls every read it can address
    and issues every write it can reach against the container it started, and a machine without
    Docker must still get a green default suite.

    Both committed files are recorded before the run and restored after it, so a check that ran
    with other work in progress reports the right thing and leaves nothing behind.
    """
    output_path = resolve_repo_path(conformance.OUTPUT_PATH)
    provenance_path = resolve_repo_path(conformance.PROVENANCE_PATH)
    with open(output_path, "rb") as handle:
        committed_raw = handle.read()
    with open(provenance_path, "rb") as handle:
        provenance_raw = handle.read()

    try:
        code, output = run_conformance()

        with open(output_path, encoding="utf-8") as handle:
            fresh = json.load(handle)
        committed = json.loads(committed_raw.decode("utf-8"))

        # The run exits 0. It used to refuse on four verdicts, and all four became impossible when
        # the document started being built from the commit the pinned image runs.
        assert code == 0, (code, output)
        assert os.path.basename(conformance.OUTPUT_PATH) in output, output
        assert fresh["externalProbeRan"] is False, "the hermetic run reached outside the container"

        for key in CONFORMANCE_REPRODUCED_KEYS:
            assert fresh[key] == committed[key], (key, fresh[key])

        # The one list the probe adds to, entry for entry including each shape. shape decides
        # whether the fifth transformation attaches an array response or an object response, and
        # that choice decides three generated method names.
        expected = [entry for entry in committed["bodilessOperationsReturningData"]
                    if entry["operation"] != CONFORMANCE_EXTERNAL_ONLY_OPERATION]
        assert len(expected) == len(committed["bodilessOperationsReturningData"]) - 1, expected
        assert fresh["bodilessOperationsReturningData"] == expected, \
            fresh["bodilessOperationsReturningData"]
        assert all(entry["shape"] in ("array", "object")
                   for entry in fresh["bodilessOperationsReturningData"]), \
            fresh["bodilessOperationsReturningData"]

        # No status observed failing is recorded as a success code, and no operation is recorded
        # both ways. Declaring 400 for a test POST would make the generated client report a real
        # validation failure as success.
        assert all(200 <= status < 300 for status in fresh["writeProbe"].values()), \
            fresh["writeProbe"]
        both = {entry["operation"] for entry in fresh["writesNotProbed"]} & set(fresh["writeProbe"])
        assert not both, both
        assert all({"operation", "reason"} <= set(entry) for entry in fresh["writesNotProbed"]), \
            fresh["writesNotProbed"]

        # Not compared entry for entry, for the reason at CONFORMANCE_REPRODUCED_KEYS. A run that
        # recorded nothing at all would mean the property recorder stopped recording, and every
        # declared property of every touched schema would read as never returned.
        assert fresh["declaredNeverReturned"], "no declared property went unreturned at all"

        # Both lists a reader could mistake for a patch list carry the reason they are not one.
        assert fresh["writesNotProbedNote"] == conformance.WRITES_NOT_PROBED_NOTE
        assert fresh["declaredNeverReturnedNote"] == conformance.DECLARED_NEVER_RETURNED_NOTE

        with open(provenance_path, "rb") as handle:
            assert handle.read() == provenance_raw, "the sweep wrote the provenance record"
    finally:
        # The committed file is the flagged run's, and this run wrote the hermetic one over it.
        with open(output_path, "wb") as handle:
            handle.write(committed_raw)
        # Restored too, and not only asserted on. The assertion above reports a sweep that wrote a
        # file it must not, and without this the record carrying every hash the rest of the
        # pipeline is measured against would be left modified by the run that reported it.
        with open(provenance_path, "wb") as handle:
            handle.write(provenance_raw)

    print("ok  docker: a hermetic sweep reproduces {} keys of the committed record entry for "
          "entry, {} probed writes with no failure status among them, {} recorded unreachable, and "
          "{} bodiless operations without the one the external probe adds".format(
              len(CONFORMANCE_REPRODUCED_KEYS), len(fresh["writeProbe"]),
              len(fresh["writesNotProbed"]), len(expected)))


DOCKER_CHECKS = (
    check_generate_check_is_clean,
    check_conformance_sweep_reproduces_the_record,
)


def main():
    parser = argparse.ArgumentParser(description="Self-test the Whisparr 2 pipeline scripts.")
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Also run the checks that regenerate the client through the pinned image.",
    )
    args = parser.parse_args()

    checks = list(OFFLINE_CHECKS)
    if args.docker:
        checks.extend(DOCKER_CHECKS)
    for check in checks:
        check()

    print("{} checks passed.".format(len(checks)))


if __name__ == "__main__":
    main()
