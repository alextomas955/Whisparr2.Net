"""Helpers shared by the pipeline scripts.

Nothing here is clever. It exists because fetch, verify, preprocess and generate all need the same
repository-relative path resolution and the same LF-terminated JSON writer, and three copies of a
two-line function drift.
"""

import hashlib
import json
import os
import sys
import tempfile
from typing import NoReturn

# generator/ sits directly under the repository root.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_repo_path(path):
    """Absolute path, resolved against the repository root when relative."""
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(REPO_ROOT, path))


def sha256_file(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def write_json_lf(path, obj):
    """Write JSON the way .gitattributes declares it: 2-space indent, LF, one trailing newline.

    ensure_ascii=False keeps the document's own characters rather than escaping them to \\uXXXX,
    which is what makes the output match the bytes this repository already carries.
    """
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return text


def write_bytes_atomic(path, data):
    """Write data to path so an interrupted run never leaves a truncated file.

    The temporary file is created in the same directory as path, because os.replace is atomic only
    within one filesystem. Either the complete new bytes land or the previous file is unchanged.
    """
    directory = os.path.dirname(os.path.abspath(path))
    handle = tempfile.NamedTemporaryFile(dir=directory, prefix=".tmp-", delete=False)
    try:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        # Inside the try, so a replace that fails for a permission or cross-device reason leaves no
        # temporary file behind. The default target directory is the committed spec/.
        os.replace(handle.name, path)
    except BaseException:
        handle.close()
        os.remove(handle.name)
        raise


def die(*lines) -> NoReturn:
    """Print a refusal and exit 1. Every caller has already left the tree untouched.

    The return type is declared because callers refuse inside an except handler and then use the
    value the failed statement would have bound. Without it a checker reads those uses as possibly
    unbound and the alternative is a placeholder assignment that hides the refusal.
    """
    for line in lines:
        print(line)
    sys.stdout.flush()
    sys.exit(1)
