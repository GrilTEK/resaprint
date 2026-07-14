using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using ResaPrint.Agent;
using ResaPrint.Shared;
using ResaPrint.Shared.Api;
using ResaPrint.Shared.Config;
using ResaPrint.Shared.Models;

if (args.Length > 0 && args[0] == "--configure")
{
    return RunConfigure(args);
}

var builder = Host.CreateApplicationBuilder(args);
builder.Services.AddWindowsService(options => options.ServiceName = "ResaPrintAgent");

var status = new AgentStatus();
builder.Services.AddSingleton(status);

var config = DpapiConfigStore.TryLoad();
if (config is null)
{
    // Not paired yet. Still run the status endpoint so the Tray app
    // (and an operator running install.ps1) can see "not configured"
    // rather than the service silently failing to start.
    builder.Services.AddHostedService<StatusEndpoint>();
}
else
{
    builder.Services.AddSingleton(config);
    builder.Services.AddHttpClient();
    builder.Services.AddSingleton<IResaPrintApiClient>(sp =>
        new ResaPrintApiClient(sp.GetRequiredService<IHttpClientFactory>().CreateClient(), config.ApiBaseUrl, config.ApiKey));
    builder.Services.AddSingleton<IPosPrinter>(_ => new WinspoolPosPrinter(config.PrinterName));
    builder.Services.AddHostedService<Worker>();
    builder.Services.AddHostedService<StatusEndpoint>();
}

var host = builder.Build();
host.Run();
return 0;

static int RunConfigure(string[] args)
{
    string? apiBaseUrl = null, apiKey = null, printerName = null;
    int stationId = 0;

    for (var i = 1; i < args.Length - 1; i++)
    {
        switch (args[i])
        {
            case "--api-base-url": apiBaseUrl = args[i + 1]; break;
            case "--station-id": stationId = int.Parse(args[i + 1]); break;
            case "--api-key": apiKey = args[i + 1]; break;
            case "--printer-name": printerName = args[i + 1]; break;
        }
    }

    if (string.IsNullOrWhiteSpace(apiBaseUrl) || string.IsNullOrWhiteSpace(apiKey) || stationId == 0)
    {
        Console.Error.WriteLine("Usage: ResaPrint.Agent.exe --configure --api-base-url <url> --station-id <id> --api-key <key> [--printer-name <name>]");
        return 1;
    }

    var config = new StationConfig
    {
        ApiBaseUrl = apiBaseUrl,
        StationId = stationId,
        ApiKey = apiKey,
        PrinterName = printerName ?? string.Empty,
    };

    DpapiConfigStore.Save(config);
    Console.WriteLine($"Configuration written to {DpapiConfigStore.DefaultPath}");
    return 0;
}
