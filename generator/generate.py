#!/usr/bin/env python3
"""Regenerate the Whisparr2.Net client tree from the committed spec, using the pinned generator.

Stages the two inputs into a temporary root, runs the pinned generator image against it, gates the
staged tree, then deletes the five generated subdirectories and copies the new ones back. The
generator never prunes, so the delete is the pruner.

Generation never bind-mounts the repository. It stages the two inputs under the system temp
directory and mounts that instead, for two reasons. The generator writes into the root it is given
and never prunes, so a run against the repository in place would mix its output into the working
tree before any check had seen it. A repository on a mapped or network drive may also not be
bind-mountable at all, and Docker reports that as an empty mount and exit 0 rather than as an
error. gen-config.yaml needs no edit either way, because its /local-rooted paths resolve against
the staging root.

That second reason is not hypothetical here. This repository sits on I:, a mapped drive, and a bind
mount of an I: path into this image lists as empty with exit 0, while a write into that mount
succeeds inside the container and never reaches the host. That is silent data loss.

There is no output-root parameter on purpose. The destination is the whole repository tree, and a
redirect without a promote guard is the fail-open shape this pipeline is hardened against.

--check runs the same generation and compares the result against the committed tree, writing
nothing anywhere. That is not the shape the paragraph above rejects, because it has no output root
and no promote step at all. generator/fetch_spec.py --propose already follows the same rule.

    python generator/generate.py
    python generator/generate.py --check
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from _common import REPO_ROOT, die, write_json_lf

# openapi-generator-cli 7.25.0, the pin recorded at the top of generator/gen-config.yaml. By digest
# and never by tag, so a retagged image cannot change this library's public surface.
DEFAULT_IMAGE_DIGEST = "sha256:2ab0a9680222de65dc9d3baf861aa02b99e1b80c211d8221ebf3ae8f8a102524"
# The generated tree is these five subdirectories, not src/Whisparr2.Net itself: the hand-owned
# csproj sits beside them and survives every run. One list, so the delete set and the copy set cannot
# drift apart.
GENERATED_SUBDIRS = ("Api", "Client", "Extensions", "Logging", "Model")
# The generator emits one extra file into Api/ that belongs to no tag: the shared IApi marker.
# Measured: Api/ holds 68 files for 67 tags.
UNTAGGED_API_FILES = frozenset({"IApi.cs"})
HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
# The three files the generator writes outside the five subdirectories. They are members of the
# generated tree and .openapi-generator/FILES does not list them, because it is one of them.
GENERATED_META_MEMBERS = (
    ".openapi-generator/FILES",
    ".openapi-generator/VERSION",
    ".openapi-generator-ignore",
)
# The generated implementation of one operation, as generichost writes it. The interface
# declaration above it carries no "public async", and the OrDefault twin is excluded by the
# stem it leaves behind. Measured over both repositories' trees on 2026-09-06: 454 matches
# here for 227 operations, 544 in the sibling for 272, exactly two per operation in both.
API_METHOD = re.compile(r"^\s*public async Task<[^>]*>\s+([A-Za-z0-9_]+)Async\(", re.M)


def expected_from_spec(spec_path):
    """The Model/ and Api/ file names and the method stems the committed spec implies.

    Derived, never pinned. The count of operations Whisparr declares moves between releases and
    this repository has no business asserting a particular one. What it can assert is the mapping,
    which is exact in both directions: one Model/<Schema>.cs per schema in components.schemas, one
    Api/<Tag>Api.cs per tag any operation carries, and one <OperationId>Async method per operation.
    A generation that stops early fails this because names are missing, which is the failure the
    old pinned count existed to catch.
    """
    with open(spec_path, "r", encoding="utf-8") as handle:
        spec = json.load(handle)

    models = {name + ".cs" for name in spec.get("components", {}).get("schemas", {})}
    tags = set()
    methods = set()
    for item in spec["paths"].values():
        for method, operation in item.items():
            if method in HTTP_METHODS:
                tags.update(operation.get("tags") or [])
                # Read without a default on purpose. Every operation in the patched document carries
                # an operationId because generator/preprocess_spec.py refuses otherwise, so a
                # KeyError here means the staged input is not the document this pipeline produces.
                methods.add(operation["operationId"])
    files = {"Model": models, "Api": {tag + "Api.cs" for tag in tags} | set(UNTAGGED_API_FILES)}
    return files, methods


def generated_cs_files(package_root):
    """Count over the five generated subdirectories, never recursively over the package root: after
    any build obj/<config>/<tfm>/Whisparr2.Net.AssemblyInfo.cs sits under it and would be counted.
    Measured: two stray .cs per configuration, one per target framework.
    """
    found = []
    for subdir in GENERATED_SUBDIRS:
        for dirpath, _, filenames in os.walk(os.path.join(package_root, subdir)):
            found.extend(os.path.join(dirpath, f) for f in filenames if f.endswith(".cs"))
    return found


def api_method_names(package_root):
    """The stems of the generated async methods, one per operation, OrDefault twins excluded."""
    found = set()
    api_dir = os.path.join(package_root, "Api")
    for name in sorted(os.listdir(api_dir)):
        if not name.endswith(".cs"):
            continue
        with open(os.path.join(api_dir, name), "r", encoding="utf-8") as handle:
            for match in API_METHOD.finditer(handle.read()):
                found.add(match.group(1))
    return {stem for stem in found if not stem.endswith("OrDefault")}


def tree_members(root):
    """Every file generate.py owns under root, as (relative posix path, absolute path), sorted.

    One function for three callers, so the digest, the --check diff and the pre-flight can never
    disagree about what the generated tree is. It walks the five subdirectories and never the
    package root: after a build, src/Whisparr2.Net/obj holds two more .cs files per configuration
    and src/Whisparr2.Net/bin holds the assemblies, and neither is generator output.

    Relative paths carry forward slashes so the value does not depend on the operating system.
    """
    package_root = os.path.join(root, "src", "Whisparr2.Net")
    found = []
    for subdir in GENERATED_SUBDIRS:
        for dirpath, _, filenames in os.walk(os.path.join(package_root, subdir)):
            for name in filenames:
                full = os.path.join(dirpath, name)
                found.append((os.path.relpath(full, root).replace(os.sep, "/"), full))
    for dirpath, _, filenames in os.walk(os.path.join(root, ".openapi-generator")):
        for name in filenames:
            full = os.path.join(dirpath, name)
            found.append((os.path.relpath(full, root).replace(os.sep, "/"), full))
    ignore = os.path.join(root, ".openapi-generator-ignore")
    if os.path.isfile(ignore):
        found.append((".openapi-generator-ignore", ignore))
    return sorted(found)


def tree_sha256(root):
    """One digest over the sorted relative path list and the file bytes.

    A rename moves it because the path is hashed, an addition and a deletion move it because the
    member list changes, and an edit moves it because the bytes are hashed. The byte length is
    hashed between the path and the content so no combination of a path and a body can be
    reinterpreted as a different pair.

    Files are opened in binary so the value cannot depend on a text-mode line-ending translation.
    This function never writes a file.
    """
    digest = hashlib.sha256()
    for relative, full in tree_members(root):
        with open(full, "rb") as handle:
            body = handle.read()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(body)).encode("ascii"))
        digest.update(b"\0")
        digest.update(body)
    return digest.hexdigest()


def read_provenance():
    """The committed provenance record, as a dict."""
    with open(os.path.join(REPO_ROOT, "spec", "PROVENANCE.json"), "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_tree_digest(digest):
    """Record generatedTreeSha256. This function and nothing else writes that field.

    Re-assigning an existing key keeps its position, so a re-run does not reorder the record, and
    write_json_lf keeps it 2-space indented and LF-terminated like the rest of the pipeline.

    Nothing here ever pops the field, which is the one asymmetry against generator/fetch_spec.py.
    That script pops generatedSpecSha256 because a new capture makes the patched document stale. A
    moved pin does not change the bytes of the committed tree, so the recorded digest still
    describes it truthfully.
    """
    provenance_path = os.path.join(REPO_ROOT, "spec", "PROVENANCE.json")
    provenance = read_provenance()
    provenance["generatedTreeSha256"] = digest
    write_json_lf(provenance_path, provenance)


def verify_committed_tree(pkg_dir):
    """Refuse to delete a tree that no longer matches the digest generate.py last recorded.

    The failure this catches is a hand edit under the generated tree. The sibling has no answer to
    it: it sets tree_touched and deletes, so the edit is absorbed with nothing said. This is the
    half of the answer that needs neither Docker nor git, so it runs on every generation.
    """
    recorded = read_provenance().get("generatedTreeSha256")
    present = all(os.path.isdir(os.path.join(pkg_dir, subdir)) for subdir in GENERATED_SUBDIRS)
    if not recorded or not present:
        print("  - no generatedTreeSha256 recorded yet, establishing it")
        return

    on_disk = tree_sha256(REPO_ROOT)
    if on_disk == recorded:
        print("  + the committed tree matches generatedTreeSha256")
        return

    # An added or a deleted file is named exactly, because .openapi-generator/FILES is a committed
    # manifest of the same member set and the comparison is free. A content edit is not localisable
    # from one hash, so the message hands the reader the command that does localise it.
    problems = []
    manifest_path = os.path.join(REPO_ROOT, ".openapi-generator", "FILES")
    if os.path.isfile(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as handle:
            listed = {line.strip() for line in handle if line.strip()}
        listed.update(GENERATED_META_MEMBERS)
        have = {relative for relative, _ in tree_members(REPO_ROOT)}
        for name in sorted(have - listed):
            problems.append("    {} is on disk and is not in .openapi-generator/FILES".format(name))
        for name in sorted(listed - have):
            problems.append("    {} is in .openapi-generator/FILES and is not on disk".format(name))
    die(
        "ERROR: REFUSED - the committed tree does not match generatedTreeSha256 in "
        "spec/PROVENANCE.json. Nothing in {} was touched.".format(pkg_dir),
        "    recorded   " + recorded,
        "    on disk    " + on_disk,
        *problems[:20],
        "  A file under the generated tree was changed by hand. Recover the committed bytes with",
        "  git checkout -- src/Whisparr2.Net .openapi-generator .openapi-generator-ignore, or name",
        "  the changed files with python generator/generate.py --check. A single digest cannot",
        "  localise a content edit and --check can, which is why the lines above name only the",
        "  files that were added or deleted."
    )


def gate_staged_tree(stage, stage_pkg_dir, pkg_dir):
    """Everything that must hold about a staged tree before a committed one is deleted.

    A function rather than a block inside main, because --check and the normal mode run the
    identical gate and that claim has to be checkable by reading. Returns the staged .cs list.
    """
    staged_cs = generated_cs_files(stage_pkg_dir)
    # A subdirectory the generator did not emit at all is invisible to the count, because
    # generated_cs_files walks a missing one as empty. The copy back would then fail partway
    # through, after the delete, which is the expensive place to find out.
    missing = [d for d in GENERATED_SUBDIRS if not os.path.isdir(os.path.join(stage_pkg_dir, d))]
    if missing:
        die(
            "ERROR: REFUSED - the staged tree is missing {} of the five generated "
            "subdirectories: {}. Nothing in {} was touched.".format(
                len(missing), ", ".join(missing), pkg_dir)
        )
    # The three meta paths the copy back reaches for. Checked here rather than trusted, so a
    # configuration change that stopped emitting one refuses before the delete instead of raising
    # after it.
    absent = [m for m in GENERATED_META_MEMBERS if not os.path.isfile(os.path.join(stage, *m.split("/")))]
    if absent:
        die(
            "ERROR: REFUSED - the staged tree is missing {}. Nothing in {} was touched.".format(
                ", ".join(absent), pkg_dir)
        )
    # Name-for-name against the spec, not a count against a literal. Whisparr moves its
    # operation count between releases and this repository asserts no particular one.
    expected_files, expected_methods = expected_from_spec(
        os.path.join(stage, "spec", "openapi.generated.json"))
    problems = []
    for subdir, want in expected_files.items():
        have = {f for f in os.listdir(os.path.join(stage_pkg_dir, subdir)) if f.endswith(".cs")}
        for name in sorted(want - have):
            problems.append("    {}/{} is implied by the spec and was not generated".format(subdir, name))
        for name in sorted(have - want):
            problems.append("    {}/{} was generated and the spec implies no such file".format(subdir, name))
    if problems:
        die(
            "ERROR: REFUSED - the staged tree does not match the spec it was generated from, "
            "in {} file(s). Nothing in {} was touched.".format(len(problems), pkg_dir),
            *problems[:20]
        )
    staged_methods = api_method_names(stage_pkg_dir)
    renames = []
    for name in sorted(expected_methods - staged_methods):
        renames.append("    {} is declared by the spec and no Api/*.cs implements {}Async".format(
            name, name))
    for name in sorted(staged_methods - expected_methods):
        renames.append("    {} is implemented as {}Async and the spec declares no such "
                       "operationId".format(name, name))
    if renames:
        die(
            "ERROR: REFUSED - the staged tree does not carry the method names the spec declares, "
            "in {} case(s). Nothing in {} was touched.".format(len(renames), pkg_dir),
            *renames[:20],
            "  The generator renamed an operationId instead of emitting it. Repair the name in",
            "  generator/preprocess_spec.py, with an OPERATION_ID_OVERRIDES entry or a stronger",
            "  shape assertion. Never by editing a file under src/Whisparr2.Net/."
        )
    for subdir in ("Client", "Extensions", "Logging"):
        if not any(f.endswith(".cs") for f in os.listdir(os.path.join(stage_pkg_dir, subdir))):
            die("ERROR: REFUSED - {}/ holds no .cs file. Nothing in {} was touched.".format(
                subdir, pkg_dir))
    print("  + generator exited 0, staged {} .cs files, every Model/ and Api/ name matches "
          "the spec".format(len(staged_cs)))
    print("  + every one of the {} method names the spec declares is implemented".format(
        len(expected_methods)))
    return staged_cs


def main():
    parser = argparse.ArgumentParser(description="Regenerate the Whisparr2.Net client tree.")
    parser.add_argument("--image-digest", default=DEFAULT_IMAGE_DIGEST)
    parser.add_argument(
        "--check", action="store_true",
        help="do not write; exit 1 if the committed tree differs from the render",
    )
    args = parser.parse_args()

    image = "openapitools/openapi-generator-cli@" + args.image_digest
    pkg_dir = os.path.join(REPO_ROOT, "src", "Whisparr2.Net")
    gen_meta_dir = os.path.join(REPO_ROOT, ".openapi-generator")
    stage = tempfile.mkdtemp(prefix="whisparr2-generate-")
    stage_pkg_dir = os.path.join(stage, "src", "Whisparr2.Net")

    print(("Check" if args.check else "Generate") + " Whisparr2.Net client -> " + pkg_dir)
    print("  - image " + image)

    # False until step 3 starts deleting. The handler branches on it, because whether the repository
    # is mid-replace is the one fact a caller needs and a bare traceback does not carry.
    tree_touched = False

    try:
        # --- 1. Stage the two inputs, mirroring the repository layout ---
        # These two files are the entire input, which is why a hand edit to the committed
        # .openapi-generator-ignore is discarded on the next run.
        os.makedirs(os.path.join(stage, "spec"))
        os.makedirs(os.path.join(stage, "generator"))
        shutil.copy2(os.path.join(REPO_ROOT, "spec", "openapi.generated.json"), os.path.join(stage, "spec"))
        shutil.copy2(os.path.join(REPO_ROOT, "generator", "gen-config.yaml"), os.path.join(stage, "generator"))

        # --- 2. Run the pinned image, then gate the staged tree before anything committed is
        # deleted ---
        # The image runs as uid 0. On a Linux runner that makes every directory it creates inside
        # the bind mount root-owned, and the cleanup below then cannot unlink under them. Windows
        # bind mounts carry no POSIX ownership, so the flag is added only where it means something.
        user_args = [] if os.name == "nt" else ["--user", "{}:{}".format(os.getuid(), os.getgid())]
        # encoding is pinned rather than left to text=True, which decodes with the locale
        # codec. On a Windows console that is cp1252, and this image emits bytes it cannot
        # decode: the reader thread dies and the failure branch below then has no output to
        # print.
        run = subprocess.run(
            ["docker", "run", "--rm"] + user_args + ["-v", stage + ":/local", image,
             "generate", "-c", "/local/generator/gen-config.yaml"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if run.returncode != 0:
            print((run.stdout or "") + (run.stderr or ""))
            print("ERROR: REFUSED - the generator exited {} for {}. Nothing in {} was touched.".format(
                run.returncode, image, pkg_dir))
            sys.exit(run.returncode)
        staged_cs = gate_staged_tree(stage, stage_pkg_dir, pkg_dir)

        if not args.check:
            # Everything that writes sits in this one block. The pre-flight runs after the gate has
            # approved the staged tree and immediately before the first unlink, which is what makes
            # it a pre-flight rather than a report.
            verify_committed_tree(pkg_dir)

            # --- 3. Replace, never merge ---
            # Copying into an existing target merges: it neither replaces the target nor nests
            # inside it, so without this delete a stale file inside Api/ survives the copy and
            # compiles. Set before the first unlink: from here to the end of step 4 the repository
            # is mid-replace.
            tree_touched = True
            # One subdirectory at a time and never pkg_dir, which holds the hand-owned
            # Whisparr2.Net.csproj beside them.
            for subdir in GENERATED_SUBDIRS:
                shutil.rmtree(os.path.join(pkg_dir, subdir), ignore_errors=True)
            shutil.rmtree(gen_meta_dir, ignore_errors=True)

            # --- 4. Copy back exactly what the generator owns, and nothing else ---
            # Not the whole staged tree, which would drag spec/ and generator/ over the committed
            # originals.
            os.makedirs(pkg_dir, exist_ok=True)
            for subdir in GENERATED_SUBDIRS:
                shutil.copytree(os.path.join(stage_pkg_dir, subdir), os.path.join(pkg_dir, subdir))
            shutil.copytree(os.path.join(stage, ".openapi-generator"), gen_meta_dir)
            shutil.copy2(os.path.join(stage, ".openapi-generator-ignore"), REPO_ROOT)

            copied_cs = generated_cs_files(pkg_dir)
            if len(copied_cs) != len(staged_cs):
                die(
                    "ERROR: copied {} .cs files but staged {}. The tree under {} is now partially "
                    "written. Recovery is to re-run generate.py, which deletes and rewrites the "
                    "whole tree.".format(len(copied_cs), len(staged_cs), pkg_dir)
                )
            print("  + copied {} .cs files into {}".format(len(copied_cs), pkg_dir))

            # --- 5. Record what was written ---
            digest = tree_sha256(REPO_ROOT)
            write_tree_digest(digest)
            print("  + wrote generatedTreeSha256 " + digest)
            print("Done. " + pkg_dir)
        else:
            # --- The check half: compare, report, write nothing ---
            # Both sides come from tree_members, so the relative paths are directly comparable
            # across the two roots. Bytes are read in binary; a text-mode read would make the
            # comparison depend on the platform.
            staged = dict(tree_members(stage))
            committed = dict(tree_members(REPO_ROOT))
            differences = []
            for relative in sorted(set(staged) | set(committed)):
                if relative not in committed:
                    differences.append("    {} is generated and is not committed".format(relative))
                elif relative not in staged:
                    differences.append("    {} is committed and is not generated".format(relative))
                else:
                    with open(staged[relative], "rb") as handle:
                        rendered = handle.read()
                    with open(committed[relative], "rb") as handle:
                        on_disk = handle.read()
                    if rendered != on_disk:
                        differences.append("    {} differs from the generated bytes".format(relative))
            if differences:
                die(
                    "ERROR: REFUSED - the committed tree differs from a fresh generation, in "
                    "{} file(s). Nothing was written.".format(len(differences)),
                    *differences[:20],
                    "  Run: python generator/generate.py"
                )
            print("  + {} files match the committed tree byte for byte. Nothing was written.".format(
                len(staged)))
    except SystemExit:
        raise
    except Exception as error:
        # Without this, a failure between the delete and the count assertion escapes as a raw
        # traceback that says nothing about the repository, by which point the five subdirectories
        # are gone. This is the only script here that deletes a committed deliverable.
        #
        # A --check run that raises always takes the second branch, because tree_touched is set
        # inside the block --check never enters. That is a true statement rather than a convenient
        # one.
        if tree_touched:
            present = generated_cs_files(pkg_dir)
            die(
                "ERROR: generate.py stopped after it had begun replacing the tree: {}".format(error),
                "  {} now holds {} .cs files and the tree is incomplete. Recovery is to re-run "
                "generate.py, or git -C {} checkout -- src/Whisparr2.Net .openapi-generator "
                ".openapi-generator-ignore".format(pkg_dir, len(present), REPO_ROOT),
            )
        die(
            "ERROR: generate.py stopped before it had begun replacing the tree: {}. Nothing in {} "
            "was touched.".format(error, pkg_dir)
        )
    finally:
        # Non-fatal on purpose. An error here would replace the pending exit code and rewrite the
        # verdict of the run above it. A leftover staging root is a nuisance to name, not a reason to
        # call a correct generation a failure.
        shutil.rmtree(stage, ignore_errors=True)
        if os.path.isdir(stage):
            print("  ! could not remove the staging root " + stage + ". Remove it by hand. The verdict above stands.")


if __name__ == "__main__":
    main()
