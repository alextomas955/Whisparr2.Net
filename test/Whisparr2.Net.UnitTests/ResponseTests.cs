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

        /// <summary>The body a create answers 201 with.</summary>
        private const string CreatedTagBody = "{\"id\":5,\"label\":\"created-tag\"}";

        /// <summary>The body an update answers 202 with.</summary>
        private const string UpdatedTagBody = "{\"id\":5,\"label\":\"updated-tag\"}";

        /// <summary>The body the ordinary-200 control on the create operation answers with.</summary>
        private const string OkCreateTagBody = "{\"id\":6,\"label\":\"ordinary-create\"}";

        /// <summary>The body the ordinary-200 control on the update operation answers with.</summary>
        private const string OkUpdateTagBody = "{\"id\":7,\"label\":\"ordinary-update\"}";

        /// <summary>
        /// A one element array, which is what makes the list case evidence.
        /// </summary>
        /// <remarks>
        /// An empty array binds the list shell and enters the element converter zero times, so it
        /// would say nothing about whether a list element deserializes.
        /// </remarks>
        private const string ListTagBody = "[{\"id\":8,\"label\":\"listed-tag\"}]";

        /// <summary>The id the update cases address. This operation takes it as a string.</summary>
        private const string UpdatedTagId = "5";

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
        /// A create answering 201 is a success and its body is reachable.
        /// </summary>
        /// <remarks>
        /// This is the case the whole layer exists for. All 227 operations declare exactly one
        /// response code and it is 200, so the generator emitted no created accessor anywhere in
        /// the tree and the generated success accessor returns null on a real 201, which reads to a
        /// caller as a failed create. It is also the detector for an ApiResponse partial declared
        /// in the wrong namespace: outside Whisparr2.Net.Client the pattern match in the generic
        /// overload never matches, every typed response goes down the generated-accessor path, and
        /// a successful create returns null. If this case fails with a null or an unexpected typed
        /// error, check that namespace before anything else.
        /// </remarks>
        [Fact]
        public async Task Created_201_body_is_reachable_and_EnsureSuccess_returns_it()
        {
            using LoopbackCapture capture = new(status: 201, body: CreatedTagBody);

            await using ServiceProvider provider = BuildProvider(capture);
            ICreateTagApiResponse response = await provider.GetRequiredService<ITagApi>()
                .CreateTagAsync(new TagResource { Label = "created-tag" });

            TagResource created = response.EnsureSuccess();

            Assert.Equal(5, created.Id);
            Assert.Equal("created-tag", created.Label);
        }

        /// <summary>
        /// An update answering 202 is a success and its body is reachable.
        /// </summary>
        /// <remarks>
        /// The other half of the same defect. A PUT on this instance answers 202, which the
        /// document does not declare either, and the id on this operation is a string while the
        /// same id on the delete operation is an int.
        /// </remarks>
        [Fact]
        public async Task Accepted_202_body_is_reachable_and_EnsureSuccess_returns_it()
        {
            using LoopbackCapture capture = new(status: 202, body: UpdatedTagBody);

            await using ServiceProvider provider = BuildProvider(capture);
            IUpdateTagApiResponse response = await provider.GetRequiredService<ITagApi>()
                .UpdateTagAsync(UpdatedTagId, new TagResource { Id = 5, Label = "updated-tag" });

            TagResource updated = response.EnsureSuccess();

            Assert.Equal(5, updated.Id);
            Assert.Equal("updated-tag", updated.Label);
        }

        /// <summary>
        /// The control for the create case. An ordinary 200 still returns the body.
        /// </summary>
        /// <remarks>
        /// Not padding. Every other case in this file sends a non-200 or an unreadable body, so a
        /// change that broke the plain path would pass all of them.
        /// </remarks>
        [Fact]
        public async Task Ok_200_on_the_create_operation_still_returns_the_body()
        {
            using LoopbackCapture capture = new(status: 200, body: OkCreateTagBody);

            await using ServiceProvider provider = BuildProvider(capture);
            ICreateTagApiResponse response = await provider.GetRequiredService<ITagApi>()
                .CreateTagAsync(new TagResource { Label = "ordinary-create" });

            TagResource created = response.EnsureSuccess();

            Assert.Equal(6, created.Id);
            Assert.Equal("ordinary-create", created.Label);
        }

        /// <summary>
        /// The same control for the update path.
        /// </summary>
        [Fact]
        public async Task Ok_200_on_the_update_operation_still_returns_the_body()
        {
            using LoopbackCapture capture = new(status: 200, body: OkUpdateTagBody);

            await using ServiceProvider provider = BuildProvider(capture);
            IUpdateTagApiResponse response = await provider.GetRequiredService<ITagApi>()
                .UpdateTagAsync(UpdatedTagId, new TagResource { Id = 7, Label = "ordinary-update" });

            TagResource updated = response.EnsureSuccess();

            Assert.Equal(7, updated.Id);
            Assert.Equal("ordinary-update", updated.Label);
        }

        /// <summary>
        /// A 201 that arrives empty is a success with nothing to return, not a failure.
        /// </summary>
        /// <remarks>
        /// Without the typed layer this is a raw serializer exception escaping with no status, no
        /// route template and no URI. The message names the status and the route template, which is
        /// what makes an exception a consumer logged enough to act on.
        /// </remarks>
        [Fact]
        public async Task Created_201_with_an_empty_body_throws_the_typed_error()
        {
            using LoopbackCapture capture = new(status: 201, body: string.Empty);

            await using ServiceProvider provider = BuildProvider(capture);
            ICreateTagApiResponse response = await provider.GetRequiredService<ITagApi>()
                .CreateTagAsync(new TagResource { Label = "created-tag" });

            Whisparr2ApiException error =
                Assert.Throws<Whisparr2ApiException>(() => response.EnsureSuccess());

            Assert.True(error.IsSuccessStatusCode);
            Assert.Equal("/api/v3/tag", error.Path);
            Assert.Contains("201", error.Message, StringComparison.Ordinal);
            Assert.Contains("/api/v3/tag", error.Message, StringComparison.Ordinal);
        }

        /// <summary>
        /// A list body binds through the generic overload with the element's fields asserted.
        /// </summary>
        /// <remarks>
        /// This is the only place a list type argument is exercised, and it stands for the 34 of
        /// the 148 typed operations whose accessor returns one. The array carries one element on
        /// purpose: an empty array binds the list shell without entering the element converter, so
        /// it is not evidence that an element deserializes.
        /// </remarks>
        [Fact]
        public async Task List_body_deserializes_with_asserted_field_values()
        {
            using LoopbackCapture capture = new(status: 200, body: ListTagBody);

            await using ServiceProvider provider = BuildProvider(capture);
            IListTagApiResponse response = await provider.GetRequiredService<ITagApi>().ListTagAsync();

            List<TagResource> tags = response.EnsureSuccess();

            TagResource only = Assert.Single(tags);

            Assert.Equal(8, only.Id);
            Assert.Equal("listed-tag", only.Label);
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
