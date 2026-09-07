// Hand-written test code. See .claude/CLAUDE.md, section "Generated code rules".

#nullable enable

using System.Globalization;
using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net.Api;
using Whisparr2.Net.Model;

namespace Whisparr2.Net.IntegrationTests
{
    /// <summary>
    /// One read-modify-write of the naming config, proving the field the committed document once
    /// omitted survives a write built from the typed model.
    /// </summary>
    /// <remarks>
    /// <para>
    /// The document this client is generated from omitted javEpisodeFormat, so a caller who round
    /// tripped the naming config through a model built from it sent a body with the field missing
    /// and the server erased its own value. That is the defect this class exists to catch, and it
    /// can only be caught against a running instance.
    /// </para>
    /// <para>
    /// The class belongs to the collection whose fixture refuses an instance this run did not
    /// start, and it defines no collection and builds no container of its own. Nothing here names
    /// a host port or a host name.
    /// </para>
    /// </remarks>
    [Collection(WhisparrCollection.Name)]
    public sealed class NamingConfigRoundTripTests(WhisparrFixture fixture)
    {
        /// <summary>
        /// Writing the naming config back with one field changed changes that field and leaves
        /// javEpisodeFormat exactly as it was found.
        /// </summary>
        /// <remarks>
        /// customColonReplacementFormat is deliberately not the witness. It is empty on a fresh
        /// instance, and a preservation assertion over an empty value passes whether or not the
        /// round trip works.
        /// </remarks>
        [SkippableFact]
        public async Task Naming_config_round_trip_preserves_the_field_the_document_omitted()
        {
            Skip.If(fixture.SkipReason is not null, fixture.SkipReason);

            await using ServiceProvider provider = BuildProvider();
            INamingConfigApi naming = provider.GetRequiredService<INamingConfigApi>();

            // The restore point. Nothing below mutates this instance: the payload sent to the
            // server is a second resource carrying a copy of every option off this one, so this
            // object still holds what the first read returned when the finally writes it back.
            NamingConfigResource original = (await naming.GetNamingConfigAsync()).EnsureSuccess();

            Assert.True(
                original.Id.HasValue,
                "The naming config came back carrying no id, so there is no route to write it "
                    + "back to.");

            string id = original.Id!.Value.ToString(CultureInfo.InvariantCulture);

            // Asserted before anything is written. A test that proves the preservation of a field
            // which was already empty proves nothing at all.
            Assert.False(
                string.IsNullOrEmpty(original.JavEpisodeFormat),
                "javEpisodeFormat is empty on this instance before any write, so this test could "
                    + "not tell a preserved value from an erased one.");

            Assert.True(
                original.ReplaceIllegalCharacters.HasValue,
                "replaceIllegalCharacters came back unset, so there is no old value for the "
                    + "changed field to be distinguishable from.");

            string preservedFormat = original.JavEpisodeFormat!;

            // Exactly one field, and one whose new value cannot be confused with its old one.
            //
            // replaceSpaces, separator, numberStyle and the three include flags are not candidates:
            // they are carried on the resource and the server does not persist them. Measured here,
            // a write that flipped replaceSpaces was reported as a success and the next read
            // returned the old value, so an assertion built on one of them cannot tell a write that
            // landed from a write that was discarded.
            bool? flipped = !original.ReplaceIllegalCharacters!.Value;

            // Every other field is copied as its option rather than as its value, so a field the
            // body did not carry stays uncarried. Copying the values instead would mark an absent
            // field as set with a null value, and the generated writer dereferences the value of
            // any option it finds set.
            NamingConfigResource changed = new(
                id: original.IdOption,
                renameEpisodes: original.RenameEpisodesOption,
                replaceIllegalCharacters: flipped,
                colonReplacementFormat: original.ColonReplacementFormatOption,
                customColonReplacementFormat: original.CustomColonReplacementFormatOption,
                multiEpisodeStyle: original.MultiEpisodeStyleOption,
                standardEpisodeFormat: original.StandardEpisodeFormatOption,
                javEpisodeFormat: original.JavEpisodeFormatOption,
                seriesFolderFormat: original.SeriesFolderFormatOption,
                includeSeriesTitle: original.IncludeSeriesTitleOption,
                includeEpisodeTitle: original.IncludeEpisodeTitleOption,
                includeQuality: original.IncludeQualityOption,
                replaceSpaces: original.ReplaceSpacesOption,
                separator: original.SeparatorOption,
                numberStyle: original.NumberStyleOption);

            IUpdateNamingConfigApiResponse restoreWrite;
            IGetNamingConfigApiResponse restoreRead;

            try
            {
                (await naming.UpdateNamingConfigAsync(id, changed)).EnsureSuccess();

                NamingConfigResource afterWrite = (await naming.GetNamingConfigAsync()).EnsureSuccess();

                // First, that the write landed. Without this the preservation assertion below
                // would pass just as well against a write that never happened.
                Assert.Equal(flipped, afterWrite.ReplaceIllegalCharacters);

                Assert.True(
                    string.Equals(preservedFormat, afterWrite.JavEpisodeFormat, StringComparison.Ordinal),
                    "javEpisodeFormat reads '" + afterWrite.JavEpisodeFormat + "' after the write "
                        + "and read '" + preservedFormat + "' before it, so a write through this "
                        + "client changed a field it was never asked to change.");
            }
            finally
            {
                // In the finally, and it matters more here than anywhere else in the suite. This
                // class shares one container with every other class, xunit contracts no order
                // between them, and a test that changed the naming config and failed before
                // putting it back would leave the container altered for whatever runs next.
                //
                // Issued without being classified. EnsureSuccess here would throw out of the
                // finally and replace whatever the try raised, and the run where javEpisodeFormat
                // is erased is the run where the restore write is most likely to be rejected too.
                // The reader would get a restore failure instead of the message naming the value
                // before and the value after.
                restoreWrite = await naming.UpdateNamingConfigAsync(id, original);
                restoreRead = await naming.GetNamingConfigAsync();
            }

            restoreWrite.EnsureSuccess();
            NamingConfigResource restored = restoreRead.EnsureSuccess();

            // Every field, in one comparison, against what the first read returned.
            Assert.Equal(original.ToString(), restored.ToString());
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
