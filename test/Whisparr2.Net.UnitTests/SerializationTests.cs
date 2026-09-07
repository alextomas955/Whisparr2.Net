// Hand-written test code. Nothing here is generator output; see .claude/CLAUDE.md,
// section "Generated code rules".

#nullable enable

using System.Net;
using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net.Api;
using Whisparr2.Net.Client;
using Whisparr2.Net.Model;

namespace Whisparr2.Net.UnitTests
{
    /// <summary>
    /// Assertions over what the client puts in a request, read off the recorded bytes.
    /// </summary>
    /// <remarks>
    /// Every case drives a real operation on a real registration against a real listener and reads
    /// what the listener recorded. An assertion over a serialized string built in the test would be
    /// a fact about the serializer call the test wrote, not about the request the client sends.
    /// </remarks>
    public sealed class SerializationTests
    {
        /// <summary>
        /// An obvious non-secret, in the same shape the other test classes use.
        /// </summary>
        private const string SentinelKey = "SENTINEL-Key-123";

        /// <summary>The label the create cases send. Nothing else on the resource is set.</summary>
        private const string OnlyLabel = "only-label";

        /// <summary>The id the update case addresses. This operation takes it as a string.</summary>
        private const string UpdatedTagId = "5";

        /// <summary>The same id on the delete operation, which takes it as an int.</summary>
        private const int DeletedTagId = 5;

        /// <summary>
        /// The command the dispatch cases send. It takes an argument, which is what makes the flat
        /// body assertions mean anything.
        /// </summary>
        private const string DispatchedCommandName = "RefreshSeries";

        /// <summary>The series the dispatch cases name.</summary>
        private const int DispatchedSeriesId = 7;

        /// <summary>
        /// The canned 201 body a dispatch reads back. It carries no JSON null member on purpose:
        /// the generated converter throws for a member that is present and null.
        /// </summary>
        private const string CommandAcceptedBody = "{\"id\":42,\"name\":\"RefreshSeries\"}";

        /// <summary>The command id the canned body above declares.</summary>
        private const int AcceptedCommandId = 42;

        /// <summary>
        /// An unset property is absent from the body rather than present and null.
        /// </summary>
        /// <remarks>
        /// Option is the whole mechanism behind that, and a create that sends a null id is rejected
        /// by the server. Both halves are needed: the first shows an unset body argument sends no
        /// body at all, and the second shows the body that is sent omits what was never set.
        /// </remarks>
        [Fact]
        public async Task Unset_option_emits_no_json_member()
        {
            using LoopbackCapture noBody = new();

            await using (ServiceProvider provider = BuildProvider(noBody))
            {
                await provider.GetRequiredService<ITagApi>().CreateTagAsync();
            }

            Assert.Empty(CapturedRequest.Body(await noBody.FirstRequest));

            using LoopbackCapture labelOnly = new();

            await using (ServiceProvider provider = BuildProvider(labelOnly))
            {
                await provider.GetRequiredService<ITagApi>()
                    .CreateTagAsync(new TagResource { Label = OnlyLabel });
            }

            string body = CapturedRequest.Body(await labelOnly.FirstRequest);

            Assert.Equal("{\"label\":\"" + OnlyLabel + "\"}", body);
        }

        /// <summary>
        /// A create request declares JSON.
        /// </summary>
        /// <remarks>
        /// The document declares more than one content type for these operations, so the generated
        /// content-type selection could pick text/plain instead and the server would reject a body
        /// it was told not to parse.
        /// </remarks>
        [Fact]
        public async Task Request_content_type_is_application_json()
        {
            using LoopbackCapture capture = new();

            await using ServiceProvider provider = BuildProvider(capture);
            await provider.GetRequiredService<ITagApi>()
                .CreateTagAsync(new TagResource { Label = OnlyLabel });

            string request = await capture.FirstRequest;

            string only = Assert.Single(CapturedRequest.HeaderLines(request, "Content-Type"));

            Assert.Equal("Content-Type: application/json", only);
        }

        /// <summary>
        /// The update puts its id into the path, and takes that id as a string.
        /// </summary>
        /// <remarks>
        /// The delete on the same controller takes the same id as an int. That asymmetry is a
        /// documented trap of this document and nothing else in the suite records it. Both request
        /// lines are read off the recorded bytes, which is what makes this a fact about the wire
        /// rather than about the two signatures.
        /// </remarks>
        [Fact]
        public async Task Update_route_template_carries_the_id_as_a_string()
        {
            using LoopbackCapture update = new();

            await using (ServiceProvider provider = BuildProvider(update))
            {
                await provider.GetRequiredService<ITagApi>()
                    .UpdateTagAsync(UpdatedTagId, new TagResource { Label = OnlyLabel });
            }

            Assert.Equal(
                "PUT /api/v3/tag/5 HTTP/1.1",
                Assert.Single(CapturedRequest.RequestLines(await update.FirstRequest)));

            using LoopbackCapture delete = new();

            await using (ServiceProvider provider = BuildProvider(delete))
            {
                await provider.GetRequiredService<ITagApi>().DeleteTagAsync(DeletedTagId);
            }

            Assert.Equal(
                "DELETE /api/v3/tag/5 HTTP/1.1",
                Assert.Single(CapturedRequest.RequestLines(await delete.FirstRequest)));
        }

        /// <summary>
        /// The command arguments reach the wire as siblings of the name member, not nested under a
        /// body member.
        /// </summary>
        /// <remarks>
        /// The server rewinds the request stream and deserializes the whole body into a concrete
        /// command type, so a nested arguments object would dispatch the command with no arguments
        /// and still be accepted. The request bytes are the only place the difference is visible.
        /// </remarks>
        [Fact]
        public async Task Command_dispatch_puts_a_flat_name_and_payload_body_on_the_wire()
        {
            using LoopbackCapture capture = new(status: 201, body: CommandAcceptedBody);

            await using ServiceProvider provider = BuildProvider(capture);
            ICreateCommandApiResponse response = await Dispatcher(provider)
                .SendCommandAsync(DispatchedCommandName, new { seriesId = DispatchedSeriesId });

            // The status is read off the response rather than off a caught exception. A dispatch
            // that succeeded reports it here, which is the status the instance sent and not one
            // composed by the caller.
            Assert.Equal(HttpStatusCode.Created, response.StatusCode);

            CommandResource command = response.EnsureSuccess();

            Assert.Equal(AcceptedCommandId, command.Id);
            Assert.Equal(DispatchedCommandName, command.Name);

            string body = CapturedRequest.Body(await capture.FirstRequest);

            using JsonDocument sent = JsonDocument.Parse(body);

            Assert.True(
                sent.RootElement.TryGetProperty("name", out JsonElement name),
                $"The captured request body carries no name member. Body: {body}");

            Assert.Equal(JsonValueKind.String, name.ValueKind);
            Assert.Equal(DispatchedCommandName, name.GetString());

            Assert.True(
                sent.RootElement.TryGetProperty("seriesId", out JsonElement seriesId),
                $"The captured request body carries no seriesId member. Body: {body}");

            Assert.Equal(DispatchedSeriesId, seriesId.GetInt32());

            Assert.False(
                sent.RootElement.TryGetProperty("body", out _),
                $"The captured request body nests the arguments under a body member. Body: {body}");
        }

        /// <summary>
        /// A command that takes no arguments is dispatched by omitting the payload, and its body
        /// carries the name and nothing else.
        /// </summary>
        [Fact]
        public async Task Command_dispatch_with_no_payload_sends_the_name_alone()
        {
            using LoopbackCapture capture = new(status: 201, body: CommandAcceptedBody);

            await using ServiceProvider provider = BuildProvider(capture);
            await Dispatcher(provider).SendCommandAsync(DispatchedCommandName);

            string body = CapturedRequest.Body(await capture.FirstRequest);

            using JsonDocument sent = JsonDocument.Parse(body);

            JsonProperty only = Assert.Single(sent.RootElement.EnumerateObject());

            Assert.Equal("name", only.Name);
            Assert.Equal(DispatchedCommandName, only.Value.GetString());
        }

        /// <summary>
        /// A payload carrying its own name member is refused before a socket is opened.
        /// </summary>
        /// <remarks>
        /// The indexer overwrites an exact-case name in place, but a differently-cased key survives
        /// alongside it and both reach the wire, leaving the server two candidates for one
        /// property. Refusing is the alternative to silently dropping or duplicating a caller's
        /// field at a public boundary.
        /// </remarks>
        [Fact]
        public async Task Command_payload_carrying_its_own_name_key_is_refused()
        {
            using LoopbackCapture capture = new(status: 201, body: CommandAcceptedBody);

            await using ServiceProvider provider = BuildProvider(capture);

            ArgumentException error = await Assert.ThrowsAsync<ArgumentException>(
                () => Dispatcher(provider).SendCommandAsync(
                    DispatchedCommandName,
                    new { Name = "collision", seriesId = DispatchedSeriesId }));

            Assert.Equal("payload", error.ParamName);
            Assert.Contains("Name", error.Message, StringComparison.Ordinal);

            Assert.Empty(capture.Requests);
        }

        /// <summary>
        /// A payload that is not a JSON object is refused before a socket is opened.
        /// </summary>
        /// <remarks>
        /// The parameter is object, which admits scalars, arrays and strings. A boxed scalar
        /// serializes to a JsonValue, and without this guard the cast to JsonObject would raise a
        /// NullReferenceException from inside the library.
        /// </remarks>
        [Fact]
        public async Task Command_payload_that_is_not_a_json_object_is_refused()
        {
            using LoopbackCapture capture = new(status: 201, body: CommandAcceptedBody);

            await using ServiceProvider provider = BuildProvider(capture);

            ArgumentException error = await Assert.ThrowsAsync<ArgumentException>(
                () => Dispatcher(provider).SendCommandAsync(DispatchedCommandName, DispatchedSeriesId));

            Assert.Equal("payload", error.ParamName);

            Assert.Empty(capture.Requests);
        }

        /// <summary>
        /// The payload is written with the serializer options the client registered, not plain
        /// defaults.
        /// </summary>
        /// <remarks>
        /// An enum is the discriminator. The client registers a JsonStringEnumConverter, so the
        /// member reaches the wire as a string, while the same payload under a bare
        /// JsonSerializerOptions writes a number. The negative control is what shows the first
        /// assertion is not passing on options a caller could have supplied.
        /// </remarks>
        [Fact]
        public async Task Command_payload_serializes_through_the_client_registered_options()
        {
            using LoopbackCapture capture = new(status: 201, body: CommandAcceptedBody);

            var payload = new { seriesId = DispatchedSeriesId, kind = PayloadProbeKind.Enabled };

            await using ServiceProvider provider = BuildProvider(capture);
            await Dispatcher(provider).SendCommandAsync(DispatchedCommandName, payload);

            string body = CapturedRequest.Body(await capture.FirstRequest);

            using JsonDocument sent = JsonDocument.Parse(body);

            Assert.True(
                sent.RootElement.TryGetProperty("kind", out JsonElement kind),
                $"The captured request body carries no kind member. Body: {body}");

            Assert.Equal(JsonValueKind.String, kind.ValueKind);
            Assert.Equal("Enabled", kind.GetString());

            using JsonDocument defaults =
                JsonDocument.Parse(JsonSerializer.Serialize(payload, new JsonSerializerOptions()));

            Assert.Equal(JsonValueKind.Number, defaults.RootElement.GetProperty("kind").ValueKind);
        }

        /// <summary>
        /// The dispatch declares JSON.
        /// </summary>
        /// <remarks>
        /// It builds its own StringContent, whose default header is text/plain, and the server
        /// answers 415 to that. The create case above covers the generated operations and says
        /// nothing about this request.
        /// </remarks>
        [Fact]
        public async Task Command_dispatch_content_type_is_application_json()
        {
            using LoopbackCapture capture = new(status: 201, body: CommandAcceptedBody);

            await using ServiceProvider provider = BuildProvider(capture);
            await Dispatcher(provider)
                .SendCommandAsync(DispatchedCommandName, new { seriesId = DispatchedSeriesId });

            string only = Assert.Single(
                CapturedRequest.HeaderLines(await capture.FirstRequest, "Content-Type"));

            Assert.Equal("Content-Type: application/json", only);
        }

        /// <summary>
        /// A dispatch raises the same response event a generated operation raises.
        /// </summary>
        /// <remarks>
        /// The dispatch assembles its own request rather than going through the generated create,
        /// so the post-response steps that method runs are ones the dispatch has to run itself.
        /// Without them a dispatch would be the one call a consumer watching CommandApiEvents could
        /// not see.
        /// </remarks>
        [Fact]
        public async Task Command_dispatch_raises_the_response_event()
        {
            using LoopbackCapture capture = new(status: 201, body: CommandAcceptedBody);

            await using ServiceProvider provider = BuildProvider(capture);

            List<ApiResponseEventArgs> raised = new();
            provider.GetRequiredService<CommandApiEvents>().OnCreateCommand += (_, args) => raised.Add(args);

            ICreateCommandApiResponse response = await Dispatcher(provider)
                .SendCommandAsync(DispatchedCommandName, new { seriesId = DispatchedSeriesId });

            ApiResponseEventArgs only = Assert.Single(raised);

            // The event must carry the response the caller got, not a second one built for it.
            Assert.Same(response, only.ApiResponse);
        }

        /// <summary>
        /// A dispatch that throws raises the error event and rethrows unchanged.
        /// </summary>
        /// <remarks>
        /// The colliding payload is used because it fails before a socket is opened, which is where
        /// the generated operation's own validation failures land too: its validate call sits
        /// inside the try that raises this event.
        /// </remarks>
        [Fact]
        public async Task Command_dispatch_failure_raises_the_error_event_and_rethrows()
        {
            using LoopbackCapture capture = new(status: 201, body: CommandAcceptedBody);

            await using ServiceProvider provider = BuildProvider(capture);

            List<ExceptionEventArgs> raised = new();
            provider.GetRequiredService<CommandApiEvents>().OnErrorCreateCommand += (_, args) => raised.Add(args);

            ArgumentException thrown = await Assert.ThrowsAsync<ArgumentException>(
                () => Dispatcher(provider).SendCommandAsync(
                    DispatchedCommandName,
                    new { Name = "collision" }));

            ExceptionEventArgs only = Assert.Single(raised);

            Assert.Same(thrown, only.Exception);

            Assert.Empty(capture.Requests);
        }

        /// <summary>
        /// An enum the client's registered converter writes as a string and plain serializer
        /// defaults write as a number.
        /// </summary>
        private enum PayloadProbeKind
        {
            /// <summary>The default, present so Enabled is not the zero value.</summary>
            Unset = 0,

            /// <summary>The value the dispatch case sends.</summary>
            Enabled = 1,
        }

        /// <summary>
        /// Resolves the command client the dispatch cases call.
        /// </summary>
        /// <param name="provider">The provider to resolve from.</param>
        /// <returns>The registered command client, as the concrete class.</returns>
        /// <remarks>
        /// The class is resolved directly, as a consumer does, because AddWhisparr2 registers it
        /// alongside the generated ICommandApi. Resolving through the container is what keeps the
        /// registration in the path.
        /// </remarks>
        private static CommandApi Dispatcher(ServiceProvider provider)
        {
            return provider.GetRequiredService<CommandApi>();
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
