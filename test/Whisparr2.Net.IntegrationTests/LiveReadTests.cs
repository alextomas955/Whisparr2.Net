// Hand-written test code. See .claude/CLAUDE.md, section "Generated code rules".

#nullable enable

using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net.Api;
using Whisparr2.Net.Model;

namespace Whisparr2.Net.IntegrationTests
{
    /// <summary>
    /// One read built by the registration method and classified by the success accessor, against a
    /// real Whisparr over a real socket.
    /// </summary>
    /// <remarks>
    /// This class's subject is the registration path rather than the instance, so it reads two
    /// fields the identity assertions do not, and it is the only place in the repository where a
    /// real server accepts what the hand-written layer builds. The unit suite proves the wire
    /// shape. Only this proves the shape is accepted.
    /// </remarks>
    [Collection(WhisparrCollection.Name)]
    public sealed class LiveReadTests(WhisparrFixture fixture)
    {
        /// <summary>
        /// A client wired by the registration method reads the system status from a real socket and
        /// gets a body back.
        /// </summary>
        /// <remarks>
        /// The response is classified by EnsureSuccess rather than by the generated success
        /// accessor. That accessor deserializes on exactly 200 and returns null on anything else,
        /// so a 401 and an empty collection read the same to a caller, and an assertion built on it
        /// would report a rejected request as an empty result. No retry policy is attached either:
        /// a retry in front of this call would mask the instability this project exists to remove.
        /// </remarks>
        [SkippableFact]
        public async Task Status_reads_through_the_registered_client()
        {
            Skip.If(fixture.SkipReason is not null, fixture.SkipReason);

            await using ServiceProvider provider = BuildProvider();

            SystemResource status = (await provider
                .GetRequiredService<ISystemApi>()
                .GetSystemStatusAsync())
                .EnsureSuccess();

            // Two fields no other test reads, so this assertion fails on a body that came back
            // structurally present but empty rather than on the two values the identity tests
            // already pin. Neither value is compared to a literal: the runtime version moves with
            // the base image and is not something this repository records.
            Assert.False(
                string.IsNullOrWhiteSpace(status.RuntimeVersion),
                "The instance reported no runtime version, so the body arrived without the fields "
                    + "a caller reads it for.");

            Assert.False(
                string.IsNullOrWhiteSpace(status.AppName),
                "The instance reported no application name, so the body arrived without the fields "
                    + "a caller reads it for.");
        }

        /// <summary>
        /// Builds a provider of its own, so no test can disturb another test's registration.
        /// </summary>
        /// <returns>A provider registered against the container this run started.</returns>
        private ServiceProvider BuildProvider()
        {
            ServiceCollection services = new();

            services.AddWhisparr2(new Whisparr2Options
            {
                BaseUrl = fixture.BaseUrl,
                ApiKey = fixture.ApiKey,
            });

            return services.BuildServiceProvider();
        }
    }
}
