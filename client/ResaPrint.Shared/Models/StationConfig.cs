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

    /// <summary>
    /// "escpos" (default): render payload_text into compact ESC/POS
    /// bytes and send RAW to the printer queue — needs the printer
    /// installed as "Generic / Text Only".
    /// "gdi_text": print payload_text through the Windows GDI printing
    /// pipeline instead (see GdiTextPrinter), matching the font/size
    /// the operator's previous standalone script used — needs the
    /// printer installed with its real Windows driver, not
    /// Generic/Text Only.
    /// </summary>
    public string PrintMode { get; set; } = "escpos";
}
