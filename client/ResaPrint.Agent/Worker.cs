using System.Text;
using Microsoft.Extensions.Logging;
using ResaPrint.Shared;
using ResaPrint.Shared.Api;
using ResaPrint.Shared.Escpos;
using ResaPrint.Shared.Models;

namespace ResaPrint.Agent;

/// <summary>
/// Polls the backend for queued print jobs targeted at this station,
/// renders each (from the server's human-readable payload_text — this
/// avoids needing to serialize raw bytes over JSON) and sends it to
/// the configured printer, then acks the result back to the backend.
///
/// Rendering depends on config.PrintMode: "escpos" (default) renders
/// compact ESC/POS bytes locally via ReceiptBuilder, keeping byte-
/// format parity with the backend's own builder; "gdi_text" skips
/// that entirely and hands the printer the raw UTF-8 text, since
/// GdiTextPrinter does its own font/layout rendering through the
/// Windows GDI printing pipeline instead of ESC/POS commands.
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
        var bytes = _config.PrintMode == "gdi_text"
            ? Encoding.UTF8.GetBytes(job.PayloadText)
            : RenderJob(job);
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
