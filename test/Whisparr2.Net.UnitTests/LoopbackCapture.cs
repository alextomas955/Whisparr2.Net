// Hand-written test support. Nothing here is generator output; see .claude/CLAUDE.md,
// section "Generated code rules".

#nullable enable

using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using System.Text;

namespace Whisparr2.Net.UnitTests
{
    /// <summary>
    /// A loopback HTTP listener that records the literal bytes of every request it receives.
    /// </summary>
    /// <remarks>
    /// <para>
    /// A mocked HttpMessageHandler cannot stand in for this. A mock returns whatever it was
    /// configured to return and would pass identically whether the header carried the key or the
    /// key behind a bearer scheme prefix, which is the exact defect these tests exist to catch.
    /// The listener binds an ephemeral port on the loopback interface only, and the port is read
    /// back from LocalEndpoint rather than assumed.
    /// </para>
    /// <para>
    /// The head and the body are both decoded as ASCII, one byte to one character, which is what
    /// makes a captured character count and a declared byte count the same number. A payload
    /// carrying any byte above 127 is therefore captured as replacement characters, so a test
    /// asserting a non-ASCII value would need a different decoding. That decoding is not changed
    /// here, because nothing in this project sends a non-ASCII value today.
    /// </para>
    /// </remarks>
    internal sealed class LoopbackCapture : IDisposable
    {
        /// <summary>How long teardown waits for a background task before giving up on it.</summary>
        /// <remarks>
        /// Bounded on purpose. An unbounded wait on a hung peer would hang the whole test run,
        /// which is worse than the leaked task this teardown exists to prevent.
        /// </remarks>
        private static readonly TimeSpan TeardownTimeout = TimeSpan.FromSeconds(5);

        private readonly TcpListener _listener;
        private readonly int _status;
        private readonly string _body;
        private readonly string _reason;
        private readonly ConcurrentQueue<string> _requests = new();
        private readonly ConcurrentBag<Task> _serving = new();
        private readonly CancellationTokenSource _stopping = new();
        private readonly SemaphoreSlim _recorded = new(0);
        private readonly Task _accepting;
        private readonly TaskCompletionSource<string> _first =
            new(TaskCreationOptions.RunContinuationsAsynchronously);
        private bool _disposed;

        /// <summary>The ephemeral port the listener actually bound.</summary>
        public int Port { get; }

        /// <summary>The base URL a client should be pointed at to reach this listener.</summary>
        public string BaseUrl => $"http://127.0.0.1:{Port}";

        /// <summary>Completes with the text of the first request recorded.</summary>
        public Task<string> FirstRequest => _first.Task;

        /// <summary>Every request text recorded so far, one entry per connection.</summary>
        public IReadOnlyCollection<string> Requests => _requests;

        /// <summary>
        /// The first failure a connection-serving task hit, or null when none has failed.
        /// </summary>
        /// <remarks>
        /// A peer that closes before the canned response is written faults the serving task. That
        /// failure is recorded here rather than left on a fire-and-forget task, where nobody sees
        /// it and a later capture timeout has no explanation.
        /// </remarks>
        public Exception? ServeFailure { get; private set; }

        /// <summary>
        /// Starts the listener.
        /// </summary>
        /// <param name="status">The status code every canned response carries.</param>
        /// <param name="body">The body every canned response carries.</param>
        /// <param name="reason">
        /// The reason phrase on the status line. An empty string sends the status line with no
        /// phrase, which is legal and is what a caller sees from an instance that sends none.
        /// </param>
        public LoopbackCapture(int status = 200, string body = "{}", string reason = "X")
        {
            _status = status;
            _body = body;
            _reason = reason;
            _listener = new TcpListener(IPAddress.Loopback, 0);
            _listener.Start();
            Port = ((IPEndPoint)_listener.LocalEndpoint).Port;
            _accepting = Task.Run(AcceptLoopAsync);
        }

        /// <summary>
        /// Waits until the given number of requests have been recorded.
        /// </summary>
        /// <param name="count">How many requests to wait for.</param>
        /// <param name="timeout">How long to wait in total.</param>
        /// <returns>The recorded request texts.</returns>
        /// <exception cref="TimeoutException">Fewer than <paramref name="count"/> requests arrived in time.</exception>
        public async Task<IReadOnlyList<string>> WaitForRequestsAsync(int count, TimeSpan timeout)
        {
            using CancellationTokenSource cancellation = new(timeout);

            for (int i = 0; i < count; i++)
            {
                try
                {
                    await _recorded.WaitAsync(cancellation.Token).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    throw new TimeoutException(
                        $"Only {_requests.Count} of {count} requests were recorded within {timeout}.");
                }
            }

            return _requests.ToArray();
        }

        private async Task AcceptLoopAsync()
        {
            while (!_stopping.IsCancellationRequested)
            {
                TcpClient client;

                try
                {
                    client = await _listener.AcceptTcpClientAsync(_stopping.Token).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    return;
                }
                catch (ObjectDisposedException)
                {
                    // The listener was stopped. That is the ordinary teardown path and the only
                    // reason this loop ends. Every other failure propagates to the accept-loop
                    // task, which Dispose observes, because a socket failure absorbed here is the
                    // explanation a later capture timeout would otherwise not have.
                    return;
                }
                catch (SocketException)
                {
                    return;
                }

                _serving.Add(Task.Run(() => ServeAsync(client)));
            }
        }

        private async Task ServeAsync(TcpClient client)
        {
            try
            {
                await ServeCoreAsync(client).ConfigureAwait(false);
            }
            catch (IOException e)
            {
                RecordServeFailure(e);
            }
            catch (SocketException e)
            {
                RecordServeFailure(e);
            }
            catch (ObjectDisposedException e)
            {
                RecordServeFailure(e);
            }
            catch (OperationCanceledException e)
            {
                RecordServeFailure(e);
            }
        }

        /// <summary>
        /// Keeps a serving failure where an assertion can reach it, instead of losing it on a
        /// task nobody awaits.
        /// </summary>
        /// <param name="failure">What went wrong while serving one connection.</param>
        private void RecordServeFailure(Exception failure)
        {
            ServeFailure ??= failure;
            _first.TrySetException(failure);
        }

        private async Task ServeCoreAsync(TcpClient client)
        {
            using (client)
            using (NetworkStream stream = client.GetStream())
            {
                byte[] buffer = new byte[8192];
                StringBuilder text = new();
                int read;

                // Read the request head only. Assertions run over these raw ASCII bytes rather
                // than over a parsed header object, so no transformation between the client and
                // the socket can hide behind the assertion.
                while ((read = await stream.ReadAsync(buffer.AsMemory()).ConfigureAwait(false)) > 0)
                {
                    text.Append(Encoding.ASCII.GetString(buffer, 0, read));

                    if (text.ToString().Contains("\r\n\r\n", StringComparison.Ordinal))
                    {
                        break;
                    }
                }

                // Then read the body, if the request declared one. The loop above stops at the
                // blank line, and whether the body bytes happened to arrive in the same segment as
                // the head is a property of the network stack rather than of the client. An
                // assertion over the body written against that coincidence passes most of the time
                // and fails on the run that splits the write.
                string request = text.ToString();
                int separator = request.IndexOf("\r\n\r\n", StringComparison.Ordinal);
                int declared = DeclaredContentLength(request);

                while (separator >= 0 && request.Length - (separator + 4) < declared)
                {
                    read = await stream.ReadAsync(buffer.AsMemory()).ConfigureAwait(false);

                    if (read <= 0)
                    {
                        break;
                    }

                    text.Append(Encoding.ASCII.GetString(buffer, 0, read));
                    request = text.ToString();
                }

                // Refuse to publish a fragment. The head loop above ends when the peer closes,
                // whether or not the blank line arrived, and the body loop ends the same way. A
                // fragment handed to an assertion produces a result about the fragment, and the
                // parsing helpers below read a short header list as a short header list rather
                // than as an incomplete capture.
                bool complete = separator >= 0 && request.Length - (separator + 4) >= declared;

                if (!complete)
                {
                    _first.TrySetException(new InvalidOperationException(
                        "The connection closed before a complete request arrived. Captured "
                            + $"{request.Length} characters."));

                    return;
                }

                _requests.Enqueue(request);
                _first.TrySetResult(request);
                _recorded.Release();

                byte[] payload = Encoding.UTF8.GetBytes(_body);
                string head = $"HTTP/1.1 {_status} {_reason}\r\n"
                    + "Content-Type: application/json\r\n"
                    + $"Content-Length: {payload.Length}\r\n"
                    + "Connection: close\r\n\r\n";

                await stream.WriteAsync(Encoding.ASCII.GetBytes(head).AsMemory()).ConfigureAwait(false);
                await stream.WriteAsync(payload.AsMemory()).ConfigureAwait(false);
                await stream.FlushAsync().ConfigureAwait(false);
            }
        }

        /// <summary>
        /// Reads the declared body length out of a captured request head.
        /// </summary>
        /// <param name="captured">The captured text so far.</param>
        /// <returns>The declared length, or 0 when the request declared none.</returns>
        /// <remarks>
        /// The head is decoded as ASCII, one byte to one character, so a character count and the
        /// declared byte count are the same number.
        /// </remarks>
        private static int DeclaredContentLength(string captured)
        {
            foreach (string line in CapturedRequest.HeaderLines(captured, "Content-Length"))
            {
                if (int.TryParse(
                        line["Content-Length:".Length..].Trim(),
                        System.Globalization.NumberStyles.None,
                        System.Globalization.CultureInfo.InvariantCulture,
                        out int length))
                {
                    return length;
                }
            }

            return 0;
        }

        /// <summary>
        /// Stops the listener and waits for the background tasks before disposing what they use.
        /// </summary>
        /// <remarks>
        /// The order matters. A serving task releases the semaphore, so disposing the semaphore
        /// while one is in flight throws on a task nobody observes. Both waits are bounded, because
        /// an unbounded wait on a hung peer would hang the whole test run.
        /// </remarks>
        public void Dispose()
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;

            _stopping.Cancel();
            _listener.Stop();

            Task.WaitAll(new[] { _accepting }, TeardownTimeout);
            Task.WaitAll(_serving.ToArray(), TeardownTimeout);

            _recorded.Dispose();
            _stopping.Dispose();
        }
    }

    /// <summary>
    /// Reads parts out of a captured request text. Every test uses these rather than its own
    /// parsing, so a negative control exercises the same assertion path as the test it guards.
    /// </summary>
    internal static class CapturedRequest
    {
        /// <summary>
        /// Returns every header line whose name matches, verbatim and with no trailing newline.
        /// </summary>
        /// <param name="captured">The captured request text.</param>
        /// <param name="headerName">The header name to match, compared without case.</param>
        /// <returns>The matching lines.</returns>
        public static IReadOnlyList<string> HeaderLines(string captured, string headerName)
        {
            string prefix = headerName + ":";

            return captured
                .Split("\r\n")
                .Skip(1)
                .TakeWhile(line => line.Length > 0)
                .Where(line => line.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                .ToArray();
        }

        /// <summary>
        /// Returns everything after the blank line that ends the request head.
        /// </summary>
        /// <param name="captured">The captured request text.</param>
        /// <returns>The body, or an empty string when the request carried none.</returns>
        public static string Body(string captured)
        {
            int separator = captured.IndexOf("\r\n\r\n", StringComparison.Ordinal);

            return separator < 0 ? string.Empty : captured[(separator + 4)..];
        }

        /// <summary>
        /// Returns every request line in the captured text.
        /// </summary>
        /// <param name="captured">The captured request text.</param>
        /// <returns>The matching lines. More than one means bytes from two connections were mixed.</returns>
        public static IReadOnlyList<string> RequestLines(string captured)
        {
            return captured
                .Split("\r\n")
                .Where(line => line.EndsWith(" HTTP/1.1", StringComparison.Ordinal))
                .ToArray();
        }
    }
}
