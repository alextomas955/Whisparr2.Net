// Hand-written. Nothing in this directory is generator output; see .claude/CLAUDE.md, section
// "Generated code rules". Do not add the generator's file-marker header to this file: it is a
// false statement here, and it switches off the analyzer coverage this file has. .editorconfig
// marks only src/Whisparr2.Net/** as generated code, so everything here is analysed like
// ordinary source.

#nullable enable

using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using Whisparr2.Net.Client;
using Whisparr2.Net.Model;

namespace Whisparr2.Net.Api
{
    public sealed partial class CommandApi
    {
        /// <summary>
        /// Dispatches a command with its arguments.
        /// </summary>
        /// <param name="name">The command name, for example <c>RefreshSeries</c>.</param>
        /// <param name="payload">
        /// The command arguments, or null for a command that takes none. Anything that serializes
        /// to a JSON object is accepted: an anonymous type, a record, or a dictionary.
        /// </param>
        /// <param name="cancellationToken">Cancels the request.</param>
        /// <returns>
        /// The response, in the same shape every generated operation returns. Read
        /// <see cref="Client.IApiResponse.StatusCode"/> to classify it, or call
        /// <see cref="ApiResponseExtensions.EnsureSuccess{T}(IOk{T})"/> to get the queued
        /// <see cref="CommandResource"/> and throw on anything else.
        /// </returns>
        /// <exception cref="ArgumentException">
        /// <paramref name="name"/> is null, empty or white space; or <paramref name="payload"/>
        /// does not serialize to a JSON object; or <paramref name="payload"/> carries a member
        /// named <c>name</c> under a case-insensitive comparison. A colliding member is refused
        /// rather than merged because a differently-cased key would survive alongside the command
        /// name and leave the server two candidates for one property. Dropping or duplicating a
        /// caller's field at a public boundary is worse than refusing the call.
        /// </exception>
        /// <remarks>
        /// <para>
        /// The generated <see cref="CreateCommandAsync"/> cannot dispatch a command that takes
        /// arguments. <see cref="CommandResource"/> declares no additional properties, so its
        /// writer emits a fixed member list, and its Body is a typed <see cref="Command"/> whose
        /// argument-bearing members are all get-only. This method exists for the arguments.
        /// </para>
        /// <para>
        /// A refused command is reported through the returned status and not by throwing. A caller
        /// that must not re-issue a command, a search for instance, needs the status of the call it
        /// made, and reading it off a caught exception gives it on the refusal path only.
        /// </para>
        /// <para>
        /// The payload members are written flat, as siblings of the name member. The server rewinds
        /// the request stream and deserializes the whole body into a concrete command type, so the
        /// arguments do not belong under CommandResource.Body and putting them there sends a
        /// command with no arguments.
        /// </para>
        /// <para>
        /// The parameter is object rather than a type per command because the document describes
        /// none of the per-command fields. The Command schema it does describe carries the
        /// scheduling and reporting members every command shares and no argument of any particular
        /// one.
        /// </para>
        /// <para>
        /// This file stays under src/hand-written/ even though its namespace belongs to the
        /// generated tree. A partial declared here reaches the private serializer options on the
        /// generated class without the file being destroyed on the next regeneration.
        /// </para>
        /// <para>
        /// ICommandApi is generated and is not declared partial, so it cannot carry this method.
        /// AddWhisparr2 therefore registers the concrete CommandApi alongside the interface: inject
        /// CommandApi to reach this method, and ICommandApi when the generated operations are all
        /// that is needed.
        /// </para>
        /// </remarks>
        public async Task<ICreateCommandApiResponse> SendCommandAsync(
            string name,
            object? payload = null,
            CancellationToken cancellationToken = default)
        {
            // uriBuilder is declared outside the try so the error hook below can report the path
            // the request had reached. It carries UriBuilder's default path, "/", when the throw
            // came before the assignment, which is what the generated operation reports too.
            UriBuilder uriBuilder = new();

            try
            {
                ArgumentException.ThrowIfNullOrWhiteSpace(name);

                JsonObject body;

                if (payload is null)
                {
                    body = new JsonObject();
                }
                else
                {
                    JsonNode? node = JsonSerializer.SerializeToNode(payload, _jsonSerializerOptions);

                    // A boxed scalar serializes to a JsonValue, so this is reachable from a caller
                    // and an unguarded null-forgiving operator here would raise a
                    // NullReferenceException from inside the library.
                    body = node as JsonObject
                        ?? throw new ArgumentException(
                            "A command payload must serialize to a JSON object.", nameof(payload));

                    // The loop only reads and the name member is set after it, so the collection is
                    // never mutated while it is enumerated.
                    foreach (KeyValuePair<string, JsonNode?> member in body)
                    {
                        if (string.Equals(member.Key, "name", StringComparison.OrdinalIgnoreCase))
                        {
                            throw new ArgumentException(
                                "A command payload must not carry a member named '" + member.Key
                                    + "'. The command name is the name parameter.",
                                nameof(payload));
                        }
                    }
                }

                body["name"] = JsonValue.Create(name);

                using HttpRequestMessage httpRequestMessage = new();

                uriBuilder.Host = HttpClient.BaseAddress!.Host;
                uriBuilder.Port = HttpClient.BaseAddress.Port;
                uriBuilder.Scheme = HttpClient.BaseAddress.Scheme;
                uriBuilder.Path = HttpClient.BaseAddress.AbsolutePath == "/"
                    ? "/api/v3/command"
                    : string.Concat(HttpClient.BaseAddress.AbsolutePath.TrimEnd('/'), "/api/v3/command");

                httpRequestMessage.Content = new StringContent(body.ToJsonString());

                // StringContent defaults to text/plain and the server answers 415 to that, so the
                // header is overwritten once the content exists.
                string? contentType = ClientUtils.SelectHeaderContentType(new string[] { "application/json" });

                if (contentType != null)
                {
                    httpRequestMessage.Content.Headers.ContentType = new MediaTypeHeaderValue(contentType);
                }

                // The credential is applied per request rather than by a handler, which is what the
                // generated operations do. A DelegatingHandler here would be a second mechanism and
                // would double the header. The header name is derived from the generated enum
                // rather than written as a literal, because Whisparr2TokenProvider refuses any name
                // but that one and a literal here could drift from it.
                List<TokenBase> tokens = new();
                ApiKeyToken apiKeyToken = (ApiKeyToken)await ApiKeyProvider
                    .GetAsync(ClientUtils.ApiKeyHeaderToString(ClientUtils.ApiKeyHeader.X_Api_Key), cancellationToken)
                    .ConfigureAwait(false);
                tokens.Add(apiKeyToken);
                apiKeyToken.UseInHeader(httpRequestMessage);

                foreach (MediaTypeWithQualityHeaderValue accept in
                    ClientUtils.SelectHeaderAcceptArray(new string[] { "application/json" }))
                {
                    httpRequestMessage.Headers.Accept.Add(accept);
                }

                httpRequestMessage.Method = HttpMethod.Post;
                httpRequestMessage.RequestUri = uriBuilder.Uri;

                DateTime requestedAt = DateTime.UtcNow;

                using HttpResponseMessage httpResponseMessage =
                    await HttpClient.SendAsync(httpRequestMessage, cancellationToken).ConfigureAwait(false);

                string rawContent =
                    await httpResponseMessage.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);

                CreateCommandApiResponse apiResponse = new(
                    Logger,
                    httpRequestMessage,
                    httpResponseMessage,
                    rawContent,
                    "/api/v3/command",
                    requestedAt,
                    _jsonSerializerOptions);

                // The same two post-response steps the generated operation runs, in its order. The
                // first writes the completion log line every other operation writes, and the second
                // raises CommandApiEvents.OnCreateCommand. Skipping them would make a dispatch the
                // one call a consumer watching the api's logs or events could not see.
                //
                // The Option<CommandResource> argument is unset, and that is accurate rather than a
                // placeholder: this method takes a name and a loose payload because CommandResource
                // cannot express command arguments, so there is no resource to pass.
                AfterCreateCommandDefaultImplementation(apiResponse, default);

                Events.ExecuteOnCreateCommand(apiResponse);

                // The token provider is shared across every api class, so skipping this would make
                // the client's rate-limit accounting depend on which method met the 429.
                if (apiResponse.StatusCode == (HttpStatusCode)429)
                {
                    foreach (TokenBase token in tokens)
                    {
                        token.BeginRateLimit();
                    }
                }

                // The response is returned rather than the deserialized body, so this method
                // classifies the same way every generated operation does. Returning the model
                // instead would leave a caller no status on the accepted path and force it to read
                // one off an exception on the refusal path. The HttpResponseMessage is disposed as
                // this returns, which is what every generated operation also does: the body was
                // already read into RawContent.
                return apiResponse;
            }
            catch (Exception e)
            {
                // The generated operation logs, raises the error event and rethrows. This does the
                // same, so a consumer subscribed to the api's event stream sees a failed dispatch
                // as it sees every other failed operation. Nothing a caller observes changes: the
                // original exception propagates unwrapped.
                OnErrorCreateCommandDefaultImplementation(e, "/api/v3/command", uriBuilder.Path, default);

                Events.ExecuteOnErrorCreateCommand(e);

                throw;
            }
        }
    }
}
