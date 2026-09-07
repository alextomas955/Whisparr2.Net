// Hand-written. Nothing in this directory is generator output; see .claude/CLAUDE.md, section
// "Generated code rules". Do not add the generator's file-marker header to this file: it is a
// false statement here, and it switches off the analyzer coverage this file has. .editorconfig
// marks only src/Whisparr2.Net/** as generated code, so everything here is analysed like
// ordinary source.

#nullable enable

using System;
using Microsoft.Extensions.DependencyInjection;

namespace Whisparr2.Net
{
    /// <summary>
    /// The settings a consumer supplies when registering the Whisparr client.
    /// </summary>
    /// <remarks>
    /// Both settings are required and neither is ever guessed. Construct this type in an object
    /// initialiser and hand it to
    /// <see cref="Whisparr2ServiceCollectionExtensions.AddWhisparr2(IServiceCollection, Whisparr2Options)"/>.
    /// </remarks>
    public sealed class Whisparr2Options
    {
        /// <summary>
        /// The base URL of the Whisparr instance, for example "http://127.0.0.1:6969".
        /// </summary>
        /// <remarks>
        /// Both http and https are accepted, because the ordinary Whisparr deployment is plain http
        /// on a loopback or LAN address and refusing that would refuse the normal case. The choice
        /// is the caller's, and it carries a consequence worth stating: the key travels in a request
        /// header, so over plain http it is on the wire in the clear and anything between the caller
        /// and the instance can read it. Loopback is fine. Across a network, prefer https or a
        /// tunnel.
        /// </remarks>
        /// <value>An absolute http or https URL. Required.</value>
        public required string BaseUrl { get; init; }

        /// <summary>
        /// The Whisparr API key. It is sent as the X-Api-Key request header and never as a query
        /// parameter, because a credential in a URL is written into server access logs, proxy
        /// logs and browser history.
        /// </summary>
        /// <value>The key exactly as Whisparr issued it. Required, and never trimmed or repaired.</value>
        public required string ApiKey { get; init; }

        /// <summary>
        /// An optional hook onto the builder for each typed client, where a message handler or a
        /// resilience policy attaches.
        /// </summary>
        /// <value>An action invoked once per typed client, or null to attach nothing.</value>
        /// <remarks>
        /// The library carries no resilience dependency, so the builder handed to this action
        /// offers whatever the consumer's own project references. Reference a resilience package
        /// directly and attach its policies here, with AddPolicyHandler for Polly through
        /// Microsoft.Extensions.Http.Polly, or with the equivalent hook of whatever package was
        /// chosen.
        /// </remarks>
        public Action<IHttpClientBuilder>? ConfigureHttpClient { get; init; }

        /// <summary>
        /// Validates both required settings and returns the parsed base URL.
        /// </summary>
        /// <returns>The base URL parsed as an absolute URI, so nothing downstream reparses the string.</returns>
        /// <exception cref="ArgumentNullException"><see cref="BaseUrl"/> or <see cref="ApiKey"/> is null.</exception>
        /// <exception cref="ArgumentException">
        /// <see cref="BaseUrl"/> or <see cref="ApiKey"/> is empty or whitespace, or
        /// <see cref="BaseUrl"/> is not an absolute http or https URL.
        /// </exception>
        /// <remarks>
        /// This runtime check is not redundant with the required modifier on the two properties.
        /// The modifier is a compile-time construct only, and ConfigurationBinder builds this type
        /// through Activator.CreateInstance, which bypasses it entirely and can produce an
        /// instance whose key is null. This is the library's one input-validation boundary, and it
        /// is the reason no defensive null check goes anywhere else in the layer. No message
        /// thrown here contains the API key.
        /// </remarks>
        public Uri Validate()
        {
            if (BaseUrl is null)
            {
                throw new ArgumentNullException(
                    nameof(BaseUrl),
                    "Whisparr2Options.BaseUrl is required. The client never guesses a host or port.");
            }

            if (ApiKey is null)
            {
                throw new ArgumentNullException(
                    nameof(ApiKey),
                    "Whisparr2Options.ApiKey is required. Whisparr rejects a request that carries no key.");
            }

            if (string.IsNullOrWhiteSpace(BaseUrl))
            {
                throw new ArgumentException(
                    "Whisparr2Options.BaseUrl is empty or whitespace. Set it to the instance base URL, "
                        + "for example \"http://127.0.0.1:6969\".",
                    nameof(BaseUrl));
            }

            if (string.IsNullOrWhiteSpace(ApiKey))
            {
                throw new ArgumentException(
                    "Whisparr2Options.ApiKey is empty or whitespace. The value is used exactly as supplied "
                        + "and is never trimmed.",
                    nameof(ApiKey));
            }

            // Parseability alone is not enough. Uri.TryCreate("localhost:6969", UriKind.Absolute)
            // succeeds and yields a scheme equal to the host name, so a bare host and port string
            // would pass and then fail obscurely inside HttpClient.
            if (!Uri.TryCreate(BaseUrl, UriKind.Absolute, out Uri? parsed)
                || (parsed.Scheme != Uri.UriSchemeHttp && parsed.Scheme != Uri.UriSchemeHttps))
            {
                throw new ArgumentException(
                    $"Whisparr2Options.BaseUrl is not an absolute http or https URL: \"{BaseUrl}\".",
                    nameof(BaseUrl));
            }

            return parsed;
        }
    }
}
