#!/usr/bin/env python3
"""Pre-process the pinned Whisparr 2 OpenAPI document into the spec the generator reads.

T1 narrows root security, T2 deletes the malformed paths["/"], T5 declares the success status code
the instance answers and attaches the response schema it returns, T3 derives an operationId for
every operation from the document itself, and T4 replaces the five CLR-shaped schemas with the
strings the server actually serialises. They run in that order, and T5's position ahead of T3 is
what names three array-returning reads for a list.

T5 is the only one whose input is a measurement rather than the document. Generating this document
from Whisparr's own source supplies neither of the two things it declares, because both are absent
[ProducesResponseType] annotations upstream, so both exist only in spec/CONFORMANCE.json.

The derivation is devopsarr's assign_operation_id.py, the algorithm behind the Go, Python and
TypeScript *arr clients. OPERATION_ID_OVERRIDES names the 8 operations it cannot get right from
the URL alone, mostly abbreviations only a human can expand: mediafiles is MediaFiles.

Nothing here pins a name against upstream change. If Whisparr renames a path, the derived method
name follows it and the break surfaces in a consumer's build. That trade was accepted in exchange
for deleting a committed name map that had to be reviewed on every version bump.

    python generator/preprocess_spec.py
"""

import argparse
import json
import os
import re

from _common import die, resolve_repo_path, sha256_file, write_json_lf

DEFAULT_RAW_SPEC = "spec/openapi.raw.json"
DEFAULT_OUT_FILE = "spec/openapi.generated.json"

# Mandatory auth, header scheme only. Both halves are load-bearing.
# Not optional: Whisparr's Startup.cs pins the fallback policy to the API-key scheme and consults
# neither AuthenticationMethod nor AuthenticationRequired, and no key measures 401 under every
# permissive configuration. A leading empty requirement is the OpenAPI spelling for "optional".
# Header only: this document declares two schemes, X-Api-Key and apikey, so this step narrows two
# to one rather than repairing an omission. generichost does not treat the two as alternatives but
# emits a call to every declared scheme, so leaving the query scheme declared at the root puts the
# key in the URL of every request, where it reaches access logs, proxy logs and Referer headers
# (upstream openapi-generator issue 24138).
SECURITY = [{"X-Api-Key": []}]

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
# A valid C# identifier of the shape this library's public method names take. Anchored on purpose.
OPERATION_ID_PATTERN = re.compile(r"[A-Z][A-Za-z0-9]*")

# The 8 operations the derivation cannot name from the URL, keyed "METHOD /path". Every other name
# in the SDK is computed.
#
# GET /feed/v3/calendar/whisparr.ics is the one entry that is not cosmetic. It derives to
# GetFeedV3CalendarWhisparr.ics, which is not a C# identifier, and the shape assertion below refuses
# it. The other seven are readability choices: their naive derivations are all valid and distinct
# C# identifiers, so deleting one of them leaves the build green. The worst of the seven is
# GET /api/v3/mediacover/{seriesId}/{filename}, which derives GetMediaCoverByFilename and so drops
# seriesId from the name of a two-parameter method.
OPERATION_ID_OVERRIDES = {
    "GET /api": "GetApiInfo",
    "GET /api/v3/filesystem/mediafiles": "GetFileSystemMediaFiles",
    "GET /api/v3/languageprofile/schema": "GetLanguageProfileSchema",
    "GET /api/v3/mediacover/{seriesId}/{filename}": "GetMediaCoverBySeriesIdAndFilename",
    "GET /api/v3/qualityprofile/schema": "GetQualityProfileSchema",
    "GET /feed/v3/calendar/whisparr.ics": "GetCalendarFeed",
    "GET /login": "GetLoginPage",
    "GET /{path}": "GetStaticResourceByPath",
}


def returns_json_array(operation):
    """devopsarr's list rule keys on the 200 response declaring a JSON array."""
    node = operation
    for key in ("responses", "200", "content", "application/json", "schema", "type"):
        if not isinstance(node, dict):
            return False
        node = node.get(key)
    return node == "array"


def derive_operation_id(method, path, tag, array):
    """devopsarr's assign_operation_id.py, ported with two fixes.

    This iterates the segment list backwards in the placeholder-removal loop, because devopsarr's
    forward loop mutates the list it is enumerating and a removal makes it skip the following
    element. And the POST test-verb rule spells testall as testAll, so the five /testall endpoints
    derive TestAllIndexer rather than TestallIndexer without needing five override entries.
    """
    parts = re.split(r"/|-", re.sub(r"^/api/v\d/(.*)$", r"\1", path))

    if parts[-1].startswith("{"):
        parts[-1] = parts[-1].strip("{}")
        parts.insert(len(parts) - 1, "by")
    verb = method
    tail_is_by_id = len(parts) > 1 and parts[-2] == "by"
    if method == "delete" and tail_is_by_id:
        del parts[-2:]
    if method == "put" and tail_is_by_id:
        verb = "update"
        del parts[-2:]
    if method == "post":
        verb = "create"
        if parts[-1].startswith("test"):
            verb = "testAll" if parts[-1] == "testall" else parts[-1]
            del parts[-1]
    if method == "get" and array:
        verb = "list"
    if len(parts) > 1 and parts[0] == "config":
        parts[0] = parts[1] + "config"
        del parts[1]
    if len(parts) > 1 and parts[1] == "settings":
        del parts[1]
    for i in range(len(parts) - 1, -1, -1):
        if parts[i].startswith("{"):
            del parts[i]
        elif parts[i].lower() == tag.lower():
            parts[i] = tag
    parts.insert(0, verb)
    return "".join(p[0].upper() + p[1:] for p in parts if p)


def apply_root_security(document):
    """T1. Narrow root security to the header scheme. Returns (change count, refusal lines).

    Assigned to the existing key, which keeps security at its position in the root key order.
    Deleting then adding would move it to the end and inflate the diff against the pin.

    What this does not do: components.securitySchemes keeps both X-Api-Key and apikey, so the
    generated client still carries both enum members. Narrowing the declared schemes would change
    what the document says the server accepts, so it is left alone and the enum is phase 4's
    problem. A reader who expects it to shrink here will otherwise think this step failed.
    """
    if document.get("security") == SECURITY:
        return 0, [
            "ERROR: REFUSED - root security already declares the header scheme alone, so there is "
            "nothing to narrow. Nothing was written."
        ]
    document["security"] = SECURITY
    return 1, []


def delete_root_path(document):
    """T2. Delete the malformed paths["/"]. Returns the operations removed with it, and refusals.

    The key is malformed because the path item declares a required path parameter named path while
    the path template "/" carries no placeholder for it.

    The count is operations rather than keys, so the census in main() can subtract it from the
    input count without knowing how the root path item was shaped.

    This refusal is not redundant with the branch check in build_spec.check_tier2. The two speak at
    different boundaries: that check says this is not the document the pipeline was measured
    against, and this one says do not delete a key that is already gone. Both are needed because
    derive_operation_id("get", "/", "StaticResource", False) returns Get, which the shape pattern
    accepts, so a root path that survived is caught by neither the shape assertion nor the
    collision assertion.
    """
    paths = document["paths"]
    if "/" not in paths:
        return 0, [
            'ERROR: REFUSED - paths["/"] is not present, so there is no malformed root path to '
            "delete. Nothing was written."
        ]
    removed = sum(1 for method in paths["/"] if method in HTTP_METHODS)
    del paths["/"]
    return removed, []


def assign_operation_ids(document):
    """T3. Derive and assign an operationId for every operation. Returns (count, refusal lines).

    Order matters and it is not the order the assignments read in. Derive first, then test the
    zero-condition, then run the three assertions, then assign. Testing the zero-condition before
    deriving would skip the stale-override check on a document that had been annotated upstream,
    which is exactly the case where an override key is most likely to have moved.
    """
    paths = document["paths"]

    operations = []
    overrides_used = set()
    shape_problems = []
    for path, item in paths.items():
        if not isinstance(item, dict):
            shape_problems.append(
                "ERROR: REFUSED - the path item " + path + " is not a JSON object. Nothing was "
                "written."
            )
            continue
        for method, operation in item.items():
            if method not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                shape_problems.append(
                    "ERROR: REFUSED - the operation {} {} is not a JSON object. Nothing was "
                    "written.".format(method, path)
                )
                continue
            key = method.upper() + " " + path
            if key in OPERATION_ID_OVERRIDES:
                operation_id = OPERATION_ID_OVERRIDES[key]
                overrides_used.add(key)
            else:
                tags = operation.get("tags") or []
                tag = tags[0] if tags and isinstance(tags[0], str) else ""
                operation_id = derive_operation_id(method, path, tag, returns_json_array(operation))
            operations.append((key, operation_id, operation))
    if shape_problems:
        return 0, shape_problems

    # Phrased "every operation already has one", not "any". A partial upstream annotation pass
    # gives some operations an operationId and not others, and the pipeline can still handle that
    # document, so the check stays quiet through it. The first operand guards the empty case, so a
    # document with no operations at all does not read as already annotated.
    if operations and all("operationId" in operation for _, _, operation in operations):
        return 0, [
            "ERROR: REFUSED - every operation already carries an operationId, so there is nothing "
            "to derive. Nothing was written."
        ]

    # An override that matches no operation is the only remaining signal that Whisparr moved a path.
    stale = [k for k in OPERATION_ID_OVERRIDES if k not in overrides_used]
    if stale:
        return 0, [
            "ERROR: REFUSED - {} override entries match no operation in this spec. Whisparr has "
            "moved or removed a path, so the name it pinned is now derived instead. Nothing was "
            "written.".format(len(stale))
        ] + ["    {} -> {}".format(k, OPERATION_ID_OVERRIDES[k]) for k in stale]

    # Not the generator's FIX_DUPLICATED_OPERATIONID normalizer, which de-duplicates by appending a
    # positional suffix: that masks this assertion, and inserting an operation upstream then moves
    # the suffix onto a different method and renames public API with no diff.
    by_id = {}
    for key, operation_id, _ in operations:
        by_id.setdefault(operation_id, []).append(key)
    collisions = {i: keys for i, keys in by_id.items() if len(keys) > 1}
    if collisions:
        return 0, [
            "ERROR: REFUSED - the collision assertion failed: {} operationIds are carried by more "
            "than one operation.".format(len(collisions))
        ] + [
            "    {} is assigned to: {}".format(i, ", ".join(keys))
            for i, keys in collisions.items()
        ] + [
            "  The generator emits one class per tag, so two operations sharing an operationId are "
            "two methods with one name on one class. Add an override for one of them. Nothing was "
            "written."
        ]

    # fullmatch, and the pattern carries no IGNORECASE: a case-insensitive match would accept
    # listMovie and pass a name the generator then sanitizes into one of its own choosing. This is
    # the assertion that catches GetFeedV3CalendarWhisparr.ics.
    bad_shape = [(k, i) for k, i, _ in operations if not OPERATION_ID_PATTERN.fullmatch(i)]
    if bad_shape:
        return 0, [
            "ERROR: REFUSED - the identifier shape assertion failed: {} names do not match {}. Add "
            "an override for each. Nothing was written.".format(
                len(bad_shape), OPERATION_ID_PATTERN.pattern
            )
        ] + ["    {} derived the invalid identifier {}".format(k, i) for k, i in bad_shape]

    # Added as a new last key, which is deterministic run to run.
    for _, operation_id, operation in operations:
        operation["operationId"] = operation_id
    return len(operations), []


STRING = {"type": "string", "nullable": True}
DATE = {"type": "string", "format": "date", "nullable": True}

# Four object expansions of CLR types the server serialises as strings, and one string enum whose
# name collides with System.DayOfWeek. Only the names and the replacements are pinned. The
# properties that reference them are found by scanning, so an upstream schema gaining an eleventh
# reference is rewritten rather than skipped.
OBJECT_SHAPED = {"Version": STRING, "HttpUri": STRING, "TimeSpan": STRING, "DateOnly": DATE}
# DayOfWeek describes the wire correctly. It is deleted because deleting DateOnly orphans it, and
# because the name collides with the framework type of the same name and produces
# "CS0104: 'DayOfWeek' is an ambiguous reference" in the generator's own Client/ClientUtils.cs.
STRING_ENUM = "DayOfWeek"
CLR_SCHEMAS = tuple(OBJECT_SHAPED) + (STRING_ENUM,)

# DayOfWeek is reachable only through DateOnly, so deleting DateOnly is what orphans it. Asserted
# rather than assumed, because it is the one reference the rewrite must not follow.
INTERNAL_REFERENCE = ("DateOnly", "dayOfWeek", "DayOfWeek")

REF_PREFIX = "#/components/schemas/"


def rewrite_clr_schemas(document):
    """T4. Replace references to the five CLR-shaped schemas with strings, then delete the five.

    Shaped as collect, assert, then mutate. That keeps every refusal ahead of every mutation, and
    it means the walk never inserts or deletes a key in a dict it is iterating.

    nullable: true is an addition and not a preservation. No reference site carries a key alongside
    its $ref, so substituting the whole node loses nothing. Dropping nullable under nullable
    reference types would produce a non-nullable string for a field the server can send as null,
    which throws on read rather than at compile time.
    """
    schemas = (document.get("components") or {}).get("schemas") or {}

    missing = [name for name in CLR_SCHEMAS if name not in schemas]
    if missing:
        return 0, [
            "ERROR: REFUSED - the schemas {} are the ones this rewrite replaces, and this document "
            "does not declare {}. Nothing was written.".format(
                ", ".join(CLR_SCHEMAS), ", ".join(missing)
            )
        ]
    # Four of the five are object expansions. The fifth, DayOfWeek, is already declared as a string
    # carrying an enum, so asserting that all five are objects would refuse the correct document.
    not_object = [
        name for name in OBJECT_SHAPED
        if not isinstance(schemas[name], dict) or schemas[name].get("type") != "object"
    ]
    if not_object:
        return 0, [
            "ERROR: REFUSED - {} is no longer declared as an object, so the CLR-shaped rewrite no "
            "longer applies. Nothing was written.".format(", ".join(not_object))
        ]
    enum_schema = schemas[STRING_ENUM]
    if not (
        isinstance(enum_schema, dict)
        and enum_schema.get("type") == "string"
        and enum_schema.get("enum")
    ):
        return 0, [
            "ERROR: REFUSED - DayOfWeek is no longer declared as a string enum, so the CLR-shaped "
            "rewrite no longer applies. Nothing was written."
        ]

    targets = set(CLR_SCHEMAS)
    # Keyed on identity, so the walk knows when the trail it is on runs through one of the five.
    owner_of = {id(schemas[name]): name for name in CLR_SCHEMAS}
    inside = []
    outside = []

    # A list is walked with its indices, not its bare items, so a $ref that sits as a direct
    # element of an allOf, oneOf or anyOf array is collected with a key its parent can be assigned
    # through. Iterating a bare item would descend into the reference node and test its string
    # value, which no branch here matches, and the schema would then be deleted with that site
    # still pointing at it.
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
                if isinstance(reference, str) and reference.startswith(REF_PREFIX):
                    name = reference[len(REF_PREFIX):]
            if name in targets:
                if owner is None:
                    outside.append((node, key, name))
                else:
                    inside.append((owner, key, name))
                continue
            walk(value, owner_of.get(id(value), owner))

    # The whole document, not only the schema section, so an upstream inline reference in a
    # parameters or requestBody node is caught rather than skipped.
    walk(document, None)

    if sorted(inside) != [INTERNAL_REFERENCE]:
        return 0, [
            "ERROR: REFUSED - the only reference expected inside these five schemas is "
            "DateOnly.dayOfWeek -> DayOfWeek, and this document carries {}. Nothing was "
            "written.".format(
                ", ".join("{}.{} -> {}".format(*site) for site in sorted(inside)) or "none"
            )
        ]
    if not outside:
        return 0, [
            "ERROR: REFUSED - no property references {}, so there is nothing to rewrite. Nothing "
            "was written.".format(", ".join(CLR_SCHEMAS))
        ]

    # A fresh copy per site. Sharing one dict across ten sites serialises correctly but leaves the
    # document holding aliased nodes, which is a trap for any later transformation.
    for parent, key, name in outside:
        parent[key] = dict(OBJECT_SHAPED.get(name, STRING))
    for name in CLR_SCHEMAS:
        del schemas[name]
    return len(outside), []


CONFORMANCE_FILE = "spec/CONFORMANCE.json"
PROVENANCE_FILE = "spec/PROVENANCE.json"
PROVENANCE_NAME = os.path.basename(PROVENANCE_FILE)

STATUS_KIND = "statusCodes"
SCHEMA_KIND = "responseSchemas"

OK = "200"


def read_json(relative):
    with open(resolve_repo_path(relative), "r", encoding="utf-8") as handle:
        return json.load(handle)


def find_operation(document, operation_key):
    """The operation node an "METHOD /path/template" key names, or None.

    The key spelling is the conformance record's, which is the spelling every measurement in it is
    keyed by. Nothing is derived from it beyond splitting on the single space.
    """
    method, path = operation_key.split(" ", 1)
    item = document.get("paths", {}).get(path)
    if not isinstance(item, dict):
        return None
    operation = item.get(method.lower())
    return operation if isinstance(operation, dict) else None


def measured_patch_plan(document, conformance):
    """What T5 would change, by kind, without touching either argument.

    Two kinds, because the two are measured differently and refuse differently, and because a
    self-test can then assert each on its own without applying anything.

    A status-code entry exists only where the probe measured a code other than 200. An operation
    the probe measured 200 for already declares what it answers, so it belongs to neither kind and
    its absence from the document would mean nothing.

    A response-schema entry exists for every bodiless operation the record names a schema for. The
    four it names none for return an object no schema in the document describes, so there is
    nothing to attach.

    `present` is whether this document declares the operation at all, and `already` is whether the
    change has been made. Both are facts, and only the caller refuses on them.
    """
    statuses = {}
    for operation_key, code in sorted(conformance["writeProbe"].items()):
        code = str(code)
        if code == OK:
            continue
        operation = find_operation(document, operation_key)
        responses = (operation or {}).get("responses") or {}
        statuses[operation_key] = {
            "code": code,
            "present": operation is not None,
            "already": code in responses,
            "declaresOk": OK in responses,
        }

    schemas = {}
    for entry in conformance["bodilessOperationsReturningData"]:
        if "schema" not in entry:
            continue
        operation = find_operation(document, entry["operation"])
        responses = (operation or {}).get("responses") or {}
        schemas[entry["operation"]] = {
            "schema": entry["schema"],
            "shape": entry["shape"],
            "present": operation is not None,
            "already": bool((responses.get(OK) or {}).get("content")),
            "declaresOk": OK in responses,
        }

    return {STATUS_KIND: statuses, SCHEMA_KIND: schemas}


def attached_schema(schema_name, shape):
    """The 200 content node for a bodiless operation, under one media type and no other.

    application/json alone is deliberate and it is load-bearing. returns_json_array above walks
    exactly responses, 200, content, application/json, schema, type, so an attachment under any
    other media type leaves this transformation reporting a non-zero change count while the three
    Get-to-List renames it exists for silently do not happen. The three-media-type sets the
    document carries elsewhere are what the server's own annotations produce; this attachment is
    not one of those and does not imitate them.
    """
    reference = {"$ref": REF_PREFIX + schema_name}
    schema = {"type": "array", "items": reference} if shape == "array" else reference
    return {"application/json": {"schema": schema}}


def declare_measured_responses(document, provenance_path=None):
    """T5. Declare the success code the instance answers and attach the schema it returns.

    Returns (change count, refusal lines) like the other four. The two kinds are the two things
    generating this document from Whisparr's own source cannot supply, because both are absent
    [ProducesResponseType] annotations upstream: they exist only as a measurement against a running
    instance, and spec/CONFORMANCE.json is that measurement.

    Nothing measured is restated here. Every status code, operation key and schema name comes out
    of the record.

    provenance_path is the record to validate against, and the caller names it rather than this
    function resolving one. It is the record describing the committed client, which is the identity
    spec/CONFORMANCE.json was measured beside. It is not the record main() may write: that one is
    derived from the output directory and a scratch run has none, so pointing this at it would
    refuse a run the refusal at step 0 tells the caller to make. Omitting it reads the committed
    record, which is what a caller driving this over a synthetic document wants.
    """
    conformance = read_json(CONFORMANCE_FILE)
    if provenance_path is None:
        provenance_path = resolve_repo_path(PROVENANCE_FILE)
    with open(provenance_path, "r", encoding="utf-8") as handle:
        provenance = json.load(handle)

    # The patch list is a measurement against a running image, so the image is the identity that
    # has to match: this asserts that the measurement and the client describe one artifact.
    #
    # Not the recorded spec hash. main() below overwrites generatedSpecSha256 with the
    # post-transformation hash on every run, so an equality on it would hold for exactly one run
    # and refuse every run after that.
    measured_digest = (conformance.get("measuredAgainst") or {}).get("imageDigest")
    if measured_digest != provenance.get("imageDigest"):
        return 0, [
            "ERROR: REFUSED - the conformance record was measured against {} and this client "
            "describes {}, so the measurement and the document describe different images. Nothing "
            "was written.".format(measured_digest, provenance.get("imageDigest"))
        ]

    plan = measured_patch_plan(document, conformance)
    entries = list(plan[STATUS_KIND].items()) + list(plan[SCHEMA_KIND].items())

    # An operation the record names and this document does not declare, or declares without the
    # code the change replaces, is the one signal left that Whisparr moved a path. Applying the
    # rest and skipping it silently would put the client back to declaring 200 for a write that
    # answers 201, which is the whole defect this transformation exists to close.
    unreachable = [
        key for key, entry in entries
        if not entry["present"] or not (entry["already"] or entry["declaresOk"])
    ]
    if unreachable:
        return 0, [
            "ERROR: REFUSED - {} measured operations cannot be patched in this document. Whisparr "
            "has moved or removed a path, or the response the change replaces is no longer "
            "declared, so re-run generator/conformance.py against the pinned "
            "image.".format(len(unreachable))
        ] + ["    " + key for key in unreachable] + ["  Nothing was written."]

    named = sorted({entry["schema"] for _key, entry in plan[SCHEMA_KIND].items()})
    declared = (document.get("components") or {}).get("schemas") or {}
    undeclared = [name for name in named if name not in declared]
    if undeclared:
        return 0, [
            "ERROR: REFUSED - the record names the schemas {} for a bodiless operation, and this "
            "document does not declare {}. Attaching them would reference nothing. Nothing was "
            "written.".format(", ".join(named), ", ".join(undeclared))
        ]

    # Composite over both kinds, never per kind. A per-kind condition would refuse the whole
    # correct document the day upstream annotates one of the two, which is the opposite of what a
    # zero-condition is for.
    if entries and all(entry["already"] for _key, entry in entries):
        return 0, [
            "ERROR: REFUSED - every measured success code is already declared and every bodiless "
            "operation the record names a schema for already declares its content, so there is "
            "nothing left to declare. Nothing was written."
        ]

    changed = 0
    for operation_key, entry in plan[STATUS_KIND].items():
        if entry["already"]:
            continue
        operation = find_operation(document, operation_key)
        # Rebuilt rather than assigned and deleted, so the measured code takes the position 200
        # held and the diff against the pin stays one line per operation.
        operation["responses"] = {
            (entry["code"] if key == OK else key): value
            for key, value in operation["responses"].items()
        }
        changed += 1
    for operation_key, entry in plan[SCHEMA_KIND].items():
        if entry["already"]:
            continue
        operation = find_operation(document, operation_key)
        operation["responses"][OK]["content"] = attached_schema(entry["schema"], entry["shape"])
        changed += 1
    return changed, []


# Walked by main(), and walked by generator/selftest.py, exactly as that script walks its own check
# tuple.
#
# T5 runs at position three, ahead of the operationId derivation, and the position is load-bearing
# for exactly three method names. returns_json_array above is what turns a Get prefix into a List
# prefix, and it can only see an array response that is already attached. Every other
# array-returning read in this SDK is already named for a list, so the earlier position produces
# the name the derivation would have given a document that told the truth about what it returns.
TRANSFORMATIONS = (
    ("T1", apply_root_security),
    ("T2", delete_root_path),
    ("T5", declare_measured_responses),
    ("T3", assign_operation_ids),
    ("T4", rewrite_clr_schemas),
)


def main():
    parser = argparse.ArgumentParser(description="Pre-process the Whisparr 2 OpenAPI document.")
    parser.add_argument("--raw-spec", default=DEFAULT_RAW_SPEC)
    parser.add_argument("--out-file", default=DEFAULT_OUT_FILE)
    args = parser.parse_args()

    raw_path = resolve_repo_path(args.raw_spec)
    out_path = resolve_repo_path(args.out_file)
    out_dir = os.path.dirname(out_path)
    # Two records, two roles, so neither reads as the other. write_provenance_path is the record
    # this run may write and is derived from the output file's own directory, so a scratch run
    # cannot overwrite the committed one. A scratch directory holds none, and step 5 below is
    # guarded on that. measured_provenance_path is the record T5 validates against: the identity
    # the committed conformance record was measured beside, which is always the committed one.
    write_provenance_path = os.path.join(out_dir, PROVENANCE_NAME)
    measured_provenance_path = resolve_repo_path(PROVENANCE_FILE)

    default_raw = resolve_repo_path(DEFAULT_RAW_SPEC)
    default_out = resolve_repo_path(DEFAULT_OUT_FILE)

    print("Pre-process Whisparr 2 openapi -> " + out_path)

    # --- 0. A fixture run must never promote itself onto the committed deliverable ---
    # The two operands take different comparisons on purpose. "Non-default input" is exact, so on
    # Linux spec/OPENAPI.RAW.JSON is not spec/openapi.raw.json. "Committed output path" is
    # case-insensitive on Windows via normcase, because on NTFS a differently-cased spelling IS the
    # committed file.
    if raw_path != default_raw and os.path.normcase(out_path) == os.path.normcase(default_out):
        die(
            "ERROR: REFUSED - a non-default input may not be written to the committed output path. "
            "Pass --out-file with a scratch path too. input {} / output {}".format(raw_path, out_path)
        )
    # The output path alone is not the whole write. The provenance path is derived from the output
    # directory, so an output anywhere beside the committed provenance rewrites a file the caller
    # never named.
    default_provenance = os.path.join(os.path.dirname(default_out), PROVENANCE_NAME)
    if raw_path != default_raw and os.path.normcase(write_provenance_path) == os.path.normcase(
        default_provenance
    ):
        die(
            "ERROR: REFUSED - a non-default input may not write beside the committed provenance "
            "record. Pass --out-file with a scratch directory. input {} / provenance {}".format(
                raw_path, write_provenance_path
            )
        )
    # The pin is an input to this script and never one of its outputs. Writing the patched document
    # over it destroys the identity every other check is measured against.
    if os.path.normcase(out_path) == os.path.normcase(default_raw):
        die("ERROR: REFUSED - the pinned input document is not a write target. output " + out_path)
    if not os.path.isfile(raw_path):
        die("ERROR: REFUSED - no input document at " + raw_path + ".")

    # --- 1. Parse ---
    with open(raw_path, "r", encoding="utf-8") as handle:
        document = json.load(handle)
    print("  + parsed {} bytes from {}".format(os.path.getsize(raw_path), raw_path))

    # Counted before the transformations run, so the census below checks the output against this
    # input rather than against a number typed into this file. Whisparr adds and removes operations
    # between releases; what has to hold is that T2 removed exactly the root path and nothing else.
    operations_in = sum(
        1 for item in document["paths"].values() for m in item if m in HTTP_METHODS
    )

    # --- 2. The transformations ---
    # Each reports what it changed and describes what it refuses. Only main() refuses, so each one
    # can be driven over a synthetic document with nothing written. One refusal per transformation:
    # a run-level test that something changed passes while all but one of them are dead.
    changes = {}
    refusals = []
    for name, transform in TRANSFORMATIONS:
        # T5 is the one transformation with an input besides the document, and the record it reads
        # is named here rather than resolved inside it.
        if transform is declare_measured_responses:
            count, problems = transform(document, measured_provenance_path)
        else:
            count, problems = transform(document)
        changes[name] = count
        refusals.extend(problems)
        if not problems:
            print("  + {} changed {}".format(name, count))
    if refusals:
        die(*refusals)

    # --- 3. The census ---
    # It runs after the refusal gate, never beside it. If T2 refuses and the census ran anyway it
    # would pass, because the input count minus zero equals the number T3 annotated.
    expected_operations = operations_in - changes["T2"]
    if changes["T3"] != expected_operations:
        die(
            "ERROR: REFUSED - the patched document carries {} operations. The input carried {} and "
            "T2 removed {}, so {} were expected. Nothing was written.".format(
                changes["T3"], operations_in, changes["T2"], expected_operations
            )
        )
    print("  + census: {} in, {} removed by T2, {} out".format(
        operations_in, changes["T2"], changes["T3"]))

    # --- 4. Write ---
    # Every refusal above has already passed, so this is the first write to anything committed.
    # There is no staging file: json.dumps either serializes the whole document or raises, so a
    # silently truncated write is not a failure mode that needs guarding here.
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    write_json_lf(out_path, document)
    print(
        "  + wrote {} bytes, sha256 {}".format(os.path.getsize(out_path), sha256_file(out_path))
    )

    # --- 5. The manifest ---
    # build_spec.merge_spec_provenance pops generatedSpecSha256 on every build. Deliberate: a new
    # capture invalidates the patched spec, and this script is what puts the field back.
    if os.path.isfile(write_provenance_path):
        promoted_sha = sha256_file(out_path)
        with open(write_provenance_path, "r", encoding="utf-8") as handle:
            provenance = json.load(handle)
        provenance["generatedSpecSha256"] = promoted_sha
        write_json_lf(write_provenance_path, provenance)
        print("  + wrote generatedSpecSha256 {} to {}".format(
            promoted_sha, write_provenance_path))

    print("Done. " + out_path)


if __name__ == "__main__":
    main()
