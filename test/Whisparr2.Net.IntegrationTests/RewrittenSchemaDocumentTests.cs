// Hand-written test code. See .claude/CLAUDE.md, section "Generated code rules".

#nullable enable

using System.Text.Json;
using Xunit.Abstractions;

namespace Whisparr2.Net.IntegrationTests
{
    /// <summary>
    /// The subject set <see cref="RewrittenSchemaTests"/> exercises, derived from the two embedded
    /// documents and compared against that class's dispatch table.
    /// </summary>
    /// <remarks>
    /// No collection attribute, so <see cref="WhisparrFixture"/> does not initialize before this
    /// runs. The fixture boots a container and throws when the boot fails, and an xunit collection
    /// fixture that throws during initialization reports every test in the collection as failed.
    /// This class needs no container, and the signal it carries is which operation joined or left
    /// the derived set, so a failed image pull or a readiness timeout must not bury it.
    /// </remarks>
    public sealed class RewrittenSchemaDocumentTests(ITestOutputHelper output)
    {
        /// <summary>The pinned document, as embedded by the project file.</summary>
        private const string PinnedDocument = "openapi.raw.json";

        /// <summary>The pre-processed document, as embedded by the project file.</summary>
        private const string PreProcessedDocument = "openapi.generated.json";

        /// <summary>
        /// The derived subject set and the dispatch table hold the same operations.
        /// </summary>
        /// <remarks>
        /// It reads only the two embedded documents, so an operation that joins or leaves the set
        /// is reported wherever this suite runs rather than only where a container can boot.
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

            Assert.Equal(
                subjects,
                RewrittenSchemaTests.CallSites.Keys.Order(StringComparer.Ordinal).ToArray());
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
            using Stream? stream = typeof(RewrittenSchemaDocumentTests).Assembly
                .GetManifestResourceStream(logicalName);

            if (stream is null)
            {
                throw new InvalidOperationException(
                    "The " + logicalName + " resource is not embedded in this assembly. Check the "
                        + "EmbeddedResource item and its LogicalName in the project file.");
            }

            return JsonDocument.Parse(stream);
        }
    }
}
