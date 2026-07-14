using ResaPrint.Shared.Escpos;
using Xunit;

namespace ResaPrint.Agent.Tests;

public class EscposBuilderTests
{
    [Fact]
    public void Init_ReturnsEscAt()
    {
        Assert.Equal(new byte[] { 0x1b, (byte)'@' }, EscposCommands.Init());
    }

    [Theory]
    [InlineData(Align.Left, 0x00)]
    [InlineData(Align.Center, 0x01)]
    [InlineData(Align.Right, 0x02)]
    public void AlignCmd_EncodesExpectedByte(Align mode, byte expected)
    {
        var result = EscposCommands.AlignCmd(mode);
        Assert.Equal(new byte[] { 0x1b, (byte)'a', expected }, result);
    }

    [Theory]
    [InlineData(true, 0x01)]
    [InlineData(false, 0x00)]
    public void Bold_TogglesExpectedByte(bool on, byte expected)
    {
        var result = EscposCommands.Bold(on);
        Assert.Equal(new byte[] { 0x1b, (byte)'E', expected }, result);
    }

    [Theory]
    [InlineData(true, 0x01)]
    [InlineData(false, 0x00)]
    public void Cut_PartialAndFull(bool partial, byte expected)
    {
        var result = EscposCommands.Cut(partial);
        Assert.Equal(new byte[] { 0x1d, (byte)'V', expected }, result);
    }

    [Fact]
    public void Feed_RepeatsNewline()
    {
        Assert.Equal(new byte[] { (byte)'\n', (byte)'\n', (byte)'\n' }, EscposCommands.Feed(3));
    }

    [Fact]
    public void ReceiptBuilder_ProducesExpectedByteSequence()
    {
        var codepage = ReceiptBuilder.CodePage437();
        var receipt = new ReceiptBuilder(codepage)
            .AlignCenter()
            .BoldLine("ResaPrint")
            .AlignLeft()
            .KvLine("Guest:", "Jane Doe", width: 20)
            .Divider(width: 10)
            .Feed(2)
            .Cut()
            .Build();

        var expected = new List<byte>();
        expected.AddRange(EscposCommands.Init());
        expected.AddRange(EscposCommands.AlignCmd(Align.Center));
        expected.AddRange(EscposCommands.Bold(true));
        expected.AddRange(EscposCommands.EncodeLine("ResaPrint", codepage));
        expected.AddRange(EscposCommands.Bold(false));
        expected.AddRange(EscposCommands.AlignCmd(Align.Left));
        var gap = 20 - "Guest:".Length - "Jane Doe".Length;
        expected.AddRange(EscposCommands.EncodeLine($"Guest:{new string(' ', gap)}Jane Doe", codepage));
        expected.AddRange(EscposCommands.EncodeLine(new string('-', 10), codepage));
        expected.AddRange(EscposCommands.Feed(2));
        expected.AddRange(EscposCommands.Cut(true));

        Assert.Equal(expected.ToArray(), receipt);
    }

    [Fact]
    public void KvLine_MinimumOneSpaceWhenOverflowingWidth()
    {
        var receipt = new ReceiptBuilder().KvLine("Very long label", "Very long value", width: 5).Build();
        var text = System.Text.Encoding.ASCII.GetString(receipt);
        Assert.Contains("Very long label Very long value", text);
    }
}
