using ResaPrint.Shared.Models;

namespace ResaPrint.Shared.Api;

public interface IResaPrintApiClient
{
    Task<List<PrintJobDto>> PollJobsAsync(CancellationToken cancellationToken = default);
    Task AckJobAsync(int jobId, string status, string? error, CancellationToken cancellationToken = default);
    Task<bool> IsBackendReachableAsync(CancellationToken cancellationToken = default);
}
