// Hand-written test code. See .claude/CLAUDE.md, section "Generated code rules".

#nullable enable

using System.Globalization;
using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net.Api;
using Whisparr2.Net.Model;

namespace Whisparr2.Net.IntegrationTests
{
    /// <summary>
    /// One full create, read, update and delete against a real Whisparr, through the registered
    /// client.
    /// </summary>
    /// <remarks>
    /// <para>
    /// This is the first committed code in the repository that changes server state. It belongs to
    /// the collection whose fixture refuses an instance this run did not start, and that refusal
    /// runs during fixture initialization rather than in a test, so it covers this class whatever
    /// order xunit gives the collection. No second collection is defined and no second container is
    /// built: collections run in parallel, and the refusal covers only the collection whose fixture
    /// ran it.
    /// </para>
    /// <para>
    /// Nothing here names a host port or a host name. The address comes from the fixture, which
    /// reads it back from the container this run started.
    /// </para>
    /// </remarks>
    [Collection(WhisparrCollection.Name)]
    public sealed class RoundTripTests(WhisparrFixture fixture)
    {
        /// <summary>
        /// A tag is created, read back with its field values intact, updated across the id type
        /// split, and deleted, with the row removed whether or not the assertions above the delete
        /// hold.
        /// </summary>
        /// <remarks>
        /// Every response is classified by EnsureSuccess rather than by the generated success
        /// accessor. That accessor deserializes on exactly the one status its operation declares
        /// and returns null on every other status, so a rejected request and an empty result read
        /// the same to a caller. The create answers 201 and the update answers 202, so the accessor
        /// would return null on both even though both succeeded.
        /// </remarks>
        [SkippableFact]
        public async Task Tag_survives_a_create_read_update_and_delete()
        {
            Skip.If(fixture.SkipReason is not null, fixture.SkipReason);

            await using ServiceProvider provider = BuildProvider();
            ITagApi tags = provider.GetRequiredService<ITagApi>();

            // Unique to the run, so neither two runs nor the two target frameworks of one run can
            // collide on the label, and a row left behind by an earlier failure cannot be mistaken
            // for this one.
            string label = "whisparr2net-roundtrip-" + Guid.NewGuid().ToString("N");
            string updatedLabel = label + "-updated";

            TagResource created = (await tags.CreateTagAsync(new TagResource(label: label)))
                .EnsureSuccess();

            Assert.True(
                created.Id.HasValue,
                "The create was reported as a success and returned a resource carrying no id, so "
                    + "there is nothing to read the row back by.");

            int id = created.Id!.Value;

            Assert.NotEqual(0, id);

            IDeleteTagApiResponse deleted;

            try
            {
                TagResource read = (await tags.GetTagByIdAsync(id)).EnsureSuccess();

                Assert.True(
                    string.Equals(label, read.Label, StringComparison.Ordinal),
                    "The row read back carries the label '" + read.Label + "' rather than the '"
                        + label + "' the create sent, so what came back is not what went in.");

                List<TagResource> listedBefore = (await tags.ListTagAsync()).EnsureSuccess();

                // Membership, never a count. Class order inside a collection is not contracted and
                // a sibling class writes rows of its own, so a count would fail intermittently and
                // would look like a container problem rather than an assertion problem.
                Assert.Contains(listedBefore, tag => tag.Id == id);

                // The id type split is the shape a real caller meets: UpdateTag declares its id
                // parameter as a string while GetTagById and DeleteTag declare theirs as an
                // integer. The integer read off the create body is formatted with the invariant
                // culture for the update and used as an integer everywhere else, so one round trip
                // crosses the split in both directions.
                TagResource updated = (await tags.UpdateTagAsync(
                        id.ToString(CultureInfo.InvariantCulture),
                        new TagResource(id: id, label: updatedLabel)))
                    .EnsureSuccess();

                Assert.True(
                    string.Equals(updatedLabel, updated.Label, StringComparison.Ordinal),
                    "The update was reported as a success and answered with the label '"
                        + updated.Label + "' rather than the '" + updatedLabel + "' it sent.");

                TagResource reread = (await tags.GetTagByIdAsync(id)).EnsureSuccess();

                Assert.True(
                    string.Equals(updatedLabel, reread.Label, StringComparison.Ordinal),
                    "A fresh read of the updated row carries the label '" + reread.Label
                        + "' rather than the '" + updatedLabel + "' the update sent, so the write "
                        + "was reported as landing and did not land.");
            }
            finally
            {
                // In the finally, so an assertion that fails above still removes the row it
                // created. The container is shared by every class in the collection.
                deleted = await tags.DeleteTagAsync(id);
            }

            // Deliberately outside the finally. An assertion there would replace the exception a
            // failing assertion above had already raised, and the delete's own outcome is only
            // interesting on a run that got this far.
            deleted.EnsureSuccess();

            List<TagResource> listedAfter = (await tags.ListTagAsync()).EnsureSuccess();

            Assert.DoesNotContain(listedAfter, tag => tag.Id == id);

            IGetTagByIdApiResponse afterDelete = await tags.GetTagByIdAsync(id);

            Assert.False(
                afterDelete.IsSuccessStatusCode,
                "Reading the deleted row was reported as a success, so the delete was reported as "
                    + "removing a row it did not remove.");
        }

        /// <summary>
        /// Builds a provider of its own, so no test can disturb another test's registration.
        /// </summary>
        /// <returns>A provider registered against the container this run started.</returns>
        private ServiceProvider BuildProvider()
        {
            ServiceCollection services = new();

            services.AddWhisparr2(new Whisparr2Options
            {
                BaseUrl = fixture.BaseUrl,
                ApiKey = fixture.ApiKey,
            });

            return services.BuildServiceProvider();
        }
    }
}
