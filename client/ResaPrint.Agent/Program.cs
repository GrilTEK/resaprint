using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using ResaPrint.Agent;
using ResaPrint.Shared;
using ResaPrint.Shared.Api;
using ResaPrint.Shared.Config;
using ResaPrint.Shared.Escpos;
using ResaPrint.Shared.Models;

if (args.Length > 0)
{
    switch (args[0])
    {
        case "--configure":
            return RunConfigure(args);
        case "--test-print":
            return RunTestPrint(args);
        case "--show-config":
            return RunShowConfig();
        case "--set-printer-name":
            return RunSetPrinterName(args);
        case "--set-poll-interval":
            return RunSetPollInterval(args);
    }
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
    int pollIntervalSeconds = 5;

    for (var i = 1; i < args.Length - 1; i++)
    {
        switch (args[i])
        {
            case "--api-base-url": apiBaseUrl = args[i + 1]; break;
            case "--station-id": stationId = int.Parse(args[i + 1]); break;
            case "--api-key": apiKey = args[i + 1]; break;
            case "--printer-name": printerName = args[i + 1]; break;
            case "--poll-interval": pollIntervalSeconds = int.Parse(args[i + 1]); break;
        }
    }

    if (string.IsNullOrWhiteSpace(apiBaseUrl) || string.IsNullOrWhiteSpace(apiKey) || stationId == 0)
    {
        Console.Error.WriteLine(
            "Usage: ResaPrint.Agent.exe --configure --api-base-url <url> --station-id <id> --api-key <key> [--printer-name <name>] [--poll-interval <seconds>]");
        return 1;
    }

    var config = new StationConfig
    {
        ApiBaseUrl = apiBaseUrl,
        StationId = stationId,
        ApiKey = apiKey,
        PrinterName = printerName ?? string.Empty,
        PollIntervalSeconds = pollIntervalSeconds,
    };

    DpapiConfigStore.Save(config);
    Console.WriteLine($"Configuration written to {DpapiConfigStore.DefaultPath}");
    return 0;
}

static int RunTestPrint(string[] args)
{
    // Standalone printer check — does not need the service to be
    // configured or the backend to be reachable at all. Useful during
    // install to confirm the Windows printer queue name/setup works
    // before wiring up pairing.
    string? printerName = null;
    for (var i = 1; i < args.Length - 1; i++)
    {
        if (args[i] == "--printer-name")
        {
            printerName = args[i + 1];
        }
    }

    printerName ??= DpapiConfigStore.TryLoad()?.PrinterName;
    if (string.IsNullOrWhiteSpace(printerName))
    {
        Console.Error.WriteLine("Usage: ResaPrint.Agent.exe --test-print --printer-name <Windows printer queue name>");
        Console.Error.WriteLine("(or configure the agent first so --printer-name can be omitted)");
        return 1;
    }

    var receipt = new ReceiptBuilder()
        .AlignCenter()
        .BoldLine("ResaPrint")
        .AlignLeft()
        .Line("Test print")
        .Line($"Printer: {printerName}")
        .Line($"Time: {DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss}")
        .Divider()
        .Feed(3)
        .Cut()
        .Build();

    Console.WriteLine($"Sending test receipt to '{printerName}'...");
    var printer = new WinspoolPosPrinter(printerName);
    var result = printer.PrintAsync(receipt).GetAwaiter().GetResult();

    if (result.Success)
    {
        Console.WriteLine("Test print sent successfully.");
        return 0;
    }

    Console.Error.WriteLine($"Test print failed: {result.Error}");
    return 1;
}

static int RunShowConfig()
{
    var config = DpapiConfigStore.TryLoad();
    if (config is null)
    {
        Console.WriteLine("Not configured yet (no config found at " + DpapiConfigStore.DefaultPath + ").");
        return 1;
    }

    var maskedKey = config.ApiKey.Length > 8 ? config.ApiKey[..4] + "..." + config.ApiKey[^4..] : "(short key)";
    Console.WriteLine($"Config path:      {DpapiConfigStore.DefaultPath}");
    Console.WriteLine($"API base URL:     {config.ApiBaseUrl}");
    Console.WriteLine($"Station ID:       {config.StationId}");
    Console.WriteLine($"API key:          {maskedKey}");
    Console.WriteLine($"Printer name:     {config.PrinterName}");
    Console.WriteLine($"Poll interval:    {config.PollIntervalSeconds}s");
    return 0;
}

static int RunSetPrinterName(string[] args)
{
    if (args.Length < 2)
    {
        Console.Error.WriteLine("Usage: ResaPrint.Agent.exe --set-printer-name <Windows printer queue name>");
        return 1;
    }

    var config = DpapiConfigStore.TryLoad();
    if (config is null)
    {
        Console.Error.WriteLine("Not configured yet — run --configure first.");
        return 1;
    }

    config.PrinterName = args[1];
    DpapiConfigStore.Save(config);
    Console.WriteLine($"Printer name updated to '{config.PrinterName}'. Restart the service for it to take effect:");
    Console.WriteLine("  Restart-Service ResaPrintAgent");
    return 0;
}

static int RunSetPollInterval(string[] args)
{
    if (args.Length < 2 || !int.TryParse(args[1], out var seconds) || seconds < 1)
    {
        Console.Error.WriteLine("Usage: ResaPrint.Agent.exe --set-poll-interval <seconds, minimum 1>");
        return 1;
    }

    var config = DpapiConfigStore.TryLoad();
    if (config is null)
    {
        Console.Error.WriteLine("Not configured yet — run --configure first.");
        return 1;
    }

    config.PollIntervalSeconds = seconds;
    DpapiConfigStore.Save(config);
    Console.WriteLine($"Poll interval updated to {seconds}s. Restart the service for it to take effect:");
    Console.WriteLine("  Restart-Service ResaPrintAgent");
    return 0;
}
