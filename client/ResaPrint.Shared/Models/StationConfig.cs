namespace ResaPrint.Shared.Models;

/// <summary>
/// Local Agent configuration written during pairing (see
/// DpapiConfigStore) and read back on every service start.
/// </summary>
public sealed class StationConfig
{
    public string ApiBaseUrl { get; set; } = string.Empty;
    public int StationId { get; set; }
    public string ApiKey { get; set; } = string.Empty;
    public string PrinterName { get; set; } = string.Empty;
    public int PollIntervalSeconds { get; set; } = 5;
}
