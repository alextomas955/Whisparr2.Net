# Whisparr2.Net

A C# SDK for Whisparr 2, generated from Whisparr 2's own OpenAPI document.

## Status

The client is generated from the pinned specification into `src/Whisparr2.Net/`, and it builds on
both target frameworks. A small hand-written layer in `src/hand-written/` supplies the registration
call, the credential shape and the response classification the generated code leaves out. The unit
suite in `test/Whisparr2.Net.UnitTests/` runs without Docker. The client has not yet been proven
against a running instance, and that is the work that follows.

## The naming trap

Whisparr 2 serves its API under `/api/v3`. The string `v3` throughout this repository refers to the
API version and not to the application version.

## Re-verifying the pin

See `docs/REGENERATION.md`. That document arrives with the regeneration work later in this phase.
