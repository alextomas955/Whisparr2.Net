#!/usr/bin/env python3
"""The pinned Whisparr 2 container: the image reference, the seed, the key and the Docker calls.

Owns four things and nothing else. The reference every probe runs, read from
spec/PROVENANCE.json rather than declared here. The one committed seed config.xml. The API key
parsed out of those same bytes, so no caller can hold a key the container was never given. And the
Docker calls that create, seed, start and address a container.

The pin lives in the record because the C# fixture reads the same field and cannot import a Python
constant. This module owns the address and the Docker calls, not the pin.

This is the single construction site for the address. Nothing here names a host port: the port is
published as ephemeral on the loopback address and read back from Docker at run time. A caller that
built an address any other way, or a second container lifecycle outside this module, is how a write
reaches an instance this run did not start.

A library. Nothing runs it directly.
"""

import io
import json
import subprocess
import tarfile
import xml.etree.ElementTree as ElementTree

from _common import die, resolve_repo_path

PROVENANCE_FILE = "spec/PROVENANCE.json"  # measured 2026-09-07
# The record declares the pin, and imageDigest is the whole reference rather than a bare digest, so
# there is one spelling of the image and no copy to check.  measured 2026-09-07
with open(resolve_repo_path(PROVENANCE_FILE), "r", encoding="utf-8") as _provenance_handle:
    IMAGE_REF = json.load(_provenance_handle)["imageDigest"]

SEED_FILE = "generator/config.seed.xml"  # measured 2026-09-05
# One committed seed, read once. The key comes out of the same document that is copied into the
# container, so a caller cannot hold a key the container was never given.  measured 2026-09-05
with open(resolve_repo_path(SEED_FILE), "rb") as _seed_handle:
    SEED_BYTES = _seed_handle.read()
API_KEY = ElementTree.fromstring(SEED_BYTES).findtext("ApiKey")  # measured 2026-09-05

CONTAINER_PORT = 6969  # measured 2026-09-05
READY_TIMEOUT_SEC = 120  # measured 2026-09-05


def run_docker(arguments):
    """Run one Docker command and capture its output as text.

    The encoding pair is not decorative: it is what stops a container log line carrying a
    non-ASCII character from raising UnicodeDecodeError on a Windows console. Every call that
    reads text sets it.
    """
    return subprocess.run(
        ["docker"] + list(arguments),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def copy_into_container(container, dest_dir, member_name, data, mode):
    """Copy one file into a created container with an explicit Unix mode.

    A plain `docker cp <file>` from this machine lands the file at mode 755 owned by root, and the
    application then throws an unhandled access-denied exception writing config during startup,
    because it runs as uid 1000. `docker cp -` reads a tar from stdin and honours the mode in its
    header. Measured: the tar form produces mode 666 owned by root, and a plain copy produces mode
    755 owned by root.

    The destination must be a directory, and the tar member name becomes the filename.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        entry = tarfile.TarInfo(member_name)
        entry.size = len(data)
        entry.mode = mode
        entry.uid = 0
        entry.gid = 0
        archive.addfile(entry, io.BytesIO(data))
    return subprocess.run(
        ["docker", "cp", "-", container + ":" + dest_dir],
        input=buffer.getvalue(), capture_output=True,
    )


def host_port(container, container_port):
    """The host port Docker assigned to a published container port.

    Publishing an ephemeral host port and reading it back removes a whole failure branch compared
    with pinning a fixed host port and refusing when it is bound. Nothing here names a host port.
    """
    result = run_docker(["port", container, "{}/tcp".format(container_port)])
    mapping = (result.stdout or "").strip().splitlines()
    if result.returncode != 0 or not mapping:
        die(
            "ERROR: REFUSED - could not read the host port for {}/tcp on {}.".format(
                container_port, container
            ),
            (result.stdout or "") + (result.stderr or ""),
        )
    return int(mapping[0].rsplit(":", 1)[1])
