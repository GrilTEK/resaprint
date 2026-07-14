using System.Net.Http.Headers;
using System.Net.Http.Json;
using ResaPrint.Shared.Models;

namespace ResaPrint.Shared.Api;

public sealed class ResaPrintApiClient : IResaPrintApiClient
{
    private readonly HttpClient _http;

    public ResaPrintApiClient(HttpClient http, string apiBaseUrl, string apiKey)
    {
        _http = http;
        _http.BaseAddress = new Uri(apiBaseUrl.TrimEnd('/') + "/");
        _http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", apiKey);
    }

    public async Task<List<PrintJobDto>> PollJobsAsync(CancellationToken cancellationToken = default)
    {
        var jobs = await _http.GetFromJsonAsync<List<PrintJobDto>>("api/v1/print-jobs/poll", cancellationToken);
        return jobs ?? new List<PrintJobDto>();
    }

    public async Task AckJobAsync(int jobId, string status, string? error, CancellationToken cancellationToken = default)
    {
        var body = new AckRequestDto { Status = status, Error = error };
        var response = await _http.PostAsJsonAsync($"api/v1/print-jobs/{jobId}/ack", body, cancellationToken);
        response.EnsureSuccessStatusCode();
    }

    public async Task<bool> IsBackendReachableAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            var response = await _http.GetAsync("healthz", cancellationToken);
            return response.IsSuccessStatusCode;
        }
        catch (Exception)
        {
            return false;
        }
    }
}
