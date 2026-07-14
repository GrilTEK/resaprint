using System.Net;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace ResaPrint.Agent;

/// <summary>
/// Localhost-only HTTP status endpoint for the Tray app (and manual
/// troubleshooting via curl). Uses HttpListener rather than Kestrel to
/// keep the trimmed/self-contained published EXE smaller. Never binds
/// anything but 127.0.0.1 — no firewall rule should ever be needed or
/// opened for this.
/// </summary>
public sealed class StatusEndpoint : BackgroundService
{
    private readonly AgentStatus _status;
    private readonly ILogger<StatusEndpoint> _logger;
    private readonly int _port;
    private readonly HttpListener _listener = new();

    public StatusEndpoint(AgentStatus status, ILogger<StatusEndpoint> logger, int port = 5990)
    {
        _status = status;
        _logger = logger;
        _port = port;
        _listener.Prefixes.Add($"http://127.0.0.1:{_port}/");
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        try
        {
            _listener.Start();
        }
        catch (HttpListenerException ex)
        {
            _logger.LogError(ex, "failed to start status endpoint on port {Port}", _port);
            return;
        }

        stoppingToken.Register(() => _listener.Stop());

        while (!stoppingToken.IsCancellationRequested)
        {
            HttpListenerContext context;
            try
            {
                context = await _listener.GetContextAsync();
            }
            catch (Exception) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "status endpoint request handling failed");
                continue;
            }

            _ = HandleAsync(context);
        }
    }

    private Task HandleAsync(HttpListenerContext context)
    {
        var json = JsonSerializer.Serialize(new
        {
            running = true,
            configured = _status.Configured,
            backendReachable = _status.BackendReachable,
            lastPollAt = _status.LastPollAt,
            lastJobAt = _status.LastJobAt,
            lastJobResult = _status.LastJobResult,
            queueDepth = _status.QueueDepth,
        });

        var bytes = Encoding.UTF8.GetBytes(json);
        context.Response.ContentType = "application/json";
        context.Response.ContentLength64 = bytes.Length;
        context.Response.OutputStream.Write(bytes, 0, bytes.Length);
        context.Response.OutputStream.Close();
        return Task.CompletedTask;
    }
}
