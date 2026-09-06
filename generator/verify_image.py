#!/usr/bin/env python3
"""Identity-check the pinned Whisparr 2 container image and record what it reported.

The same image name carries tags for a different application. A digest that turned out to be
Whisparr 3 would make every later integration test prove the client against the wrong application,
and the API prefix and the application name are identical on both, so neither discriminates.

Boots the pinned digest with a seeded config.xml, reads GET /api/v3/system/status with the seeded
key, refuses unless the instance reports branch v2 and major version 2, then merges six image
fields into spec/PROVENANCE.json. The container is removed whether the run succeeded or failed.

Requires Docker. Run it when the pin moves, not per change.

    python generator/verify_image.py
"""

import argparse
import io
import json
import os
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ElementTree

from _common import die, resolve_repo_path, write_json_lf

IMAGE_TAG = "ghcr.io/hotio/whisparr:v2-2.2.0-release.231"  # measured 2026-09-05
IMAGE_DIGEST = "sha256:c6dae7dc99b52c3f73b64c9eca9bb38db0f646c98a3ea5829c57b1ebdce0d170"  # measured 2026-09-05
# Only the digest is ever used to run. The tag is recorded beside it so a reader can tell which
# release line the digest belongs to, and the repository name is taken from the tag rather than
# written twice.  measured 2026-09-05
IMAGE_REF = IMAGE_TAG.rsplit(":", 1)[0] + "@" + IMAGE_DIGEST
CONTAINER_NAME = "whisparr2-verify"  # measured 2026-09-05

SEED_FILE = "generator/config.seed.xml"  # measured 2026-09-05
# One committed seed, read once. The key comes out of the same document that is copied into the
# container, so the script cannot hold a key the container was never given.  measured 2026-09-05
with open(resolve_repo_path(SEED_FILE), "rb") as _seed_handle:
    SEED_BYTES = _seed_handle.read()
API_KEY = ElementTree.fromstring(SEED_BYTES).findtext("ApiKey")  # measured 2026-09-05

CONTAINER_PORT = 6969  # measured 2026-09-05
READY_TIMEOUT_SEC = 120  # measured 2026-09-05
PROVENANCE_PATH = "spec/PROVENANCE.json"  # measured 2026-09-05
EXPECTED_BRANCH = "v2"  # measured 2026-09-05
EXPECTED_MAJOR = 2  # measured 2026-09-05
# At a root-owned 0755 seed the identity read still succeeds and this is the only trace of the
# failure. Grepping the log for it is what stops that defect reaching the integration suite.
FORBIDDEN_LOG_MARKER = "UnauthorizedAccessException"  # measured 2026-09-05


def assert_identity(status):
    """Return refusal lines for a status document. An empty list means the identity holds.

    Pure, and takes a dict, which is what lets every identity assertion run with no Docker daemon.
    It reads branch and the major component of version and nothing else: appName is Whisparr on
    both applications and the API prefix is /api/v3 on both, so neither discriminates.
    """
    branch = status.get("branch")
    version = status.get("version")
    # An absent or unparseable version is a failed assertion, not a raise.
    major = None
    if isinstance(version, str):
        head = version.split(".")[0]
        if head.isdigit():
            major = int(head)
    if branch != EXPECTED_BRANCH or major != EXPECTED_MAJOR:
        return [
            "ERROR: REFUSED - the instance reports branch '{}' version '{}'. Required: branch "
            "'{}' and major version {}.".format(branch, version, EXPECTED_BRANCH, EXPECTED_MAJOR)
        ]
    return []


def image_provenance(status):
    """The six provenance fields this script owns, and no others."""
    return {
        "imageTag": IMAGE_TAG,
        "imageDigest": IMAGE_REF,
        "whisparrVersion": status.get("version"),
        "whisparrBranch": status.get("branch"),
        "whisparrBuildTime": status.get("buildTime"),
        "whisparrPackageVersion": status.get("packageVersion"),
    }


def merge_image_provenance(path, updates):
    """Merge the image block into a provenance document this script does not create.

    Refuses when the file is absent rather than creating one with an image block and no spec block,
    which keeps the ordering between the two scripts explicit rather than implicit in the file's
    contents.
    """
    provenance_path = resolve_repo_path(path)
    if not os.path.exists(provenance_path):
        die(
            "ERROR: REFUSED - {} does not exist. Run generator/fetch_spec.py first: it writes the "
            "spec block this script merges into.".format(provenance_path)
        )

    # A null is not an observation. The comprehension runs over the six keys this script owns,
    # before the merge, so a pre-existing key it does not own cannot implicate it.
    unobserved = [
        key
        for key, value in updates.items()
        if value is None or (isinstance(value, str) and not value.strip())
    ]
    if unobserved:
        die(
            "ERROR: REFUSED - provenance would record no observed value for: {}. {} is "
            "untouched.".format(", ".join(unobserved), provenance_path)
        )

    with open(provenance_path, encoding="utf-8") as handle:
        provenance = json.load(handle)
    # Python dicts preserve insertion order and re-assigning an existing key keeps its position, so
    # these land after the spec block on a first run and stay put on a re-run.
    for key, value in updates.items():
        provenance[key] = value
    write_json_lf(provenance_path, provenance)
    return provenance_path


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


def wait_for_status(base_url, timeout_sec):
    """Poll the status endpoint until it answers 200, and return the parsed document.

    This script reads only identity fields and asserts no seeded counts, so a 200 is sufficient
    readiness for it. The log-marker strategy belongs to the container test fixture, where the
    seeding race actually bites.
    """
    url = base_url + "/api/v3/system/status"
    request = urllib.request.Request(url, headers={"X-Api-Key": API_KEY})
    started = time.monotonic()
    last_status = 0
    while time.monotonic() - started < timeout_sec:
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.status == 200:
                    return json.loads(response.read().decode("utf-8"))
                last_status = response.status
        except urllib.error.HTTPError as error:
            last_status = error.code
        except (urllib.error.URLError, OSError):
            last_status = 0
        time.sleep(1)
    logs = run_docker(["logs", CONTAINER_NAME, "--tail", "40"])
    die(
        "ERROR: REFUSED - {} returned HTTP {}, not 200, within {}s.".format(
            url, last_status, timeout_sec
        ),
        "  Nothing was written to " + PROVENANCE_PATH + ".",
        (logs.stdout or "") + (logs.stderr or ""),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Identity-check the pinned Whisparr 2 image and record what it reported."
    )
    parser.add_argument("--timeout-sec", type=int, default=READY_TIMEOUT_SEC)
    args = parser.parse_args()

    print("Verify image identity -> " + IMAGE_REF)
    try:
        # -v removes the anonymous volume the image declares for /config, which every run would
        # otherwise leak. The loopback address is explicit: a bare publish binds every interface
        # and Docker adds its own firewall rule, which would put this constant key on every
        # interface for the whole run.
        run_docker(["rm", "-f", "-v", CONTAINER_NAME])
        created = run_docker([
            "create", "--name", CONTAINER_NAME,
            "-p", "127.0.0.1::{}".format(CONTAINER_PORT),
            IMAGE_REF,
        ])
        if created.returncode != 0:
            die(
                "ERROR: docker create failed for " + IMAGE_REF + ".",
                (created.stdout or "") + (created.stderr or ""),
            )

        # Before start, per D-10: the application reads the key at startup and rewrites the file.
        copied = copy_into_container(CONTAINER_NAME, "/config", "config.xml", SEED_BYTES, 0o666)
        if copied.returncode != 0:
            die(
                "ERROR: seeding /config/config.xml failed.",
                (copied.stdout or b"").decode("utf-8", "replace")
                + (copied.stderr or b"").decode("utf-8", "replace"),
            )

        started = run_docker(["start", CONTAINER_NAME])
        if started.returncode != 0:
            die(
                "ERROR: docker start failed for " + CONTAINER_NAME + ".",
                (started.stdout or "") + (started.stderr or ""),
            )
        port = host_port(CONTAINER_NAME, CONTAINER_PORT)
        print("  + started {} on host port {}".format(CONTAINER_NAME, port))

        status = wait_for_status("http://127.0.0.1:{}".format(port), args.timeout_sec)
        problems = assert_identity(status)
        if problems:
            die(*(problems + ["  " + PROVENANCE_PATH + " is untouched."]))
        print("  + identity ok")

        # At the wrong file mode the identity read succeeds anyway and the exception is only
        # visible here. Without this check the defect surfaces much later as an integration suite
        # failing for a reason nobody connects to a file mode, which is silent and expensive.
        logs = run_docker(["logs", CONTAINER_NAME])
        if FORBIDDEN_LOG_MARKER in (logs.stdout or "") + (logs.stderr or ""):
            die(
                "ERROR: REFUSED - the container log carries an access-denied exception, so the "
                "seed did not land at mode 0666. " + PROVENANCE_PATH + " is untouched."
            )

        updates = image_provenance(status)
        written = merge_image_provenance(PROVENANCE_PATH, updates)
        print("  + wrote " + written)
        for key, value in updates.items():
            print("    {} {}".format(key, value))
        print("Done.")
    finally:
        # Force-remove by name so a failed run cannot leave a container holding a published port
        # and a live key.
        run_docker(["rm", "-f", "-v", CONTAINER_NAME])


if __name__ == "__main__":
    main()
