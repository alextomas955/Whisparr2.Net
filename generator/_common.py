"""Helpers shared by the pipeline scripts.

Nothing here is clever. It exists because fetch, verify, preprocess and generate all need the same
repository-relative path resolution and the same LF-terminated JSON writer, and three copies of a
two-line function drift.
"""

import hashlib
import json
import os
import sys

# generator/ sits directly under the repository root.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# raw.githubusercontent.com serves without one, but api.github.com refuses an unidentified client,
# and the drift check reads the contents API. Set here so both callers send the same string.
USER_AGENT = "Whisparr2.Net-pipeline"


def resolve_repo_path(path):
    """Absolute path, resolved against the repository root when relative."""
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(REPO_ROOT, path))


def sha256_file(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def git_blob_sha1(data):
    """Git's own object identity for a blob, recomputed locally.

    Git hashes 'blob <length>\\0' followed by the raw bytes. This is the value `git hash-object`
    prints, so a reader with git and no Python reproduces it.
    """
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def write_json_lf(path, obj):
    """Write JSON the way .gitattributes declares it: 2-space indent, LF, one trailing newline.

    ensure_ascii=False keeps the document's own characters rather than escaping them to \\uXXXX,
    which is what makes the output match the bytes this repository already carries.
    """
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return text


def die(*lines):
    """Print a refusal and exit 1. Every caller has already left the tree untouched."""
    for line in lines:
        print(line)
    sys.stdout.flush()
    sys.exit(1)
