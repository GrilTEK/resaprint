namespace ResaPrint.Agent;

/// <summary>Shared mutable status snapshot read by StatusEndpoint and written by Worker.</summary>
public sealed class AgentStatus
{
    public bool Configured { get; set; }
    public bool BackendReachable { get; set; }
    public DateTimeOffset? LastPollAt { get; set; }
    public DateTimeOffset? LastJobAt { get; set; }
    public string? LastJobResult { get; set; }
    public int QueueDepth { get; set; }
}
