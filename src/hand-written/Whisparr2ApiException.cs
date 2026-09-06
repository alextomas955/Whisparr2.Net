// Hand-written. Nothing in this directory is generator output; see .claude/CLAUDE.md, section
// "Generated code rules". Do not add the generator's file-marker header to this file: it is a
// false statement here, and it switches off the analyzer coverage this file has. .editorconfig
// marks only src/Whisparr2.Net/** as generated code, so everything here is analysed like
// ordinary source.

#nullable enable

using System;
using Whisparr2.Net.Client;

namespace Whisparr2.Net
{
    /// <summary>
    /// The error a Whisparr call raises when it did not produce a body the caller can read.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Two different outcomes throw this type, and <see cref="IsSuccessStatusCode"/> is what tells
    /// them apart. A failing status, such as the 401 an unaccepted key produces, throws with the
    /// flag false. A succeeding status whose body cannot be turned into a resource throws with the
    /// flag true. Collapsing those two together is the confusion this layer exists to remove, so
    /// read the flag rather than assuming a thrown exception means the request failed.
    /// </para>
    /// <para>
    /// Every value carried here is read straight off the response. Nothing is captured at the call
    /// site, no reflection is involved, and the body is never parsed. Whisparr answers an error
    /// with one of several unrelated shapes: a message and description object on 404 and 503, a
    /// message and content object on 400, an RFC 7807 document on 415, and zero bytes on 401. A
    /// single model for all of those would be wrong for most of them.
    /// </para>
    /// </remarks>
    public sealed class Whisparr2ApiException : Exception
    {
        /// <summary>
        /// The status code the instance answered with.
        /// </summary>
        public System.Net.HttpStatusCode StatusCode { get; }

        /// <summary>
        /// The reason phrase the instance answered with, or null when it sent none.
        /// </summary>
        public string? ReasonPhrase { get; }

        /// <summary>
        /// The route template the operation was declared with, for example "/api/v3/system/status".
        /// </summary>
        /// <value>
        /// The template, not the concrete path. A parameterised operation reports
        /// "/api/v3/tag/{id}" here whatever id was passed, which is what makes this value usable as
        /// a grouping key in a log. Use <see cref="RequestUri"/> for the concrete URI.
        /// </value>
        public string Path { get; }

        /// <summary>
        /// The concrete URI the request was sent to, or null when the response carried none.
        /// </summary>
        /// <value>
        /// The real URI, with any route parameters substituted and the host and port resolved. It
        /// carries no credential: the key travels in the X-Api-Key header and nothing on the
        /// registration path puts it in a query string.
        /// </value>
        public Uri? RequestUri { get; }

        /// <summary>
        /// The response body exactly as the instance sent it, untruncated.
        /// </summary>
        /// <value>
        /// <para>
        /// The verbatim bytes, which for some operations contain instance secrets that this library
        /// never had and cannot strip. GET /api/v3/config/host returns the instance API key, the
        /// admin password, sslCertPassword, proxyUsername and proxyPassword in plaintext, and the
        /// log-file operations return raw log text that can contain the key. A consumer that logs
        /// this exception verbatim after calling one of those operations writes a credential into
        /// its own logs.
        /// </para>
        /// <para>
        /// A 404 or a 503 body carries a full .NET stack trace with the source file paths and line
        /// numbers of the Whisparr build, roughly four kilobytes of it. Logging that verbatim
        /// publishes the server's internal structure into the consumer's log.
        /// </para>
        /// <para>
        /// <see cref="Exception.Message"/> does not embed this value, precisely so that a default
        /// logger cannot publish it. Read this member only where the body is actually needed, and
        /// decide there whether it is safe to record.
        /// </para>
        /// </value>
        public string RawContent { get; }

        /// <summary>
        /// Whether the status code was a success, which is what separates the two throwing outcomes.
        /// </summary>
        /// <value>
        /// False when the request failed. True when it succeeded but no body could be read, which
        /// covers a 200 whose body is JSON null and a real 201 or 202 that arrived empty.
        /// </value>
        public bool IsSuccessStatusCode { get; }

        /// <summary>
        /// Builds the exception from the response that produced it.
        /// </summary>
        /// <param name="response">The response to read status, route template, URI and body from.</param>
        /// <param name="summary">One sentence saying which of the two throwing outcomes this is.</param>
        /// <param name="innerException">The deserialization failure that caused this, when there was one.</param>
        /// <exception cref="ArgumentNullException"><paramref name="response"/> is null.</exception>
        /// <remarks>
        /// One constructor, rather than the usual pair of a message overload and a message plus
        /// inner exception overload. Both of those would let a caller build an instance whose
        /// properties contradict its message, and there is no case in this library where an
        /// exception is raised from anything but a response. The optional inner exception is a
        /// parameter rather than a second constructor, so the deserialization cause survives
        /// without widening that surface.
        /// </remarks>
        public Whisparr2ApiException(IApiResponse response, string summary, Exception? innerException = null)
            : base(BuildMessage(response, summary), innerException)
        {
            StatusCode = response.StatusCode;

            ReasonPhrase = response.ReasonPhrase;

            Path = response.Path;

            RequestUri = response.RequestUri;

            RawContent = response.RawContent;

            IsSuccessStatusCode = response.IsSuccessStatusCode;
        }

        /// <summary>
        /// Composes the message. The body is deliberately absent from it.
        /// </summary>
        /// <remarks>
        /// <para>
        /// A message is the one part of an exception that every default logger writes, including an
        /// unhandled-exception handler the consumer never wrote. The body can carry a credential,
        /// so putting it there would leak through a path the consumer never chose. The message
        /// reports the body's length and names <see cref="RawContent"/> instead, and a caller who
        /// wants the body reads that member and decides for itself where it goes.
        /// </para>
        /// <para>
        /// The null check belongs here rather than in the constructor body. This method runs in the
        /// base constructor argument list, so a check placed in the body would run after the first
        /// dereference.
        /// </para>
        /// </remarks>
        /// <param name="response">The response the message describes.</param>
        /// <param name="summary">One sentence saying which throwing outcome this is.</param>
        /// <returns>The message.</returns>
        /// <exception cref="ArgumentNullException"><paramref name="response"/> is null.</exception>
        private static string BuildMessage(IApiResponse response, string summary)
        {
            ArgumentNullException.ThrowIfNull(response);

            string reason = string.IsNullOrEmpty(response.ReasonPhrase)
                ? response.StatusCode.ToString()
                : response.ReasonPhrase;

            string body = string.IsNullOrEmpty(response.RawContent)
                ? "no body"
                : $"{response.RawContent.Length} character body in {nameof(RawContent)}";

            return $"Whisparr returned {(int)response.StatusCode} {reason} for {response.Path}. "
                + $"{summary} ({body})";
        }
    }
}
