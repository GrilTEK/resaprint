using Microsoft.Extensions.Logging;
using ResaPrint.Shared;
using ResaPrint.Shared.Api;
using ResaPrint.Shared.Escpos;
using ResaPrint.Shared.Models;

namespace ResaPrint.Agent;

/// <summary>
/// Polls the backend for queued print jobs targeted at this station,
/// renders each as ESC/POS bytes (from the server's human-readable
/// payload_text via the local ReceiptBuilder — this avoids needing to
/// serialize raw bytes over JSON while keeping byte-format parity
/// with the backend's own builder), sends them to the configured
/// printer, and acks the result back to the backend.
/// </summary>
public sealed class Worker : BackgroundService
{
    private readonly ILogger<Worker> _logger;
    private readonly IResaPrintApiClient _apiClient;
    private readonly IPosPrinter _printer;
    private readonly StationConfig _config;
    private readonly AgentStatus _status;

    public Worker(ILogger<Worker> logger, IResaPrintApiClient apiClient, IPosPrinter printer, StationConfig config, AgentStatus status)
    {
        _logger = logger;
        _apiClient = apiClient;
        _printer = printer;
        _config = config;
        _status = status;
        _status.Configured = true;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var interval = TimeSpan.FromSeconds(Math.Max(1, _config.PollIntervalSeconds));

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                await PollOnceAsync(stoppingToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "poll iteration failed");
                _status.BackendReachable = false;
            }

            try
            {
                await Task.Delay(interval, stoppingToken);
            }
            catch (TaskCanceledException)
            {
                break;
            }
        }
    }

    public async Task PollOnceAsync(CancellationToken cancellationToken)
    {
        var jobs = await _apiClient.PollJobsAsync(cancellationToken);
        _status.BackendReachable = true;
        _status.LastPollAt = DateTimeOffset.UtcNow;
        _status.QueueDepth = jobs.Count;

        foreach (var job in jobs)
        {
            await ProcessJobAsync(job, cancellationToken);
        }
    }

    public async Task ProcessJobAsync(PrintJobDto job, CancellationToken cancellationToken)
    {
        var bytes = RenderJob(job);
        var result = await _printer.PrintAsync(bytes, cancellationToken);

        _status.LastJobAt = DateTimeOffset.UtcNow;
        _status.LastJobResult = result.Success ? "printed" : $"failed: {result.Error}";

        await _apiClient.AckJobAsync(job.Id, result.Success ? "printed" : "failed", result.Error, cancellationToken);
    }

    public static byte[] RenderJob(PrintJobDto job)
    {
        var builder = new ReceiptBuilder();
        foreach (var line in job.PayloadText.Split('\n'))
        {
            builder.Line(line.TrimEnd('\r'));
        }
        builder.Feed(3).Cut();
        return builder.Build();
    }
}
