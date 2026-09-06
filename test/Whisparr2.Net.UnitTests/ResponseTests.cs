// Hand-written test code. Nothing here is generator output; see .claude/CLAUDE.md,
// section "Generated code rules".

#nullable enable

using System.Net;
using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net.Api;
using Whisparr2.Net.Model;

namespace Whisparr2.Net.UnitTests
{
    /// <summary>
    /// Assertions over the three outcomes a response can have, observed over a real socket.
    /// </summary>
    /// <remarks>
    /// Every case here drives a real operation on a real registration against a real listener, and
    /// none constructs the typed error directly. A directly constructed exception proves the
    /// constructor works and nothing about the path a consumer takes.
    /// </remarks>
    public sealed class ResponseTests
    {
        /// <summary>
        /// An obvious non-secret, in the same shape the other test classes use.
        /// </summary>
        private const string SentinelKey = "SENTINEL-Key-123";

        /// <summary>A body of literal null, which the serializer resolves before any converter runs.</summary>
        private const string NullBody = "null";

        /// <summary>A body with the three status members the success case asserts by value.</summary>
        private const string StatusBody =
            "{\"appName\":\"Whisparr\",\"instanceName\":\"Whisparr Two\",\"version\":\"2.0.0.5344\"}";

        /// <summary>How long the canned body of the message-bound case is.</summary>
        private const int LongBodyLength = 4000;

        /// <summary>
        /// How many characters of body the message is allowed to carry.
        /// </summary>
        /// <remarks>
        /// The shipped message carries none of it: it reports the body's length and names
        /// RawContent instead, so a default logger cannot publish a credential the body happened to
        /// contain. The bound is written as a cap plus a framing allowance rather than as an exact
        /// message, so the framing wording can change without this case becoming a copy of the
        /// implementation.
        /// </remarks>
        private const int MessageBodyCap = 512;

        /// <summary>How much room the bound leaves for everything in the message but the body.</summary>
        private const int MessageFramingAllowance = 256;

        /// <summary>
        /// A long body that is not JSON, so it reaches the message path rather than binding.
        /// </summary>
        private static readonly string LongBody = new('a', LongBodyLength);

        /// <summary>
        /// The measured shape of a rejected key: 401 with zero bytes and no useful reason phrase.
        /// </summary>
        /// <remarks>
        /// The four values asserted here all come off the response and none of them came from
        /// parsing the body, which is the half of CLIENT-05 that a caller cannot get any other way.
        /// Path is the route template rather than the concrete path, so a log can group by
        /// operation.
        /// </remarks>
        [Fact]
        public async Task Bodiless_401_throws_a_typed_error_carrying_status_path_and_body()
        {
            using LoopbackCapture capture = new(status: 401, body: string.Empty);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemStatusApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemStatusAsync();

            Whisparr2ApiException error =
                Assert.Throws<Whisparr2ApiException>(() => response.EnsureSuccess());

            Assert.Equal(HttpStatusCode.Unauthorized, error.StatusCode);
            Assert.Equal("/api/v3/system/status", error.Path);
            Assert.NotNull(error.RequestUri);
            Assert.Equal(string.Empty, error.RawContent);
            Assert.False(error.IsSuccessStatusCode);
        }

        /// <summary>
        /// A success whose body cannot be read is its own outcome, not a failure.
        /// </summary>
        /// <remarks>
        /// IsSuccessStatusCode is the one member that separates the two throwing outcomes. A caller
        /// that cannot tell them apart may retry a create that already succeeded. The body here is
        /// a literal null, which System.Text.Json resolves before dispatching to a converter, so
        /// the outcome is the no-body path with a null inner exception rather than a wrapped
        /// deserialization failure.
        /// </remarks>
        [Fact]
        public async Task Success_with_an_unreadable_body_is_distinguishable_from_a_failure()
        {
            using LoopbackCapture capture = new(status: 200, body: NullBody);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemStatusApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemStatusAsync();

            Whisparr2ApiException error =
                Assert.Throws<Whisparr2ApiException>(() => response.EnsureSuccess());

            Assert.True(error.IsSuccessStatusCode);
            Assert.Contains("no body could be read", error.Message, StringComparison.Ordinal);
            Assert.Null(error.InnerException);
        }

        /// <summary>
        /// One of the 79 operations that carry no typed accessor can still report a failure.
        /// </summary>
        /// <remarks>
        /// IGetSystemRoutesApiResponse has nothing after IApiResponse in its base list, so there is
        /// no IOk for a type argument to be inferred from and only the non-generic overload can
        /// bind. Without this case those 79 operations have no evidence that EnsureSuccess reaches
        /// them at all.
        /// </remarks>
        [Fact]
        public async Task Content_less_operation_failure_throws_through_the_non_generic_overload()
        {
            using LoopbackCapture capture = new(status: 500, body: string.Empty);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemRoutesApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemRoutesAsync();

            Whisparr2ApiException error =
                Assert.Throws<Whisparr2ApiException>(() => response.EnsureSuccess());

            Assert.Equal(HttpStatusCode.InternalServerError, error.StatusCode);
            Assert.Equal("/api/v3/system/routes", error.Path);
            Assert.False(error.IsSuccessStatusCode);
        }

        /// <summary>
        /// An ordinary 200 returns a resource whose named members carry the sent values.
        /// </summary>
        /// <remarks>
        /// Three members are asserted by value. A non-null assertion would pass against a resource
        /// whose every member is empty, which is exactly what a converter that bound nothing
        /// produces, and that failure raises nothing of its own.
        /// </remarks>
        [Fact]
        public async Task Success_returns_the_body_with_asserted_field_values()
        {
            using LoopbackCapture capture = new(status: 200, body: StatusBody);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemStatusApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemStatusAsync();

            SystemResource status = response.EnsureSuccess();

            Assert.Equal("Whisparr", status.AppName);
            Assert.Equal("Whisparr Two", status.InstanceName);
            Assert.Equal("2.0.0.5344", status.VarVersion);
        }

        /// <summary>
        /// Neither the concrete URI nor the message carries the credential.
        /// </summary>
        /// <remarks>
        /// The exception is captured from a real failed call rather than constructed, so a leak
        /// reintroduced anywhere between the request builder and the exception is caught here. The
        /// query is checked for the key parameter in any casing, because Whisparr accepts the key
        /// that way too and a request that took that route would still succeed while writing the
        /// credential into every access log on the path.
        /// </remarks>
        [Fact]
        public async Task Exception_surface_does_not_contain_the_api_key()
        {
            using LoopbackCapture capture = new(status: 401, body: string.Empty);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemStatusApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemStatusAsync();

            Whisparr2ApiException error =
                Assert.Throws<Whisparr2ApiException>(() => response.EnsureSuccess());

            Assert.NotNull(error.RequestUri);

            string uri = error.RequestUri.ToString();

            Assert.DoesNotContain(SentinelKey, uri, StringComparison.Ordinal);
            Assert.DoesNotContain(SentinelKey, error.Message, StringComparison.Ordinal);
            Assert.DoesNotContain("apikey", uri, StringComparison.OrdinalIgnoreCase);
        }

        /// <summary>
        /// A four thousand character body reaches RawContent whole and the message stays bounded.
        /// </summary>
        /// <remarks>
        /// A message is the one part of an exception that every default logger writes, including an
        /// unhandled-exception handler the consumer never wrote, so an instance-controlled body
        /// interpolated into it is a log-flooding surface. The bound is asserted rather than the
        /// exact wording, and the failure names the length it saw so a regression is readable.
        /// </remarks>
        [Fact]
        public async Task Message_stays_bounded_while_raw_content_keeps_the_whole_body()
        {
            using LoopbackCapture capture = new(status: 200, body: LongBody);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemStatusApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemStatusAsync();

            Whisparr2ApiException error =
                Assert.Throws<Whisparr2ApiException>(() => response.EnsureSuccess());

            Assert.Equal(LongBodyLength, error.RawContent.Length);
            Assert.DoesNotContain(LongBody, error.Message, StringComparison.Ordinal);
            Assert.True(
                error.Message.Length <= MessageBodyCap + MessageFramingAllowance,
                $"The message was {error.Message.Length} characters, over the bound of "
                    + $"{MessageBodyCap + MessageFramingAllowance}.");
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
    }
}
