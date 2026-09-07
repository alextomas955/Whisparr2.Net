// Hand-written test code. Nothing here is generator output; see .claude/CLAUDE.md,
// section "Generated code rules".

#nullable enable

using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net.Api;
using Whisparr2.Net.Model;

namespace Whisparr2.Net.UnitTests
{
    /// <summary>
    /// Assertions over the array response the pre-processing pass attached to the series lookup.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Before that pass the operation declared a 200 with no content, so the generator emitted no
    /// typed accessor for it and a caller got back no typed value at all. The subject here is the
    /// attached schema: that the operation now returns a list of series and that an empty answer
    /// comes back as an empty list rather than as nothing.
    /// </para>
    /// <para>
    /// Driven over the loopback rather than against a container. The live operation answers 200
    /// only by reaching a metadata service outside the machine, so the schema itself is provable
    /// here with no Docker and no outbound network, which is what a per-change check runs. The
    /// live counterpart sits in the integration project behind an opt-in flag.
    /// </para>
    /// </remarks>
    public sealed class SeriesLookupSchemaTests
    {
        /// <summary>
        /// An obvious non-secret, in the same shape the other test classes use.
        /// </summary>
        private const string SentinelKey = "SENTINEL-Key-123";

        /// <summary>The term the lookup is called with. Its value reaches only the query string.</summary>
        private const string Term = "probe-term";

        /// <summary>
        /// Two series, small enough that a reader can hold the whole expectation in their head.
        /// </summary>
        /// <remarks>
        /// Two rather than one, so an element converter that bound only the first is visible. The
        /// live body measured against the pinned image is far larger; its size belongs to that
        /// measurement, and restating it here would assert the fixture rather than the client.
        /// </remarks>
        private const string TwoSeriesBody =
            "[{\"title\":\"First Probe Series\",\"titleSlug\":\"first-probe-series\",\"tvdbId\":11},"
                + "{\"title\":\"Second Probe Series\",\"titleSlug\":\"second-probe-series\",\"tvdbId\":22}]";

        /// <summary>An empty array, which is what the operation answers for a term that matches nothing.</summary>
        private const string EmptyArrayBody = "[]";

        /// <summary>
        /// A populated array binds to a typed list whose elements carry their values.
        /// </summary>
        /// <remarks>
        /// The response is read through EnsureSuccess rather than through the generated Ok accessor
        /// or its Try companion. The Ok accessor returns null on any status but the declared one, and
        /// the Try companion returns false on a failed deserialization and on an absent body
        /// alike, so a case built on either would report the attached schema failing to bind as an
        /// empty answer. That is the exact confusion this pre-processing pass exists to remove.
        /// </remarks>
        [Fact]
        public async Task A_populated_lookup_body_binds_to_a_typed_list()
        {
            using LoopbackCapture capture = new(status: 200, body: TwoSeriesBody);

            await using ServiceProvider provider = BuildProvider(capture);

            List<SeriesResource> found = (await provider
                .GetRequiredService<ISeriesLookupApi>()
                .ListSeriesLookupAsync(term: Term))
                .EnsureSuccess();

            Assert.Equal(2, found.Count);

            // By value, not by non-null. A list of two default-constructed resources would pass a
            // non-null assertion, and a Pascal-cased member with no JsonPropertyName binds nothing
            // from a camel-cased body without throwing.
            Assert.Equal("First Probe Series", found[0].Title);
            Assert.Equal("second-probe-series", found[1].TitleSlug);
            Assert.Equal(22, found[1].TvdbId);
        }

        /// <summary>
        /// An empty array is an empty list, not an absent value.
        /// </summary>
        /// <remarks>
        /// This is what lets a caller tell a term that matched nothing from a body that could not
        /// be read. The second outcome throws, and the assertion below would catch a change that
        /// merged the two.
        /// </remarks>
        [Fact]
        public async Task An_empty_lookup_body_binds_to_an_empty_list()
        {
            using LoopbackCapture capture = new(status: 200, body: EmptyArrayBody);

            await using ServiceProvider provider = BuildProvider(capture);

            List<SeriesResource> found = (await provider
                .GetRequiredService<ISeriesLookupApi>()
                .ListSeriesLookupAsync(term: Term))
                .EnsureSuccess();

            Assert.Empty(found);
        }

        /// <summary>
        /// Registers a client pointed at the listener.
        /// </summary>
        /// <param name="capture">The listener to reach.</param>
        /// <returns>A provider the caller disposes.</returns>
        private static ServiceProvider BuildProvider(LoopbackCapture capture)
        {
            ServiceCollection services = new();
            services.AddWhisparr2(new Whisparr2Options
            {
                BaseUrl = capture.BaseUrl,
                ApiKey = SentinelKey,
            });

            return services.BuildServiceProvider();
        }
    }
}
