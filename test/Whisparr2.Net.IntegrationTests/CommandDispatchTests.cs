// Hand-written test code. See .claude/CLAUDE.md, section "Generated code rules".

#nullable enable

using System.Net;
using Microsoft.Extensions.DependencyInjection;
using Whisparr2.Net.Api;
using Whisparr2.Net.Model;

namespace Whisparr2.Net.IntegrationTests
{
    /// <summary>
    /// The command dispatch against a real Whisparr, on the route that carries a search or a
    /// refresh.
    /// </summary>
    /// <remarks>
    /// <para>
    /// The unit suite proves the flat body left the client, read off the captured bytes. Only a
    /// real instance proves the body is accepted, what status the answer carries, and that the
    /// answer reads back as a CommandResource through the hand-written layer.
    /// </para>
    /// <para>
    /// CommandApi is resolved as the concrete type. SendCommandAsync is declared on it and not on
    /// ICommandApi, which is generator output and is not partial, and AddWhisparr2 registers the
    /// concrete type for exactly that reason. Resolving it here is what proves the registration
    /// works from a consumer's position.
    /// </para>
    /// <para>
    /// Nothing here names a host port or a host name. The address comes from the fixture, which
    /// reads it back from the container this run started.
    /// </para>
    /// </remarks>
    [Collection(WhisparrCollection.Name)]
    public sealed class CommandDispatchTests(WhisparrFixture fixture)
    {
        /// <summary>
        /// The command the accepted case dispatches. It takes an argument, which is the reason the
        /// dispatch exists at all.
        /// </summary>
        private const string DispatchedCommandName = "RefreshSeries";

        /// <summary>
        /// A series id no row in this container carries. The dispatch is an acknowledgement rather
        /// than a result, so naming a row that does not exist keeps this case from depending on the
        /// library contents.
        /// </summary>
        private const int UnknownSeriesId = 999999;

        /// <summary>A command name the server does not know.</summary>
        private const string UnknownCommandName = "NotARealCommand";

        /// <summary>
        /// A real Whisparr accepts a flat command body and answers with a readable command
        /// resource.
        /// </summary>
        /// <remarks>
        /// <para>
        /// Nothing is asserted about the echoed seriesId. The typed CommandResource.Body is a
        /// Command, whose generated reader ends default: break;, so the argument is dropped on the
        /// way in and no assertion here could see it. The wire shape is pinned instead by
        /// SerializationTests.Command_dispatch_puts_a_flat_name_and_payload_body_on_the_wire.
        /// </para>
        /// <para>
        /// Nothing is asserted about the outcome either. The answer is a dispatch acknowledgement
        /// and not a statement about execution, and this command's terminal status is failed by
        /// design, because the id it names does not exist.
        /// </para>
        /// </remarks>
        [SkippableFact]
        public async Task Command_dispatch_is_accepted_and_reads_back_as_a_command_resource()
        {
            Skip.If(fixture.SkipReason is not null, fixture.SkipReason);

            await using ServiceProvider provider = BuildProvider();
            CommandApi commands = provider.GetRequiredService<CommandApi>();

            ICreateCommandApiResponse response = await commands.SendCommandAsync(
                DispatchedCommandName,
                new { seriesId = UnknownSeriesId });

            // Measured against the pinned image: an accepted command answers 201, while the
            // document declares 200 for this operation. The generated Ok accessor therefore reads
            // nothing here and EnsureSuccess is what reads the body. Asserting the status first is
            // what pins that a caller no longer has to compose one for the accepted path.
            Assert.Equal(HttpStatusCode.Created, response.StatusCode);

            CommandResource dispatched = response.EnsureSuccess();

            Assert.True(dispatched.Id.HasValue, "The dispatch response carried no id.");

            Assert.True(
                dispatched.Id!.Value > 0,
                $"The server assigned command id {dispatched.Id!.Value}, which is not a positive integer.");

            Assert.True(
                string.Equals(DispatchedCommandName, dispatched.Name, StringComparison.Ordinal),
                $"The dispatch returned name '{dispatched.Name}'. The request sent '{DispatchedCommandName}'.");
        }

        /// <summary>
        /// A command name the server does not know is reported through the status, not by throwing.
        /// </summary>
        /// <remarks>
        /// <para>
        /// This is the half of the return shape a caller depends on: a caller that must not
        /// re-issue a command needs the status of the call it made, and reading it off a caught
        /// exception would give it on the refusal path only. EnsureSuccess turning the refusal into
        /// an exception is the caller's choice rather than the method's. This case creates nothing.
        /// </para>
        /// <para>
        /// The 500 is measured rather than expected. The controller looks the command name up with
        /// Single and does not guard the no-match case, so an unknown name leaves an unhandled
        /// InvalidOperationException and the answer is a 500 carrying that exception's message and
        /// stack trace. Whisparr 3 answers 400 to the same request. A caller cannot read an unknown
        /// command name off the status here, because a 500 is also what an accepted command answers
        /// when it fails inside the application.
        /// </para>
        /// <para>
        /// The body is not asserted. It is a JSON object with message and description members, and
        /// description carries a stack trace with source paths from the Whisparr build, so an
        /// assertion on it would pin a build detail rather than the API's behaviour.
        /// </para>
        /// </remarks>
        [SkippableFact]
        public async Task Unknown_command_name_surfaces_as_a_failure()
        {
            Skip.If(fixture.SkipReason is not null, fixture.SkipReason);

            await using ServiceProvider provider = BuildProvider();
            CommandApi commands = provider.GetRequiredService<CommandApi>();

            ICreateCommandApiResponse response = await commands.SendCommandAsync(UnknownCommandName);

            Assert.Equal(HttpStatusCode.InternalServerError, response.StatusCode);
            Assert.False(response.IsSuccessStatusCode);

            Whisparr2ApiException error =
                Assert.Throws<Whisparr2ApiException>(() => { response.EnsureSuccess(); });

            Assert.Equal(response.StatusCode, error.StatusCode);
            Assert.False(error.IsSuccessStatusCode);
        }

        /// <summary>
        /// Registers against the container this run started, through the same single call a
        /// consumer makes.
        /// </summary>
        /// <returns>A provider from which the command client resolves.</returns>
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
