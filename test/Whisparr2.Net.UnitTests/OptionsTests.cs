// Hand-written test code. Nothing here is generator output; see .claude/CLAUDE.md,
// section "Generated code rules".

#nullable enable

using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net.Client;
using Whisparr2.Net.Extensions;

namespace Whisparr2.Net.UnitTests
{
    /// <summary>
    /// The refusals AddWhisparr2 performs before it registers anything, and the control that shows
    /// the failure those refusals prevent is real rather than argued.
    /// </summary>
    public sealed class OptionsTests
    {
        /// <summary>
        /// An obvious non-secret. The leak control searches for this exact value, so it must be
        /// something no other part of the file produces by accident.
        /// </summary>
        private const string SentinelKey = "SENTINEL-Key-123";

        /// <summary>
        /// A base URL that passes validation. Nothing in this file issues a request, so port 1
        /// only has to parse.
        /// </summary>
        private const string ValidBaseUrl = "http://127.0.0.1:1";

        /// <summary>
        /// Null, empty and whitespace keys are all refused, and the value is never trimmed or
        /// repaired. The null case passes null! because the required modifier is compile-time
        /// only: this is the ConfigurationBinder path in miniature, since reflection-based
        /// construction bypasses required entirely.
        /// </summary>
        [Fact]
        public void AddWhisparr2_throws_when_the_api_key_is_blank()
        {
            ArgumentNullException fromNull = Assert.Throws<ArgumentNullException>(
                () =>
                {
                    new ServiceCollection().AddWhisparr2(
                        new Whisparr2Options { BaseUrl = ValidBaseUrl, ApiKey = null! });
                });
            Assert.Contains("ApiKey", fromNull.Message, StringComparison.Ordinal);

            foreach (string blank in new[] { string.Empty, "   " })
            {
                ArgumentException thrown = Assert.Throws<ArgumentException>(
                    () =>
                    {
                        new ServiceCollection().AddWhisparr2(
                            new Whisparr2Options { BaseUrl = ValidBaseUrl, ApiKey = blank });
                    });
                Assert.Contains("ApiKey", thrown.Message, StringComparison.Ordinal);
            }
        }

        /// <summary>
        /// The symmetric counterpart for the base URL. The null case is the one the fallback risk
        /// is actually about: an absent base URL is what reaches the generated default constant,
        /// so it is exercised rather than assumed to follow from the blank case.
        /// </summary>
        [Fact]
        public void AddWhisparr2_throws_when_the_base_url_is_blank()
        {
            ArgumentNullException fromNull = Assert.Throws<ArgumentNullException>(
                () =>
                {
                    new ServiceCollection().AddWhisparr2(
                        new Whisparr2Options { BaseUrl = null!, ApiKey = SentinelKey });
                });
            Assert.Contains("BaseUrl", fromNull.Message, StringComparison.Ordinal);

            foreach (string blank in new[] { string.Empty, "   " })
            {
                ArgumentException thrown = Assert.Throws<ArgumentException>(
                    () =>
                    {
                        new ServiceCollection().AddWhisparr2(
                            new Whisparr2Options { BaseUrl = blank, ApiKey = SentinelKey });
                    });
                Assert.Contains("BaseUrl", thrown.Message, StringComparison.Ordinal);
            }
        }

        /// <summary>
        /// A later reader will be tempted to delete this as redundant with the blank case. It is
        /// not. Uri.TryCreate("localhost:6969", UriKind.Absolute) succeeds and yields a scheme
        /// equal to the host name, so parseability alone would accept this string and the client
        /// would then fail obscurely inside HttpClient. The BCL behaviour is asserted first so
        /// that a reader meets the reason before meeting the refusal.
        /// </summary>
        [Fact]
        public void AddWhisparr2_throws_when_the_base_url_has_no_http_scheme()
        {
            Assert.True(Uri.TryCreate("localhost:6969", UriKind.Absolute, out Uri? parsed));
            Assert.Equal("localhost", parsed!.Scheme);

            ArgumentException thrown = Assert.Throws<ArgumentException>(
                () =>
                {
                    new ServiceCollection().AddWhisparr2(
                        new Whisparr2Options { BaseUrl = "localhost:6969", ApiKey = SentinelKey });
                });
            Assert.Contains("BaseUrl", thrown.Message, StringComparison.Ordinal);
        }

        /// <summary>
        /// A URL that parses cleanly but does not speak http.
        /// </summary>
        [Fact]
        public void AddWhisparr2_throws_when_the_base_url_uses_a_non_http_scheme()
        {
            foreach (string url in new[] { "ftp://127.0.0.1:6969/", "file:///c:/whisparr" })
            {
                ArgumentException thrown = Assert.Throws<ArgumentException>(
                    () =>
                    {
                        new ServiceCollection().AddWhisparr2(
                            new Whisparr2Options { BaseUrl = url, ApiKey = SentinelKey });
                    });
                Assert.Contains("BaseUrl", thrown.Message, StringComparison.Ordinal);
            }
        }

        /// <summary>
        /// An https base URL is accepted and is what the typed clients are pointed at.
        /// </summary>
        /// <remarks>
        /// Every other case in the suite uses http, because the loopback listener speaks nothing
        /// else, so a scheme check that had narrowed to http alone would refuse every consumer
        /// behind TLS and no other case would notice. No request is issued: the registered base
        /// address is read back instead.
        /// </remarks>
        [Fact]
        public void AddWhisparr2_accepts_an_https_base_url()
        {
            const string HttpsBaseUrl = "https://whisparr.example:6969/";

            ServiceCollection services = new();
            services.AddWhisparr2(new Whisparr2Options { BaseUrl = HttpsBaseUrl, ApiKey = SentinelKey });

            using ServiceProvider provider = services.BuildServiceProvider();
            IHttpClientFactory factory = provider.GetRequiredService<IHttpClientFactory>();
            using HttpClient client = factory.CreateClient("Whisparr2.Net.Api.ISystemApi");

            Assert.Equal(new Uri(HttpsBaseUrl), client.BaseAddress);
        }

        /// <summary>
        /// The refusal happens before any registration, so a rejected configuration leaves the
        /// collection untouched rather than half wired. Without this case the validation could
        /// move below the registration calls and nothing would notice.
        /// </summary>
        [Fact]
        public void AddWhisparr2_throws_before_it_registers_anything()
        {
            ServiceCollection services = new();

            Assert.Throws<ArgumentException>(
                () =>
                {
                    services.AddWhisparr2(
                        new Whisparr2Options { BaseUrl = "localhost:6969", ApiKey = SentinelKey });
                });

            Assert.DoesNotContain(
                services,
                descriptor => descriptor.ServiceType == typeof(TokenProvider<ApiKeyToken>));
            Assert.Empty(services);
        }

        /// <summary>
        /// No refusal message may carry the credential into a log or an error surface.
        /// </summary>
        [Fact]
        public void Validation_messages_never_contain_the_api_key()
        {
            List<string> messages = new();

            foreach (Whisparr2Options options in new[]
            {
                new Whisparr2Options { BaseUrl = null!, ApiKey = SentinelKey },
                new Whisparr2Options { BaseUrl = string.Empty, ApiKey = SentinelKey },
                new Whisparr2Options { BaseUrl = "localhost:6969", ApiKey = SentinelKey },
                new Whisparr2Options { BaseUrl = "ftp://127.0.0.1:6969/", ApiKey = SentinelKey },
                new Whisparr2Options { BaseUrl = ValidBaseUrl, ApiKey = "   " },
            })
            {
                ArgumentException thrown = Assert.ThrowsAny<ArgumentException>(
                    () =>
                    {
                        new ServiceCollection().AddWhisparr2(options);
                    });
                messages.Add(thrown.Message);
            }

            Assert.Equal(5, messages.Count);
            Assert.All(
                messages,
                message => Assert.DoesNotContain(SentinelKey, message, StringComparison.Ordinal));
        }

        /// <summary>
        /// The base URL negative control. It shows the default this validation exists to prevent
        /// is real: with no base URL supplied, the generated registration substitutes its own
        /// constant and the client would deliver the API key to whatever is listening there.
        /// No request is issued. That is deliberate rather than incidental, because the machine
        /// running this suite may well have something live on the generated default port.
        /// </summary>
        [Fact]
        public void Generated_default_base_address_is_real_negative_control()
        {
            ServiceCollection services = new();
            services.AddLogging();
            services.AddSingleton<TokenProvider<ApiKeyToken>>(new StubTokenProvider(SentinelKey));
            services.AddApi(cfg => cfg.AddApiHttpClients());

            using ServiceProvider provider = services.BuildServiceProvider();
            IHttpClientFactory factory = provider.GetRequiredService<IHttpClientFactory>();
            using HttpClient client = factory.CreateClient("Whisparr2.Net.Api.ISystemApi");

            Assert.Equal(new Uri(ClientUtils.BASE_ADDRESS), client.BaseAddress);
        }

        /// <summary>
        /// A token provider that answers with a token and nothing else, so the control above can
        /// wire the generated path without AddWhisparr2.
        /// </summary>
        private sealed class StubTokenProvider : TokenProvider<ApiKeyToken>
        {
            private readonly ApiKeyToken _token;

            public StubTokenProvider(string apiKey)
            {
                _token = new ApiKeyToken(apiKey, ClientUtils.ApiKeyHeader.X_Api_Key, prefix: string.Empty);
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
