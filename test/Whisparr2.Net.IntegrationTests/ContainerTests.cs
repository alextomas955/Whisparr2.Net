// Hand-written test code. See .claude/CLAUDE.md, section "Generated code rules".

#nullable enable

using System.Diagnostics;

namespace Whisparr2.Net.IntegrationTests
{
    /// <summary>
    /// Assertions over the container itself, rather than over anything it serves.
    /// </summary>
    /// <remarks>
    /// A source assertion that the fixture calls the binding modifier proves intent, not effect.
    /// Asserting that the base URL starts with the loopback address proves nothing either, because
    /// Testcontainers reports Hostname as the loopback address under a wildcard binding too. The
    /// Docker daemon's own view of the published binding is the only evidence available, so this
    /// test reads it back with docker port.
    /// </remarks>
    [Collection(WhisparrCollection.Name)]
    public sealed class ContainerTests(WhisparrFixture fixture)
    {
        /// <summary>
        /// The address a bare published port binds, and the one this test exists to refuse.
        /// </summary>
        private const string WildcardAddress = "0.0.0.0";

        /// <summary>
        /// The loopback address the binding modifier sets on every published binding.
        /// </summary>
        private const string LoopbackAddress = "127.0.0.1";

        /// <summary>
        /// The published binding names the loopback address and nothing else, so the key the
        /// container was started with is not reachable from another machine.
        /// </summary>
        [SkippableFact]
        public async Task Container_publishes_only_on_loopback()
        {
            Skip.If(fixture.SkipReason is not null, fixture.SkipReason);

            ProcessStartInfo start = new("docker")
            {
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            };

            // Scoped to the container this run started. The reaper publishes on the wildcard
            // address, so an assertion phrased over every binding on this daemon would fail on it
            // and would read containers this suite must never touch.
            start.ArgumentList.Add("port");
            start.ArgumentList.Add(fixture.ContainerId);
            start.ArgumentList.Add($"{WhisparrFixture.ContainerPort}/tcp");

            using Process query = Process.Start(start)
                ?? throw new InvalidOperationException("Could not start the docker client process.");

            // Both reads are started before either is awaited. Draining one pipe to end while the
            // other fills is the shape that deadlocks: the child blocks writing to the full pipe
            // and never closes the one being read. Reversing the two reads is the same defect
            // pointed the other way, so neither is read to end on its own.
            Task<string> outputRead = query.StandardOutput.ReadToEndAsync();
            Task<string> errorRead = query.StandardError.ReadToEndAsync();

            await query.WaitForExitAsync();

            string output = await outputRead;
            string errors = await errorRead;

            Assert.True(
                query.ExitCode == 0,
                $"docker port exited {query.ExitCode}, so the daemon reported no binding to inspect. {errors}");

            // The emptiness case comes first and carries its own message. An empty snapshot
            // trivially satisfies the absence check below, and passing on one is the exact silent
            // pass this test exists to avoid.
            string[] lines = output
                .Split('\n')
                .Select(line => line.Trim())
                .Where(line => line.Length > 0)
                .ToArray();

            Assert.True(
                lines.Length > 0,
                "docker port printed nothing, so no published binding was observed at all.");

            foreach (string line in lines)
            {
                Assert.True(
                    line.Contains(LoopbackAddress + ":", StringComparison.Ordinal),
                    $"A published binding does not name the loopback address: {line}");

                Assert.False(
                    line.Contains(WildcardAddress, StringComparison.Ordinal),
                    $"A published binding names the wildcard address, which puts the container's "
                        + $"key on every interface: {line}");
            }
        }
    }
}
