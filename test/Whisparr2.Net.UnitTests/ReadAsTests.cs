// Hand-written test code. Nothing here is generator output; see .claude/CLAUDE.md,
// section "Generated code rules".

#nullable enable

using System.Net;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net.Api;
using Whisparr2.Net.Client;

namespace Whisparr2.Net.UnitTests
{
    /// <summary>
    /// Assertions over the accessor that makes the 79 content-less operations readable.
    /// </summary>
    /// <remarks>
    /// 79 of the 227 operations declare a 200 with no content, so the generator emits no typed
    /// accessor for them and nothing turns their body into a type. ApiResponse.ReadAs is that
    /// missing step. Every case here drives one of those operations against a real listener
    /// through the same single registration call a consumer makes.
    /// </remarks>
    public sealed class ReadAsTests
    {
        /// <summary>
        /// An obvious non-secret, in the same shape the other test classes use.
        /// </summary>
        private const string SentinelKey = "SENTINEL-Key-123";

        /// <summary>Two routes, camel cased, in the shape the duplicate-routes operation sends.</summary>
        private const string RouteListBody =
            "[{\"path\":\"/api/v3/tag\",\"action\":\"list\",\"method\":\"Get\"},"
                + "{\"path\":\"/api/v3/tag/{id}\",\"action\":\"delete\",\"method\":\"Post\"}]";

        /// <summary>One route whose method is a string-valued enum.</summary>
        private const string EnumRouteBody =
            "{\"path\":\"/api/v3/tag\",\"action\":\"create\",\"method\":\"Post\"}";

        /// <summary>
        /// A Graphviz DOT graph, which is what the routes operation actually answers with.
        /// </summary>
        private const string DotGraphBody = "digraph routes { rankdir=LR; tag -> tagdetail; }";

        /// <summary>
        /// A body that is not JSON, which is what reaches the serializer and fails there.
        /// </summary>
        /// <remarks>
        /// A body of literal null is resolved before any converter is dispatched and returns null,
        /// so it lands on the empty-body sibling branch with no inner exception rather than here.
        /// </remarks>
        private const string NotJsonBody = "not json at all";

        /// <summary>
        /// A method name that arrives as a string and binds through a registered converter.
        /// </summary>
        private enum ProbeMethod
        {
            /// <summary>The value a body that bound nothing leaves behind.</summary>
            Unknown = 0,

            /// <summary>A read route.</summary>
            Get = 1,

            /// <summary>A write route.</summary>
            Post = 2,
        }

        /// <summary>
        /// A content-less operation that answers JSON is readable as the type the caller names.
        /// </summary>
        /// <remarks>
        /// Two elements are asserted by value. A non-null assertion would pass against a list whose
        /// elements bound nothing, which is the failure this file exists to separate from success.
        /// </remarks>
        [Fact]
        public async Task Content_less_operation_body_is_readable_as_the_type_the_caller_names()
        {
            using LoopbackCapture capture = new(status: 200, body: RouteListBody);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemRoutesDuplicateApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemRoutesDuplicateAsync();

            List<RouteProbe> routes = ((ApiResponse)response).ReadAs<List<RouteProbe>>();

            Assert.Equal(2, routes.Count);
            Assert.Equal("/api/v3/tag", routes[0].Path);
            Assert.Equal("list", routes[0].Action);
            Assert.Equal("/api/v3/tag/{id}", routes[1].Path);
            Assert.Equal("delete", routes[1].Action);
        }

        /// <summary>
        /// A content-less operation that answers text still delivers its payload verbatim.
        /// </summary>
        /// <remarks>
        /// This is the claim the accessor rests on. Every one of the 79 reads the whole response
        /// into RawContent whether or not it is JSON, so the accessor is an extra step over a body
        /// that is already there rather than the only way to reach it. The routes operation answers
        /// a Graphviz DOT graph as text, so nothing here could bind.
        /// </remarks>
        [Fact]
        public async Task Content_less_operation_delivers_a_non_json_body_through_raw_content()
        {
            using LoopbackCapture capture = new(status: 200, body: DotGraphBody);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemRoutesApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemRoutesAsync();

            response.EnsureSuccess();

            Assert.Equal(DotGraphBody, response.RawContent);
        }

        /// <summary>
        /// A failing status is a failure, reported before anything is deserialized.
        /// </summary>
        /// <remarks>
        /// Without this the accessor could report a rejected key as a malformed body, which sends a
        /// reader to the payload instead of to the credential.
        /// </remarks>
        [Fact]
        public async Task ReadAs_reports_a_failing_status_as_a_failure()
        {
            using LoopbackCapture capture = new(status: 401, body: string.Empty);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemRoutesDuplicateApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemRoutesDuplicateAsync();

            Whisparr2ApiException error = Assert.Throws<Whisparr2ApiException>(
                () => ((ApiResponse)response).ReadAs<List<RouteProbe>>());

            Assert.False(error.IsSuccessStatusCode);
            Assert.Equal(HttpStatusCode.Unauthorized, error.StatusCode);
            Assert.Equal("/api/v3/system/routes/duplicate", error.Path);
        }

        /// <summary>
        /// An empty success is its own outcome, not a malformed body.
        /// </summary>
        /// <remarks>
        /// A delete answering an empty 200 is the ordinary case for many of these operations.
        /// Reporting it as a malformed body sends a reader looking for a defect that is not there.
        /// </remarks>
        [Fact]
        public async Task ReadAs_separates_an_empty_success_from_a_malformed_one()
        {
            using LoopbackCapture capture = new(status: 200, body: string.Empty);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemRoutesDuplicateApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemRoutesDuplicateAsync();

            Whisparr2ApiException error = Assert.Throws<Whisparr2ApiException>(
                () => ((ApiResponse)response).ReadAs<List<RouteProbe>>());

            Assert.True(error.IsSuccessStatusCode);
            Assert.Contains("empty", error.Message, StringComparison.Ordinal);
            Assert.Null(error.InnerException);
        }

        /// <summary>
        /// A malformed body produces the typed error with the serializer's exception kept.
        /// </summary>
        /// <remarks>
        /// Without the wrapping, the serializer's own exception escapes the layer carrying no
        /// status, no route template and no URI, and a consumer catching the typed error misses it.
        /// </remarks>
        [Fact]
        public async Task ReadAs_wraps_a_deserialization_failure_in_the_typed_error()
        {
            using LoopbackCapture capture = new(status: 200, body: NotJsonBody);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemRoutesDuplicateApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemRoutesDuplicateAsync();

            Whisparr2ApiException error = Assert.Throws<Whisparr2ApiException>(
                () => ((ApiResponse)response).ReadAs<List<RouteProbe>>());

            Assert.True(error.IsSuccessStatusCode);
            Assert.IsAssignableFrom<JsonException>(error.InnerException);
        }

        /// <summary>
        /// The accessor reads through the converters the client registered, not through defaults.
        /// </summary>
        /// <remarks>
        /// This is the case that holds the design decision. The accessor is a partial of the
        /// generated response base because the options are protected there. Convert it to an
        /// extension method taking options from its caller and every one of the roughly 170
        /// registered converters is lost, which changes how a date and an enum read with nothing
        /// raised. Both halves are required: the second is what shows the binding came from the
        /// registered converters rather than from what any options object would do.
        /// </remarks>
        [Fact]
        public async Task ReadAs_uses_the_serializer_options_the_client_registered()
        {
            using LoopbackCapture capture = new(status: 200, body: EnumRouteBody);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemRoutesDuplicateApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemRoutesDuplicateAsync();

            RouteProbe route = ((ApiResponse)response).ReadAs<RouteProbe>();

            Assert.Equal(ProbeMethod.Post, route.Method);
            Assert.Equal("create", route.Action);

            Assert.Throws<JsonException>(
                () => JsonSerializer.Deserialize<RouteProbe>(EnumRouteBody, new JsonSerializerOptions()));
        }

        /// <summary>
        /// A caller type with no property names binds nothing and raises nothing.
        /// </summary>
        /// <remarks>
        /// The client's options carry no naming policy and no case-insensitive matching, so a
        /// camel-cased body binds nothing into Pascal-cased members. The failure is silent, so the
        /// members are asserted at their defaults. A non-null assertion would pass against exactly
        /// this failure, because binding nothing still returns an object.
        /// </remarks>
        [Fact]
        public async Task ReadAs_binds_nothing_when_the_caller_type_omits_property_names()
        {
            using LoopbackCapture capture = new(status: 200, body: EnumRouteBody);

            await using ServiceProvider provider = BuildProvider(capture);
            IGetSystemRoutesDuplicateApiResponse response =
                await provider.GetRequiredService<ISystemApi>().GetSystemRoutesDuplicateAsync();

            UnnamedRouteProbe route = ((ApiResponse)response).ReadAs<UnnamedRouteProbe>();

            Assert.Null(route.Path);
            Assert.Null(route.Action);
            Assert.Equal(ProbeMethod.Unknown, route.Method);
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
        /// A caller-written route type that names every member it expects to bind.
        /// </summary>
        private sealed class RouteProbe
        {
            /// <summary>The route template.</summary>
            [JsonPropertyName("path")]
            public string? Path { get; set; }

            /// <summary>The action the route dispatches to.</summary>
            [JsonPropertyName("action")]
            public string? Action { get; set; }

            /// <summary>The method, which arrives as a string.</summary>
            [JsonPropertyName("method")]
            public ProbeMethod Method { get; set; }
        }

        /// <summary>
        /// The same shape with no property names, which is the trap the accessor documents.
        /// </summary>
        private sealed class UnnamedRouteProbe
        {
            /// <summary>The route template, which never binds from a camel-cased body.</summary>
            public string? Path { get; set; }

            /// <summary>The action, which never binds either.</summary>
            public string? Action { get; set; }

            /// <summary>The method, which stays at its default.</summary>
            public ProbeMethod Method { get; set; }
        }
    }
}
