// Hand-written test code. Nothing here is generator output; see .claude/CLAUDE.md,
// section "Generated code rules".

#nullable enable

using System.Net;
using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net.Api;
using Whisparr2.Net.Client;
using Whisparr2.Net.Model;

namespace Whisparr2.Net.UnitTests
{
    /// <summary>
    /// Assertions over the members of the typed error that no other file reads, and over the one
    /// ReadAs outcome that a body-carrying failure produces.
    /// </summary>
    /// <remarks>
    /// Every case here was written against a mutation of the shipped code that the rest of the
    /// suite did not notice. Each drives a real operation against a real listener through the same
    /// single registration call a consumer makes.
    /// </remarks>
    public sealed class ErrorSurfaceTests
    {
        /// <summary>An obvious non-secret, in the same shape the other test classes use.</summary>
        private const string SentinelKey = "SENTINEL-Key-123";

        /// <summary>The id the update cases address. This operation takes it as a string.</summary>
        private const string UpdatedTagId = "5";

        /// <summary>A JSON body a failing response carries, readable as the type below.</summary>
        private const string FailingJsonBody = "[{\"path\":\"/api/v3/tag\",\"action\":\"list\"}]";

        /// <summary>How long the body of the message case is.</summary>
        private const int LongBodyLength = 4000;

        /// <summary>A body long enough that its length is unmistakable in the message.</summary>
        private static readonly string LongBody = new('a', LongBodyLength);

        /// <summary>
        /// The reason phrase and the concrete URI come off the response rather than from a
        /// constant.
        /// </summary>
        /// <remarks>
        /// Both members are read from the response and neither is asserted anywhere else, so a
        /// constructor that dropped the phrase or invented a URI would leave the rest of the suite
        /// green. The URI is asserted whole, with the ephemeral port and the substituted route
        /// parameter, which is what separates it from Path. Path is the template for the same call.
        /// </remarks>
        [Fact]
        public async Task Reason_phrase_and_concrete_uri_are_read_off_the_response()
        {
            using LoopbackCapture capture = new(status: 500, body: string.Empty, reason: "Kaboom");

            await using ServiceProvider provider = BuildProvider(capture);
            IUpdateTagApiResponse response = await provider.GetRequiredService<ITagApi>()
                .UpdateTagAsync(UpdatedTagId, new TagResource { Id = 5, Label = "updated-tag" });

            Whisparr2ApiException error =
                Assert.Throws<Whisparr2ApiException>(() => response.EnsureSuccess());

            Assert.Equal("Kaboom", error.ReasonPhrase);
            Assert.Equal(new Uri($"{capture.BaseUrl}/api/v3/tag/{UpdatedTagId}"), error.RequestUri);
            Assert.Equal("/api/v3/tag/{id}", error.Path);
        }

        /// <summary>
        /// The message reports the body's length and names the member that holds it.
        /// </summary>
        /// <remarks>
        /// This is what a reader of a log has instead of the body. Without it the message could
        /// stop saying anything about the body at all and the existing bound case, which only
        /// asserts the message is short and carries no fragment of the body, would still pass.
        /// </remarks>
        [Fact]
        public async Task Message_reports_the_body_length_and_names_RawContent()
        {
            using LoopbackCapture capture = new(status: 500, body: LongBody);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemStatusApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemStatusAsync();

            Whisparr2ApiException error =
                Assert.Throws<Whisparr2ApiException>(() => response.EnsureSuccess());

            Assert.Equal(LongBodyLength, error.RawContent.Length);
            Assert.Contains(
                $"{LongBodyLength} character body",
                error.Message,
                StringComparison.Ordinal);
            Assert.Contains(nameof(Whisparr2ApiException.RawContent), error.Message, StringComparison.Ordinal);
        }

        /// <summary>
        /// A response with no body says so, rather than reporting a length of zero.
        /// </summary>
        [Fact]
        public async Task Message_says_no_body_when_the_response_carried_none()
        {
            using LoopbackCapture capture = new(status: 401, body: string.Empty);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemStatusApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemStatusAsync();

            Whisparr2ApiException error =
                Assert.Throws<Whisparr2ApiException>(() => response.EnsureSuccess());

            Assert.Contains("no body", error.Message, StringComparison.Ordinal);
            Assert.DoesNotContain("0 character", error.Message, StringComparison.Ordinal);
        }

        /// <summary>
        /// An instance that sends no reason phrase still produces a message naming the status.
        /// </summary>
        /// <remarks>
        /// The status line here is "HTTP/1.1 401 " with nothing after the code, which is legal.
        /// Every other case in the suite receives a phrase, so the fallback that turns an absent
        /// one into the status name has no other case standing on it, and a message reading
        /// "Whisparr returned 401  for ..." would go unnoticed.
        /// </remarks>
        [Fact]
        public async Task Message_names_the_status_when_the_reason_phrase_is_absent()
        {
            using LoopbackCapture capture = new(status: 401, body: string.Empty, reason: string.Empty);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemStatusApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemStatusAsync();

            Whisparr2ApiException error =
                Assert.Throws<Whisparr2ApiException>(() => response.EnsureSuccess());

            Assert.True(string.IsNullOrEmpty(error.ReasonPhrase));
            Assert.Contains(
                $"401 {nameof(HttpStatusCode.Unauthorized)}",
                error.Message,
                StringComparison.Ordinal);
        }

        /// <summary>
        /// A failing status whose body happens to be readable is still a failure.
        /// </summary>
        /// <remarks>
        /// This is the case that pins the status check in ReadAs. Every other failure case in the
        /// suite sends an empty body, so removing that check leaves them all green: they fall
        /// through to the empty-body branch and throw the same type. A 500 carrying JSON is where
        /// the difference shows, and returning it would hand a caller an error document as if it
        /// were a result.
        /// </remarks>
        [Fact]
        public async Task ReadAs_refuses_a_failing_status_that_carries_a_readable_body()
        {
            using LoopbackCapture capture = new(status: 500, body: FailingJsonBody);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemRoutesDuplicateApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemRoutesDuplicateAsync();

            Whisparr2ApiException error = Assert.Throws<Whisparr2ApiException>(
                () => ((ApiResponse)response).ReadAs<List<FailureProbe>>());

            Assert.False(error.IsSuccessStatusCode);
            Assert.Equal(HttpStatusCode.InternalServerError, error.StatusCode);
            Assert.Equal(FailingJsonBody, error.RawContent);
        }

        /// <summary>
        /// Registers against a capture through the same single call a consumer makes.
        /// </summary>
        /// <param name="capture">The listener the client is pointed at.</param>
        /// <returns>A provider from which typed clients resolve.</returns>
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

        /// <summary>
        /// A caller-written type the failing body above would bind to if it were ever read.
        /// </summary>
        internal sealed class FailureProbe
        {
            /// <summary>The route template.</summary>
            [System.Text.Json.Serialization.JsonPropertyName("path")]
            public string? Path { get; set; }

            /// <summary>The action the route dispatches to.</summary>
            [System.Text.Json.Serialization.JsonPropertyName("action")]
            public string? Action { get; set; }
        }
    }
}
