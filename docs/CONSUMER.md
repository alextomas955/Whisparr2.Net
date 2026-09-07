# Consuming the package

This document is for a .NET caller who has `Whisparr2.Net` and wants to know what the consumer side
looks like: which files a project needs, how the package is registered, and what it takes to get a
real answer back from a running Whisparr 2.

The consumer path is proven rather than asserted. A throwaway console application was built outside
this repository, restored the packed `.nupkg` from a local folder feed, called a read endpoint
against a Whisparr 2 container the same run created, and was then deleted. Its three files and its
observed output are recorded below so a reader can repeat the run.

## The feed is the pack output

```
dotnet pack src/Whisparr2.Net/Whisparr2.Net.csproj -c Release -o artifacts --nologo
```

That is the whole of the feed setup. The flat `artifacts/` folder is used directly as a NuGet
source. No `nuget add`, no `nuget init` and no `dotnet nuget push` was run at any point. Microsoft's
documentation describes local feeds as hierarchical folder trees and notes that a single flat folder
performs worse; for a feed holding one package that note does not apply, and the flat form means the
pack is the only command a reader has to remember.

## The three files the consumer needed

### `NuGet.config`

```xml
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="local" value="<repo-root>\artifacts" />
    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />
  </packageSources>
</configuration>
```

`<repo-root>` stands for the absolute path of this clone.

Both parts are load-bearing. `<clear />` is needed so the local source is not merged with whatever
the machine's user-level NuGet configuration defines, which would leave the restore depending on one
developer's machine. `nuget.org` must then be added back explicitly, because the package's three
transitive dependencies resolve from there and nothing else in the local folder can supply them.

### The project file

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net10.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Whisparr2.Net" Version="0.2.0" />
  </ItemGroup>
</Project>
```

One target framework, not two. The library cross-targets, and naming a single framework here proves
the package's `net10.0` lib folder rather than this repository's build configuration.

### The program

The consumer holds no address of any kind. It reads `WHISPARR2_URL` and `WHISPARR2_API_KEY` from the
environment and refuses with a non-zero exit if either is absent, so the caller decides which
instance it talks to and the program cannot reach one by accident.

```csharp
using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net;
using Whisparr2.Net.Api;

string? baseUrl = Environment.GetEnvironmentVariable("WHISPARR2_URL");
string? apiKey = Environment.GetEnvironmentVariable("WHISPARR2_API_KEY");

if (string.IsNullOrWhiteSpace(baseUrl) || string.IsNullOrWhiteSpace(apiKey))
{
    Console.Error.WriteLine("REFUSED: set WHISPARR2_URL and WHISPARR2_API_KEY. This program holds no address.");
    return 2;
}

var services = new ServiceCollection();
services.AddWhisparr2(new Whisparr2Options { BaseUrl = baseUrl, ApiKey = apiKey });
var provider = services.BuildServiceProvider();

var api = provider.GetRequiredService<ISystemApi>();
var status = (await api.GetSystemStatusAsync()).EnsureSuccess();

Console.WriteLine("appName: " + status.AppName);
Console.WriteLine("runtimeVersion: " + status.RuntimeVersion);

if (string.IsNullOrWhiteSpace(status.RuntimeVersion))
{
    Console.Error.WriteLine("REFUSED: runtimeVersion came back empty, so this is not live data.");
    return 1;
}

return 0;
```

Three `using` directives, and they are the three the namespace layout predicts: `Whisparr2.Net` for
the options type, the registration call and the success accessor, `Whisparr2.Net.Api` for the typed
client interface, and `Microsoft.Extensions.DependencyInjection` for the collection itself. A bare
`ServiceCollection` is enough. No Generic Host, no application builder and no logging registration
of the consumer's own.

`EnsureSuccess` is the accessor to use rather than the generated `Ok`, `TryOk` or `IsOk` members.
Those three test for exactly 200, and Whisparr answers other success statuses to writes.

## Two traps

**`AddWhisparr2` takes an options instance, not a configuration lambda.** The signature is
`AddWhisparr2(this IServiceCollection services, Whisparr2Options options)`. Passing a lambda gets
`CS1660`, because the parameter is a type and not a delegate. Write
`new Whisparr2Options { BaseUrl = ..., ApiKey = ... }`. Both properties are `required` and `init`
only, so they are set in the initializer and nowhere else.

**A consumer project placed inside this repository inherits the root `Directory.Build.props`.**
MSBuild walks upward from the project directory and stops at the first `Directory.Build.props` it
finds, so a project under this tree picks up the root file, which sets `PackageId`, both target
frameworks, `TreatWarningsAsErrors` and a `README.md` item for everything below it. It would then
need the same overrides the test projects need, and the result would describe this repository's
build configuration rather than the consumer path. The proven consumer was built under the system
temporary directory and carried its own `Directory.Build.props`, empty apart from the root `Project`
element, so it inherits nothing regardless of where the directory sits.

## The observed run

Measured 2026-09-07 against the 0.2.0 pack, on the digest `spec/PROVENANCE.json` pins.

```
dotnet pack src/Whisparr2.Net/Whisparr2.Net.csproj -c Release -o artifacts --nologo
dotnet build consumer.csproj -c Release --nologo
dotnet run -c Release
```

The build restored against the flat folder:

```
Restored ...\whisparr2-consumer\consumer.csproj (in 276 ms).
Build succeeded.
    0 Warning(s)
    0 Error(s)
```

Nothing named Polly appears anywhere in the restored graph or in the build output. That is the
observation behind the dependency removal in 0.2.0: before it, three Polly assemblies landed beside
this program.

The program printed:

```
appName: Whisparr
runtimeVersion: 6.0.36
```

and exited 0.

`runtimeVersion` is asserted on rather than a status code, because a non-empty value can only come
from an instance that answered.

The instance the run addressed was a container created from the pinned digest by the run itself,
seeded with the committed `generator/config.seed.xml`, waited on until its readiness marker appeared
in the log, and force-removed afterwards. Its port was published as ephemeral on the loopback
address and read back from Docker, and the resulting address was handed to the consumer through
`WHISPARR2_URL`. Neither the consumer nor the driver names a host port. That is not decoration: it
is what makes the run repeatable on a machine that is already running a real Whisparr 2 library on
the same image.

`generator/container.py` is the single construction site for that address. A driver that built one
any other way, or started a second container lifecycle of its own, is how a call reaches an instance
the run did not start.

## Why none of this is committed

No consumer project, no `NuGet.config` and no consumer job live in this repository. A committed
consumer would sit under the root `Directory.Build.props` and need overrides to escape it, which
turns the proof into a statement about this repository's build configuration. It would also have to
carry an absolute feed path from one machine. The run and this record are the evidence instead.
