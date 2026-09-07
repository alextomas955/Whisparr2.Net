#!/usr/bin/env python3
"""Render docs/SURFACE.md from the committed spec and the conformance record.

The document is almost entirely derived: counts of operations, and tables listing them. Typing them
by hand and guarding them with a script that re-derives every number pins a repository to one
release of the API, because a Whisparr release that adds an operation moves a count and turns the
build red as though something had broken. Generating them removes the pin. Nothing here asserts that
the API has a particular number of operations. The counts are whatever the committed spec declares,
and they change when it changes.

Three of the counts come from spec/CONFORMANCE.json rather than from the spec: how many operations
declaring no response body answered with one, how many reads answered with something other than
JSON, and how many answered a status other than 200. They are rendered rather than written into the
prose because a count typed into a second place goes stale against the record it was copied from,
and this repository keeps no such copies.

Prose lives in generator/templates/SURFACE.md.in and is copied through untouched. Derived values are
substituted for @@TOKEN@@ markers. The marker syntax is deliberately not Python's own str.format
braces, because every path in these tables can contain a brace: /api/v3/episodefile/{id} is a real
key.

Three things here are judgement rather than derivation, and each is a named list below. Which paths
serve the web interface, which responses carry credentials, and which operations have effects the
spec does not describe are all facts about Whisparr that no field of the spec states. They are
written down, and every one is checked against the spec on each run: a path that disappears upstream
refuses the render rather than leaving prose describing an operation nobody can call.

The lists describe. They do not instruct. What a caller does with an operation is the caller's
decision, and this library has no standing to rule on it.

    python generator/render_docs.py            # write the document
    python generator/render_docs.py --check    # exit 1 if the document on disk differs
"""

import argparse
import json
from pathlib import Path

from _common import die, resolve_repo_path, write_bytes_atomic

RAW_SPEC = Path(resolve_repo_path("spec/openapi.raw.json"))
SPEC = Path(resolve_repo_path("spec/openapi.generated.json"))
CONFORMANCE = Path(resolve_repo_path("spec/CONFORMANCE.json"))
TEMPLATE = Path(resolve_repo_path("generator/templates/SURFACE.md.in"))
SURFACE = Path(resolve_repo_path("docs/SURFACE.md"))

# The document path as a reader types it, used in both the success line and the mismatch line.
SURFACE_NAME = "docs/SURFACE.md"

# Printed verbatim by a passing --check. A silent success is indistinguishable in a run log from a
# step that never executed, so this line is the evidence in a run log that the gate ran at all. No
# workflow step reads it back. A reader checking a run does so by hand.
CHECK_PASSES_LINE = "%s matches the render of the committed spec." % SURFACE_NAME

HTTP_METHODS = ("get", "put", "post", "delete", "patch", "head", "options", "trace")

# Paths that serve Whisparr's browser interface or a calendar subscriber. A path list rather than an
# operation list, so a new method on one of these paths is picked up.
WEB_INTERFACE_PATHS = (
    "/{path}",
    "/content/{path}",
    "/login",
    "/logout",
    "/feed/v3/calendar/whisparr.ics",
)

# Operations the template describes by name under "Operations whose effect the spec does not
# describe". Checked, never rendered: the descriptions are prose and belong in the template. Listed
# here so that one leaving the spec refuses the render instead of leaving prose about a method that
# no longer exists. Whisparr 2's vocabulary is inherited from Sonarr, so these are episodefile
# operations and there is no moviefile path to name.
DESCRIBED_BY_NAME = (
    ("POST", "/api/v3/command"),
    ("POST", "/api/v3/release"),
    ("DELETE", "/api/v3/episodefile/{id}"),
    ("DELETE", "/api/v3/episodefile/bulk"),
    ("PUT", "/api/v3/episodefile/editor"),
)

# Operations whose responses carry credentials. Which responses leak is a property of the schemas
# rather than of the method, so the rows are judgement and the render only checks that each
# operation still exists. Each row names the properties a response carries and never a value.
CREDENTIAL_ROWS = (
    ("GET", "/api/v3/config/host",
     "The instance API key and the admin password, both in plaintext. `HostConfigResource` "
     "declares `password`, `passwordConfirmation`, `apiKey`, `sslCertPassword` and "
     "`proxyPassword`."),
    ("GET", "/api/v3/config/host/{id}", "The same resource, reached by id."),
    ("GET", "/api/v3/log",
     "Log records from the instance database. Log text can contain the key."),
    ("GET", "/api/v3/log/file/{filename}",
     "Raw log file text, with no schema at all in the spec."),
    ("GET", "/api/v3/log/file/update/{filename}", "The same, for the updater's log files."),
)


def operations(spec):
    """Every operation in one spec, as (METHOD, path, operationId, operation) rows."""
    found = []
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if method in HTTP_METHODS:
                found.append((method.upper(), path, operation.get("operationId", ""), operation))
    return found


def in_document_order(rows):
    """Sorted by path, then by method, which is the order the document states it uses."""
    return sorted(rows, key=lambda row: (row[1], row[0]))


def table(rows):
    """A three-column Markdown table of (method, path, operation) rows."""
    out = ["| Method | Path | Operation |", "| --- | --- | --- |"]
    out += ["| %s | %s | %s |" % row[:3] for row in rows]
    return "\n".join(out)


def validate_judgement_lists(declared):
    """Refuse when a judgement list names something the generated spec no longer declares.

    A function rather than inline code in render_surface because the self-test drives it directly,
    which is the only way to observe a branch a render against the committed spec never reaches.
    """
    paths = {path for _method, path in declared}

    missing = [path for path in WEB_INTERFACE_PATHS if path not in paths]
    if missing:
        die("ERROR: REFUSED - WEB_INTERFACE_PATHS names paths the spec no longer declares: "
            "%s. The list holds which paths serve Whisparr's own browser interface and its "
            "calendar subscribers, which no field of the spec states. A path that disappeared "
            "upstream should be investigated rather than deleted, because the prose describing it "
            "goes with it. Nothing was written." % ", ".join(missing))

    missing = ["%s %s" % (method, path) for method, path, _carries in CREDENTIAL_ROWS
               if (method, path) not in declared]
    if missing:
        die("ERROR: REFUSED - CREDENTIAL_ROWS names operations the spec no longer declares: "
            "%s. The list holds which responses carry a secret, which is a property of the schemas "
            "rather than anything the spec labels. An operation that disappeared upstream should "
            "be investigated rather than deleted, because the credential may have moved to another "
            "operation. Nothing was written." % ", ".join(missing))

    missing = ["%s %s" % row for row in DESCRIBED_BY_NAME if row not in declared]
    if missing:
        die("ERROR: REFUSED - DESCRIBED_BY_NAME names operations the spec no longer declares: "
            "%s. The list holds which operations have effects the spec does not describe, which no "
            "field of the spec states. An operation that disappeared upstream should be "
            "investigated rather than deleted, because the template describes each one by name and "
            "the prose goes with it. Nothing was written." % ", ".join(missing))


def render_surface(raw_ops, ops, conformance):
    """The rendered document, as text, with every marker substituted."""
    void = [row for row in ops if not any(
        "content" in response
        for code, response in row[3].get("responses", {}).items()
        if code.startswith("2")
    )]
    web = [row for row in ops if row[1] in WEB_INTERFACE_PATHS]

    validate_judgement_lists({(row[0], row[1]) for row in ops})

    credential_table = ["| Operation | What its response carries |", "| --- | --- |"]
    credential_table += ["| `%s %s` | %s |" % row for row in CREDENTIAL_ROWS]

    text = TEMPLATE.read_text(encoding="utf-8")
    for token, value in (
        ("@@RAW_TOTAL@@", str(len(raw_ops))),
        ("@@TOTAL@@", str(len(ops))),
        ("@@VOID_COUNT@@", str(len(void))),
        ("@@VOID_TABLE@@", table(in_document_order(void))),
        ("@@WEB_INTERFACE_TABLE@@", table(in_document_order(web))),
        ("@@CREDENTIAL_TABLE@@", "\n".join(credential_table)),
        ("@@BODILESS_COUNT@@", str(len(conformance["bodilessOperationsReturningData"]))),
        ("@@NON_JSON_COUNT@@", str(len(conformance["nonJsonReads"]))),
        ("@@READS_NOT_200_COUNT@@", str(len(conformance["readsNotAnswering200"]))),
    ):
        text = text.replace(token, value)
    return text


def main():
    parser = argparse.ArgumentParser(
        description="Render docs/SURFACE.md from the committed spec.")
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if the document on disk differs")
    args = parser.parse_args()

    for path in (RAW_SPEC, SPEC, CONFORMANCE, TEMPLATE):
        if not path.exists():
            die("ERROR: REFUSED - %s does not exist, so there is nothing to render from. Nothing "
                "was written." % path)

    with RAW_SPEC.open(encoding="utf-8") as handle:
        raw_ops = operations(json.load(handle))
    with SPEC.open(encoding="utf-8") as handle:
        ops = operations(json.load(handle))
    with CONFORMANCE.open(encoding="utf-8") as handle:
        conformance = json.load(handle)

    rendered = render_surface(raw_ops, ops, conformance).encode("utf-8")
    current = SURFACE.read_bytes() if SURFACE.exists() else None

    # --check opens nothing for writing at any point. The comparison is between the render held in
    # memory and the bytes read off disk, so an interrupted check leaves the working tree as it was.
    if args.check:
        if current != rendered:
            die("%s differs from the render of the committed spec." % SURFACE_NAME,
                "Run: python generator/render_docs.py")
        print(CHECK_PASSES_LINE)
        return

    if current == rendered:
        print("%s unchanged" % SURFACE_NAME)
        return

    # Atomic, so an interrupted write leaves either the previous document or the complete new one,
    # and never a truncated file or a stray temporary file beside it.
    write_bytes_atomic(str(SURFACE), rendered)
    print("%s written" % SURFACE_NAME)


if __name__ == "__main__":
    main()
