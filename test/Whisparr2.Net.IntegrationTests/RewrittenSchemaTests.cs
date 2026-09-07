// Hand-written test code. See .claude/CLAUDE.md, section "Generated code rules".

#nullable enable

using System.Text.Json;
using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net.Api;
using Whisparr2.Net.Model;
using Xunit.Abstractions;

namespace Whisparr2.Net.IntegrationTests
{
    /// <summary>
    /// Every read whose body reaches a schema the pre-processing rewrite turned into a string,
    /// called against a real instance and deserialized.
    /// </summary>
    /// <remarks>
    /// <para>
    /// The rewrite exists because six of eight first-call endpoints threw a serializer exception on
    /// an HTTP 200: the document declared five schemas as objects that the application sends as
    /// strings. This class is what shows they no longer do.
    /// </para>
    /// <para>
    /// The subject set is derived from the two embedded documents rather than typed into this file.
    /// The rewritten schemas are the component schemas the pinned document declares and the
    /// pre-processed document does not, which is the rewrite's own footprint. Their carriers are the
    /// schemas holding a property that referenced one of them, and the subject operations are the
    /// reads whose 200 body reaches a carrier. Nothing here restates a name or a population size
    /// from either document.
    /// </para>
    /// <para>
    /// What stops the proof shrinking is the equality between that derived set and the dispatch
    /// table below. A literal list of operations would fail on the members a fresh instance cannot
    /// answer, for reasons unrelated to deserialization, and a literal list of the ones that pass
    /// today would quietly shrink the day upstream changed the reference graph. The equality fails
    /// instead, naming the operation that moved.
    /// </para>
    /// </remarks>
    [Collection(WhisparrCollection.Name)]
    public sealed class RewrittenSchemaTests(WhisparrFixture fixture, ITestOutputHelper output)
    {
        /// <summary>The pinned document, as embedded by the project file.</summary>
        private const string PinnedDocument = "openapi.raw.json";

        /// <summary>The pre-processed document, as embedded by the project file.</summary>
        private const string PreProcessedDocument = "openapi.generated.json";

        /// <summary>A parse subject, so the parse operation has a title to answer about.</summary>
        /// <remarks>
        /// Invented, not taken from any library. The operation answers about the string it is
        /// given and reaches no file, so the title only has to be parseable.
        /// </remarks>
        private const string ParseSubject = "Some.Series.S01E02.1080p.WEB-DL.x264-GROUP";

        /// <summary>
        /// Every subject operation a fresh instance does not answer, with the reason.
        /// </summary>
        /// <remarks>
        /// Committed so the remainder cannot grow silently, and asserted in both directions: no
        /// operation named here was answered, and no operation that went unanswered is missing from
        /// here. A one-directional assertion would let a regression that broke a working read look
        /// like a documented gap.
        /// </remarks>
        private static readonly IReadOnlyDictionary<string, string> Unreachable =
            new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["GetCalendarById"] =
                    "No discoverable id: the calendar read answers 200 and carries no entry, "
                        + "because the calendar is derived from monitored series and a fresh "
                        + "instance has none.",
                ["GetCommandById"] =
                    "No discoverable id: the command list answers 200 and carries no entry, "
                        + "because nothing has queued a command on a fresh instance.",
                ["GetImportListById"] =
                    "No discoverable id: the import list read answers 200 and carries no entry, "
                        + "because none is configured on a fresh instance.",
                ["GetWantedCutoffById"] =
                    "No discoverable id: the cutoff-unmet page answers 200 with no records, "
                        + "because there is no series to be short of its cutoff.",
                ["GetWantedMissingById"] =
                    "No discoverable id: the missing page answers 200 with no records, because "
                        + "there is no series to be missing an episode.",
                ["GetEpisodeById"] =
                    "Answers a non-200: the discovery read this depends on is the episode list, "
                        + "which answers 400 without a series id, an episode file id or an "
                        + "episode id list.",
                ["ListEpisode"] =
                    "Answers a non-200: 400 without a series id, an episode file id or an episode "
                        + "id list, and a fresh instance has none to give it.",
                ["ListHistorySeries"] =
                    "Answers a non-200: 404 without a series id.",
                ["ListManualImport"] =
                    "Answers a non-200: 500 without a folder or a download id, because a fresh "
                        + "instance has no download client and no root folder.",
            };

        /// <summary>
        /// One call site per subject operation.
        /// </summary>
        /// <remarks>
        /// <para>
        /// A table rather than reflection over the generated assembly. A reflective dispatch that
        /// failed to find a method would read as a missing operation rather than as a typing
        /// mistake here, and the equality against the derived set is the assertion this class turns
        /// on.
        /// </para>
        /// <para>
        /// Every delegate reads its response through EnsureSuccess. The generated success accessor
        /// deserializes on exactly the declared status and returns null on every other, and the Try
        /// companion returns false on a failed deserialization and on an empty result alike, so a
        /// class built on either would report the serializer exception this phase exists to remove
        /// as an empty collection. EnsureSuccess separates the three outcomes and throws on two of
        /// them.
        /// </para>
        /// <para>
        /// A by-id delegate discovers its id from the sibling collection read and throws
        /// <see cref="NoDiscoverableIdException"/> when there is none, which is a distinct outcome
        /// from a request the instance rejected.
        /// </para>
        /// </remarks>
        private static readonly IReadOnlyDictionary<string, Func<ServiceProvider, Task<object>>> CallSites =
            new Dictionary<string, Func<ServiceProvider, Task<object>>>(StringComparer.Ordinal)
            {
                ["GetSystemStatus"] = async provider =>
                    (await provider.GetRequiredService<ISystemApi>().GetSystemStatusAsync())
                        .EnsureSuccess(),

                ["ListHealth"] = async provider =>
                    (await provider.GetRequiredService<IHealthApi>().ListHealthAsync())
                        .EnsureSuccess(),

                ["ListCommand"] = async provider =>
                    (await provider.GetRequiredService<ICommandApi>().ListCommandAsync())
                        .EnsureSuccess(),

                ["ListSystemTask"] = async provider =>
                    (await provider.GetRequiredService<ITaskApi>().ListSystemTaskAsync())
                        .EnsureSuccess(),

                ["ListUpdate"] = async provider =>
                    (await provider.GetRequiredService<IUpdateApi>().ListUpdateAsync())
                        .EnsureSuccess(),

                ["ListImportList"] = async provider =>
                    (await provider.GetRequiredService<IImportListApi>().ListImportListAsync())
                        .EnsureSuccess(),

                ["ListImportListSchema"] = async provider =>
                    (await provider.GetRequiredService<IImportListApi>().ListImportListSchemaAsync())
                        .EnsureSuccess(),

                ["ListCalendar"] = async provider =>
                    (await provider.GetRequiredService<ICalendarApi>().ListCalendarAsync())
                        .EnsureSuccess(),

                ["ListEpisode"] = async provider =>
                    (await provider.GetRequiredService<IEpisodeApi>().ListEpisodeAsync())
                        .EnsureSuccess(),

                ["ListQueueDetails"] = async provider =>
                    (await provider.GetRequiredService<IQueueDetailsApi>().ListQueueDetailsAsync())
                        .EnsureSuccess(),

                ["ListManualImport"] = async provider =>
                    (await provider.GetRequiredService<IManualImportApi>().ListManualImportAsync())
                        .EnsureSuccess(),

                ["ListHistorySeries"] = async provider =>
                    (await provider.GetRequiredService<IHistoryApi>().ListHistorySeriesAsync())
                        .EnsureSuccess(),

                ["ListHistorySince"] = async provider =>
                    (await provider.GetRequiredService<IHistoryApi>()
                        .ListHistorySinceAsync(date: DateTime.UnixEpoch))
                        .EnsureSuccess(),

                ["GetHistory"] = async provider =>
                    (await provider.GetRequiredService<IHistoryApi>().GetHistoryAsync())
                        .EnsureSuccess(),

                ["GetQueue"] = async provider =>
                    (await provider.GetRequiredService<IQueueApi>().GetQueueAsync())
                        .EnsureSuccess(),

                ["GetParse"] = async provider =>
                    (await provider.GetRequiredService<IParseApi>().GetParseAsync(title: ParseSubject))
                        .EnsureSuccess(),

                ["GetWantedCutoff"] = async provider =>
                    (await provider.GetRequiredService<ICutoffApi>().GetWantedCutoffAsync())
                        .EnsureSuccess(),

                ["GetWantedMissing"] = async provider =>
                    (await provider.GetRequiredService<IMissingApi>().GetWantedMissingAsync())
                        .EnsureSuccess(),

                ["GetCommandById"] = async provider =>
                {
                    ICommandApi api = provider.GetRequiredService<ICommandApi>();
                    List<CommandResource> commands = (await api.ListCommandAsync()).EnsureSuccess();
                    int id = FirstId(commands.Select(command => command.Id), "ListCommand");
                    return (await api.GetCommandByIdAsync(id)).EnsureSuccess();
                },

                ["GetSystemTaskById"] = async provider =>
                {
                    ITaskApi api = provider.GetRequiredService<ITaskApi>();
                    List<TaskResource> tasks = (await api.ListSystemTaskAsync()).EnsureSuccess();
                    int id = FirstId(tasks.Select(task => task.Id), "ListSystemTask");
                    return (await api.GetSystemTaskByIdAsync(id)).EnsureSuccess();
                },

                ["GetImportListById"] = async provider =>
                {
                    IImportListApi api = provider.GetRequiredService<IImportListApi>();
                    List<ImportListResource> lists = (await api.ListImportListAsync()).EnsureSuccess();
                    int id = FirstId(lists.Select(list => list.Id), "ListImportList");
                    return (await api.GetImportListByIdAsync(id)).EnsureSuccess();
                },

                ["GetCalendarById"] = async provider =>
                {
                    ICalendarApi api = provider.GetRequiredService<ICalendarApi>();
                    List<EpisodeResource> entries = (await api.ListCalendarAsync()).EnsureSuccess();
                    int id = FirstId(entries.Select(entry => entry.Id), "ListCalendar");
                    return (await api.GetCalendarByIdAsync(id)).EnsureSuccess();
                },

                ["GetEpisodeById"] = async provider =>
                {
                    // The discovery read this depends on needs a series id of its own, so on a
                    // fresh instance it is the discovery that is refused rather than the id that
                    // is absent. Attempted anyway rather than declared unreachable in advance: an
                    // id invented here would answer a 404 and prove nothing, while letting the
                    // discovery read speak is what makes the reason a measurement.
                    IEpisodeApi api = provider.GetRequiredService<IEpisodeApi>();
                    List<EpisodeResource> episodes = (await api.ListEpisodeAsync()).EnsureSuccess();
                    int id = FirstId(episodes.Select(episode => episode.Id), "ListEpisode");
                    return (await api.GetEpisodeByIdAsync(id)).EnsureSuccess();
                },

                ["GetWantedCutoffById"] = async provider =>
                {
                    ICutoffApi api = provider.GetRequiredService<ICutoffApi>();
                    EpisodeResourcePagingResource page =
                        (await api.GetWantedCutoffAsync()).EnsureSuccess();
                    int id = FirstId(
                        (page.Records ?? new List<EpisodeResource>()).Select(record => record.Id),
                        "GetWantedCutoff");
                    return (await api.GetWantedCutoffByIdAsync(id)).EnsureSuccess();
                },

                ["GetWantedMissingById"] = async provider =>
                {
                    IMissingApi api = provider.GetRequiredService<IMissingApi>();
                    EpisodeResourcePagingResource page =
                        (await api.GetWantedMissingAsync()).EnsureSuccess();
                    int id = FirstId(
                        (page.Records ?? new List<EpisodeResource>()).Select(record => record.Id),
                        "GetWantedMissing");
                    return (await api.GetWantedMissingByIdAsync(id)).EnsureSuccess();
                },
            };

        /// <summary>
        /// The derived subject set and the dispatch table hold the same operations.
        /// </summary>
        /// <remarks>
        /// Separate from the live exercise below so it runs on a machine with no Docker. It reads
        /// only the two embedded documents, so an operation that joins or leaves the set is
        /// reported wherever this suite runs rather than only where a container can boot.
        /// </remarks>
        [Fact]
        public void The_dispatch_table_holds_exactly_the_operations_the_documents_name()
        {
            using JsonDocument pinned = ReadEmbedded(PinnedDocument);
            using JsonDocument preProcessed = ReadEmbedded(PreProcessedDocument);

            IReadOnlyCollection<string> rewritten = RewrittenSchemas(pinned, preProcessed);
            IReadOnlyCollection<string> carriers = CarrierSchemas(pinned, rewritten);
            IReadOnlyCollection<string> subjects = SubjectOperations(preProcessed, carriers);

            // Printed, not compared to a number. Each of these three populations is a fact of the
            // committed documents, and a literal here would be a copy of it with a check that the
            // copy still matches. What holds the proof to its size is the equality below, which
            // names the operation that moved instead of reporting a count that changed.
            output.WriteLine("rewritten schemas: " + string.Join(", ", rewritten));
            output.WriteLine("carrier schemas: " + string.Join(", ", carriers));
            output.WriteLine("subject operations: " + string.Join(", ", subjects));

            Assert.NotEmpty(rewritten);
            Assert.NotEmpty(carriers);
            Assert.NotEmpty(subjects);

            Assert.Equal(subjects, CallSites.Keys.Order(StringComparer.Ordinal).ToArray());
        }

        /// <summary>
        /// Every subject operation the instance answers deserializes, and the rest are the ones
        /// this file says they are.
        /// </summary>
        [SkippableFact]
        public async Task Every_answered_subject_operation_deserializes()
        {
            Skip.If(fixture.SkipReason is not null, fixture.SkipReason);

            await using ServiceProvider provider = BuildProvider();

            Dictionary<string, object> answered = new(StringComparer.Ordinal);
            Dictionary<string, string> refused = new(StringComparer.Ordinal);

            foreach ((string operationId, Func<ServiceProvider, Task<object>> call) in
                CallSites.OrderBy(entry => entry.Key, StringComparer.Ordinal))
            {
                try
                {
                    object value = await call(provider);

                    Assert.NotNull(value);
                    answered.Add(operationId, value);
                }
                catch (NoDiscoverableIdException e)
                {
                    refused.Add(operationId, e.Message);
                }
                catch (Whisparr2ApiException e)
                {
                    // A success whose body could not be read is a deserialization failure, which
                    // is the defect this class exists to catch, so it is not absorbed here.
                    Assert.False(
                        e.IsSuccessStatusCode,
                        operationId + " answered a success whose body could not be read: " + e.Message);

                    refused.Add(operationId, e.Message);
                }
            }

            foreach ((string operationId, object value) in answered.OrderBy(
                entry => entry.Key, StringComparer.Ordinal))
            {
                output.WriteLine("answered " + operationId + ": " + Describe(value));
            }

            foreach ((string operationId, string reason) in refused.OrderBy(
                entry => entry.Key, StringComparer.Ordinal))
            {
                output.WriteLine("not answered " + operationId + ": " + reason);
            }

            Assert.NotEmpty(answered);

            // Both directions. Nothing enumerated as unreachable was answered, and nothing that
            // went unanswered is missing from the enumeration.
            Assert.Equal(
                Unreachable.Keys.Order(StringComparer.Ordinal).ToArray(),
                refused.Keys.Order(StringComparer.Ordinal).ToArray());

            AssertRewrittenValuesArrived(answered);
        }

        /// <summary>
        /// One non-empty rewritten value per carrier that a fresh instance populates.
        /// </summary>
        /// <param name="answered">Every subject operation's deserialized body, by operation id.</param>
        /// <remarks>
        /// <para>
        /// Without this, an instance answering every subject with an empty collection would pass
        /// the whole class. Each assertion below reads a property that referenced one of the
        /// rewritten schemas, so it fails on a body that arrived structurally present and empty.
        /// </para>
        /// <para>
        /// Four of the eight carriers have no live element on a fresh instance, so they get no
        /// witness here. EpisodeResource has none because every path to an episode is closed: the
        /// episode list answers 400 without a series id, the calendar is derived from monitored
        /// series, and both wanted pages answer with no records. CommandResource has none because
        /// nothing has queued a command, and QueueResource has none because nothing is
        /// downloading. UpdateResource is the fourth carrier reached through a paging shell, and it
        /// does carry an entry, which is why it has a witness above.
        /// </para>
        /// <para>
        /// DateOnly and DayOfWeek therefore have no live carrier at all: both were referenced only
        /// from EpisodeResource.releaseDate and from each other. Opening that path would mean
        /// adding a series, which reaches a metadata service outside the container. That is what
        /// the flagged lookup elsewhere in this project is gated for.
        /// </para>
        /// </remarks>
        private void AssertRewrittenValuesArrived(IReadOnlyDictionary<string, object> answered)
        {
            SystemResource status = Answer<SystemResource>(answered, "GetSystemStatus");

            // The named case in the phase goal. runtimeVersion is one of the rewritten sites: the
            // document declared it as a Version object and the instance sends "6.0.36".
            Assert.False(
                string.IsNullOrWhiteSpace(status.RuntimeVersion),
                "system/status answered with no runtimeVersion, so the rewritten site arrived "
                    + "empty rather than deserialized.");

            Assert.False(
                string.IsNullOrWhiteSpace(status.DatabaseVersion),
                "system/status answered with no databaseVersion, which is a second rewritten site "
                    + "on the same body.");

            // sqliteVersion is the third rewritten site on this body and is printed rather than
            // asserted. Measured against the pinned image: the instance answers an empty string
            // there while runtimeVersion and databaseVersion both carry a value, so an assertion
            // on it would fail on a body that deserialized correctly.
            output.WriteLine("system/status runtimeVersion: " + status.RuntimeVersion);
            output.WriteLine("system/status databaseVersion: " + status.DatabaseVersion);
            output.WriteLine("system/status sqliteVersion: " + status.SqliteVersion);

            UpdateResource update = FirstOf(
                Answer<List<UpdateResource>>(answered, "ListUpdate"),
                "ListUpdate");

            Assert.False(
                // VarVersion, not Version. The generator prefixes a member whose name would
                // collide with the enclosing type's own, and the wire name is still "version".
                string.IsNullOrWhiteSpace(update.VarVersion),
                "An update entry arrived with no version, which is the rewritten site on that "
                    + "schema.");

            HealthResource health = FirstOf(
                Answer<List<HealthResource>>(answered, "ListHealth"),
                "ListHealth");

            Assert.False(
                string.IsNullOrWhiteSpace(health.WikiUrl),
                "A health entry arrived with no wikiUrl, which is the rewritten site on that "
                    + "schema.");

            TaskResource task = FirstOf(
                Answer<List<TaskResource>>(answered, "ListSystemTask"),
                "ListSystemTask");

            Assert.False(
                string.IsNullOrWhiteSpace(task.LastDuration),
                "A scheduled task arrived with no lastDuration, which is the rewritten site on "
                    + "that schema.");

            ImportListResource schema = FirstOf(
                Answer<List<ImportListResource>>(answered, "ListImportListSchema"),
                "ListImportListSchema");

            Assert.False(
                string.IsNullOrWhiteSpace(schema.MinRefreshInterval),
                "An import list schema arrived with no minRefreshInterval, which is the rewritten "
                    + "site on that schema.");
        }

        /// <summary>Names what one answered body turned out to be.</summary>
        /// <param name="value">The deserialized body.</param>
        /// <returns>Its type, and its element count when it is a collection.</returns>
        /// <remarks>
        /// The count is printed rather than asserted. Which reads a fresh instance populates is a
        /// property of the application, and the witness assertions below name the ones it does
        /// populate; a number here would be a copy of that with nothing keeping it true.
        /// </remarks>
        private static string Describe(object value)
        {
            return value is System.Collections.ICollection items
                ? value.GetType().Name + ", " + items.Count + " element(s)"
                : value.GetType().Name;
        }

        /// <summary>Reads one answered body at the type its operation returns.</summary>
        /// <typeparam name="T">The body type.</typeparam>
        /// <param name="answered">Every answered body, by operation id.</param>
        /// <param name="operationId">The operation to read.</param>
        /// <returns>The body.</returns>
        private static T Answer<T>(IReadOnlyDictionary<string, object> answered, string operationId)
            where T : class
        {
            Assert.True(
                answered.ContainsKey(operationId),
                operationId + " was not answered, so no rewritten value from it can be asserted. "
                    + "If that is now expected, it belongs in the unreachable enumeration and its "
                    + "carrier loses its live witness.");

            return Assert.IsType<T>(answered[operationId]);
        }

        /// <summary>Reads the first element of a body that must not be empty.</summary>
        /// <typeparam name="T">The element type.</typeparam>
        /// <param name="items">The deserialized collection.</param>
        /// <param name="operationId">The operation that answered it, for the message.</param>
        /// <returns>The first element.</returns>
        private static T FirstOf<T>(List<T> items, string operationId)
        {
            Assert.True(
                items.Count > 0,
                operationId + " answered an empty collection, so nothing in it carries a "
                    + "rewritten value and a serializer that dropped every element would pass.");

            return items[0];
        }

        /// <summary>Returns the first non-null id, or reports that there is none.</summary>
        /// <param name="ids">The ids the collection read carried.</param>
        /// <param name="source">The operation the ids came from, for the message.</param>
        /// <returns>The first id.</returns>
        /// <exception cref="NoDiscoverableIdException">The collection carried no id.</exception>
        private static int FirstId(IEnumerable<int?> ids, string source)
        {
            foreach (int? id in ids)
            {
                if (id is int found)
                {
                    return found;
                }
            }

            throw new NoDiscoverableIdException(source);
        }

        /// <summary>
        /// The component schemas the rewrite removed: present in the pinned document, absent from
        /// the pre-processed one.
        /// </summary>
        /// <param name="pinned">The pinned document.</param>
        /// <param name="preProcessed">The pre-processed document.</param>
        /// <returns>The removed schema names, ordinally sorted.</returns>
        /// <remarks>
        /// Derived rather than listed. The rewrite replaces each of these object schemas with a
        /// string at every site that referenced it and then deletes the schema, so the set
        /// difference between the two documents is the rewrite's own footprint. A list here would
        /// be a copy of that footprint with nothing keeping it honest.
        /// </remarks>
        private static IReadOnlyCollection<string> RewrittenSchemas(
            JsonDocument pinned,
            JsonDocument preProcessed)
        {
            HashSet<string> surviving = new(Schemas(preProcessed).Select(schema => schema.Name), StringComparer.Ordinal);

            return Schemas(pinned)
                .Select(schema => schema.Name)
                .Where(name => !surviving.Contains(name))
                .Order(StringComparer.Ordinal)
                .ToArray();
        }

        /// <summary>
        /// The component schemas holding a property that referenced a rewritten schema.
        /// </summary>
        /// <param name="pinned">The pinned document, which is the only one that still names them.</param>
        /// <param name="rewritten">The rewritten schema names.</param>
        /// <returns>The carrier schema names, ordinally sorted.</returns>
        private static IReadOnlyCollection<string> CarrierSchemas(
            JsonDocument pinned,
            IReadOnlyCollection<string> rewritten)
        {
            HashSet<string> targets = new(rewritten, StringComparer.Ordinal);
            SortedSet<string> carriers = new(StringComparer.Ordinal);

            foreach (JsonProperty schema in Schemas(pinned))
            {
                if (targets.Contains(schema.Name))
                {
                    // A reference between two rewritten schemas is internal to the set and carries
                    // nothing a caller reads.
                    continue;
                }

                if (!schema.Value.TryGetProperty("properties", out JsonElement properties)
                    || properties.ValueKind != JsonValueKind.Object)
                {
                    continue;
                }

                foreach (JsonProperty property in properties.EnumerateObject())
                {
                    if (ReferencedSchema(property.Value) is string referenced
                        && targets.Contains(referenced))
                    {
                        carriers.Add(schema.Name);
                    }
                }
            }

            return carriers;
        }

        /// <summary>
        /// The reads whose 200 body reaches a carrier schema, transitively.
        /// </summary>
        /// <param name="preProcessed">The pre-processed document, which names each operation.</param>
        /// <param name="carriers">The carrier schema names.</param>
        /// <returns>The operation ids, ordinally sorted.</returns>
        private static IReadOnlyCollection<string> SubjectOperations(
            JsonDocument preProcessed,
            IReadOnlyCollection<string> carriers)
        {
            HashSet<string> targets = new(carriers, StringComparer.Ordinal);
            Dictionary<string, JsonElement> schemas = Schemas(preProcessed)
                .ToDictionary(schema => schema.Name, schema => schema.Value, StringComparer.Ordinal);
            SortedSet<string> subjects = new(StringComparer.Ordinal);

            foreach (JsonProperty path in preProcessed.RootElement.GetProperty("paths").EnumerateObject())
            {
                if (!path.Value.TryGetProperty("get", out JsonElement read)
                    || !read.TryGetProperty("responses", out JsonElement responses)
                    || !responses.TryGetProperty("200", out JsonElement success)
                    || !read.TryGetProperty("operationId", out JsonElement operationId))
                {
                    continue;
                }

                HashSet<string> reached = new(StringComparer.Ordinal);
                CollectReferences(success, reached);

                HashSet<string> expanded = new(StringComparer.Ordinal);

                foreach (string name in reached)
                {
                    Expand(name, schemas, expanded);
                }

                if (expanded.Overlaps(targets))
                {
                    subjects.Add(operationId.GetString()!);
                }
            }

            return subjects;
        }

        /// <summary>Adds a schema and everything it references to the reached set.</summary>
        /// <param name="name">The schema to expand.</param>
        /// <param name="schemas">Every component schema, by name.</param>
        /// <param name="reached">The set to add to.</param>
        private static void Expand(
            string name,
            IReadOnlyDictionary<string, JsonElement> schemas,
            HashSet<string> reached)
        {
            if (!reached.Add(name) || !schemas.TryGetValue(name, out JsonElement schema))
            {
                return;
            }

            HashSet<string> referenced = new(StringComparer.Ordinal);
            CollectReferences(schema, referenced);

            foreach (string next in referenced)
            {
                Expand(next, schemas, reached);
            }
        }

        /// <summary>Collects every component schema name a subtree references.</summary>
        /// <param name="node">The subtree to walk.</param>
        /// <param name="found">The set to add to.</param>
        private static void CollectReferences(JsonElement node, HashSet<string> found)
        {
            switch (node.ValueKind)
            {
                case JsonValueKind.Object:
                    foreach (JsonProperty member in node.EnumerateObject())
                    {
                        if (member.NameEquals("$ref") && member.Value.ValueKind == JsonValueKind.String)
                        {
                            found.Add(LastSegment(member.Value.GetString()!));
                        }

                        CollectReferences(member.Value, found);
                    }

                    break;

                case JsonValueKind.Array:
                    foreach (JsonElement element in node.EnumerateArray())
                    {
                        CollectReferences(element, found);
                    }

                    break;

                default:
                    break;
            }
        }

        /// <summary>
        /// The schema a property node references directly, or through a single-member allOf.
        /// </summary>
        /// <param name="property">The property node.</param>
        /// <returns>The referenced schema name, or null when the property references none.</returns>
        /// <remarks>
        /// A one-member allOf is how this document wraps a reference it also wants to annotate, and
        /// it is the shape four of the five rewritten schemas were referenced through.
        /// </remarks>
        private static string? ReferencedSchema(JsonElement property)
        {
            if (property.ValueKind != JsonValueKind.Object)
            {
                return null;
            }

            if (property.TryGetProperty("$ref", out JsonElement direct)
                && direct.ValueKind == JsonValueKind.String)
            {
                return LastSegment(direct.GetString()!);
            }

            if (property.TryGetProperty("allOf", out JsonElement wrapped)
                && wrapped.ValueKind == JsonValueKind.Array)
            {
                foreach (JsonElement member in wrapped.EnumerateArray())
                {
                    if (member.ValueKind == JsonValueKind.Object
                        && member.TryGetProperty("$ref", out JsonElement inner)
                        && inner.ValueKind == JsonValueKind.String)
                    {
                        return LastSegment(inner.GetString()!);
                    }
                }
            }

            return null;
        }

        /// <summary>The schema name at the end of a local reference pointer.</summary>
        /// <param name="pointer">The reference pointer.</param>
        /// <returns>Its last segment.</returns>
        private static string LastSegment(string pointer)
        {
            int separator = pointer.LastIndexOf('/');

            return separator < 0 ? pointer : pointer[(separator + 1)..];
        }

        /// <summary>Every component schema of a document.</summary>
        /// <param name="openapi">The document.</param>
        /// <returns>The schema members.</returns>
        private static IEnumerable<JsonProperty> Schemas(JsonDocument openapi)
        {
            return openapi.RootElement
                .GetProperty("components")
                .GetProperty("schemas")
                .EnumerateObject();
        }

        /// <summary>Reads one document out of this assembly.</summary>
        /// <param name="logicalName">The logical name the project file gave it.</param>
        /// <returns>The parsed document, which the caller disposes.</returns>
        /// <exception cref="InvalidOperationException">The resource is missing from the assembly.</exception>
        private static JsonDocument ReadEmbedded(string logicalName)
        {
            using Stream? stream = typeof(RewrittenSchemaTests).Assembly
                .GetManifestResourceStream(logicalName);

            if (stream is null)
            {
                throw new InvalidOperationException(
                    "The " + logicalName + " resource is not embedded in this assembly. Check the "
                        + "EmbeddedResource item and its LogicalName in the project file.");
            }

            return JsonDocument.Parse(stream);
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

        /// <summary>
        /// Raised when a by-id read has no id to address, which is not a rejected request.
        /// </summary>
        /// <remarks>
        /// A distinct type rather than a flag on the failure path. A by-id read attempted with an
        /// invented id would answer a 404, and reporting that as the same outcome as an empty
        /// collection read would let a genuinely broken read hide behind a documented gap.
        /// </remarks>
        private sealed class NoDiscoverableIdException(string source)
            : InvalidOperationException(
                "No discoverable id: " + source + " carried none on this instance.")
        {
        }
    }
}
