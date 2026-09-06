// Hand-written test code. Nothing here is generator output; see .claude/CLAUDE.md,
// section "Generated code rules".

#nullable enable

using System.Globalization;
using System.Net.Sockets;
using System.Text;

namespace Whisparr2.Net.UnitTests
{
    /// <summary>
    /// Assertions over the capture helper's own contract.
    /// </summary>
    /// <remarks>
    /// Every wire and serialization assertion in this project reads what the capture publishes and
    /// trusts it to be a whole request. Until these two cases nothing asserted that contract, so a
    /// helper that published a fragment would have been reported as a failing assertion about the
    /// fragment rather than as a broken helper. Both cases drive a raw socket rather than the
    /// generated client, because the point is what the helper does with bytes a client would never
    /// send.
    /// </remarks>
    public sealed class CaptureTests
    {
        /// <summary>How long a published-or-faulted capture is waited for before failing.</summary>
        /// <remarks>
        /// Explicit, so a helper that neither publishes nor faults fails this test rather than
        /// hanging the run.
        /// </remarks>
        private static readonly TimeSpan Budget = TimeSpan.FromSeconds(10);

        /// <summary>
        /// A connection that closes before the head is terminated publishes nothing, and the
        /// awaiting task is faulted with a message naming how much was captured.
        /// </summary>
        [Fact]
        public async Task Truncated_request_is_refused_rather_than_published()
        {
            using LoopbackCapture capture = new(status: 200, body: "{}");

            // No terminating blank line, so this request never becomes complete however long the
            // helper waits, and the peer then closes.
            const string Fragment =
                "POST /api/v3/tag HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 40\r\n";

            using (TcpClient client = new())
            {
                await client.ConnectAsync("127.0.0.1", capture.Port);

                byte[] head = Encoding.ASCII.GetBytes(Fragment);

                await client.GetStream().WriteAsync(head.AsMemory());
                await client.GetStream().FlushAsync();
            }

            Task<string> published = capture.FirstRequest;
            Task finished = await Task.WhenAny(published, Task.Delay(Budget));

            Assert.True(
                ReferenceEquals(finished, published),
                $"The capture neither published nor faulted within {Budget}.");

            InvalidOperationException refusal =
                await Assert.ThrowsAsync<InvalidOperationException>(() => published);

            // The captured character count is asserted so a refusal that fires with a message
            // saying nothing fails here. A message naming what was captured is what makes the next
            // failure readable. The count is derived from the bytes this test sent rather than
            // written out, because the head is ASCII and one byte is one character.
            Assert.Contains(
                Fragment.Length.ToString(CultureInfo.InvariantCulture),
                refusal.Message,
                StringComparison.Ordinal);
            Assert.Empty(capture.Requests);
        }

        /// <summary>
        /// The positive control. A complete request, written as a head and then a body so the two
        /// arrive in separate segments, is still published with its body intact.
        /// </summary>
        /// <remarks>
        /// Not optional. The refusal case above passes on its own against a helper that refuses
        /// every request, which would break every other test in this project and none of this one.
        /// </remarks>
        [Fact]
        public async Task Complete_request_is_published_with_its_body_intact()
        {
            using LoopbackCapture capture = new(status: 200, body: "{}");

            const string Body = "{\"label\":\"probe-complete\"}";

            using (TcpClient client = new())
            {
                await client.ConnectAsync("127.0.0.1", capture.Port);

                byte[] payload = Encoding.ASCII.GetBytes(Body);
                byte[] head = Encoding.ASCII.GetBytes(
                    "POST /api/v3/tag HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                        + $"Content-Length: {payload.Length}\r\n\r\n");

                NetworkStream stream = client.GetStream();

                await stream.WriteAsync(head.AsMemory());
                await stream.FlushAsync();
                await stream.WriteAsync(payload.AsMemory());
                await stream.FlushAsync();

                Task<string> published = capture.FirstRequest;
                Task finished = await Task.WhenAny(published, Task.Delay(Budget));

                Assert.True(
                    ReferenceEquals(finished, published),
                    $"The capture neither published nor faulted within {Budget}.");

                string request = await published;

                Assert.True(
                    string.Equals(Body, CapturedRequest.Body(request), StringComparison.Ordinal),
                    $"The published body was '{CapturedRequest.Body(request)}'.");
            }
        }
    }
}
