#!/usr/bin/env python3
"""Check what a running Whisparr 2 instance returns against what the pinned document declares.

The committed document omits properties the running application returns, at the same commit, so the
spec alone cannot say what the wire looks like. This boots the pinned digest under a name unique to
the run, calls every read it can address without inventing state, compares each JSON body against
the schema the document declares for its 200, and writes the result to spec/CONFORMANCE.json. The
container is removed whether the run succeeded or failed.

Nothing here records an observed value. One read returns the instance key in plaintext and its
schema declares four more credentials beside it, so the output carries a JSON type name and never a
sample.

Requires Docker. Run it when the pin moves, not per change.

    python generator/conformance.py
"""

REFUSAL_PREFIX = "ERROR: REFUSED - "

# One entry, measured rather than copied. GET /api/v3/series/lookup declares no response body and
# returns SeriesResource-shaped items, and it is the only route on a fresh instance that produces
# one at all: the collection returns [], every by-id read 404s, and a create with a fabricated
# tvdbId returns 400 because the series is not found upstream. The value is the schema its payload
# matches, the shape of that payload, and the query the read needs.
BODILESS_SCHEMA_MAP = {
    "GET /api/v3/series/lookup": ("SeriesResource", "array", {"term": "test"}),
}

# The JSON types the document declares, mapped to what Python parses them into. number accepts an
# integer because JSON draws no line there and the document's int32 fields are declared integer.
JSON_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


def json_type_of(value):
    """The JSON type name of a parsed value, which is the only thing the output file records.

    A sample would be a credential on the host-config read, so the type name is the whole of what a
    finding carries about what it saw.
    """
    if value is None:
        return "null"
    # bool before int, because bool is a subclass of int in Python and an unguarded check would
    # report a true value as an integer.
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def resolve(document, node):
    """A schema node with any reference followed, or an empty dict when it names nothing.

    A walker that compared a reference node directly would find no type, no properties and no
    additionalProperties, and would silently pass every body it was handed.
    """
    seen = set()
    while isinstance(node, dict) and "$ref" in node:
        reference = node["$ref"]
        if reference in seen:
            return {}
        seen.add(reference)
        target = document
        for part in reference.lstrip("#/").split("/"):
            if not isinstance(target, dict) or part not in target:
                return {}
            target = target[part]
        node = target
    return node if isinstance(node, dict) else {}


def schema_name_of(document, node):
    """The component name a reference points at, or None for an inline subschema.

    The output file is keyed by schema and property, so a finding that could not name its schema
    could not be keyed at all.
    """
    if isinstance(node, dict) and isinstance(node.get("$ref"), str):
        name = node["$ref"].rsplit("/", 1)[-1]
        if name in document.get("components", {}).get("schemas", {}):
            return name
    return None


def classify_json(content_type):
    """Whether a response body should be parsed as JSON, from the content type alone.

    Read before the body is parsed. One read answers 184,918 bytes of Graphviz, and parsing that as
    JSON costs a wasted exception on every run and reports a finding about a document that was
    never JSON.
    """
    return "json" in (content_type or "").lower()


def schema_for_200(document, method, path):
    """The JSON schema the document declares for an operation's 200, or None when it declares none.

    None is not a failure. Six operations answer 200 with JSON and declare no body at all, and they
    are recorded rather than validated.
    """
    operation = document.get("paths", {}).get(path, {}).get(method.lower())
    if not isinstance(operation, dict):
        return None
    content = operation.get("responses", {}).get("200", {}).get("content")
    if not isinstance(content, dict):
        return None
    for media_type, entry in content.items():
        if classify_json(media_type) and isinstance(entry, dict) and "schema" in entry:
            return entry["schema"]
    return None


def walk(document, schema_node, value, findings, seen_props, name_hint=None, path="$"):
    """Compare one value against one schema node, recording findings and seen properties in place.

    A finding is (verdict, schema name, path, detail). The four failing verdicts are undeclared,
    type, null and enum. A wrong answer here is a patch list that either misses a property the
    application returns, which leaves the SDK unable to read it, or invents one it does not.
    """
    name = schema_name_of(document, schema_node) or name_hint
    schema = resolve(document, schema_node)

    if not schema:
        return

    # allOf is used in this document for a single-member wrapper around a reference.
    if "allOf" in schema:
        for member in schema["allOf"]:
            walk(document, member, value, findings, seen_props, name, path)
        return

    declared = schema.get("type")
    nullable = schema.get("nullable") is True

    if value is None:
        # No schema in this document declares a required array, so an absent key is legal and only
        # an explicit null against a property that does not declare nullable is a violation.
        if not nullable:
            findings.append(("null", name, path, None))
        return

    if declared == "array":
        if not isinstance(value, list):
            findings.append(("type", name, path, json_type_of(value)))
            return
        items = schema.get("items", {})
        for index, entry in enumerate(value):
            walk(document, items, entry, findings, seen_props, None, path + "[" + str(index) + "]")
        return

    if "enum" in schema and isinstance(value, str):
        if value not in schema["enum"]:
            findings.append(("enum", name, path, value))
        return

    if declared in JSON_TYPES and declared != "object":
        # bool is a subclass of int in Python, so an unguarded isinstance would read True as a
        # conforming integer and miss the mismatch this check exists for.
        if not isinstance(value, JSON_TYPES[declared]) or (
            declared != "boolean" and isinstance(value, bool)
        ):
            findings.append(("type", name, path, json_type_of(value)))
        return

    if not isinstance(value, dict):
        if declared == "object":
            findings.append(("type", name, path, json_type_of(value)))
        return

    extra = schema.get("additionalProperties")

    # A map-shaped site. Every member is validated against the map's value schema and no key is
    # ever undeclared. Three such sites exist, all three nested under a property, and a walker that
    # ignored them reported several thousand findings on the localization read alone.
    if isinstance(extra, dict):
        for key, member in value.items():
            walk(document, extra, member, findings, seen_props, None, path + "." + key)
        return
    if extra is True:
        return

    properties = schema.get("properties", {})

    for key, member in value.items():
        if key in properties:
            if name:
                seen_props.add((name, key))
            # The owning schema name is carried down. A property whose subschema is inline rather
            # than a reference has no name of its own, and a finding on it that reported no schema
            # could not be keyed by schema and property, which is the whole shape of the output.
            walk(document, properties[key], member, findings, seen_props, name, path + "." + key)
        elif extra is False:
            findings.append(("undeclared", name, path + "." + key, json_type_of(member)))


def select_reads(document):
    """Partition every GET the document declares into the three tiers, from the document itself.

    Tier 1 is every GET with no path parameter, called with no query parameter at all. Tier 2 is a
    by-id GET whose collection path is itself a tier 1 read, and its id comes from that collection
    read rather than from source. Tier 3 is every other parameterised GET and is not called.

    Returns three lists of paths. Deriving the tiers rather than writing them down is what stops a
    read the document gained from going uncalled and unnoticed.
    """
    paths = document.get("paths", {})
    tier1 = [path for path in paths if "get" in paths[path] and "{" not in path]
    collections = set(tier1)
    tier2 = []
    tier3 = []
    for path in paths:
        if "get" not in paths[path] or "{" not in path:
            continue
        # The parameter must be a trailing {id}. A trailing {filename} is a name rather than an
        # identifier, and feeding it a row's id addresses a resource that does not exist.
        if path.endswith("/{id}") and path.count("{") == 1 and path.rsplit("/", 1)[0] in collections:
            tier2.append(path)
        else:
            tier3.append(path)
    return tier1, tier2, tier3


def refuse_bodiless_map(document, mapping):
    """Refuse when the bodiless-operation map names a schema the document no longer declares.

    The map is a measurement against one document. Against a document that has moved it would
    validate a payload against the wrong schema and report every difference as a finding.
    """
    schemas = document.get("components", {}).get("schemas", {})
    for schema_name, _shape, _query in mapping.values():
        if schema_name not in schemas:
            return (
                REFUSAL_PREFIX
                + "the bodiless-operation map names the schema {}, and this document does not "
                "declare it. Nothing was written.".format(schema_name)
            )
    return None


def refuse_empty_selection(answered):
    """Refuse when no selected read reached the instance at all.

    An empty patch list from a run that reached nothing is indistinguishable from an empty patch
    list from a clean run, and the second is the one a reader would assume.
    """
    if answered <= 0:
        return (
            REFUSAL_PREFIX
            + "the read selection reached no operation at all, so nothing was validated. Nothing "
            "was written."
        )
    return None


def refuse_invariant(schema_checked, answered, non_json, bodiless_with_data):
    """Refuse when the counts do not add up.

    Derived, and compared against nothing literal. Whatever the numbers are, the number
    schema-checked must equal the reads that answered 200 with JSON and declared a JSON schema for
    200. A sweep that quietly stopped validating would otherwise still write a file.
    """
    expected = answered - non_json - bodiless_with_data
    if schema_checked != expected:
        return (
            REFUSAL_PREFIX
            + "the schema-checked count {} does not equal the {} selected reads that answered 200 "
            "with JSON and declare a JSON schema. Nothing was written.".format(
                schema_checked, expected
            )
        )
    return None


# The four failing verdicts, in the order the refusal lines are printed, each with its sentence.
VERDICT_SENTENCES = (
    (
        "undeclared",
        "a response carries a property the document does not declare, under additionalProperties "
        "false. Findings: {}.",
    ),
    ("type", "a response carries a value of the wrong JSON type. Findings: {}."),
    (
        "null",
        "a response carries null for a property that does not declare nullable. Findings: {}.",
    ),
    ("enum", "a response carries an enum value outside the declared set. Findings: {}."),
)


def refuse_findings(findings):
    """One refusal line per failing verdict category that has at least one finding.

    The count sits at the end rather than inside the sentence, so no sentence needs a plural form
    and the invariant part of each stays long enough to key a table on. The sites each line covers
    are printed separately, so a reader gets the schema, the property and the operation without the
    refusal line growing.
    """
    lines = []
    for verdict, sentence in VERDICT_SENTENCES:
        count = sum(1 for finding in findings if finding[0] == verdict)
        if count:
            lines.append(REFUSAL_PREFIX + sentence.format(count))
    return lines
