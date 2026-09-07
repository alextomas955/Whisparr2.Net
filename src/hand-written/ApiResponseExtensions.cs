// Hand-written. Nothing in this directory is generator output; see .claude/CLAUDE.md, section
// "Generated code rules". Do not add the generator's file-marker header to this file: it is a
// false statement here, and it switches off the analyzer coverage this file has. .editorconfig
// marks only src/Whisparr2.Net/** as generated code, so everything here is analysed like
// ordinary source.

#nullable enable

using System;
using System.Text.Json;
using Whisparr2.Net.Client;

namespace Whisparr2.Net
{
    /// <summary>
    /// Turns a response into either its body or a typed error.
    /// </summary>
    /// <remarks>
    /// <para>
    /// The generated success accessor deserializes on exactly the one status code its operation
    /// declares and returns null on every other status, so a 401 and an empty collection are both
    /// reported to a caller as null. That still matters after the document was corrected: only the
    /// writes a probe reached against a running instance declare the code that instance answers,
    /// and every write it could not reach declares 200 while the instance may answer a 201 or a
    /// 202. These methods classify the same response into three outcomes instead: a success
    /// carrying a body, a success whose body cannot be read, and a failure. The last two both
    /// throw, and Whisparr2ApiException.IsSuccessStatusCode is what tells them apart. A body is
    /// read on any success status, not on the declared one alone.
    /// </para>
    /// <para>
    /// The generated accessor and its Try and Is companions stay on every response and nothing
    /// here can remove them. A caller who reads them directly still gets null from a success the
    /// document does not declare. Call EnsureSuccess instead.
    /// </para>
    /// <para>
    /// Every operation also exposes an OrDefaultAsync variant that wraps its whole body in a
    /// catch-all returning null. That variant destroys the distinction these methods restore. Call
    /// the plain variant and use EnsureSuccess.
    /// </para>
    /// </remarks>
    public static class ApiResponseExtensions
    {
        /// <summary>
        /// Returns the body of a response with any success status, or throws.
        /// </summary>
        /// <typeparam name="T">The resource the operation returns.</typeparam>
        /// <param name="response">The response to classify.</param>
        /// <returns>The deserialized body, never null.</returns>
        /// <exception cref="ArgumentNullException"><paramref name="response"/> is null.</exception>
        /// <exception cref="Whisparr2ApiException">
        /// The status was not a success, or it was a success whose body could not be read. Read
        /// Whisparr2ApiException.IsSuccessStatusCode to tell those two apart.
        /// </exception>
        /// <remarks>
        /// <para>
        /// This overload covers the response interfaces whose operation declares 200 with content.
        /// Each of the other typed success interfaces the generator emits has an overload of its
        /// own below, and the interfaces carrying no typed accessor at all are covered by the
        /// non-generic overload at the end.
        /// </para>
        /// <para>
        /// The body is read through ApiResponse.ReadAs rather than through the generated accessor,
        /// which is what makes a status the document does not declare readable. Every response
        /// class this library produces derives from Whisparr2.Net.Client.ApiResponse, so the
        /// pattern match in the shared body is total in practice. A response some other code
        /// implemented against IOk stays on the accessor path, which is why the match is a pattern
        /// rather than a cast.
        /// </para>
        /// </remarks>
        public static T EnsureSuccess<T>(this IOk<T?> response)
            where T : class
        {
            ArgumentNullException.ThrowIfNull(response);

            return Classify(response, response.Ok);
        }

        /// <summary>
        /// Returns the body of a response with any success status, or throws.
        /// </summary>
        /// <typeparam name="T">The resource the operation returns.</typeparam>
        /// <param name="response">The response to classify.</param>
        /// <returns>The deserialized body, never null.</returns>
        /// <exception cref="ArgumentNullException"><paramref name="response"/> is null.</exception>
        /// <exception cref="Whisparr2ApiException">
        /// The status was not a success, or it was a success whose body could not be read. Read
        /// Whisparr2ApiException.IsSuccessStatusCode to tell those two apart.
        /// </exception>
        /// <remarks>
        /// The overload for a response whose operation declares 201. Without it a caller reaches
        /// the non-generic overload below, which returns void and hands back no body at all, and
        /// the mistake compiles.
        /// </remarks>
        public static T EnsureSuccess<T>(this ICreated<T?> response)
            where T : class
        {
            ArgumentNullException.ThrowIfNull(response);

            return Classify(response, response.Created);
        }

        /// <summary>
        /// Returns the body of a response with any success status, or throws.
        /// </summary>
        /// <typeparam name="T">The resource the operation returns.</typeparam>
        /// <param name="response">The response to classify.</param>
        /// <returns>The deserialized body, never null.</returns>
        /// <exception cref="ArgumentNullException"><paramref name="response"/> is null.</exception>
        /// <exception cref="Whisparr2ApiException">
        /// The status was not a success, or it was a success whose body could not be read. Read
        /// Whisparr2ApiException.IsSuccessStatusCode to tell those two apart.
        /// </exception>
        /// <remarks>
        /// The overload for a response whose operation declares 202, on the same terms as the
        /// created one above.
        /// </remarks>
        public static T EnsureSuccess<T>(this IAccepted<T?> response)
            where T : class
        {
            ArgumentNullException.ThrowIfNull(response);

            return Classify(response, response.Accepted);
        }

        /// <summary>
        /// The body all three typed overloads share.
        /// </summary>
        /// <typeparam name="T">The resource the operation returns.</typeparam>
        /// <param name="response">The response to classify, already known to be non-null.</param>
        /// <param name="accessor">
        /// The generated success accessor of the interface the caller reached, used only on the
        /// foreign path below.
        /// </param>
        /// <returns>The deserialized body, never null.</returns>
        /// <remarks>
        /// One body rather than three, because three copies of this classification would drift and
        /// only one of the three has a case in the test project driving every branch. The accessor
        /// is passed in because it is the one thing that differs between them: each generated
        /// interface names its own, Ok, Created or Accepted.
        /// </remarks>
        private static T Classify<T>(IApiResponse response, Func<T?> accessor)
            where T : class
        {
            if (!response.IsSuccessStatusCode)
            {
                throw new Whisparr2ApiException(response, "The request failed.");
            }

            if (response is ApiResponse apiResponse)
            {
                // The generated accessor gates on exactly 200, so it returns null on the 201 a
                // create answers with and on the 202 an update answers with. ReadAs gates on
                // IsSuccessStatusCode and reads RawContent through the client's own serializer
                // options, producing the same value on a 200 and a body on the rest.
                return apiResponse.ReadAs<T>();
            }

            // Below is the path for a success interface this library did not produce. It cannot
            // reach ReadAs, because the serializer options that method needs are protected on
            // ApiResponse.
            T? body;

            try
            {
                body = accessor();
            }
            catch (JsonException e)
            {
                // Without this the accessor's own JsonException escapes the typed layer, so a
                // consumer catching Whisparr2ApiException misses it and gets a serializer error
                // carrying no status, no route template and no URI.
                throw new Whisparr2ApiException(
                    response,
                    "The request succeeded but its body could not be deserialized.",
                    e);
            }
            catch (NotSupportedException e)
            {
                throw new Whisparr2ApiException(
                    response,
                    "The request succeeded but its body could not be deserialized.",
                    e);
            }

            if (body is null)
            {
                // A success with nothing to return. This is not a failure and the exception says
                // so through its IsSuccessStatusCode, which is true here and false above.
                throw new Whisparr2ApiException(response, "The request succeeded but no body could be read.");
            }

            return body;
        }

        /// <summary>
        /// Throws when a response failed, and returns normally when it succeeded.
        /// </summary>
        /// <param name="response">The response to classify.</param>
        /// <exception cref="ArgumentNullException"><paramref name="response"/> is null.</exception>
        /// <exception cref="Whisparr2ApiException">The status was not a success.</exception>
        /// <remarks>
        /// This overload covers the response interfaces that carry no typed success accessor,
        /// which is where the document declares a success with no content for it. There is no body
        /// to return through the accessor, so a success is simply a normal return. Where such an
        /// operation does send a body, read it with ApiResponse.ReadAs or straight off RawContent.
        /// </remarks>
        public static void EnsureSuccess(this IApiResponse response)
        {
            ArgumentNullException.ThrowIfNull(response);

            if (!response.IsSuccessStatusCode)
            {
                throw new Whisparr2ApiException(response, "The request failed.");
            }
        }
    }
}

namespace Whisparr2.Net.Client
{
    /// <summary>
    /// The second part of the generated response base, holding the accessor that reads a body the
    /// document never described.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Many operations declare a success and declare no content for it, so the generator emits no
    /// typed accessor for them. The body is not lost: every one of those operations reads the
    /// whole response with ReadAsStringAsync and stores it, so RawContent already carries whatever
    /// the server sent. What is missing is a way to turn that string into a type using the client's
    /// own serializer options.
    /// </para>
    /// <para>
    /// This is a partial rather than an extension method because _jsonSerializerOptions is
    /// protected on this class, so only code inside the class can reach it. An extension method
    /// would have to take the options from its caller, and a caller that passes plain defaults
    /// loses every converter the client registered, which silently changes how a date is read.
    /// </para>
    /// <para>
    /// It sits under src/hand-written/ even though its namespace belongs to the generated tree.
    /// Nothing under src/Whisparr2.Net/ is ever hand-edited: the generator deletes its output
    /// subdirectories wholesale on every run, and it verifies the on-disk tree against a recorded
    /// digest before the first delete and refuses when they differ.
    /// </para>
    /// </remarks>
    public partial class ApiResponse
    {
        /// <summary>
        /// Reads the response body as the type the caller names.
        /// </summary>
        /// <typeparam name="T">The shape the caller expects the body to have.</typeparam>
        /// <returns>The deserialized body, never null.</returns>
        /// <exception cref="Whisparr2ApiException">
        /// The status was not a success, or it was a success whose body was empty or could not be
        /// read as T. Read Whisparr2ApiException.IsSuccessStatusCode to tell those apart.
        /// </exception>
        /// <remarks>
        /// <para>
        /// The three outcomes are the same ones EnsureSuccess classifies, so a caller reads both
        /// the same way. The type is the caller's to name, because the document does not name it.
        /// </para>
        /// <para>
        /// Not every one of these operations answers with JSON. GET /api/v3/system/routes answers
        /// with a Graphviz DOT graph as text/plain, GET /feed/v3/calendar/whisparr.ics answers with
        /// iCalendar, GET /api/v3/log/file/{filename} answers with raw log text, and
        /// GET /api/v3/mediacover/{seriesId}/{filename} answers with a JPEG. Read RawContent
        /// directly for those; this method is for the ones that do send JSON.
        /// </para>
        /// <para>
        /// T needs a JsonPropertyName on every member it expects to bind. The client builds its
        /// options as a bare JsonSerializerOptions plus a converter list, with no naming policy and
        /// no case-insensitive matching, so a camel-cased body binds nothing to a Pascal-cased
        /// member. That failure is silent: the object is returned with every property at its
        /// default and nothing is thrown. The generated models in Whisparr2.Net.Model already carry
        /// the attributes; a type written by a caller does not.
        /// </para>
        /// </remarks>
        public T ReadAs<T>()
            where T : class
        {
            if (!IsSuccessStatusCode)
            {
                throw new Whisparr2ApiException(this, "The request failed.");
            }

            // Separated from the deserialization failure below on purpose. A DELETE that answers
            // an empty 200 is the ordinary case for many of these operations, and reporting it as
            // a malformed body would send a reader looking for a defect that is not there.
            if (string.IsNullOrWhiteSpace(RawContent))
            {
                throw new Whisparr2ApiException(this, "The request succeeded and its body was empty.");
            }

            T? body;

            try
            {
                body = System.Text.Json.JsonSerializer.Deserialize<T>(RawContent, _jsonSerializerOptions);
            }
            catch (System.Text.Json.JsonException e)
            {
                // Without this the serializer's own exception escapes the typed layer carrying no
                // status, no route template and no URI, which is the same hole EnsureSuccess
                // closes.
                throw new Whisparr2ApiException(
                    this,
                    "The request succeeded but its body could not be read as " + typeof(T).Name + ".",
                    e);
            }
            catch (NotSupportedException e)
            {
                throw new Whisparr2ApiException(
                    this,
                    "The request succeeded but its body could not be read as " + typeof(T).Name + ".",
                    e);
            }

            if (body is null)
            {
                // A body of literal null returns null from the serializer without ever entering the
                // generated converter, so it lands here with no inner exception rather than as a
                // wrapped deserialization failure.
                throw new Whisparr2ApiException(this, "The request succeeded but no body could be read.");
            }

            return body;
        }
    }
}
