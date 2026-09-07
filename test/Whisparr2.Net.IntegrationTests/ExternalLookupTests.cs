// Hand-written test code. See .claude/CLAUDE.md, section "Generated code rules".

#nullable enable

using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net.Api;
using Whisparr2.Net.Model;

namespace Whisparr2.Net.IntegrationTests
{
    /// <summary>
    /// The series lookup against a real instance, behind the same opt-in flag the conformance
    /// sweep uses.
    /// </summary>
    /// <remarks>
    /// <para>
    /// The gate is not tidiness. This operation answers 200 only by reaching a metadata service
    /// outside the container, and it answers 503 when it is called with no term, so on a runner
    /// with no route out an ungated assertion here fails and the failure reads as a
    /// deserialization defect in this client. That is the wrong diagnosis for a network the runner
    /// does not have.
    /// </para>
    /// <para>
    /// What is left when the flag is unset is not a gap. The array schema the pre-processing pass
    /// attached to this operation is proved in the unit project over a loopback listener, with no
    /// Docker and no outbound network, and that is what a per-change check runs. This class adds
    /// the one thing the loopback cannot say: that a real instance's own answer binds to the same
    /// type. A reader who finds it skipped is looking at a deliberately optional extra, not at
    /// something abandoned.
    /// </para>
    /// </remarks>
    [Collection(WhisparrCollection.Name)]
    public sealed class ExternalLookupTests(WhisparrFixture fixture)
    {
        /// <summary>
        /// The variable that opts a run into assertions which leave the machine.
        /// </summary>
        /// <remarks>
        /// The same name the conformance sweep reads, so one decision covers both. Restated here
        /// rather than shared, because the sweep is a Python script and there is nothing for a C#
        /// class to import from it.
        /// </remarks>
        private const string ExternalFlagVariable = "WHISPARR2NET_CONFORMANCE_EXTERNAL";

        /// <summary>The value that opts in. Any other value, including none, stays out.</summary>
        private const string ExternalFlagValue = "1";

        /// <summary>
        /// A term broad enough that a working metadata route returns something for it.
        /// </summary>
        /// <remarks>
        /// Deliberately generic. A specific title would tie the assertion to one record in
        /// somebody else's catalogue, and its removal there would fail this test for a reason that
        /// has nothing to do with this client.
        /// </remarks>
        private const string SearchTerm = "the";

        /// <summary>
        /// A real instance's own lookup answer binds to the typed list.
        /// </summary>
        [SkippableFact]
        public async Task Series_lookup_returns_a_typed_list_from_the_instance()
        {
            Skip.If(fixture.SkipReason is not null, fixture.SkipReason);
            Skip.If(
                Environment.GetEnvironmentVariable(ExternalFlagVariable) != ExternalFlagValue,
                "This assertion reaches a metadata service outside the container. Set "
                    + ExternalFlagVariable + "=" + ExternalFlagValue + " to opt in. The schema "
                    + "itself is proved without leaving the machine by "
                    + "SeriesLookupSchemaTests in the unit project.");

            await using ServiceProvider provider = BuildProvider();

            List<SeriesResource> found = (await provider
                .GetRequiredService<ISeriesLookupApi>()
                .ListSeriesLookupAsync(term: SearchTerm))
                .EnsureSuccess();

            // Read through EnsureSuccess above, never through the generated accessor's Try
            // companion, which returns false on a failed deserialization and on an empty answer
            // alike. Here that would report a metadata route this run could not reach as a search
            // that matched nothing.
            Assert.NotEmpty(found);

            // One non-empty string off the first element, so an array of empty objects cannot pass
            // as a successful deserialization.
            Assert.False(
                string.IsNullOrWhiteSpace(found[0].Title),
                "The lookup answered with an entry carrying no title, so the body arrived "
                    + "structurally present and empty rather than deserialized.");
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
