<!-- GSD:project-start source:PROJECT.md -->

## Project

**Whisparr2.Net**

A C# SDK for Whisparr 2, generated from Whisparr 2's own OpenAPI document. It is the sibling of
`Whisparr3.Net`, which covers Whisparr 3 (Eros), and it follows that repository's pipeline: capture
a pinned spec, pre-process it, run openapi-generator, add a small hand-written ergonomic layer, and
prove the result against a real Whisparr 2 instance. It is for .NET callers who need to drive
Whisparr 2 from code, and for the owner, who is building a family of C# SDKs for this ecosystem
alongside `StashDB.Net` and `ThePornDB.Net`.

**Core Value:** A .NET caller can drive a real Whisparr 2 instance through a typed client, and the client is proven
against a real instance rather than against the spec alone.

### Constraints

- **Tech stack**: C#/.NET, openapi-generator, Python generator scripts - copied from
  `Whisparr3.Net` so the two repositories read the same way.
- **Spec source**: the committed `openapi.json` in `Whisparr/Whisparr`, pinned to the `v2` release
  line - Whisparr 2 serves no spec endpoint, so there is nothing to capture from a running instance.
- **The spec is wrong about its own application**: the committed document omits fields the running
  app returns, at the same commit - no pinning strategy fixes this, so live conformance checking is
  a deliverable rather than a drift alarm. See "The spec is stale against its own source" below.
- **Repository independence**: no shared code with the sibling SDKs - each stays self-contained,
  accepting duplicated generator scripts.
- **Docker**: integration tests require it and skip themselves when it is unreachable - a machine
  without Docker still gets a green build.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:STACK.md -->

## Technology Stack

Technology stack not yet documented. Will populate after codebase mapping or first phase.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

## Generated code rules

The generated `src/Whisparr2.Net/Client/ClientUtils.cs` carries
`[assembly: InternalsVisibleTo("Whisparr2.Net.Test")]`, which openapi-generator derives from
`packageName`. That project does not exist and will not be created. Do not rename a test project to
match it, do not add a second `InternalsVisibleTo`, and do not hand-edit the generated file to
remove it. Tests use the public surface.

`src/hand-written/` holds the hand-written client layer, and nothing in it is generator output.
Those files compile into the library through a `Compile` glob in
`src/Whisparr2.Net/Whisparr2.Net.csproj`, even though they sit outside that project's directory. One
of them declares a partial in the generated `Whisparr2.Net.Client` namespace, and it still lives
under `src/hand-written/` because nothing under `src/Whisparr2.Net/` survives a regeneration.

`.gitattributes` applies `linguist-generated` to `src/Whisparr2.Net/**` and to no path under
`src/hand-written/`, so these files are reviewed line by line. `.editorconfig` sets
`generated_code = true` for `src/Whisparr2.Net/**` only, so analyzer coverage stays on for them. Do
not add the generator's file-marker header to a file in that directory. It would be a false
statement, and it would switch off the analyzer coverage those files are meant to keep.

This section sits outside the marker-bracketed regions above and below, which a documentation
regeneration replaces wholesale.

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
