// Hand-written. Nothing in this directory is generator output; see .claude/CLAUDE.md, section
// "Generated code rules". Do not add the generator's file-marker header to this file: it is a
// false statement here, and it switches off the analyzer coverage this file has. .editorconfig
// marks only src/Whisparr2.Net/** as generated code, so everything here is analysed like
// ordinary source.

#nullable enable

using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net.Client;
using Whisparr2.Net.Extensions;

namespace Whisparr2.Net
{
    /// <summary>
    /// Supplies the one API key token the generated operations ask for.
    /// </summary>
    /// <remarks>
    /// Registered directly as the singleton TokenProvider, with no TokenContainer alongside it.
    /// That is deliberate: the generated AddApi installs its own RateLimitProvider only when it
    /// finds a container and no provider, and that provider starts a timer per token and hands each
    /// token out through a bounded channel. Its default interval is 40 milliseconds, so a single
    /// token is released roughly 25 times a second and every request beyond that waits. The cost of
    /// skipping it is the only 429 backoff in the stack. A consumer that needs one attaches it
    /// through <see cref="Whisparr2Options.ConfigureHttpClient"/>; the usual transient-error
    /// definition covers 5xx and 408 and does not cover 429, so it is not a substitute.
    /// </remarks>
    internal sealed class Whisparr2TokenProvider : TokenProvider<ApiKeyToken>
    {
        private readonly string _header;
        private readonly ApiKeyToken _token;

        /// <summary>
        /// Builds the single token, once, at registration time.
        /// </summary>
        /// <param name="apiKey">The validated API key.</param>
        internal Whisparr2TokenProvider(string apiKey)
        {
            _header = ClientUtils.ApiKeyHeaderToString(ClientUtils.ApiKeyHeader.X_Api_Key);

            // prefix: string.Empty is the whole of the credential shape. The generated constructor
            // defaults that parameter to a bearer scheme token and builds its raw value by
            // concatenating it in front of the key, and Whisparr answers that form with 401 and a
            // zero-byte body, which reads as a permissions problem rather than a client defect.
            // Building the token here also fixes the raw value once rather than per call.
            _token = new ApiKeyToken(apiKey, ClientUtils.ApiKeyHeader.X_Api_Key, prefix: string.Empty);
        }

        /// <summary>
        /// Returns the token for the X-Api-Key header, and refuses any other header name.
        /// </summary>
        /// <param name="header">The header name the caller wants a token for.</param>
        /// <param name="cancellation">Unused; the token is already in memory.</param>
        /// <returns>The single API key token.</returns>
        /// <exception cref="KeyNotFoundException">The caller asked for a header this provider holds no token for.</exception>
        protected internal override ValueTask<ApiKeyToken> GetAsync(
            string header = "",
            CancellationToken cancellation = default)
        {
            // All 227 generated operations ask for this one header today. A provider that answered
            // any header name would silently satisfy a regenerated tree that had moved the
            // credential into the query string, where every call would still succeed while the key
            // reached server access logs, proxy logs and browser history. Whisparr accepts the key
            // either way, and a correct header with an empty query value returns 401 while a wrong
            // header with a good query value returns 200, so the query path wins and does so
            // quietly. Refusing turns that regression into a loud failure. The accepted name is
            // derived from the generated enum rather than written as a literal, so the two cannot
            // drift.
            //
            // This refusal has no test that calls it, and that is a constraint rather than an
            // omission. The base member is protected internal, so the test project, which sits
            // outside this assembly, cannot reach it, and the public surface is not widened to
            // make it reachable. What is verified instead is the outcome it protects: a census of
            // the generated call sites, and a wire assertion that no query parameter carries the
            // key.
            if (!StringComparer.Ordinal.Equals(header, _header))
            {
                throw new KeyNotFoundException($"Could not locate a token for header '{header}'.");
            }

            return new ValueTask<ApiKeyToken>(_token);
        }
    }

    /// <summary>
    /// Registers the Whisparr client on an <see cref="IServiceCollection"/>.
    /// </summary>
    public static class Whisparr2ServiceCollectionExtensions
    {
        /// <summary>
        /// Registers every generated typed client, the API key token and the base address.
        /// </summary>
        /// <param name="services">The collection to register on.</param>
        /// <param name="options">The base URL, the API key and the optional client builder hook.</param>
        /// <returns>The same collection, so calls chain.</returns>
        /// <exception cref="ArgumentNullException"><paramref name="services"/> or <paramref name="options"/> is null, or a required setting is null.</exception>
        /// <exception cref="ArgumentException">A required setting is empty, whitespace, or not an absolute http or https URL.</exception>
        /// <remarks>
        /// <para>
        /// Nothing on this path can produce an X-Api-Key header carrying a scheme prefix in front
        /// of the key. The one place a token is built passes an empty prefix, and
        /// <see cref="Whisparr2Options"/> exposes no prefix and no header name. ApiKeyToken and
        /// HostConfiguration.AddTokens are both public generated types, so a caller who bypasses
        /// this method can still construct the defaulted token; the guarantee is about this
        /// registration path and not about the whole assembly.
        /// </para>
        /// <para>
        /// One call per <see cref="IServiceCollection"/> is supported. A second call silently wins
        /// for both the base address and the token provider, because the named HttpClient
        /// configuration and the token provider registration are both last-wins and the generated
        /// registration layer has no keyed-instance concept. Two Whisparr instances therefore need
        /// two service collections.
        /// </para>
        /// <para>
        /// The base URL is required and is never guessed. Validation runs before anything is
        /// registered, so a misconfiguration fails here rather than on the first request.
        /// </para>
        /// <para>
        /// Read a response through EnsureSuccess rather than through the generated Ok, TryOk or
        /// IsOk members. Those three test for exactly 200, and Whisparr answers 201 to a create and
        /// 202 to an update, so a successful write reads as a failure through them and returns
        /// null. EnsureSuccess reads a body on any success status.
        /// </para>
        /// <para>
        /// Every generated operation also exposes an OrDefaultAsync variant that catches every
        /// exception and returns null. Prefer the plain variant; the OrDefaultAsync form cannot
        /// tell a failure from an empty result.
        /// </para>
        /// </remarks>
        public static IServiceCollection AddWhisparr2(this IServiceCollection services, Whisparr2Options options)
        {
            ArgumentNullException.ThrowIfNull(services);
            ArgumentNullException.ThrowIfNull(options);

            // Validate first and register nothing until it returns. A half-registered collection
            // after a throw is what turns a configuration mistake into a runtime surprise.
            Uri baseUri = options.Validate();

            // Every generated api constructor takes an ILogger, so a consumer on a plain
            // ServiceCollection who never calls AddLogging would fail at resolve time. AddLogging
            // uses TryAdd internally, so a consumer who already called it is unaffected.
            services.AddLogging();

            services.AddSingleton<TokenProvider<ApiKeyToken>>(new Whisparr2TokenProvider(options.ApiKey));

            services.AddApi(cfg => cfg.AddApiHttpClients(
                client => client.BaseAddress = baseUri,
                options.ConfigureHttpClient));

            return services;
        }
    }
}
