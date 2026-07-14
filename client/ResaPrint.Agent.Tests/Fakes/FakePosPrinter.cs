using ResaPrint.Shared;

namespace ResaPrint.Agent.Tests.Fakes;

public sealed class FakePosPrinter : IPosPrinter
{
    public List<byte[]> Received { get; } = new();
    public bool ShouldFail { get; set; }
    public string? FailureMessage { get; set; } = "simulated printer failure";

    public Task<PrintResult> PrintAsync(byte[] payload, CancellationToken cancellationToken = default)
    {
        Received.Add(payload);
        return Task.FromResult(ShouldFail ? new PrintResult(false, FailureMessage) : new PrintResult(true, null));
    }
}
