// Hand-written test code. See .claude/CLAUDE.md, section "Generated code rules".

#nullable enable

using System.Globalization;
using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net.Api;
using Whisparr2.Net.Model;

namespace Whisparr2.Net.IntegrationTests
{
    /// <summary>
    /// What the instance the suite reached says about itself: when it started, and whether it
    /// finished seeding before the tests read it.
    /// </summary>
    /// <remarks>
    /// Every response is classified by EnsureSuccess rather than by the generated success accessor.
    /// That accessor deserializes on exactly 200 and returns null on anything else, so a 401 and an
    /// empty collection read the same to a caller, and an assertion built on it would report a
    /// rejected request as an empty result.
    /// </remarks>
    [Collection(WhisparrCollection.Name)]
    public sealed class InstanceIdentityTests(WhisparrFixture fixture)
    {
        /// <summary>
        /// The instance started no earlier than the whole second in which this run began its boot,
        /// and the same comparison refuses a stamp three days old.
        /// </summary>
        /// <remarks>
        /// This is the one identity signal in this repository that a long-running instance on the
        /// pinned image cannot pass. Every other signal passes against it, because it is the same
        /// image.
        /// </remarks>
        [SkippableFact]
        public async Task Instance_started_no_earlier_than_this_run_did()
        {
            Skip.If(fixture.SkipReason is not null, fixture.SkipReason);

            await using ServiceProvider provider = BuildProvider();

            SystemResource status = (await provider
                .GetRequiredService<ISystemApi>()
                .GetSystemStatusAsync())
                .EnsureSuccess();

            DateTime reported = Assert.NotNull(status.StartTime);

            // Asserted before the comparison. A value that lost its zone marker would be read as
            // local time and the comparison would silently move by this machine's offset, which on
            // a machine east of UTC turns a stale instance into a fresh-looking one.
            Assert.Equal(DateTimeKind.Utc, reported.Kind);

            DateTimeOffset startedAt = new(reported);

            Assert.Null(WhisparrFixture.StaleStartTimeRefusal(startedAt, fixture.BootBeganAt));

            // The boundary the truncation exists for. An application that starts inside the second
            // the stamp records reports a value equal to it, so an implementation using a strict
            // comparison passes every other check here and fails intermittently the first time a
            // boot lands in the same second.
            Assert.Null(WhisparrFixture.StaleStartTimeRefusal(fixture.BootBeganAt, fixture.BootBeganAt));

            // The refusing branch, driven over a stamp no container this run started could report.
            // Without this the branch that fails closed against a long-running instance is never
            // observed refusing anything.
            DateTimeOffset threeDaysEarly = fixture.BootBeganAt.AddDays(-3);
            string? refusal = WhisparrFixture.StaleStartTimeRefusal(threeDaysEarly, fixture.BootBeganAt);

            Assert.NotNull(refusal);
            Assert.Contains(
                threeDaysEarly.ToString("o", CultureInfo.InvariantCulture),
                refusal,
                StringComparison.Ordinal);
        }

        /// <summary>
        /// The instance returns the seven quality profiles and the twenty-three quality definitions
        /// the pinned image seeds.
        /// </summary>
        /// <remarks>
        /// Independent evidence that the wait strategy returned after seeding rather than at the
        /// first HTTP 200, which it is only because the wait condition is the log marker and not
        /// this count. A fixture that polled until the profiles read seven would leave this test
        /// asserting that the timeout did not fire.
        /// </remarks>
        [SkippableFact]
        public async Task Quality_profiles_and_definitions_are_settled()
        {
            Skip.If(fixture.SkipReason is not null, fixture.SkipReason);

            await using ServiceProvider provider = BuildProvider();

            List<QualityProfileResource> profiles = (await provider
                .GetRequiredService<IQualityProfileApi>()
                .ListQualityProfileAsync())
                .EnsureSuccess();

            List<QualityDefinitionResource> definitions = (await provider
                .GetRequiredService<IQualityDefinitionApi>()
                .ListQualityDefinitionAsync())
                .EnsureSuccess();

            // Both are equalities and neither is a lower bound. They are properties of the database
            // this image version seeds rather than of the API, so a reader who finds them moved
            // after the pin moves should re-measure against the new digest rather than read the
            // change as a defect. A lower bound would stop proving that seeding finished.
            Assert.Equal(7, profiles.Count);
            Assert.Equal(23, definitions.Count);
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
