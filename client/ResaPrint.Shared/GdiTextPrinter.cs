using System.Drawing;
using System.Drawing.Printing;
using System.Runtime.Versioning;
using System.Text;

namespace ResaPrint.Shared;

/// <summary>
/// Prints receipt text through the Windows GDI printing pipeline
/// (System.Drawing.Printing) instead of sending raw ESC/POS bytes —
/// matching the font, size, and layout the operator's previous
/// standalone Python script used (win32ui CreateFont at a 40px cell
/// height/semibold weight, 60px line spacing, starting at (50, 50)),
/// which reads noticeably larger on a thermal receipt printer than
/// its own built-in ESC/POS Font A/B does even at the largest text_size
/// multiplier.
///
/// Unlike WinspoolPosPrinter (RAW datatype, bypasses the driver
/// entirely), this requires the printer to be installed with an
/// actual Windows-compatible driver capable of GDI rendering — not a
/// "Generic / Text Only" RAW-passthrough queue. It's the printer setup
/// the old script was built against, so operators switching to this
/// mode should already have the right driver installed.
/// </summary>
[SupportedOSPlatform("windows")]
public sealed class GdiTextPrinter : IPosPrinter
{
    private static readonly string[] FontCandidates = { "Arial Unicode MS", "Segoe UI", "Arial" };
    private const float FontHeightPx = 40f;
    private const float LineGapPx = 60f;
    private const float StartX = 50f;
    private const float StartY = 50f;

    private readonly string _printerName;

    public GdiTextPrinter(string printerName)
    {
        _printerName = printerName;
    }

    public Task<PrintResult> PrintAsync(byte[] payload, CancellationToken cancellationToken = default)
    {
        var text = Encoding.UTF8.GetString(payload);
        return Task.Run(() => PrintText(text), cancellationToken);
    }

    private PrintResult PrintText(string text)
    {
        using var font = CreateFont();
        var lines = text.Replace("\r\n", "\n").TrimEnd('\n').Split('\n');

        try
        {
            using var doc = new PrintDocument();
            doc.PrinterSettings.PrinterName = _printerName;
            if (!doc.PrinterSettings.IsValid)
            {
                return new PrintResult(false, $"printer '{_printerName}' not found or invalid");
            }

            doc.PrintPage += (_, e) =>
            {
                var g = e.Graphics!;
                g.PageUnit = GraphicsUnit.Pixel;
                var y = StartY;
                foreach (var line in lines)
                {
                    g.DrawString(line, font, Brushes.Black, StartX, y);
                    y += LineGapPx;
                }
            };

            doc.Print();
            return new PrintResult(true, null);
        }
        catch (Exception ex)
        {
            return new PrintResult(false, ex.Message);
        }
    }

    private static Font CreateFont()
    {
        // win32ui's CreateFont({"weight": 600}) is semibold — .NET's
        // FontStyle only offers a plain Bold toggle (no numeric
        // weights), so Bold is the closest match available here.
        foreach (var name in FontCandidates)
        {
            try
            {
                return new Font(name, FontHeightPx, FontStyle.Bold, GraphicsUnit.Pixel);
            }
            catch (ArgumentException)
            {
                // Font family not installed on this machine — try the next candidate.
            }
        }

        return new Font(FontFamily.GenericSansSerif, FontHeightPx, FontStyle.Bold, GraphicsUnit.Pixel);
    }
}
