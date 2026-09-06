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

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import verify_image
from _common import die, resolve_repo_path, write_json_lf

REFUSAL_PREFIX = "ERROR: REFUSED - "

# The container this run creates, and the only address this run ever speaks to. The suffix is not
# decoration. The module this script reuses force-removes its own fixed name at the start of a run
# and again in its finally, so two runs sharing a name would have the second destroy the first
# mid-sweep.
CONTAINER_NAME = "whisparr2-conformance-" + uuid.uuid4().hex[:12]

SPEC_PATH = "spec/openapi.generated.json"
PROVENANCE_PATH = "spec/PROVENANCE.json"
OUTPUT_PATH = "spec/CONFORMANCE.json"

# Both HTTP readiness signals answer before the instance has settled, so readiness is the log line
# and nothing else. Matched on its prefix: the tail reads False on a network-less boot.
READY_MARKER = "ManagedHttpDispatcher: IPv4 is available"
READY_TIMEOUT_SEC = 120

# Off by default. The read behind it reaches an external metadata service over the public internet,
# and on a runner with no route out it fails for a reason that has nothing to do with the spec.
EXTERNAL_FLAG = "WHISPARR2NET_CONFORMANCE_EXTERNAL"

# The one write. Created and deleted inside the same run, on the container this run started.
PROBE_LABEL = "conformance-probe"

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


def send(base, method, path, key, query=None, payload=None):
    """One request to the container this run started, returning (status, content type, body).

    The base URL is the host port Docker assigned, read back from that container. No address is
    written into this file, because an address written down is an address that can outlive the
    container it was measured on.
    """
    url = base + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None
    headers = {"X-Api-Key": key}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read()


def wait_for_marker(container, timeout_sec):
    """Block until the container log carries the readiness marker.

    Both HTTP signals return before the application has finished loading its defaults, so a sweep
    started on either of them reads a half-populated instance and reports properties as never
    returned that the instance returns a second later.
    """
    started = time.monotonic()
    while time.monotonic() - started < timeout_sec:
        logs = verify_image.run_docker(["logs", container])
        if READY_MARKER in (logs.stdout or "") + (logs.stderr or ""):
            return time.monotonic() - started
        time.sleep(0.2)
    logs = verify_image.run_docker(["logs", container, "--tail", "40"])
    die(
        REFUSAL_PREFIX
        + "the container did not report readiness within {}s. Nothing was written.".format(
            timeout_sec
        ),
        (logs.stdout or "") + (logs.stderr or ""),
    )


def media_type_of(content_type):
    """The content type without its parameters, which is what the output file records."""
    return (content_type or "").split(";")[0].strip()


def record(result, document, opkey, template, status, content_type, body):
    """Judge one answered read and fold it into the running result.

    A read is validated only when it answered 200, carried JSON and declares a JSON schema for its
    200. Everything else is recorded under the reason it was not validated, which is what lets the
    counts be checked against each other rather than against a number written down.
    """
    if status != 200:
        result["readsNotAnswering200"].append({"operation": opkey, "status": status})
        return
    result["answered"] += 1
    media_type = media_type_of(content_type)
    if not classify_json(content_type):
        result["nonJsonReads"].append(
            {"operation": opkey, "contentType": media_type, "bytes": len(body)}
        )
        return
    schema = schema_for_200(document, "get", template)
    if schema is None:
        result["bodilessOperationsReturningData"].append(
            {"operation": opkey, "contentType": media_type, "bytes": len(body)}
        )
        return
    found = []
    walk(document, schema, json.loads(body.decode("utf-8")), found, result["seenProps"])
    result["findings"].extend((finding, opkey) for finding in found)
    result["schemaChecked"] += 1


def sweep_reads(document, base, key):
    """Call every read this run can address without inventing state, and judge each answer.

    Tier 1 first, then the by-id tier whose ids come out of those tier 1 bodies. A by-id read whose
    collection returned no id is left uncalled rather than fed a value from this file, because an
    id written into source is an id that could address something this run did not create.
    """
    tier1, tier2, _tier3 = select_reads(document)
    result = {
        "selected": 0,
        "answered": 0,
        "schemaChecked": 0,
        "findings": [],
        "seenProps": set(),
        "nonJsonReads": [],
        "bodilessOperationsReturningData": [],
        "readsNotAnswering200": [],
    }
    bodies = {}
    for path in tier1:
        status, content_type, body = send(base, "GET", path, key)
        result["selected"] += 1
        bodies[path] = (status, content_type, body)
        record(result, document, "GET " + path, path, status, content_type, body)

    for template in tier2:
        collection = template.rsplit("/", 1)[0]
        status, content_type, body = bodies.get(collection, (0, "", b""))
        if status != 200 or not classify_json(content_type):
            continue
        parsed = json.loads(body.decode("utf-8"))
        identifier = None
        if isinstance(parsed, list):
            for row in parsed:
                if isinstance(row, dict) and "id" in row:
                    identifier = row["id"]
                    break
        elif isinstance(parsed, dict) and "id" in parsed:
            identifier = parsed["id"]
        if identifier is None:
            continue
        called = template.replace("{id}", str(identifier))
        status, content_type, body = send(base, "GET", called, key)
        result["selected"] += 1
        # Keyed by the template rather than by the address, so the output names an operation the
        # document declares rather than one run's discovered id.
        record(result, document, "GET " + template, template, status, content_type, body)

    return result


def external_probe(document, base, key, result):
    """Call the operations that declare no response body but return a known shape.

    Behind a flag, because the one entry reaches an external metadata service. Its findings join the
    sweep's, and its reads are deliberately outside the sweep's counts: it is a probe of a declared
    gap rather than one of the reads the document says returns a body.
    """
    for opkey, (schema_name, shape, query) in BODILESS_SCHEMA_MAP.items():
        method, path = opkey.split(" ", 1)
        status, content_type, body = send(base, method, path, key, query=query)
        print("  + external probe {} -> {} {} bytes".format(opkey, status, len(body)))
        if status != 200 or not classify_json(content_type):
            continue
        parsed = json.loads(body.decode("utf-8"))
        reference = {"$ref": "#/components/schemas/" + schema_name}
        node = {"type": "array", "items": reference} if shape == "array" else reference
        found = []
        walk(document, node, parsed, found, result["seenProps"])
        result["findings"].extend((finding, opkey) for finding in found)


def write_probe(base, key):
    """Create, update and delete one tag, recording the three status codes the instance answers.

    The one write in this script. The next stage needs the real success codes, and measuring them
    here is what stops three numbers being copied by hand out of a document. No field value is
    asserted and nothing goes through the typed client.
    """
    status_create, _content_type, body = send(
        base, "POST", "/api/v3/tag", key, payload={"label": PROBE_LABEL}
    )
    tag_id = json.loads(body.decode("utf-8"))["id"]
    status_update, _content_type, _body = send(
        base,
        "PUT",
        "/api/v3/tag/{}".format(tag_id),
        key,
        payload={"id": tag_id, "label": PROBE_LABEL + "-2"},
    )
    status_delete, _content_type, _body = send(
        base, "DELETE", "/api/v3/tag/{}".format(tag_id), key
    )
    return {"create": status_create, "update": status_update, "delete": status_delete}


def collapse(findings, verdict, with_type):
    """Collapse raw findings of one verdict into entries keyed by schema and property.

    One property appears on two operations, and a per-operation list would have the consumer apply
    the same patch twice. Nothing observed survives the collapse: the entry carries a JSON type name
    and the operations it was seen on, never a value.
    """
    entries = {}
    for (found_verdict, schema, path, detail), opkey in findings:
        if found_verdict != verdict:
            continue
        prop = path.rsplit(".", 1)[-1]
        entry = entries.setdefault(
            (schema, prop),
            {"schema": schema, "property": prop, "observedOn": []},
        )
        if with_type:
            if detail == "null":
                entry["nullObserved"] = True
            elif "jsonType" not in entry:
                entry["jsonType"] = detail
        if opkey not in entry["observedOn"]:
            entry["observedOn"].append(opkey)
    ordered = []
    for key in sorted(entries, key=lambda item: (item[0] or "", item[1])):
        entry = entries[key]
        if with_type:
            entry = {
                "schema": entry["schema"],
                "property": entry["property"],
                "jsonType": entry.get("jsonType", "null"),
                "nullObserved": entry.get("nullObserved", False),
                "observedOn": sorted(entry["observedOn"]),
            }
        else:
            entry = {
                "schema": entry["schema"],
                "property": entry["property"],
                "observedOn": sorted(entry["observedOn"]),
            }
        ordered.append(entry)
    return ordered


def declared_never_returned(document, seen_props):
    """The properties a touched schema declares that no body carried.

    Recorded and never fatal. It is drift running the other way, and it is upstream input rather
    than a build failure: one of these entries is the reason a by-id read has no id to be called
    with.
    """
    schemas = document.get("components", {}).get("schemas", {})
    touched = {name for name, _prop in seen_props}
    missing = []
    for name in sorted(touched):
        for prop in sorted(schemas.get(name, {}).get("properties", {})):
            if (name, prop) not in seen_props:
                missing.append({"schema": name, "property": prop})
    return missing


def main():
    # Checked before anything boots. The map is a measurement against one document, and against a
    # document that has moved it would validate a payload against the wrong schema.
    document_path = resolve_repo_path(SPEC_PATH)
    with open(document_path, encoding="utf-8") as handle:
        document = json.load(handle)
    stale = refuse_bodiless_map(document, BODILESS_SCHEMA_MAP)
    if stale:
        die(stale)

    with open(resolve_repo_path(PROVENANCE_PATH), encoding="utf-8") as handle:
        provenance = json.load(handle)

    output_path = resolve_repo_path(OUTPUT_PATH)
    external = os.environ.get(EXTERNAL_FLAG) == "1"
    total_gets = sum(len(tier) for tier in select_reads(document))

    print("Check conformance against " + verify_image.IMAGE_REF)
    try:
        # -v removes the anonymous volume the image declares for /config. The loopback publish is
        # explicit: a bare publish binds every interface and puts this run's key on all of them.
        verify_image.run_docker(["rm", "-f", "-v", CONTAINER_NAME])
        created = verify_image.run_docker([
            "create", "--name", CONTAINER_NAME,
            "-p", "127.0.0.1::{}".format(verify_image.CONTAINER_PORT),
            verify_image.IMAGE_REF,
        ])
        if created.returncode != 0:
            die(
                "ERROR: docker create failed for " + verify_image.IMAGE_REF + ".",
                (created.stdout or "") + (created.stderr or ""),
            )

        # Before start: the application reads the key at startup and rewrites the file.
        copied = verify_image.copy_into_container(
            CONTAINER_NAME, "/config", "config.xml", verify_image.SEED_BYTES, 0o666
        )
        if copied.returncode != 0:
            die(
                "ERROR: seeding /config/config.xml failed.",
                (copied.stdout or b"").decode("utf-8", "replace")
                + (copied.stderr or b"").decode("utf-8", "replace"),
            )

        started = verify_image.run_docker(["start", CONTAINER_NAME])
        if started.returncode != 0:
            die(
                "ERROR: docker start failed for " + CONTAINER_NAME + ".",
                (started.stdout or "") + (started.stderr or ""),
            )

        # The only address this run speaks to, read back from the container it just created.
        port = verify_image.host_port(CONTAINER_NAME, verify_image.CONTAINER_PORT)
        base = "http://127.0.0.1:{}".format(port)
        elapsed = wait_for_marker(CONTAINER_NAME, READY_TIMEOUT_SEC)
        print("  + started {} on host port {}, ready in {:.2f}s".format(
            CONTAINER_NAME, port, elapsed))

        result = sweep_reads(document, base, verify_image.API_KEY)
        if external:
            external_probe(document, base, verify_image.API_KEY, result)

        # After the sweep, never before. It writes a row, and a row changes what some reads return.
        probe = write_probe(base, verify_image.API_KEY)
        print("  + write probe create {} update {} delete {}".format(
            probe["create"], probe["update"], probe["delete"]))

        empty = refuse_empty_selection(result["answered"])
        if empty:
            die(empty)
        inconsistent = refuse_invariant(
            result["schemaChecked"],
            result["answered"],
            len(result["nonJsonReads"]),
            len(result["bodilessOperationsReturningData"]),
        )
        if inconsistent:
            die(inconsistent)

        conformance = {
            "measuredAgainst": {
                "imageDigest": provenance["imageDigest"],
                "whisparrVersion": provenance["whisparrVersion"],
                "generatedSpecSha256": provenance["generatedSpecSha256"],
            },
            "readsSelected": result["selected"],
            "readsSchemaChecked": result["schemaChecked"],
            "externalProbeRan": external,
            "writeProbe": probe,
            "undeclaredProperties": collapse(result["findings"], "undeclared", True),
            "typeMismatches": collapse(result["findings"], "type", True),
            "nullOnNonNullable": collapse(result["findings"], "null", False),
            "enumViolations": collapse(result["findings"], "enum", False),
            "declaredNeverReturned": declared_never_returned(document, result["seenProps"]),
            "bodilessOperationsReturningData": result["bodilessOperationsReturningData"],
            "nonJsonReads": result["nonJsonReads"],
            "readsNotAnswering200": result["readsNotAnswering200"],
        }
        write_json_lf(output_path, conformance)
        print("  + wrote " + output_path)
        print("  selected {}, answered 200 {}, non-JSON {}, bodiless with data {}".format(
            result["selected"],
            result["answered"],
            len(result["nonJsonReads"]),
            len(result["bodilessOperationsReturningData"]),
        ))
        print("schema-checked {} of {} GETs".format(result["schemaChecked"], total_gets))

        # After the write, because the file is the record of what was found. Each line is followed
        # by the sites it covers, so a reader gets the schema, the property and the operation
        # without the refusal line growing.
        refusals = refuse_findings([finding for finding, _opkey in result["findings"]])
        for line in refusals:
            print(line)
        for (verdict, schema, path, _detail), opkey in result["findings"]:
            print("    {} {} {} on {}".format(verdict, schema, path, opkey))
        # The undeclared list is what this script exists to produce, and the next stage reads it,
        # so it is reported rather than refused: a run that exited on it could never write the file
        # it was run for. The other three are zero against this pin and each one is a break.
        breaks = [finding for finding, _opkey in result["findings"] if finding[0] != "undeclared"]
        if breaks:
            die("  " + output_path + " records what was found.")
        print("Done. " + output_path)
    finally:
        # Force-remove so a failed run cannot leave a container holding a published port and a key.
        verify_image.run_docker(["rm", "-f", "-v", CONTAINER_NAME])


if __name__ == "__main__":
    main()
