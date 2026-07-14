using Microsoft.Extensions.Logging.Abstractions;
using ResaPrint.Agent.Tests.Fakes;
using ResaPrint.Shared.Models;
using Xunit;

namespace ResaPrint.Agent.Tests;

public class WorkerTests
{
    private static Worker CreateWorker(FakeApiClient api, FakePosPrinter printer, AgentStatus? status = null)
    {
        var config = new StationConfig { ApiBaseUrl = "https://example.test", StationId = 1, ApiKey = "key", PollIntervalSeconds = 1 };
        return new Worker(NullLogger<Worker>.Instance, api, printer, config, status ?? new AgentStatus());
    }

    [Fact]
    public async Task ProcessJobAsync_PrintsAndAcksPrinted_OnSuccess()
    {
        var api = new FakeApiClient();
        var printer = new FakePosPrinter();
        var worker = CreateWorker(api, printer);
        var job = new PrintJobDto { Id = 42, StationId = 1, PayloadText = "Hello\nWorld" };

        await worker.ProcessJobAsync(job, CancellationToken.None);

        Assert.Single(printer.Received);
        Assert.Single(api.Acks);
        Assert.Equal((42, "printed", (string?)null), api.Acks[0]);
    }

    [Fact]
    public async Task ProcessJobAsync_AcksFailed_WhenPrinterFails()
    {
        var api = new FakeApiClient();
        var printer = new FakePosPrinter { ShouldFail = true, FailureMessage = "offline" };
        var worker = CreateWorker(api, printer);
        var job = new PrintJobDto { Id = 7, StationId = 1, PayloadText = "Hello" };

        await worker.ProcessJobAsync(job, CancellationToken.None);

        Assert.Single(api.Acks);
        Assert.Equal((7, "failed", "offline"), api.Acks[0]);
    }

    [Fact]
    public async Task PollOnceAsync_ProcessesAllReturnedJobs()
    {
        var api = new FakeApiClient
        {
            JobsToReturn = new List<PrintJobDto>
            {
                new() { Id = 1, StationId = 1, PayloadText = "A" },
                new() { Id = 2, StationId = 1, PayloadText = "B" },
                new() { Id = 3, StationId = 1, PayloadText = "C" },
            },
        };
        var printer = new FakePosPrinter();
        var status = new AgentStatus();
        var worker = CreateWorker(api, printer, status);

        await worker.PollOnceAsync(CancellationToken.None);

        Assert.Equal(3, printer.Received.Count);
        Assert.Equal(3, api.Acks.Count);
        Assert.Equal(3, status.QueueDepth);
        Assert.True(status.BackendReachable);
        Assert.NotNull(status.LastPollAt);
    }

    [Fact]
    public async Task PollOnceAsync_NoJobs_LeavesStatusConsistent()
    {
        var api = new FakeApiClient { JobsToReturn = new List<PrintJobDto>() };
        var printer = new FakePosPrinter();
        var status = new AgentStatus();
        var worker = CreateWorker(api, printer, status);

        await worker.PollOnceAsync(CancellationToken.None);

        Assert.Empty(printer.Received);
        Assert.Empty(api.Acks);
        Assert.Equal(0, status.QueueDepth);
    }

    [Fact]
    public void RenderJob_ProducesNonEmptyEscposBytesEndingInCut()
    {
        var job = new PrintJobDto { Id = 1, StationId = 1, PayloadText = "Guest: Jane\nRoom: 101" };
        var bytes = Worker.RenderJob(job);

        Assert.NotEmpty(bytes);
        // GS V 0x01 (partial cut) should be the final three bytes.
        Assert.Equal(0x1d, bytes[^3]);
        Assert.Equal((byte)'V', bytes[^2]);
        Assert.Equal(0x01, bytes[^1]);
    }

    [Fact]
    public async Task ProcessJobAsync_MultipleJobsWithMixedResults_EachAckedIndependently()
    {
        var api = new FakeApiClient();
        var printer = new FakePosPrinter();
        var worker = CreateWorker(api, printer);

        await worker.ProcessJobAsync(new PrintJobDto { Id = 1, StationId = 1, PayloadText = "ok" }, CancellationToken.None);

        printer.ShouldFail = true;
        printer.FailureMessage = "jam";
        await worker.ProcessJobAsync(new PrintJobDto { Id = 2, StationId = 1, PayloadText = "bad" }, CancellationToken.None);

        Assert.Equal((1, "printed", (string?)null), api.Acks[0]);
        Assert.Equal((2, "failed", "jam"), api.Acks[1]);
    }
}
