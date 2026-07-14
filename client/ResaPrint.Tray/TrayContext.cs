using System.Diagnostics;
using System.Drawing.Drawing2D;
using System.Net.Http.Json;
using System.Text.Json;

namespace ResaPrint.Tray;

/// <summary>
/// Status-only indicator: talks solely to the Agent's localhost
/// status endpoint, contains no printing logic. Deliberately has no
/// "Exit"/"Stop service" menu item — closing this has zero effect on
/// the ResaPrintAgent Windows Service.
/// </summary>
public sealed class TrayContext : ApplicationContext
{
    private const string StatusUrl = "http://127.0.0.1:5990/status";

    private readonly NotifyIcon _notifyIcon;
    private readonly System.Windows.Forms.Timer _timer;
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(2) };
    private readonly JsonSerializerOptions _jsonOptions = new() { PropertyNameCaseInsensitive = true };
    private string? _adminUrl;

    public TrayContext()
    {
        var menu = new ContextMenuStrip();
        menu.Items.Add("Open admin web UI", null, (_, _) => OpenAdminUi());
        menu.Items.Add("Show recent print jobs", null, (_, _) => OpenAdminUi("/print-jobs"));
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("About ResaPrint Agent", null, (_, _) => ShowAbout());

        _notifyIcon = new NotifyIcon
        {
            Icon = BuildStatusIcon(Color.Gray),
            Text = "ResaPrint Agent — checking status…",
            Visible = true,
            ContextMenuStrip = menu,
        };

        _timer = new System.Windows.Forms.Timer { Interval = 5000 };
        _timer.Tick += async (_, _) => await RefreshStatusAsync();
        _timer.Start();

        _ = RefreshStatusAsync();
    }

    private async Task RefreshStatusAsync()
    {
        try
        {
            var status = await _http.GetFromJsonAsync<AgentStatusDto>(StatusUrl, _jsonOptions);
            if (status is null)
            {
                SetState(Color.Red, "ResaPrint Agent — service not running");
                return;
            }

            if (!status.Configured)
            {
                SetState(Color.Orange, "ResaPrint Agent — not paired yet");
            }
            else if (status.BackendReachable)
            {
                SetState(Color.Green, "ResaPrint Agent — running, backend reachable");
            }
            else
            {
                SetState(Color.Gold, "ResaPrint Agent — running, backend unreachable");
            }
        }
        catch (Exception)
        {
            SetState(Color.Red, "ResaPrint Agent — service not running");
        }
    }

    private void SetState(Color color, string tooltip)
    {
        var oldIcon = _notifyIcon.Icon;
        _notifyIcon.Icon = BuildStatusIcon(color);
        _notifyIcon.Text = tooltip.Length > 63 ? tooltip[..63] : tooltip;
        oldIcon?.Dispose();
    }

    private void OpenAdminUi(string path = "/")
    {
        var baseUrl = _adminUrl ?? "http://localhost:8000";
        try
        {
            Process.Start(new ProcessStartInfo(baseUrl.TrimEnd('/') + path) { UseShellExecute = true });
        }
        catch (Exception)
        {
            // Best-effort — nothing meaningful to do if the browser can't be launched.
        }
    }

    private void ShowAbout()
    {
        var version = typeof(TrayContext).Assembly.GetName().Version?.ToString() ?? "unknown";
        MessageBox.Show(
            $"ResaPrint Agent tray v{version}\n\nStatus-only indicator for the ResaPrintAgent Windows Service.\nClosing this icon does not stop the service.",
            "About ResaPrint Agent",
            MessageBoxButtons.OK,
            MessageBoxIcon.Information);
    }

    private static Icon BuildStatusIcon(Color color)
    {
        using var bitmap = new Bitmap(32, 32);
        using (var g = Graphics.FromImage(bitmap))
        {
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.Clear(Color.Transparent);
            using var brush = new SolidBrush(color);
            g.FillEllipse(brush, 4, 4, 24, 24);
        }
        return Icon.FromHandle(bitmap.GetHicon());
    }

    private sealed class AgentStatusDto
    {
        public bool Configured { get; set; }
        public bool BackendReachable { get; set; }
    }
}
