#!/usr/bin/env python3
"""Assert that a packed Whisparr2.Net package carries what a consumer needs, before it ships.

A NuGet publish cannot be undone. A published version can be unlisted and never deleted, so a
defect in the archive is permanent and the only place to catch one is before the push.

Four claims are asserted, and each is about a fact no source file shows.

The nuspec repository url must name a host a stranger can resolve. The sibling repository shipped a
package whose url read `https://github.com-alex/...`, an SSH account alias that resolves only on
the machine that defined it. SourceLink derives that value from the git origin at pack time, and it
appears nowhere but in the produced nuspec. `Directory.Build.props` sets `RepositoryUrl` by hand
precisely to override that derivation, and this is the assertion that proves the override held.

The nuspec id must be the package id this repository publishes, and its version must match the one
supplied when one is supplied, so a mispacked archive cannot be pushed under the wrong identity.

Both target frameworks must carry a documentation file that parses and declares members. XML
comments are the API reference a consumer reads on hover, and a documentation file can be present,
well formed and empty.

The readme the nuspec names must be in the archive, which is what proves the `None` item in
`Directory.Build.props` that `PackageReadmeFile` requires is still doing its job.

Failures accumulate, so one run names every defect it found rather than stopping at the first. The
refusal wording the generator scripts use, keyed in `docs/REGENERATION.md` to a script declining to
write a file, is deliberately not reused here: this script guards no write and writes nothing, so a
defect is reported with a `FAILED: ` prefix instead.

    python scripts/assert_package.py artifacts/Whisparr2.Net.VERSION.nupkg --expect-version VERSION

VERSION stands for whatever `Directory.Build.props` sets, rather than a release, so this line does
not go stale on the next bump. Both workflows read that value instead of writing it out.
"""

import argparse
import sys
# The only documents parsed here are the nuspec and the two documentation files, produced by the
# same run from this repository's own sources seconds earlier. There is no untrusted input at this
# boundary, so no third-party XML hardening dependency is added to a repository whose scripts are
# standard library only.
import xml.etree.ElementTree as ElementTree
import zipfile

# The values Directory.Build.props sets, repeated here on purpose: a gate that reads its
# expectation out of the thing it checks asserts nothing.
PACKAGE_ID = "Whisparr2.Net"
REPOSITORY_URL = "https://github.com/alextomas955/Whisparr2.Net"
# One entry per target framework in Directory.Build.props. Adding or dropping a target framework
# has to move both together.
DOCUMENTATION_ENTRIES = ("lib/net8.0/Whisparr2.Net.xml", "lib/net10.0/Whisparr2.Net.xml")
# Each documentation file currently declares 7,794 members. A floor against a stub, not an
# equality, so an ordinary change to the library does not trip it.
MIN_MEMBERS = 1000


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("nupkg", help="the packed .nupkg to assert over")
    # Optional deliberately. build-and-test.yml packs on every push with no version to expect, and
    # only the tag-triggered release path knows one.
    parser.add_argument("--expect-version", help="the version the nuspec must declare")
    args = parser.parse_args()

    failures = []

    with zipfile.ZipFile(args.nupkg) as archive:
        names = archive.namelist()
        print("%s, %d entries" % (args.nupkg, len(names)))

        for entry in DOCUMENTATION_ENTRIES:
            if entry not in names:
                print("  %-40s ABSENT" % entry)
                failures.append("%s is not in the package" % entry)
                continue
            members = len(ElementTree.fromstring(archive.read(entry)).findall(".//member"))
            print("  %-40s %d member elements" % (entry, members))
            if members < MIN_MEMBERS:
                failures.append(
                    "%s declares %d members, below the %d floor" % (entry, members, MIN_MEMBERS)
                )

        nuspec_name = next(n for n in names if n.endswith(".nuspec") and "/" not in n)
        nuspec = ElementTree.fromstring(archive.read(nuspec_name))

    identifier = nuspec.findtext(".//{*}id")
    version = nuspec.findtext(".//{*}version")
    print("  %-40s id=%s version=%s" % (nuspec_name, identifier, version))
    if identifier != PACKAGE_ID:
        failures.append("the nuspec id reads %s, expected %s" % (identifier, PACKAGE_ID))
    if args.expect_version is not None and version != args.expect_version:
        failures.append(
            "the nuspec version reads %s, expected %s" % (version, args.expect_version)
        )

    # The repository element's branch attribute is derived from the current branch and moves on a
    # rename, with no correctness meaning, so only the url is asserted.
    repository = nuspec.find(".//{*}repository")
    url = repository.get("url") if repository is not None else None
    print("  %-40s url=%s" % ("repository", url))
    if url != REPOSITORY_URL:
        failures.append("the nuspec repository url reads %s, expected %s" % (url, REPOSITORY_URL))

    readme = nuspec.findtext(".//{*}readme")
    print("  %-40s %s, %s" % ("readme", readme, "in the archive" if readme in names else "ABSENT"))
    if readme is None:
        failures.append("the nuspec declares no readme")
    elif readme not in names:
        failures.append("the nuspec names the readme %s, which is not in the package" % readme)

    if failures:
        for failure in failures:
            print("FAILED: " + failure)
        sys.exit(1)

    # Fixed wording. A silent success is indistinguishable in a run log from a step that never
    # executed, so this line is the evidence in a run log that this gate ran. No workflow step
    # reads it back. A reader checking a run does so by hand.
    print("PASSED: all package assertions held.")


if __name__ == "__main__":
    main()
