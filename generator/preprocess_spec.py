#!/usr/bin/env python3
"""Pre-process the pinned Whisparr 2 OpenAPI document into the spec the generator reads.

T1 narrows root security, T2 deletes the malformed paths["/"], T3 derives an operationId for every
operation from the document itself, and T4 replaces the five CLR-shaped schemas with the strings
the server actually serialises.

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

    This refusal is not redundant with the one in generator/fetch_spec.py:136-141. The two speak at
    different boundaries: the fetch says this is not the document the pipeline was measured
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
