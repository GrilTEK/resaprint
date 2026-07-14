using ResaPrint.Shared.Api;
using ResaPrint.Shared.Models;

namespace ResaPrint.Agent.Tests.Fakes;

public sealed class FakeApiClient : IResaPrintApiClient
{
    public List<PrintJobDto> JobsToReturn { get; set; } = new();
    public List<(int JobId, string Status, string? Error)> Acks { get; } = new();
    public bool BackendReachable { get; set; } = true;

    public Task<List<PrintJobDto>> PollJobsAsync(CancellationToken cancellationToken = default)
        => Task.FromResult(JobsToReturn);

    public Task AckJobAsync(int jobId, string status, string? error, CancellationToken cancellationToken = default)
    {
        Acks.Add((jobId, status, error));
        return Task.CompletedTask;
    }

    public Task<bool> IsBackendReachableAsync(CancellationToken cancellationToken = default)
        => Task.FromResult(BackendReachable);
}
