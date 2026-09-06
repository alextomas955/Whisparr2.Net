// Hand-written test code. Nothing here is generator output; see .claude/CLAUDE.md,
// section "Generated code rules".

#nullable enable

using System.Net;
using System.Text.Json;
using Whisparr2.Net.Client;
using Whisparr2.Net.Model;

namespace Whisparr2.Net.UnitTests
{
    /// <summary>
    /// The branch EnsureSuccess takes for a response this library did not build.
    /// </summary>
    /// <remarks>
    /// Every response the generator emits derives from ApiResponse, so every other case in the
    /// suite takes the ReadAs branch and nothing exercises the accessor branch beside it. That
    /// branch is public behaviour: EnsureSuccess accepts any IOk, and IOk is a public interface a
    /// consumer's own type or test double can implement. Deleting the whole branch leaves the rest
    /// of the suite green. The double here implements IOk directly and never touches a socket,
    /// which is the point: it is the one thing in the suite that is not an ApiResponse.
    /// </remarks>
    public sealed class ForeignResponseTests
    {
        /// <summary>The route template the double reports, matching a real operation.</summary>
        private const string TagPath = "/api/v3/tag";

        /// <summary>
        /// A foreign response that succeeded and has a body returns it through the accessor.
        /// </summary>
        [Fact]
        public void Foreign_success_returns_the_body_through_the_accessor()
        {
            ForeignOk response = new(HttpStatusCode.Created, () => new TagResource { Id = 5, Label = "foreign" });

            TagResource body = response.EnsureSuccess();

            Assert.Equal(5, body.Id);
            Assert.Equal("foreign", body.Label);
        }

        /// <summary>
        /// A foreign response that succeeded with nothing to return is a success, not a failure.
        /// </summary>
        [Fact]
        public void Foreign_success_with_no_body_throws_the_typed_error_as_a_success()
        {
            ForeignOk response = new(HttpStatusCode.Created, () => null);

            Whisparr2ApiException error =
                Assert.Throws<Whisparr2ApiException>(() => response.EnsureSuccess());

            Assert.True(error.IsSuccessStatusCode);
            Assert.Equal(TagPath, error.Path);
            Assert.Contains("no body could be read", error.Message, StringComparison.Ordinal);
            Assert.Null(error.InnerException);
        }

        /// <summary>
        /// A serializer failure inside the accessor is wrapped rather than allowed to escape.
        /// </summary>
        /// <remarks>
        /// An escaping JsonException carries no status, no route template and no URI, and a
        /// consumer catching Whisparr2ApiException would miss it entirely. The inner exception is
        /// asserted by identity so the cause survives the wrapping.
        /// </remarks>
        [Fact]
        public void Foreign_deserialization_failure_is_wrapped_with_its_cause()
        {
            JsonException cause = new("the body was not JSON");
            ForeignOk response = new(HttpStatusCode.OK, () => throw cause);

            Whisparr2ApiException error =
                Assert.Throws<Whisparr2ApiException>(() => response.EnsureSuccess());

            Assert.True(error.IsSuccessStatusCode);
            Assert.Same(cause, error.InnerException);
            Assert.Equal(HttpStatusCode.OK, error.StatusCode);
            Assert.Equal(TagPath, error.Path);
        }

        /// <summary>
        /// A type the serializer cannot handle is wrapped by the same branch.
        /// </summary>
        /// <remarks>
        /// NotSupportedException is a separate catch, and it is the one System.Text.Json raises
        /// for an unsupported type rather than for a malformed document. Without a case of its own
        /// that catch can be deleted with nothing noticing.
        /// </remarks>
        [Fact]
        public void Foreign_unsupported_type_failure_is_wrapped_with_its_cause()
        {
            NotSupportedException cause = new("the type has no converter");
            ForeignOk response = new(HttpStatusCode.OK, () => throw cause);

            Whisparr2ApiException error =
                Assert.Throws<Whisparr2ApiException>(() => response.EnsureSuccess());

            Assert.True(error.IsSuccessStatusCode);
            Assert.Same(cause, error.InnerException);
        }

        /// <summary>
        /// A foreign failure is reported before the accessor is ever called.
        /// </summary>
        /// <remarks>
        /// The accessor records that it ran. Asserting it did not is what shows the status check
        /// happens first rather than the failure being discovered downstream, which is what keeps
        /// a 500 carrying an error document from being handed back as a result.
        /// </remarks>
        [Fact]
        public void Foreign_failure_throws_without_reading_the_body()
        {
            bool accessorCalled = false;
            ForeignOk response = new(
                HttpStatusCode.InternalServerError,
                () =>
                {
                    accessorCalled = true;
                    return new TagResource();
                });

            Whisparr2ApiException error =
                Assert.Throws<Whisparr2ApiException>(() => response.EnsureSuccess());

            Assert.False(accessorCalled);
            Assert.False(error.IsSuccessStatusCode);
            Assert.Equal(HttpStatusCode.InternalServerError, error.StatusCode);
        }

        /// <summary>
        /// A null response is refused rather than dereferenced.
        /// </summary>
        [Fact]
        public void Null_response_is_refused_by_both_overloads()
        {
            Assert.Throws<ArgumentNullException>(() => ((IOk<TagResource?>)null!).EnsureSuccess());
            Assert.Throws<ArgumentNullException>(() => ((IApiResponse)null!).EnsureSuccess());
        }

        /// <summary>
        /// An IOk implementation that is not an ApiResponse, which is the whole point of it.
        /// </summary>
        private sealed class ForeignOk : IOk<TagResource?>
        {
            private readonly Func<TagResource?> _accessor;
            private readonly HttpResponseMessage _message = new();
            private readonly HttpContent _content = new StringContent(string.Empty);

            public ForeignOk(HttpStatusCode statusCode, Func<TagResource?> accessor)
            {
                StatusCode = statusCode;
                _accessor = accessor;
            }

            public bool IsSuccessStatusCode => (int)StatusCode is >= 200 and <= 299;

            public HttpStatusCode StatusCode { get; }

            public string RawContent => string.Empty;

            public Stream? ContentStream => null;

            public DateTime DownloadedAt { get; } = DateTime.UtcNow;

            public System.Net.Http.Headers.HttpResponseHeaders Headers => _message.Headers;

            public System.Net.Http.Headers.HttpContentHeaders ContentHeaders => _content.Headers;

            public string Path => TagPath;

            public string? ReasonPhrase => "Foreign";

            public DateTime RequestedAt { get; } = DateTime.UtcNow;

            public Uri? RequestUri => new("http://127.0.0.1:1" + TagPath);

            public TagResource? Ok()
            {
                return _accessor();
            }

            public bool TryOk(
                [System.Diagnostics.CodeAnalysis.NotNullWhen(true)] out TagResource? result)
            {
                result = _accessor();

                return result is not null;
            }
        }
    }
}
