// Hand-written test support. See .claude/CLAUDE.md, section "Generated code rules".

#nullable enable

using System.Globalization;
using System.Net.Http;
using System.Text.Json;
using System.Xml.Linq;
using DotNet.Testcontainers.Builders;
using DotNet.Testcontainers.Configurations;
using DotNet.Testcontainers.Containers;
using DotNet.Testcontainers.Images;

namespace Whisparr2.Net.IntegrationTests
{
    /// <summary>
    /// Boots one pinned Whisparr container for the whole collection and publishes the values a
    /// test needs to reach it.
    /// </summary>
    /// <remarks>
    /// <para>
    /// One failure path is deliberately kept out of the throwing path: an unreachable Docker
    /// daemon. When Docker is unreachable this fixture records a skip reason and returns, and every
    /// test in the collection starts by skipping on that reason. Throwing there would fail rather
    /// than skip, because an xunit 2.x collection fixture that throws during InitializeAsync
    /// reports every test in the collection as failed, and Build() is exactly where Testcontainers
    /// throws.
    /// </para>
    /// <para>
    /// This machine runs a real Whisparr 2 library on the same image this repository pins, so every
    /// identity signal the repository owns passes against it. The only thing that keeps this suite
    /// off it is that the base URL is read back from the container this run started. Nothing here
    /// names a host port or a host name, nothing lists containers, and nothing probes a port.
    /// </para>
    /// </remarks>
    public sealed class WhisparrFixture : IAsyncLifetime
    {
        /// <summary>
        /// The port Whisparr listens on inside the container. The host port is never named here.
        /// </summary>
        public const ushort ContainerPort = 6969;

        /// <summary>
        /// The path the seed lands at. The application reads the key from this file at startup and
        /// rewrites the file, which is why it must be writable by uid 1000.
        /// </summary>
        private const string SeedPath = "/config/config.xml";

        /// <summary>
        /// The prefix of the line written when the application first tries to reach the outside
        /// world, which is the last thing it does after the startup handlers that seed the
        /// database have returned.
        /// </summary>
        /// <remarks>
        /// Matched on the prefix, never on the whole line. The tail reads "IPv4 is available: True"
        /// on a networked boot and "IPv4 is available: False, IPv6 will be left enabled" on a boot
        /// with no route, and both are ready states. Both HTTP readiness signals are measurably too
        /// early: at the first unauthenticated 200 the instance reported 0 quality profiles on two
        /// of three boots, and at the first authenticated 200 it reported 4 against a settled 7 on
        /// one of three. At this line it reported 7 and 23 every time.
        /// </remarks>
        private const string ReadyLogMarker = "ManagedHttpDispatcher: IPv4 is available";

        /// <summary>
        /// The exception the application logs when it cannot rewrite its own configuration file.
        /// </summary>
        /// <remarks>
        /// The library's default resource mode is 0644 owned by root and the application runs as
        /// uid 1000, so at the default the process throws this on every restart and the supervisor
        /// loops. The wait strategy then times out with a message naming no cause, which is why the
        /// grep for this marker lives in the catch around the start call rather than in an
        /// assertion. generator/verify_image.py greps its container log for the same string.
        /// </remarks>
        private const string AccessDeniedMarker = "UnauthorizedAccessException";

        /// <summary>
        /// How many log lines a diagnostic prints after the line it is about.
        /// </summary>
        /// <remarks>
        /// One bound, used by both branches of <see cref="LogWindow"/>, so the two cannot disagree
        /// about how much of the log a reader is shown.
        /// </remarks>
        private const int LogWindowLines = 20;

        /// <summary>
        /// The reaper image, by digest.
        /// </summary>
        /// <remarks>
        /// Testcontainers 4.14.0 already pins this digest as its own default. Restating it here is
        /// what makes a version bump that moves the reaper a visible diff in this repository rather
        /// than a silent pull of a different image. Bumping Testcontainers therefore has a second
        /// step: reflect ResourceReaper.RyukImage on the new assembly and move this constant to
        /// match. A stale pin shows as a hang or a timeout at container start, not as a version
        /// error. The reaper stays enabled because it is the only layer that removes the container
        /// when the test host is killed, and it is the reason a loopback assertion is scoped to one
        /// container id: the reaper itself publishes on the wildcard address. It also runs
        /// privileged with the Docker socket mounted, which is the price of cleanup that survives a
        /// killed test host.
        /// </remarks>
        private const string ReaperImage =
            "testcontainers/ryuk@sha256:7c1a8a9a47c780ed0f983770a662f80deb115d95cce3e2daa3d12115b8cd28f0";

        /// <summary>
        /// Set to "1" to make the probe report Docker as absent on a machine that has it. The
        /// default is to run, and the variable exists only so the skip branch can be observed here.
        /// </summary>
        private const string ForceNoDockerVariable = "WHISPARR2NET_FORCE_NO_DOCKER";

        /// <summary>
        /// Set to "1" to declare that this run must produce live evidence. A run that declares it
        /// and then finds no reachable daemon fails instead of reporting a green skip.
        /// </summary>
        private const string RequireDockerVariable = "WHISPARR2NET_REQUIRE_DOCKER";

        /// <summary>
        /// The wait budget for the one wait strategy.
        /// </summary>
        /// <remarks>
        /// One strategy, so this is the whole budget rather than half of it. It is sixty times the
        /// measured boot of about two seconds, and it absorbs a cold pull on a slower runner. The
        /// only cost of a generous value is how long a genuine failure takes to report.
        /// </remarks>
        private static readonly TimeSpan ReadinessTimeout = TimeSpan.FromSeconds(120);

        private IContainer? _container;

        /// <summary>Why the collection's tests should skip, or null when the container is up.</summary>
        public string? SkipReason { get; private set; }

        /// <summary>The base URL of the container this run started, host and port read back from it.</summary>
        public string BaseUrl { get; private set; } = string.Empty;

        /// <summary>The Docker id of the container this run started.</summary>
        public string ContainerId { get; private set; } = string.Empty;

        /// <summary>The key parsed out of the one committed seed the container was started with.</summary>
        public string ApiKey { get; private set; } = string.Empty;

        /// <summary>The version string spec/PROVENANCE.json records for the pinned digest.</summary>
        public string ExpectedVersion { get; private set; } = string.Empty;

        /// <summary>The branch string spec/PROVENANCE.json records for the pinned digest.</summary>
        public string ExpectedBranch { get; private set; } = string.Empty;

        /// <summary>
        /// The whole second, in UTC, in which this run began its boot.
        /// </summary>
        /// <remarks>
        /// Truncated to the second because that is the resolution the instance reports startTime
        /// at. An application that starts at 16:36:56.95 reports 16:36:56Z, which an untruncated
        /// comparison reads as 0.8 seconds before the boot began.
        /// </remarks>
        public DateTimeOffset BootBeganAt { get; private set; }

        /// <summary>
        /// Whether a container can be started at all.
        /// </summary>
        /// <remarks>
        /// The second clause is the same value Testcontainers itself guards on before it throws, so
        /// the probe and the library cannot disagree, and reading it costs no process launch.
        /// </remarks>
        public static bool DockerIsAvailable =>
            !string.Equals(
                Environment.GetEnvironmentVariable(ForceNoDockerVariable),
                "1",
                StringComparison.Ordinal)
            && TestcontainersSettings.OS.DockerEndpointAuthConfig is not null;

        /// <summary>Whether this run declared that it requires a live container.</summary>
        public static bool DockerIsRequired =>
            string.Equals(
                Environment.GetEnvironmentVariable(RequireDockerVariable),
                "1",
                StringComparison.Ordinal);

        /// <summary>
        /// Starts the container, or records why it could not be started.
        /// </summary>
        /// <exception cref="InvalidOperationException">
        /// The run declared that it requires a live container and none is reachable, an embedded
        /// resource is missing, the provenance document is missing a key or carries a blank value,
        /// or the container did not become ready.
        /// </exception>
        public async Task InitializeAsync()
        {
            if (!DockerIsAvailable)
            {
                if (DockerIsRequired)
                {
                    // Deliberately a throw. A collection fixture that throws during initialization
                    // fails every test in the collection, which is what turns an evidence-free run
                    // into an error rather than a green skip.
                    throw new InvalidOperationException(
                        RequireDockerVariable + " is set, so this run declared that it requires a "
                            + "live Whisparr container, and no Docker daemon is reachable from this "
                            + "process. Nothing was started and nothing was proven.");
                }

                SkipReason = "Docker is not reachable from this process, so no Whisparr container was started.";
                return;
            }

            byte[] seed = ReadSeedBytes();
            ApiKey = ReadSeedApiKey(seed);

            using (JsonDocument provenance = ReadProvenance())
            {
                ExpectedVersion = RequiredString(provenance, "whisparrVersion");
                ExpectedBranch = RequiredString(provenance, "whisparrBranch");

                TestcontainersSettings.ResourceReaperImage = new DockerImage(ReaperImage);

                _container = new ContainerBuilder(RequiredString(provenance, "imageDigest"))
                    .WithPortBinding(ContainerPort, true)
                    .WithCreateParameterModifier(parameters =>
                    {
                        // WithPortBinding on its own publishes on the wildcard address, which puts
                        // the seeded key on every interface for as long as the container lives. The
                        // null check is not defensive noise: without it the build fails CS8602
                        // under this repository's nullable setting plus warnings as errors.
                        var bindings = parameters.HostConfig?.PortBindings;
                        if (bindings is null)
                        {
                            return;
                        }

                        foreach (var published in bindings.Values)
                        {
                            foreach (var binding in published)
                            {
                                binding.HostIP = "127.0.0.1";
                            }
                        }
                    })
                    // The mode is passed explicitly and the two zeroes in front of it are not
                    // decoration. The library default is 0644 owned by root, which this image
                    // cannot boot from, and the three-argument form binds the mode enum to the uid
                    // parameter and fails to compile with CS1503.
                    .WithResourceMapping(
                        seed,
                        SeedPath,
                        0U,
                        0U,
                        UnixFileModes.UserRead | UnixFileModes.UserWrite
                            | UnixFileModes.GroupRead | UnixFileModes.GroupWrite
                            | UnixFileModes.OtherRead | UnixFileModes.OtherWrite)
                    // One signal. Both HTTP signals answer before the database is seeded, so a
                    // fixture that returned on either would hand the suite a half-seeded instance.
                    .WithWaitStrategy(Wait.ForUnixContainer()
                        .UntilMessageIsLogged(
                            ReadyLogMarker,
                            waitStrategy => waitStrategy.WithTimeout(ReadinessTimeout)))
                    .Build();
            }

            // Stamped after the build and before the start, so nothing between the two can put the
            // recorded second after the second the application records.
            BootBeganAt = TruncateToSecond(DateTimeOffset.UtcNow);

            try
            {
                await _container.StartAsync().ConfigureAwait(false);
            }
            catch (Exception start)
            {
                // At the wrong file mode the wait strategy times out before any assertion runs and
                // the exception names no cause, so the log is read here rather than in a test.
                string log = await ReadContainerLogAsync().ConfigureAwait(false);

                if (log.Contains(AccessDeniedMarker, StringComparison.Ordinal))
                {
                    throw new InvalidOperationException(
                        "The container never served: its log carries " + AccessDeniedMarker
                            + ", so the seed did not land at mode 0666 and the application could "
                            + "not rewrite " + SeedPath + ". Check the mode argument on "
                            + "WithResourceMapping." + Environment.NewLine + LogWindow(log, AccessDeniedMarker),
                        start);
                }

                throw new InvalidOperationException(
                    "The container did not become ready within "
                        + ReadinessTimeout.TotalSeconds.ToString("0", CultureInfo.InvariantCulture)
                        + " seconds, and its log carries no access-denied marker."
                        + Environment.NewLine + LogWindow(log, AccessDeniedMarker),
                    start);
            }

            // Read the host port back rather than assume one. This machine already runs a Whisparr
            // instance on the same image, and a port written into source is the one mistake that
            // would reach it.
            BaseUrl = "http://" + _container.Hostname + ":"
                + _container.GetMappedPublicPort(ContainerPort).ToString(CultureInfo.InvariantCulture);
            ContainerId = _container.Id;

            await RefuseAnInstanceThisRunDidNotStart().ConfigureAwait(false);
        }

        /// <summary>Refuses before any test runs if the reachable instance predates this boot.</summary>
        /// <remarks>
        /// This machine runs a personal Whisparr library on the same image digest this fixture
        /// pins, so it satisfies every other identity signal: same branch, same major version,
        /// same image. Start time is the one signal it cannot satisfy, because a long-running
        /// instance reports a value days old.
        ///
        /// The check lives here rather than only in a test because xunit does not contract class
        /// order within a collection. A test that writes could otherwise run before the test that
        /// checks, and a write against a real library has no undo. Running it in initialization
        /// covers every test in the collection whatever order they take.
        ///
        /// A raw read rather than the typed client, so the guard does not depend on the layer the
        /// suite exists to exercise.
        /// </remarks>
        private async Task RefuseAnInstanceThisRunDidNotStart()
        {
            using HttpClient probe = new() { BaseAddress = new Uri(BaseUrl) };
            probe.DefaultRequestHeaders.Add("X-Api-Key", ApiKey);

            using HttpResponseMessage response =
                await probe.GetAsync("api/v3/system/status").ConfigureAwait(false);
            response.EnsureSuccessStatusCode();

            string body = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
            string? reported = JsonDocument.Parse(body).RootElement
                .GetProperty("startTime").GetString();

            if (reported is null)
            {
                throw new InvalidOperationException(
                    "The instance reported no start time, so this fixture cannot prove it reached "
                        + "the container this run started. Nothing was proven.");
            }

            DateTimeOffset startedAt = DateTimeOffset.Parse(
                reported, CultureInfo.InvariantCulture, DateTimeStyles.AdjustToUniversal);

            string? refusal = StaleStartTimeRefusal(startedAt, BootBeganAt);
            if (refusal is not null)
            {
                throw new InvalidOperationException(refusal);
            }
        }

        /// <summary>Destroys the container, if one was started.</summary>
        public async Task DisposeAsync()
        {
            if (_container is not null)
            {
                await _container.DisposeAsync().ConfigureAwait(false);
            }
        }

        /// <summary>Truncates a timestamp to the whole second, which is startTime's own resolution.</summary>
        /// <param name="value">The timestamp to truncate.</param>
        /// <returns>The same instant with every sub-second tick removed.</returns>
        public static DateTimeOffset TruncateToSecond(DateTimeOffset value) =>
            new(value.Ticks - (value.Ticks % TimeSpan.TicksPerSecond), value.Offset);

        /// <summary>
        /// Says whether a reported start time is too old to belong to the container this run
        /// started.
        /// </summary>
        /// <param name="reportedStartTime">The start time the instance reports about itself.</param>
        /// <param name="bootBeganAt">The whole second in which this run began its boot.</param>
        /// <returns>Null when the instance started no earlier than the run did, and a sentence
        /// naming both stamps when it started before.</returns>
        /// <remarks>
        /// A separate method rather than an inline comparison, so a test can drive the refusing
        /// branch over a synthetic stamp. A comparison that lives inside an assertion can only ever
        /// be observed passing, and this is the one identity signal in this repository that a
        /// long-running instance on the pinned image cannot pass.
        /// </remarks>
        public static string? StaleStartTimeRefusal(
            DateTimeOffset reportedStartTime,
            DateTimeOffset bootBeganAt)
        {
            // Not greater than. startTime has whole-second resolution and the recorded stamp is
            // truncated to the same resolution, so a boot that lands inside the stamped second
            // reports a value equal to it. A strict comparison would refuse that correct run, and
            // would do so only sometimes.
            if (reportedStartTime >= bootBeganAt)
            {
                return null;
            }

            return "The instance reports a start time of "
                + reportedStartTime.ToString("o", CultureInfo.InvariantCulture)
                + ", which is before this run began its boot at "
                + bootBeganAt.ToString("o", CultureInfo.InvariantCulture)
                + ". The suite is reading an instance it did not start.";
        }

        /// <summary>Reads both container log streams, or says why it could not.</summary>
        private async Task<string> ReadContainerLogAsync()
        {
            if (_container is null)
            {
                return string.Empty;
            }

            try
            {
                (string stdout, string stderr) = await _container.GetLogsAsync().ConfigureAwait(false);
                return stdout + stderr;
            }
            catch (Exception read)
            {
                // A failure to read the log must not replace the start failure being reported.
                return "The container log could not be read: " + read.Message;
            }
        }

        /// <summary>
        /// Returns the part of a log a reader needs, which is the failure and what followed it.
        /// </summary>
        /// <param name="log">Both log streams, concatenated.</param>
        /// <param name="marker">The text the failing line carries.</param>
        /// <returns>The matched line and at most the next twenty, or the last twenty lines when
        /// nothing matched.</returns>
        /// <remarks>
        /// The plain tail of this concatenation is the tail of stderr, which on this image is
        /// supervisor chatter, so a diagnostic built from it shows everything except the cause.
        /// </remarks>
        private static string LogWindow(string log, string marker)
        {
            string[] lines = log.Split('\n');
            int matched = Array.FindIndex(lines, line => line.Contains(marker, StringComparison.Ordinal));

            if (matched < 0)
            {
                return string.Join("\n", lines.Skip(Math.Max(0, lines.Length - LogWindowLines)));
            }

            return string.Join("\n", lines.Skip(matched).Take(LogWindowLines + 1));
        }

        /// <summary>
        /// Reads the embedded copy of generator/config.seed.xml as bytes.
        /// </summary>
        /// <returns>The seed exactly as it is committed.</returns>
        /// <exception cref="InvalidOperationException">The resource is missing from the assembly.</exception>
        /// <remarks>
        /// Bytes, never text. A round trip through the platform decoder can add or drop a byte
        /// order mark in a file the application parses as XML at startup.
        /// </remarks>
        private static byte[] ReadSeedBytes()
        {
            using Stream? stream = typeof(WhisparrFixture).Assembly
                .GetManifestResourceStream("config.seed.xml");

            if (stream is null)
            {
                throw new InvalidOperationException(
                    "The config.seed.xml resource is not embedded in this assembly. Check the "
                        + "EmbeddedResource item and its LogicalName in the project file.");
            }

            using MemoryStream buffer = new();
            stream.CopyTo(buffer);
            return buffer.ToArray();
        }

        /// <summary>
        /// Reads the key out of the same bytes that are copied into the container.
        /// </summary>
        /// <param name="seed">The seed bytes.</param>
        /// <returns>The key, never null and never blank.</returns>
        /// <exception cref="InvalidOperationException">The seed declares no ApiKey element.</exception>
        /// <remarks>
        /// Parsed from the seed rather than restated, so the fixture cannot hold a key the
        /// container was never given. generator/verify_image.py reads the same element out of the
        /// same file.
        /// </remarks>
        private static string ReadSeedApiKey(byte[] seed)
        {
            using MemoryStream stream = new(seed, writable: false);
            string? key = XDocument.Load(stream).Root?.Element("ApiKey")?.Value;

            if (string.IsNullOrWhiteSpace(key))
            {
                throw new InvalidOperationException(
                    "generator/config.seed.xml declares no ApiKey element, so the fixture has no "
                        + "key to authenticate the container it started.");
            }

            return key;
        }

        /// <summary>
        /// Reads the embedded copy of spec/PROVENANCE.json.
        /// </summary>
        /// <returns>The parsed document, which the caller owns and disposes.</returns>
        /// <exception cref="InvalidOperationException">The resource is missing from the assembly.</exception>
        private static JsonDocument ReadProvenance()
        {
            using Stream? stream = typeof(WhisparrFixture).Assembly
                .GetManifestResourceStream("PROVENANCE.json");

            if (stream is null)
            {
                throw new InvalidOperationException(
                    "The PROVENANCE.json resource is not embedded in this assembly. Check the "
                        + "EmbeddedResource item and its LogicalName in the project file.");
            }

            return JsonDocument.Parse(stream);
        }

        /// <summary>
        /// Reads one required string out of the provenance document.
        /// </summary>
        /// <param name="provenance">The parsed document.</param>
        /// <param name="name">The key to read.</param>
        /// <returns>The value, never null and never blank.</returns>
        /// <exception cref="InvalidOperationException">The key is absent, or its value is blank.</exception>
        private static string RequiredString(JsonDocument provenance, string name)
        {
            if (!provenance.RootElement.TryGetProperty(name, out JsonElement value))
            {
                throw new InvalidOperationException(
                    "spec/PROVENANCE.json carries no '" + name + "' key. The fixture reads all "
                        + "three of its container constants from that file and duplicates none of them.");
            }

            string? text = value.GetString();

            if (string.IsNullOrWhiteSpace(text))
            {
                throw new InvalidOperationException(
                    "spec/PROVENANCE.json has an empty '" + name + "' key.");
            }

            return text;
        }
    }

    /// <summary>
    /// The collection every test that needs a live Whisparr belongs to. One container serves them
    /// all, once per target framework.
    /// </summary>
    [CollectionDefinition(Name)]
    public sealed class WhisparrCollection : ICollectionFixture<WhisparrFixture>
    {
        /// <summary>
        /// The collection name, held as a constant so every Collection attribute binds to this
        /// declaration rather than to a repeated string literal.
        /// </summary>
        public const string Name = "whisparr";
    }
}
