// Hand-written test code. Nothing here is generator output; see .claude/CLAUDE.md,
// section "Generated code rules".

#nullable enable

using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net.Api;
using Whisparr2.Net.Model;

namespace Whisparr2.Net.UnitTests
{
    /// <summary>
    /// Assertions over what the client puts in a request, read off the recorded bytes.
    /// </summary>
    /// <remarks>
    /// Every case drives a real operation on a real registration against a real listener and reads
    /// what the listener recorded. An assertion over a serialized string built in the test would be
    /// a fact about the serializer call the test wrote, not about the request the client sends.
    /// </remarks>
    public sealed class SerializationTests
    {
        /// <summary>
        /// An obvious non-secret, in the same shape the other test classes use.
        /// </summary>
        private const string SentinelKey = "SENTINEL-Key-123";

        /// <summary>The label the create cases send. Nothing else on the resource is set.</summary>
        private const string OnlyLabel = "only-label";

        /// <summary>The id the update case addresses. This operation takes it as a string.</summary>
        private const string UpdatedTagId = "5";

        /// <summary>The same id on the delete operation, which takes it as an int.</summary>
        private const int DeletedTagId = 5;

        /// <summary>
        /// An unset property is absent from the body rather than present and null.
        /// </summary>
        /// <remarks>
        /// Option is the whole mechanism behind that, and a create that sends a null id is rejected
        /// by the server. Both halves are needed: the first shows an unset body argument sends no
        /// body at all, and the second shows the body that is sent omits what was never set.
        /// </remarks>
        [Fact]
        public async Task Unset_option_emits_no_json_member()
        {
            using LoopbackCapture noBody = new();

            await using (ServiceProvider provider = BuildProvider(noBody))
            {
                await provider.GetRequiredService<ITagApi>().CreateTagAsync();
            }

            Assert.Empty(CapturedRequest.Body(await noBody.FirstRequest));

            using LoopbackCapture labelOnly = new();

            await using (ServiceProvider provider = BuildProvider(labelOnly))
            {
                await provider.GetRequiredService<ITagApi>()
                    .CreateTagAsync(new TagResource { Label = OnlyLabel });
            }

            string body = CapturedRequest.Body(await labelOnly.FirstRequest);

            Assert.Equal("{\"label\":\"" + OnlyLabel + "\"}", body);
        }

        /// <summary>
        /// A create request declares JSON.
        /// </summary>
        /// <remarks>
        /// The document declares more than one content type for these operations, so the generated
        /// content-type selection could pick text/plain instead and the server would reject a body
        /// it was told not to parse.
        /// </remarks>
        [Fact]
        public async Task Request_content_type_is_application_json()
        {
            using LoopbackCapture capture = new();

            await using ServiceProvider provider = BuildProvider(capture);
            await provider.GetRequiredService<ITagApi>()
                .CreateTagAsync(new TagResource { Label = OnlyLabel });

            string request = await capture.FirstRequest;

            string only = Assert.Single(CapturedRequest.HeaderLines(request, "Content-Type"));

            Assert.Equal("Content-Type: application/json", only);
        }

        /// <summary>
        /// The update puts its id into the path, and takes that id as a string.
        /// </summary>
        /// <remarks>
        /// The delete on the same controller takes the same id as an int. That asymmetry is a
        /// documented trap of this document and nothing else in the suite records it. Both request
        /// lines are read off the recorded bytes, which is what makes this a fact about the wire
        /// rather than about the two signatures.
        /// </remarks>
        [Fact]
        public async Task Update_route_template_carries_the_id_as_a_string()
        {
            using LoopbackCapture update = new();

            await using (ServiceProvider provider = BuildProvider(update))
            {
                await provider.GetRequiredService<ITagApi>()
                    .UpdateTagAsync(UpdatedTagId, new TagResource { Label = OnlyLabel });
            }

            Assert.Equal(
                "PUT /api/v3/tag/5 HTTP/1.1",
                Assert.Single(CapturedRequest.RequestLines(await update.FirstRequest)));

            using LoopbackCapture delete = new();

            await using (ServiceProvider provider = BuildProvider(delete))
            {
                await provider.GetRequiredService<ITagApi>().DeleteTagAsync(DeletedTagId);
            }

            Assert.Equal(
                "DELETE /api/v3/tag/5 HTTP/1.1",
                Assert.Single(CapturedRequest.RequestLines(await delete.FirstRequest)));
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
    }
}
