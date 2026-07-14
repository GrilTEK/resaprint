using System.Text;

namespace ResaPrint.Shared.Escpos;

public enum Align
{
    Left,
    Center,
    Right,
}

/// <summary>
/// C# port of backend/app/services/escpos_builder.py — kept as a
/// small hand-written builder (not a full library wrapper) so the two
/// implementations are easy to keep in sync and both are trivially
/// byte-testable. Used by the Agent as a fallback / manual-print path;
/// the primary path renders the receipt text server-side and prints
/// the same line-based payload_text through this builder locally.
/// </summary>
public static class EscposCommands
{
    private static readonly byte[] Esc = { 0x1b };
    private static readonly byte[] Gs = { 0x1d };

    public static byte[] Init() => Concat(Esc, "@"u8.ToArray());

    public static byte[] AlignCmd(Align mode)
    {
        byte code = mode switch
        {
            Align.Left => 0x00,
            Align.Center => 0x01,
            Align.Right => 0x02,
            _ => throw new ArgumentOutOfRangeException(nameof(mode)),
        };
        return Concat(Esc, "a"u8.ToArray(), new[] { code });
    }

    public static byte[] Bold(bool on) => Concat(Esc, "E"u8.ToArray(), new byte[] { (byte)(on ? 1 : 0) });

    public static byte[] Cut(bool partial = true) => Concat(Gs, "V"u8.ToArray(), new byte[] { (byte)(partial ? 1 : 0) });

    public static byte[] Feed(int n = 3) => Encoding.ASCII.GetBytes(new string('\n', n));

    public static byte[] EncodeLine(string text, Encoding codepage)
    {
        var line = codepage.GetBytes(text);
        return Concat(line, "\n"u8.ToArray());
    }

    private static byte[] Concat(params byte[][] parts)
    {
        var total = 0;
        foreach (var p in parts) total += p.Length;
        var result = new byte[total];
        var offset = 0;
        foreach (var p in parts)
        {
            Buffer.BlockCopy(p, 0, result, offset, p.Length);
            offset += p.Length;
        }
        return result;
    }
}

public sealed class ReceiptBuilder
{
    private readonly List<byte> _buf = new();
    private readonly Encoding _codepage;

    public ReceiptBuilder(Encoding? codepage = null)
    {
        _codepage = codepage ?? CodePage437();
        _buf.AddRange(EscposCommands.Init());
    }

    public static Encoding CodePage437()
    {
        Encoding.RegisterProvider(System.Text.CodePagesEncodingProvider.Instance);
        return Encoding.GetEncoding(437);
    }

    public ReceiptBuilder AlignLeft() { _buf.AddRange(EscposCommands.AlignCmd(Align.Left)); return this; }
    public ReceiptBuilder AlignCenter() { _buf.AddRange(EscposCommands.AlignCmd(Align.Center)); return this; }
    public ReceiptBuilder AlignRight() { _buf.AddRange(EscposCommands.AlignCmd(Align.Right)); return this; }

    public ReceiptBuilder BoldLine(string text)
    {
        _buf.AddRange(EscposCommands.Bold(true));
        _buf.AddRange(EscposCommands.EncodeLine(text, _codepage));
        _buf.AddRange(EscposCommands.Bold(false));
        return this;
    }

    public ReceiptBuilder Line(string text = "")
    {
        _buf.AddRange(EscposCommands.EncodeLine(text, _codepage));
        return this;
    }

    public ReceiptBuilder KvLine(string label, string value, int width = 42)
    {
        var gap = Math.Max(1, width - label.Length - value.Length);
        _buf.AddRange(EscposCommands.EncodeLine($"{label}{new string(' ', gap)}{value}", _codepage));
        return this;
    }

    public ReceiptBuilder Divider(int width = 42, char c = '-')
    {
        _buf.AddRange(EscposCommands.EncodeLine(new string(c, width), _codepage));
        return this;
    }

    public ReceiptBuilder Feed(int n = 3) { _buf.AddRange(EscposCommands.Feed(n)); return this; }

    public ReceiptBuilder Cut(bool partial = true) { _buf.AddRange(EscposCommands.Cut(partial)); return this; }

    public byte[] Build() => _buf.ToArray();
}
