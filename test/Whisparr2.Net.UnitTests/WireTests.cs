// Hand-written test code. Nothing here is generator output; see .claude/CLAUDE.md,
// section "Generated code rules".

#nullable enable

using System.Runtime.CompilerServices;
using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net.Api;
using Whisparr2.Net.Client;
using Whisparr2.Net.Extensions;

namespace Whisparr2.Net.UnitTests
{
    /// <summary>
    /// Assertions over the literal bytes a configured client puts on a socket.
    /// </summary>
    /// <remarks>
    /// Every case but the negative control registers through the same single AddWhisparr2 call a
    /// consumer makes. A case that hand-wired the registration would not be evidence about the
    /// registration.
    /// </remarks>
    public sealed class WireTests
    {
        /// <summary>
        /// An obvious non-secret. It carries upper case, lower case, digits and a hyphen, which is
        /// what makes the byte-identity assertion mean anything.
        /// </summary>
        private const string SentinelKey = "SENTINEL-Key-123";

        /// <summary>How many calls the concurrency cases issue at once.</summary>
        private const int Concurrency = 8;

        /// <summary>
        /// A base URL for the case that resolves clients without issuing a request. Port 1 is not
        /// a port anything on this machine serves, and nothing here connects to it in any case.
        /// </summary>
        private const string UnusedBaseUrl = "http://127.0.0.1:1";

        /// <summary>How long a capture waits for its expected requests before failing.</summary>
        private static readonly TimeSpan CaptureTimeout = TimeSpan.FromSeconds(30);

        /// <summary>
        /// The credential Whisparr accepts, in the shape Whisparr accepts it. This is the case the
        /// whole loopback helper exists for.
        /// </summary>
        /// <remarks>
        /// The key header is compared for equality against the whole line rather than tested for
        /// containment of the sentinel. A containment test passes against a value that carries a
        /// prefix in front of the key, which is the one defect this case exists to rule out.
        /// </remarks>
        [Fact]
        public async Task Configured_key_reaches_the_wire_as_X_Api_Key_with_no_prefix()
        {
            using LoopbackCapture capture = new();

            await using ServiceProvider provider = BuildProvider(capture);
            await provider.GetRequiredService<ISystemApi>().GetSystemStatusAsync();

            string request = await capture.FirstRequest;

            Assert.Contains("GET /api/v3/system/status HTTP/1.1", request, StringComparison.Ordinal);

            IReadOnlyList<string> headers = CapturedRequest.HeaderLines(request, "X-Api-Key");
            string only = Assert.Single(headers);
            Assert.Equal("X-Api-Key: " + SentinelKey, only);

            Assert.DoesNotContain("Bearer", request, StringComparison.Ordinal);
            Assert.DoesNotContain("apikey", request, StringComparison.OrdinalIgnoreCase);
        }

        /// <summary>
        /// The negative control. It exists so the case above cannot pass by the assertion being
        /// blind to a prefix: the same listener and the same helper must be able to see one.
        /// </summary>
        /// <remarks>
        /// The prefixed form is the generated constructor's default, and it is measured to return
        /// 401 with a zero-byte body against a real Whisparr instance, so it fails in a way that
        /// reads as a permissions problem rather than as a client defect.
        /// </remarks>
        [Fact]
        public async Task Prefixed_token_is_visible_to_the_same_assertion_negative_control()
        {
            using LoopbackCapture capture = new();

            // No AddWhisparr2 here. This wires the raw generated path by hand so the prefix the
            // registration entry point suppresses is the one thing that differs.
            ServiceCollection services = new();
            services.AddLogging();
            services.AddSingleton<TokenProvider<ApiKeyToken>>(new PrefixedTokenProvider(SentinelKey));
            services.AddApi(cfg => cfg.AddApiHttpClients(
                client => client.BaseAddress = new Uri(capture.BaseUrl),
                null));

            await using ServiceProvider provider = services.BuildServiceProvider();
            await provider.GetRequiredService<ISystemApi>().GetSystemStatusAsync();

            string request = await capture.FirstRequest;

            IReadOnlyList<string> headers = CapturedRequest.HeaderLines(request, "X-Api-Key");
            string only = Assert.Single(headers);
            Assert.Equal("X-Api-Key: Bearer " + SentinelKey, only);
        }

        /// <summary>
        /// Eight requests in flight at once all carry one identical, unprefixed credential.
        /// </summary>
        /// <remarks>
        /// The purpose is the raw value, not throughput. Eight identical credentials across eight
        /// connections is what pins the header value to being computed once when the token is
        /// built rather than assembled per call. Asserting one request line per recorded text is
        /// what shows the capture recorded each connection separately instead of interleaving
        /// bytes from concurrent sockets into a single buffer.
        /// </remarks>
        [Fact]
        public async Task Eight_concurrent_calls_all_carry_the_identical_key_and_no_prefix()
        {
            using LoopbackCapture capture = new();

            await using ServiceProvider provider = BuildProvider(capture);
            ISystemApi api = provider.GetRequiredService<ISystemApi>();

            await Task.WhenAll(Enumerable.Range(0, Concurrency).Select(_ => api.GetSystemStatusAsync()));

            IReadOnlyList<string> requests = await capture.WaitForRequestsAsync(Concurrency, CaptureTimeout);

            Assert.Equal(Concurrency, requests.Count);
            Assert.All(requests, request =>
            {
                Assert.Single(CapturedRequest.RequestLines(request));
                string only = Assert.Single(CapturedRequest.HeaderLines(request, "X-Api-Key"));
                Assert.Equal("X-Api-Key: " + SentinelKey, only);
                Assert.DoesNotContain("Bearer", request, StringComparison.Ordinal);
                Assert.DoesNotContain("apikey", request, StringComparison.OrdinalIgnoreCase);
            });
        }

        /// <summary>
        /// A collection on which only AddWhisparr2 was called resolves typed clients, with no
        /// AddLogging call of its own and no Generic Host.
        /// </summary>
        /// <remarks>
        /// This is the only thing in the suite that notices if the AddLogging call inside
        /// AddWhisparr2 is dropped, because every generated api constructor takes an ILogger.
        /// Three of the generated interfaces are resolved as a sample; a sweep of all of them is
        /// not claimed.
        /// </remarks>
        [Fact]
        public void Registration_resolves_three_named_typed_clients()
        {
            ServiceCollection services = new();
            services.AddWhisparr2(new Whisparr2Options
            {
                BaseUrl = UnusedBaseUrl,
                ApiKey = SentinelKey,
            });

            using ServiceProvider provider = services.BuildServiceProvider();

            Assert.NotNull(provider.GetRequiredService<ISystemApi>());
            Assert.NotNull(provider.GetRequiredService<ITagApi>());
            Assert.NotNull(provider.GetRequiredService<IQualityProfileApi>());
        }

        /// <summary>
        /// A handler attached through the options hook sits in the pipeline of the typed client
        /// every call goes through, and eight concurrent calls all reach it.
        /// </summary>
        /// <remarks>
        /// The counter is what proves the handler was reached rather than merely registered, so
        /// the hook cannot be accepted and quietly dropped. The counting handler is a handler
        /// under test, not a substitute for the socket: every byte asserted here was still
        /// recorded by the listener.
        /// </remarks>
        [Fact]
        public async Task A_handler_attached_through_the_hook_sees_every_call()
        {
            using LoopbackCapture capture = new();

            StrongBox<int> seen = new(0);

            ServiceCollection services = new();
            services.AddWhisparr2(new Whisparr2Options
            {
                BaseUrl = capture.BaseUrl,
                ApiKey = SentinelKey,
                ConfigureHttpClient = builder => AttachCountingHandler(builder, seen),
            });

            await using ServiceProvider provider = services.BuildServiceProvider();
            ISystemApi api = provider.GetRequiredService<ISystemApi>();

            await Task.WhenAll(Enumerable.Range(0, Concurrency).Select(_ => api.GetSystemStatusAsync()));

            IReadOnlyList<string> requests = await capture.WaitForRequestsAsync(Concurrency, CaptureTimeout);

            Assert.Equal(Concurrency, requests.Count);
            Assert.Equal(Concurrency, Volatile.Read(ref seen.Value));
            Assert.All(requests, request =>
                Assert.Equal(
                    "X-Api-Key: " + SentinelKey,
                    Assert.Single(CapturedRequest.HeaderLines(request, "X-Api-Key"))));
        }

        /// <summary>
        /// A measured limitation of the generated registration layer, recorded as a fact rather
        /// than left an undocumented surprise.
        /// </summary>
        /// <remarks>
        /// Both the named client configuration and the token provider registration are last-wins
        /// and there is no keyed-instance concept, so a second call silently replaces the first
        /// for both the base address and the key. Two Whisparr instances need two service
        /// collections. The assertion that the first listener recorded nothing is what makes the
        /// last-wins sentence in the registration documentation true rather than merely written.
        /// </remarks>
        [Fact]
        public async Task A_second_AddWhisparr2_last_wins_including_the_client_configuration()
        {
            using LoopbackCapture first = new();
            using LoopbackCapture second = new();

            const string SecondKey = "SECOND-Key-456";

            ServiceCollection services = new();
            services.AddWhisparr2(new Whisparr2Options
            {
                BaseUrl = first.BaseUrl,
                ApiKey = SentinelKey,
            });
            services.AddWhisparr2(new Whisparr2Options
            {
                BaseUrl = second.BaseUrl,
                ApiKey = SecondKey,
            });

            await using ServiceProvider provider = services.BuildServiceProvider();
            await provider.GetRequiredService<ISystemApi>().GetSystemStatusAsync();

            string request = await second.FirstRequest;

            Assert.Equal(
                "X-Api-Key: " + SecondKey,
                Assert.Single(CapturedRequest.HeaderLines(request, "X-Api-Key")));
            Assert.Empty(first.Requests);
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
        /// Attaches a handler that counts what passes through it.
        /// </summary>
        /// <param name="builder">The builder for one typed client.</param>
        /// <param name="seen">The counter every attached handler increments.</param>
        private static void AttachCountingHandler(IHttpClientBuilder builder, StrongBox<int> seen)
        {
            // A factory rather than an instance: the hook runs once per typed client, and a single
            // DelegatingHandler cannot sit in two pipelines.
            builder.AddHttpMessageHandler(() => new CountingHandler(seen));
        }

        /// <summary>
        /// Counts the requests that reach it, which is how a case tells an attached handler from a
        /// registered one.
        /// </summary>
        private sealed class CountingHandler(StrongBox<int> seen) : DelegatingHandler
        {
            protected override Task<HttpResponseMessage> SendAsync(
                HttpRequestMessage request,
                CancellationToken cancellationToken)
            {
                Interlocked.Increment(ref seen.Value);

                return base.SendAsync(request, cancellationToken);
            }
        }

        /// <summary>
        /// Hands out a token built without naming the generated prefix argument, so the generated
        /// default applies. Omitting the argument is what makes the control a control.
        /// </summary>
        private sealed class PrefixedTokenProvider : TokenProvider<ApiKeyToken>
        {
            private readonly ApiKeyToken _token;

            public PrefixedTokenProvider(string apiKey)
            {
                _token = new ApiKeyToken(apiKey, ClientUtils.ApiKeyHeader.X_Api_Key);
            }

            // protected, not protected internal: the base member is protected internal and this
            // project sits outside the library assembly, where that degrades to protected.
            protected override ValueTask<ApiKeyToken> GetAsync(
                string header = "",
                CancellationToken cancellation = default)
            {
                return new ValueTask<ApiKeyToken>(_token);
            }
        }
    }
}
