#!/usr/bin/env python3
"""Record what a running Whisparr 2 instance returns, and what status code each write answers.

The document is now built from the same commit the pinned image runs, so a body and its declared
schema cannot disagree about a property or a type and there is nothing to compare. What is still
unknown is what the wire carries where the document declares nothing, and what status code each
write really answers. This boots the pinned digest under a name unique to the run, calls every read
it can address without inventing state, issues every write it can make a fresh instance answer, and
writes the record to spec/CONFORMANCE.json. The container is removed whether the run succeeded or
failed.

Nothing here records an observed value. One read returns the instance key in plaintext and its
schema declares four more credentials beside it, so the output carries a JSON type name and never a
sample.

Requires Docker. Run it when the pin moves, not per change.

    python generator/conformance.py
"""

import datetime
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import container
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

# The label every row this run creates carries. Created and deleted inside the same run, on the
# container this run started, which is force-removed at the end of it.
PROBE_LABEL = "conformance-probe"

# The two providers whose bulk PUT and bulk DELETE the probe reaches, each with the fields that
# keep the row it creates from contacting anything. A disabled row answers the bulk writes exactly
# as an enabled one would, and reaches no network on the way.
# The bulk path is spelled out rather than derived from the collection, so the operations this
# probe reaches can be read off one table.
PROVIDER_BULK = (
    ("/api/v3/downloadclient", "/api/v3/downloadclient/bulk", {"enable": False}),
    ("/api/v3/indexer", "/api/v3/indexer/bulk", {
        "enableRss": False,
        "enableAutomaticSearch": False,
        "enableInteractiveSearch": False,
    }),
)

# The five providers carrying a test and a testall POST. testall answers 200 with nothing
# configured; test answers 400 on every template a fresh instance can supply.
TEST_PROVIDERS = ("downloadclient", "importlist", "indexer", "metadata", "notification")

# A second delay profile, so the reorder has an order to move. The instance ships with one.
DELAY_PROFILE_PAYLOAD = {
    "enableUsenet": True,
    "enableTorrent": True,
    "preferredProtocol": "usenet",
    "usenetDelay": 0,
    "torrentDelay": 0,
    "bypassIfHighestQuality": False,
    "bypassIfAboveCustomFormatScore": False,
    "minimumCustomFormatScore": 0,
    "tags": [],
}

# Why each write the probe cannot make a fresh instance answer could not be reached. Recorded
# beside the status the attempt observed, and never turned into a status code.
TEST_REASON = (
    "the template a fresh instance supplies describes an unconfigured provider that fails its own "
    "validation, so the attempt answered 400. The success code is 200, which the document already "
    "declares, and the metadata provider answered it directly."
)
EPISODE_FILE_REASON = (
    "the application dereferences the first element of an empty sequence when no episode file "
    "exists, so this answers 500 on a fresh instance. That is an upstream defect, not a status "
    "contract."
)
IMPORT_LIST_BULK_REASON = (
    "no import-list template creates a row without a working list behind it, so the probe has no "
    "id to address this with."
)
CUSTOM_FORMAT_CREATE_REASON = (
    "the one body this run attempts, the first specification template the instance offers with its "
    "field values filled in, does not pass the application's own validation. One attempt is the "
    "budget: a second would be iterating on a shape the source already answers."
)
CUSTOM_FORMAT_REASON = (
    "the custom-format create did not succeed on the one body this run attempts, so the probe has "
    "no id to address this with."
)
PROVIDER_SCHEMA_REASON = "the {} schema route offered no template to create a row from."
PROVIDER_ROW_REASON = "the {} create did not succeed, so the probe has no id to address this with."

# Written at the key in the output file. A reader who found status codes here would reasonably read
# them as the codes to declare, and most of them are a failure rather than a contract.
WRITES_NOT_PROBED_NOTE = (
    "Every write this run could not make a fresh instance answer with success, and the status it "
    "did answer. Not a patch list: a status recorded here is the failure that was observed, not a "
    "code to declare. Declaring 400 for a test POST would make the generated client report a real "
    "validation failure as success, and declaring 500 for an episodefile write would record an "
    "upstream null dereference as a status contract."
)

# Written at the key in the output file, because the list is one a reader would reasonably mistake
# for a patch list and the mistake deletes real properties from the generated models.
DECLARED_NEVER_RETURNED_NOTE = (
    "Recorded and never patched. These are properties a touched schema declares that no body on a "
    "fresh instance carried, which is a fact about an empty instance rather than about the "
    "document. DownloadClientResource.id is returned the moment a download client exists, and "
    "Field.helpTextWarning is returned by any provider field that carries a warning. Treating this "
    "list as a patch list would delete both from the generated models."
)

# Every bodiless operation whose returned shape this document can name, measured rather than
# copied. The value is the schema its payload matches, the shape of that payload, and the query the
# read needs, or None where the sweep already reaches the route unaided. The schema name is written
# into the output record, so the fifth transformation reads it from there and this file stays the
# only place it is stated.
#
# The two schema routes were measured 2026-09-06 against the pinned digest: every key in every item
# they return is declared by the schema named here, and each is the tightest schema in the document
# that covers all of them. Both leave id and name unset, which is what a template that describes a
# specification rather than a saved row does.
#
# GET /api/v3/series/lookup is the one entry the hermetic sweep cannot reach, so it carries a
# query and is read by the external probe: the collection returns [], every by-id read 404s, and a
# create with a fabricated tvdbId returns 400 because the series is not found upstream.
#
# The four bodiless operations not named here return an object no schema in this document
# describes, so nothing can be attached for them and nothing is.
BODILESS_SCHEMA_MAP = {
    "GET /api/v3/autotagging/schema": ("AutoTaggingSpecificationSchema", "array", None),
    "GET /api/v3/customformat/schema": ("CustomFormatSpecificationSchema", "array", None),
    "GET /api/v3/series/lookup": ("SeriesResource", "array", {"term": "test"}),
}

def json_type_of(value):
    """The JSON type name of a parsed value, which is the only thing the output file records.

    A sample would be a credential on the host-config read, so the type name is the whole of what
    the record carries about what a body held. It is what the `shape` of a bodiless response is
    read from, and the fifth transformation attaches an array response or an object response
    according to that one word.
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

    A recorder that read a reference node directly would find no type and no properties, and would
    report every declared property of every schema as never returned.
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

    The never-returned list is keyed by schema and property, so a property recorded without its
    owning schema name could not be keyed at all.
    """
    if isinstance(node, dict) and isinstance(node.get("$ref"), str):
        name = node["$ref"].rsplit("/", 1)[-1]
        if name in document.get("components", {}).get("schemas", {}):
            return name
    return None


def classify_json(content_type):
    """Whether a response body should be parsed as JSON, from the content type alone.

    Read before the body is parsed. One read answers 184,918 bytes of Graphviz, and parsing that as
    JSON costs a wasted exception on every run and records a shape for a document that was never
    JSON.
    """
    return "json" in (content_type or "").lower()


def schema_for_200(document, method, path):
    """The JSON schema the document declares for an operation's 200, or None when it declares none.

    None is not a failure. It is the whole subject of this script: an operation that answers 200
    with JSON and declares no body at all is a gap the fifth transformation closes, so None routes
    the read into the recorded list rather than out of it.
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


def record_seen_properties(document, schema_node, value, seen_props, name_hint=None):
    """Record which declared properties a body carried, as (schema name, property) pairs, in place.

    This judges nothing. The recursive comparison that used to live here reported four verdicts,
    and all four became impossible by construction when the document started being built from the
    commit the pinned image runs: one document and one application cannot disagree about a declared
    property or a declared type. What is left is the record of what a body touched, which is the
    only input to the never-returned list.
    """
    name = schema_name_of(document, schema_node) or name_hint
    schema = resolve(document, schema_node)

    if not schema or value is None:
        return

    # allOf is used in this document for a single-member wrapper around a reference.
    if "allOf" in schema:
        for member in schema["allOf"]:
            record_seen_properties(document, member, value, seen_props, name)
        return

    if isinstance(value, list):
        items = schema.get("items", {})
        for entry in value:
            record_seen_properties(document, items, entry, seen_props)
        return

    if not isinstance(value, dict):
        return

    extra = schema.get("additionalProperties")

    # A map-shaped site. Its keys are data rather than declared properties, so none of them is a
    # property this record can be keyed by. Three such sites exist, all three nested under a
    # property, and folding their keys in would name several thousand properties on the
    # localization read alone that no schema declares.
    if isinstance(extra, dict):
        for member in value.values():
            record_seen_properties(document, extra, member, seen_props)
        return

    properties = schema.get("properties", {})

    for key, member in value.items():
        if key not in properties:
            continue
        if name:
            seen_props.add((name, key))
        # The owning schema name is carried down. A property whose subschema is inline rather than
        # a reference has no name of its own, and a pair that reported no schema could not be keyed
        # by schema and property, which is the shape of the never-returned list.
        record_seen_properties(document, properties[key], member, seen_props, name)


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

    The map is a measurement against one document, and the schema it names is what the fifth
    transformation attaches to the operation. Against a document that has moved it would name a
    schema that is not there, and the transformation would attach a reference to nothing.
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


def refuse_bodiless_shape(entries, mapping):
    """Refuse when a mapped operation returned a shape the map does not expect.

    The map states the shape its schema is wrapped in and the sweep measures the shape the instance
    actually returned. Both halves exist here and nowhere else, so this is where they are compared.
    A disagreement means the fifth transformation would attach an array where the instance sends an
    object, or the reverse, and the generated method would be named for the wrong one.

    Only an operation that produced an entry is judged. A hermetic run reaches no entry for the
    route behind the external probe, which is not a disagreement.
    """
    for entry in entries:
        expected = mapping.get(entry["operation"])
        if expected and entry["shape"] != expected[1]:
            return (
                REFUSAL_PREFIX
                + "{} returned a {} and the bodiless-operation map expects a {}. Nothing was "
                "written.".format(entry["operation"], entry["shape"], expected[1])
            )
    return None


def refuse_empty_selection(answered):
    """Refuse when no selected read reached the instance at all.

    An empty record from a run that reached nothing is indistinguishable from an empty record from
    an instance with nothing to report, and the second is the one a reader would assume.
    """
    if answered <= 0:
        return (
            REFUSAL_PREFIX
            + "the read selection reached no operation at all, so nothing was recorded. Nothing "
            "was written."
        )
    return None


def refuse_invariant(schema_checked, answered, non_json, bodiless_with_data):
    """Refuse when the counts do not add up.

    Derived, and compared against nothing literal. Whatever the numbers are, the number recorded
    against a declared schema must equal the reads that answered 200 with JSON and declared a JSON
    schema for 200. A sweep that quietly stopped reading bodies would otherwise still write a file.
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


def wait_for_marker(container_name, timeout_sec):
    """Block until the container log carries the readiness marker.

    Both HTTP signals return before the application has finished loading its defaults, so a sweep
    started on either of them reads a half-populated instance and reports properties as never
    returned that the instance returns a second later.
    """
    started = time.monotonic()
    while time.monotonic() - started < timeout_sec:
        logs = container.run_docker(["logs", container_name])
        if READY_MARKER in (logs.stdout or "") + (logs.stderr or ""):
            return time.monotonic() - started
        time.sleep(0.2)
    logs = container.run_docker(["logs", container_name, "--tail", "40"])
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


def bodiless_entry(opkey, content_type, body, parsed):
    """One entry for an operation that answered with data while declaring none.

    Content type, byte count and top-level shape, and nothing read out of the body. `shape` is what
    the fifth transformation reads to decide whether to attach an array response or an object
    response, and that choice decides three generated method names, so an entry without it would
    leave the transformation guessing.

    `schema` is present only for an operation BODILESS_SCHEMA_MAP names, and it is what makes this
    record the whole input to that transformation. Without it the transformation would need its own
    copy of the map, which is a second place for one fact to be stated.
    """
    entry = {
        "operation": opkey,
        "contentType": media_type_of(content_type),
        "bytes": len(body),
        "shape": json_type_of(parsed),
    }
    if opkey in BODILESS_SCHEMA_MAP:
        entry["schema"] = BODILESS_SCHEMA_MAP[opkey][0]
    return entry


def record(result, document, opkey, template, status, content_type, body):
    """Fold one answered read into the running record.

    A body is read against its declared schema only when the read answered 200, carried JSON and
    declares a JSON schema for its 200. Everything else is recorded under the reason it was not,
    which is what lets the counts be checked against each other rather than against a number
    written down.
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
    parsed = json.loads(body.decode("utf-8"))
    schema = schema_for_200(document, "get", template)
    if schema is None:
        result["bodilessOperationsReturningData"].append(
            bodiless_entry(opkey, content_type, body, parsed)
        )
        return
    record_seen_properties(document, schema, parsed, result["seenProps"])
    result["schemaChecked"] += 1


def sweep_reads(document, base, key):
    """Call every read this run can address without inventing state, and record each answer.

    Tier 1 first, then the by-id tier whose ids come out of those tier 1 bodies. A by-id read whose
    collection returned no id is left uncalled rather than fed a value from this file, because an
    id written into source is an id that could address something this run did not create.
    """
    tier1, tier2, _tier3 = select_reads(document)
    result = {
        "selected": 0,
        "answered": 0,
        "schemaChecked": 0,
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


def external_probe(base, key, result):
    """Record the bodiless operations the hermetic sweep cannot make answer.

    Behind a flag, because the one entry reaches an external metadata service over the public
    internet. The sweep calls `GET /api/v3/series/lookup` with no term and the instance answers 503
    from that service, so the operation lands in `readsNotAnswering200` and its shape goes
    unmeasured. Called with a term it answers 200, and this is where that answer is recorded.

    Its reads are deliberately outside the sweep's counts, and it records no property against a
    schema. Both are what keeps a flagged run and a hermetic run comparable: the only difference
    between the two records is the entry this adds.

    Only an entry carrying a query is read here. The other operations the map names are answered by
    the hermetic sweep on a fresh instance, and reading them a second time would record each of
    them twice.
    """
    for opkey, (_schema_name, _shape, query) in BODILESS_SCHEMA_MAP.items():
        if query is None:
            continue
        method, path = opkey.split(" ", 1)
        status, content_type, body = send(base, method, path, key, query=query)
        print("  + external probe {} -> {} {} bytes".format(opkey, status, len(body)))
        if status != 200 or not classify_json(content_type):
            continue
        parsed = json.loads(body.decode("utf-8"))
        result["bodilessOperationsReturningData"].append(
            bodiless_entry(opkey, content_type, body, parsed)
        )


def first_schema_template(base, key, provider):
    """The first template a provider's own schema route offers, or None when it offers none.

    Read off the instance rather than written into this file. A template written down here would
    describe a provider list that moves with the image.
    """
    status, content_type, body = send(base, "GET", "/api/v3/" + provider + "/schema", key)
    if status != 200 or not classify_json(content_type):
        return None
    templates = json.loads(body.decode("utf-8"))
    return templates[0] if templates else None


def filled_field(field):
    """One provider or specification field carrying a value the application will accept.

    A schema template arrives with its field values unset, and a specification whose field has no
    value fails the application's own validation. A field offering a fixed set takes the first
    option it offers, because an arbitrary string is not one of them.
    """
    if field.get("value") is not None:
        return field
    options = field.get("selectOptions") or []
    return dict(field, value=options[0]["value"] if options else PROBE_LABEL)


def write_probe(base, key):
    """Issue every write a fresh instance can be made to answer, one status code per operation.

    Returns (probe, unreached). `probe` maps `METHOD /path/template`, the spelling
    `readsNotAnswering200` already uses and the one the fifth transformation looks an operation up
    by, to the success status the instance answered. `unreached` carries every write this run could
    not make succeed, with the status the attempt observed and why.

    Two rules hold here, each stated where it is enforced. A status observed failing never enters
    `probe`: declaring 400 for a `test` POST would make the generated client report a real
    validation failure as success, and declaring 500 for an `episodefile` write would record an
    upstream null dereference as a status contract. And nothing read out of a response body reaches
    either structure: an id from a create addresses the next call and is never recorded.

    Every row this creates is left behind. The container is force-removed in the caller's `finally`,
    so restoring state would be work with no subject.
    """
    probe = {}
    unreached = []

    def issue(template, method, path, payload=None, query=None, reason=None):
        """One write, recorded under its operation key. Returns the parsed body, or None."""
        status, content_type, body = send(base, method, path, key, query=query, payload=payload)
        if 200 <= status < 300:
            probe[method + " " + template] = status
            if body and classify_json(content_type):
                return json.loads(body.decode("utf-8"))
            return None
        unreached.append({
            "operation": method + " " + template,
            "status": status,
            "reason": reason or "the attempt answered {}.".format(status),
        })
        return None

    def unreachable(operation, reason):
        """A write the probe never issued, because nothing on a fresh instance can address it."""
        unreached.append({"operation": operation, "reason": reason})

    # The controls, measured independently in the phase before at 201, 202 and 200.
    tag = issue("/api/v3/tag", "POST", "/api/v3/tag", payload={"label": PROBE_LABEL})
    if tag:
        issue("/api/v3/tag/{id}", "PUT", "/api/v3/tag/{}".format(tag["id"]),
              payload={"id": tag["id"], "label": PROBE_LABEL + "-2"})
        issue("/api/v3/tag/{id}", "DELETE", "/api/v3/tag/{}".format(tag["id"]))

    # A provider row is what the bulk pair addresses, and forceSave is what lets one be created
    # without a working service behind it. The row is created disabled, so it contacts nothing.
    for collection, bulk, disabled in PROVIDER_BULK:
        provider = collection.rsplit("/", 1)[-1]
        template = first_schema_template(base, key, provider)
        row = None
        if template is None:
            unreachable("POST " + collection, PROVIDER_SCHEMA_REASON.format(provider))
        else:
            row = issue(collection, "POST", collection,
                        payload=dict(template, name=PROBE_LABEL, **disabled),
                        query={"forceSave": "true"})
        if row is None:
            unreachable("PUT " + bulk, PROVIDER_ROW_REASON.format(collection))
            unreachable("DELETE " + bulk, PROVIDER_ROW_REASON.format(collection))
            continue
        ids = {"ids": [row["id"]]}
        issue(bulk, "PUT", bulk, payload=dict(ids, **disabled))
        issue(bulk, "DELETE", bulk, payload=ids)

    # The definitions are written back exactly as they were read. Nothing about them is recorded.
    status, content_type, body = send(base, "GET", "/api/v3/qualitydefinition", key)
    if status == 200 and classify_json(content_type):
        issue("/api/v3/qualitydefinition/update", "PUT", "/api/v3/qualitydefinition/update",
              payload=json.loads(body.decode("utf-8")))
    else:
        unreachable("PUT /api/v3/qualitydefinition/update",
                    "the definition collection answered {} rather than 200, so this run has "
                    "nothing to write back.".format(status))

    # An empty id list is accepted by each of these, and an empty list changes nothing.
    issue("/api/v3/episode/monitor", "PUT", "/api/v3/episode/monitor",
          payload={"episodeIds": [], "monitored": False})
    issue("/api/v3/series/editor", "PUT", "/api/v3/series/editor", payload={"seriesIds": []})
    issue("/api/v3/series/editor", "DELETE", "/api/v3/series/editor", payload={"seriesIds": []})
    issue("/api/v3/blocklist/bulk", "DELETE", "/api/v3/blocklist/bulk", payload={"ids": []})
    issue("/api/v3/queue/bulk", "DELETE", "/api/v3/queue/bulk", payload={"ids": []})

    # The reorder needs a second profile to have an order to move. The instance ships with one, and
    # every profile but that first one must carry at least one tag or the create answers 400. The
    # tag goes through send rather than issue: POST /api/v3/tag is measured above as a control, and
    # recording the same operation twice would say nothing new.
    status, content_type, body = send(base, "POST", "/api/v3/tag", key,
                                      payload={"label": PROBE_LABEL + "-delay"})
    tags = []
    if 200 <= status < 300 and classify_json(content_type):
        tags = [json.loads(body.decode("utf-8"))["id"]]
    profile = issue("/api/v3/delayprofile", "POST", "/api/v3/delayprofile",
                    payload=dict(DELAY_PROFILE_PAYLOAD, tags=tags))
    if profile:
        issue("/api/v3/delayprofile/reorder/{id}", "PUT",
              "/api/v3/delayprofile/reorder/{}".format(profile["id"]))
    else:
        unreachable("PUT /api/v3/delayprofile/reorder/{id}",
                    "the delay-profile create did not succeed, so the probe has no order to move.")

    for provider in TEST_PROVIDERS:
        issue("/api/v3/" + provider + "/testall", "POST", "/api/v3/" + provider + "/testall")

    # One bounded attempt. A body the application accepts converts the custom-format bulk pair from
    # inferred to measured, and a second iteration on the body would be guessing at a shape the
    # source already answers.
    specification = first_schema_template(base, key, "customformat")
    format_row = None
    if specification is not None:
        specification = dict(
            specification, name=PROBE_LABEL, negate=False, required=False,
            fields=[filled_field(field) for field in specification.get("fields") or []],
        )
        format_row = issue(
            "/api/v3/customformat", "POST", "/api/v3/customformat",
            payload={
                "name": PROBE_LABEL,
                "includeCustomFormatWhenRenaming": False,
                "specifications": [specification],
            },
            reason=CUSTOM_FORMAT_CREATE_REASON,
        )
    if format_row is None:
        unreachable("PUT /api/v3/customformat/bulk", CUSTOM_FORMAT_REASON)
        unreachable("DELETE /api/v3/customformat/bulk", CUSTOM_FORMAT_REASON)
    else:
        ids = {"ids": [format_row["id"]]}
        issue("/api/v3/customformat/bulk", "PUT", "/api/v3/customformat/bulk",
              payload=dict(ids, includeCustomFormatWhenRenaming=False))
        issue("/api/v3/customformat/bulk", "DELETE", "/api/v3/customformat/bulk", payload=ids)

    # Issued rather than assumed, so the status each answers is measured. None of them can succeed
    # on a fresh instance and none of the statuses below is a code to declare.
    for provider in TEST_PROVIDERS:
        template = first_schema_template(base, key, provider)
        issue("/api/v3/" + provider + "/test", "POST", "/api/v3/" + provider + "/test",
              payload=dict(template or {}, name=PROBE_LABEL), reason=TEST_REASON)

    issue("/api/v3/episodefile/editor", "PUT", "/api/v3/episodefile/editor",
          payload={"episodeFileIds": []}, reason=EPISODE_FILE_REASON)
    issue("/api/v3/episodefile/bulk", "PUT", "/api/v3/episodefile/bulk",
          payload=[], reason=EPISODE_FILE_REASON)
    issue("/api/v3/episodefile/bulk", "DELETE", "/api/v3/episodefile/bulk",
          payload={"episodeFileIds": []}, reason=EPISODE_FILE_REASON)

    unreachable("PUT /api/v3/importlist/bulk", IMPORT_LIST_BULK_REASON)
    unreachable("DELETE /api/v3/importlist/bulk", IMPORT_LIST_BULK_REASON)

    return probe, unreached


def declared_never_returned(document, seen_props):
    """The properties a touched schema declares that no body carried.

    Recorded and never patched. See DECLARED_NEVER_RETURNED_NOTE, which is written at the key in
    the output file, for the two properties that make the difference concrete.
    """
    schemas = document.get("components", {}).get("schemas", {})
    touched = {name for name, _prop in seen_props}
    missing = []
    for name in sorted(touched):
        for prop in sorted(schemas.get(name, {}).get("properties", {})):
            if (name, prop) not in seen_props:
                missing.append({"schema": name, "property": prop})
    return missing


def stale_start_time_refusal(reported, boot_began_at):
    """Return a refusal sentence when the instance predates this run, or None.

    The one identity signal a long-running instance on the pinned image cannot satisfy. Branch,
    major version and image digest are all identical on a personal instance running the same
    release, so they say nothing about which instance answered.

    Not greater than. startTime has whole-second resolution and the recorded stamp is truncated to
    the same resolution, so a boot that lands inside the stamped second reports a value equal to it.
    A strict comparison would refuse that correct run, and would do so only sometimes.
    """
    if reported >= boot_began_at:
        return None
    return (
        "ERROR: REFUSED - the instance reports a start time of "
        + reported.isoformat()
        + ", which is before this run began its boot at "
        + boot_began_at.isoformat()
        + ". This run did not start the instance that answered, so nothing was written."
    )


def refuse_an_instance_this_run_did_not_start(base, key, boot_began_at):
    """Refuse before the sweep writes anything, if the reachable instance predates this boot.

    The address is the first protection: the port was read back from the container this run created
    under a name carrying a per-run suffix. This is the second. It exists because the write probe
    below issues a real delete, and a delete against an instance this run did not create has no
    undo.
    """
    status, _ctype, body = send(base, "GET", "/api/v3/system/status", key)
    if status != 200:
        die(
            "ERROR: REFUSED - the status read answered {} rather than 200, so this run cannot "
            "prove which instance it reached. Nothing was written.".format(status)
        )
    reported = json.loads(body).get("startTime")
    if not reported:
        die(
            "ERROR: REFUSED - the instance reported no start time, so this run cannot prove it "
            "reached the container it created. Nothing was written."
        )
    parsed = datetime.datetime.fromisoformat(reported.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        die(
            "ERROR: REFUSED - the reported start time " + reported + " carries no time zone, so "
            "the comparison would silently move by this machine's offset. Nothing was written."
        )
    refusal = stale_start_time_refusal(parsed.astimezone(datetime.timezone.utc), boot_began_at)
    if refusal:
        die(refusal)


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

    print("Check conformance against " + container.IMAGE_REF)
    try:
        # -v removes the anonymous volume the image declares for /config. The loopback publish is
        # explicit: a bare publish binds every interface and puts this run's key on all of them.
        boot_began_at = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        container.run_docker(["rm", "-f", "-v", CONTAINER_NAME])
        created = container.run_docker([
            "create", "--name", CONTAINER_NAME,
            "-p", "127.0.0.1::{}".format(container.CONTAINER_PORT),
            container.IMAGE_REF,
        ])
        if created.returncode != 0:
            die(
                "ERROR: docker create failed for " + container.IMAGE_REF + ".",
                (created.stdout or "") + (created.stderr or ""),
            )

        # Before start: the application reads the key at startup and rewrites the file.
        copied = container.copy_into_container(
            CONTAINER_NAME, "/config", "config.xml", container.SEED_BYTES, 0o666
        )
        if copied.returncode != 0:
            die(
                "ERROR: seeding /config/config.xml failed.",
                (copied.stdout or b"").decode("utf-8", "replace")
                + (copied.stderr or b"").decode("utf-8", "replace"),
            )

        started = container.run_docker(["start", CONTAINER_NAME])
        if started.returncode != 0:
            die(
                "ERROR: docker start failed for " + CONTAINER_NAME + ".",
                (started.stdout or "") + (started.stderr or ""),
            )

        # The only address this run speaks to, read back from the container it just created.
        port = container.host_port(CONTAINER_NAME, container.CONTAINER_PORT)
        base = "http://127.0.0.1:{}".format(port)
        elapsed = wait_for_marker(CONTAINER_NAME, READY_TIMEOUT_SEC)
        print("  + started {} on host port {}, ready in {:.2f}s".format(
            CONTAINER_NAME, port, elapsed))

        refuse_an_instance_this_run_did_not_start(
            base, container.API_KEY, boot_began_at)

        result = sweep_reads(document, base, container.API_KEY)

        # Checked here, before the external probe adds an entry the sweep's counts do not know
        # about and before the first write, so a run whose sweep did not add up issues no write at
        # all.
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

        if external:
            external_probe(base, container.API_KEY, result)

        # After the external probe, because the entry it adds is one of the three the map names,
        # and before the first write, so a disagreement between what the map expects and what the
        # instance returned issues no write at all.
        disagreed = refuse_bodiless_shape(
            result["bodilessOperationsReturningData"], BODILESS_SCHEMA_MAP
        )
        if disagreed:
            die(disagreed)

        # After the sweep, never before. It writes rows, and a row changes what some reads return,
        # so a probe moved ahead of the sweep makes the recorded byte counts irreproducible.
        probe, unreached = write_probe(base, container.API_KEY)
        for operation in sorted(probe):
            print("  + write probe {} -> {}".format(operation, probe[operation]))
        for entry in unreached:
            print("  - not probed {} {}".format(
                entry["operation"], entry.get("status", "not issued")))

        conformance = {
            "measuredAgainst": {
                "imageDigest": provenance["imageDigest"],
                "specCommit": provenance["specCommit"],
                "generatedSpecSha256": provenance["generatedSpecSha256"],
            },
            "readsSelected": result["selected"],
            "readsSchemaChecked": result["schemaChecked"],
            "externalProbeRan": external,
            "writeProbe": probe,
            "writesNotProbedNote": WRITES_NOT_PROBED_NOTE,
            "writesNotProbed": unreached,
            "declaredNeverReturnedNote": DECLARED_NEVER_RETURNED_NOTE,
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
        print("  write probe reached {} operations, {} recorded unreachable".format(
            len(probe), len(unreached)))
        # The run exits 0. It used to refuse on four verdicts, and all four became impossible when
        # the document started being built from the commit the pinned image runs. What is left is a
        # record, and a record has nothing to refuse on.
        print("Done. " + output_path)
    finally:
        # Force-remove so a failed run cannot leave a container holding a published port and a key.
        container.run_docker(["rm", "-f", "-v", CONTAINER_NAME])


if __name__ == "__main__":
    main()
