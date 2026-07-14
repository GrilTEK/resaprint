using System.Text.Json.Serialization;

namespace ResaPrint.Shared.Models;

public sealed class PrintJobDto
{
    [JsonPropertyName("id")]
    public int Id { get; set; }

    [JsonPropertyName("reservation_id")]
    public int? ReservationId { get; set; }

    [JsonPropertyName("station_id")]
    public int StationId { get; set; }

    [JsonPropertyName("status")]
    public string Status { get; set; } = "queued";

    [JsonPropertyName("payload_text")]
    public string PayloadText { get; set; } = string.Empty;

    [JsonPropertyName("attempts")]
    public int Attempts { get; set; }

    [JsonPropertyName("last_error")]
    public string? LastError { get; set; }
}

public sealed class AckRequestDto
{
    [JsonPropertyName("status")]
    public string Status { get; set; } = "printed";

    [JsonPropertyName("error")]
    public string? Error { get; set; }
}
