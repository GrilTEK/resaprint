namespace ResaPrint.Shared;

public readonly record struct PrintResult(bool Success, string? Error);

/// <summary>
/// Abstraction over "send these raw ESC/POS bytes to a physical
/// printer". The Windows Agent's implementation talks to winspool.drv
/// directly (see ResaPrint.Agent/WinspoolPosPrinter.cs); tests use a
/// fake implementation so poll/ack/retry logic can be exercised
/// without real hardware.
/// </summary>
public interface IPosPrinter
{
    Task<PrintResult> PrintAsync(byte[] payload, CancellationToken cancellationToken = default);
}
