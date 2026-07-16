using System.Diagnostics;
using System.Drawing.Printing;
using System.Net.Http.Json;
using System.Text.Json;
using ResaPrint.Shared.Escpos;

namespace ResaPrint.Installer;

/// <summary>
/// Graphical alternative to install.ps1: pick a printer from a list
/// (instead of typing the exact Windows queue name), send a test print
/// before installing anything, and either auto-pair a new station via
/// an admin PIN or use a station ID/API key already paired manually.
/// Actually installing the service/scheduled task shells out to the
/// same sc.exe/schtasks.exe/--configure commands install-agent.ps1 and
/// install-tray-task.ps1 use, so both installers stay in lockstep.
/// </summary>
public sealed class InstallerForm : Form
{
    private readonly TextBox _apiBaseUrlBox;
    private readonly RadioButton _autoPairRadio;
    private readonly RadioButton _manualPairRadio;
    private readonly TextBox _adminPinBox;
    private readonly TextBox _stationNameBox;
    private readonly TextBox _stationIdBox;
    private readonly TextBox _apiKeyBox;
    private readonly ComboBox _printerCombo;
    private readonly ComboBox _printModeCombo;
    private readonly Button _testPrintButton;
    private readonly Button _installButton;
    private readonly TextBox _logBox;
    private readonly Label _statusLabel;
    private readonly ProgressBar _progressBar;

    public InstallerForm()
    {
        Text = "ResaPrint Client Setup";
        Width = 640;
        Height = 640;
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(560, 560);

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(16),
            ColumnCount = 1,
            RowCount = 8,
            AutoSize = false,
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        Controls.Add(root);

        // ---- Backend URL ----
        var urlGroup = new GroupBox { Text = "Backend", Dock = DockStyle.Top, Height = 60 };
        var urlPanel = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, Padding = new Padding(8) };
        urlPanel.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        urlPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        urlPanel.Controls.Add(new Label { Text = "API base URL:", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 0);
        _apiBaseUrlBox = new TextBox { Dock = DockStyle.Fill, Text = "http://" };
        urlPanel.Controls.Add(_apiBaseUrlBox, 1, 0);
        urlGroup.Controls.Add(urlPanel);
        root.Controls.Add(urlGroup, 0, 0);

        // ---- Pairing ----
        var pairGroup = new GroupBox { Text = "Station pairing", Dock = DockStyle.Top, Height = 190 };
        var pairPanel = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, Padding = new Padding(8) };
        pairPanel.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        pairPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));

        _autoPairRadio = new RadioButton { Text = "Auto-pair with admin PIN (recommended)", Checked = true, AutoSize = true };
        _manualPairRadio = new RadioButton { Text = "I already paired a station manually", AutoSize = true };
        pairPanel.Controls.Add(_autoPairRadio, 0, 0);
        pairPanel.SetColumnSpan(_autoPairRadio, 2);

        pairPanel.Controls.Add(new Label { Text = "Admin PIN:", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 1);
        _adminPinBox = new TextBox { Dock = DockStyle.Fill, UseSystemPasswordChar = true };
        pairPanel.Controls.Add(_adminPinBox, 1, 1);

        pairPanel.Controls.Add(new Label { Text = "Station name:", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 2);
        _stationNameBox = new TextBox { Dock = DockStyle.Fill, Text = Environment.MachineName };
        pairPanel.Controls.Add(_stationNameBox, 1, 2);

        pairPanel.Controls.Add(_manualPairRadio, 0, 3);
        pairPanel.SetColumnSpan(_manualPairRadio, 2);

        pairPanel.Controls.Add(new Label { Text = "Station ID:", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 4);
        _stationIdBox = new TextBox { Dock = DockStyle.Fill, Enabled = false };
        pairPanel.Controls.Add(_stationIdBox, 1, 4);

        pairPanel.Controls.Add(new Label { Text = "API key:", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 5);
        _apiKeyBox = new TextBox { Dock = DockStyle.Fill, Enabled = false };
        pairPanel.Controls.Add(_apiKeyBox, 1, 5);

        pairGroup.Controls.Add(pairPanel);
        root.Controls.Add(pairGroup, 0, 1);

        _autoPairRadio.CheckedChanged += (_, _) => UpdatePairingFieldsEnabled();
        _manualPairRadio.CheckedChanged += (_, _) => UpdatePairingFieldsEnabled();

        // ---- Printer ----
        var printerGroup = new GroupBox { Text = "Receipt printer", Dock = DockStyle.Top, Height = 100 };
        var printerPanel = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, RowCount = 2, Padding = new Padding(8) };
        printerPanel.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        printerPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        printerPanel.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        printerPanel.Controls.Add(new Label { Text = "Printer:", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 0);
        _printerCombo = new ComboBox { Dock = DockStyle.Fill, DropDownStyle = ComboBoxStyle.DropDownList };
        foreach (string name in PrinterSettings.InstalledPrinters)
        {
            _printerCombo.Items.Add(name);
        }
        if (_printerCombo.Items.Count > 0)
        {
            _printerCombo.SelectedIndex = 0;
        }
        printerPanel.Controls.Add(_printerCombo, 1, 0);
        _testPrintButton = new Button { Text = "Test Print", AutoSize = true };
        _testPrintButton.Click += OnTestPrintClick;
        printerPanel.Controls.Add(_testPrintButton, 2, 0);

        printerPanel.Controls.Add(new Label { Text = "Print mode:", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 1);
        _printModeCombo = new ComboBox { Dock = DockStyle.Fill, DropDownStyle = ComboBoxStyle.DropDownList };
        _printModeCombo.Items.Add("ESC/POS (compact, needs Generic / Text Only printer)");
        _printModeCombo.Items.Add("GDI text (larger font, needs the printer's real driver)");
        _printModeCombo.SelectedIndex = 0;
        printerPanel.Controls.Add(_printModeCombo, 1, 1);
        printerPanel.SetColumnSpan(_printModeCombo, 2);

        printerGroup.Controls.Add(printerPanel);
        root.Controls.Add(printerGroup, 0, 2);

        if (_printerCombo.Items.Count == 0)
        {
            AppendLog("No Windows printers found. Install the receipt printer as a Windows printer queue first (see docs/CLIENT.md), then restart this installer.");
        }

        // ---- Log ----
        var logGroup = new GroupBox { Text = "Log", Dock = DockStyle.Fill };
        _logBox = new TextBox
        {
            Multiline = true,
            ReadOnly = true,
            ScrollBars = ScrollBars.Vertical,
            Dock = DockStyle.Fill,
            Font = new Font(FontFamily.GenericMonospace, 8.5f),
        };
        logGroup.Controls.Add(_logBox);
        root.Controls.Add(logGroup, 0, 5);

        // ---- Progress + status ----
        _progressBar = new ProgressBar { Dock = DockStyle.Top, Style = ProgressBarStyle.Marquee, MarqueeAnimationSpeed = 0, Height = 12 };
        root.Controls.Add(_progressBar, 0, 6);

        var bottomPanel = new TableLayoutPanel { Dock = DockStyle.Top, ColumnCount = 2, Height = 40 };
        bottomPanel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        bottomPanel.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        _statusLabel = new Label { Text = "Ready.", Anchor = AnchorStyles.Left | AnchorStyles.Bottom, AutoSize = true };
        bottomPanel.Controls.Add(_statusLabel, 0, 0);
        _installButton = new Button { Text = "Install", Width = 120, Height = 32, Anchor = AnchorStyles.Right };
        _installButton.Click += OnInstallClick;
        bottomPanel.Controls.Add(_installButton, 1, 0);
        root.Controls.Add(bottomPanel, 0, 7);

        UpdatePairingFieldsEnabled();
    }

    private void UpdatePairingFieldsEnabled()
    {
        _adminPinBox.Enabled = _autoPairRadio.Checked;
        _stationNameBox.Enabled = _autoPairRadio.Checked;
        _stationIdBox.Enabled = _manualPairRadio.Checked;
        _apiKeyBox.Enabled = _manualPairRadio.Checked;
    }

    private void AppendLog(string line)
    {
        if (_logBox.InvokeRequired)
        {
            _logBox.Invoke(new Action(() => AppendLog(line)));
            return;
        }
        _logBox.AppendText(line + Environment.NewLine);
    }

    private string SelectedPrintMode => _printModeCombo.SelectedIndex == 1 ? "gdi_text" : "escpos";

    private void SetBusy(bool busy, string status)
    {
        _progressBar.MarqueeAnimationSpeed = busy ? 30 : 0;
        _installButton.Enabled = !busy;
        _testPrintButton.Enabled = !busy;
        _statusLabel.Text = status;
    }

    private async void OnTestPrintClick(object? sender, EventArgs e)
    {
        if (_printerCombo.SelectedItem is not string printerName)
        {
            MessageBox.Show(this, "Select a printer first.", "ResaPrint Setup", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        SetBusy(true, "Sending test print...");
        try
        {
            ResaPrint.Shared.PrintResult result;
            if (SelectedPrintMode == "gdi_text")
            {
                var text = string.Join('\n', new[]
                {
                    "ResaPrint",
                    "Test print",
                    $"Printer: {printerName}",
                    $"Time: {DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss}",
                });
                var gdiPrinter = new ResaPrint.Shared.GdiTextPrinter(printerName);
                result = await gdiPrinter.PrintAsync(System.Text.Encoding.UTF8.GetBytes(text));
            }
            else
            {
                var receipt = new ReceiptBuilder()
                    .AlignCenter()
                    .BoldLine("ResaPrint")
                    .AlignLeft()
                    .Line("Test print")
                    .Line($"Printer: {printerName}")
                    .Line($"Time: {DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss}")
                    .Divider()
                    .Feed(3)
                    .Cut()
                    .Build();

                var printer = new ResaPrint.Shared.WinspoolPosPrinter(printerName);
                result = await printer.PrintAsync(receipt);
            }

            if (result.Success)
            {
                AppendLog($"Test print sent to '{printerName}'.");
            }
            else
            {
                AppendLog($"Test print FAILED: {result.Error}");
                MessageBox.Show(this, $"Test print failed:\n{result.Error}", "ResaPrint Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }
        catch (Exception ex)
        {
            AppendLog($"Test print FAILED: {ex.Message}");
        }
        finally
        {
            SetBusy(false, "Ready.");
        }
    }

    private async void OnInstallClick(object? sender, EventArgs e)
    {
        var apiBaseUrl = _apiBaseUrlBox.Text.Trim().TrimEnd('/');
        if (string.IsNullOrWhiteSpace(apiBaseUrl) || _printerCombo.SelectedItem is not string printerName)
        {
            MessageBox.Show(this, "Enter the backend URL and select a printer first.", "ResaPrint Setup", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }

        SetBusy(true, "Installing...");
        try
        {
            int stationId;
            string apiKey;

            if (_autoPairRadio.Checked)
            {
                AppendLog($"Logging in to {apiBaseUrl} ...");
                using var http = new HttpClient(new HttpClientHandler
                {
                    CookieContainer = new System.Net.CookieContainer(),
                    UseCookies = true,
                })
                { BaseAddress = new Uri(apiBaseUrl + "/") };

                var loginResp = await http.PostAsync("login", new FormUrlEncodedContent(new Dictionary<string, string>
                {
                    ["pin"] = _adminPinBox.Text,
                }));
                if (!loginResp.IsSuccessStatusCode)
                {
                    throw new InvalidOperationException($"Login failed ({(int)loginResp.StatusCode}) — check the backend URL and admin PIN.");
                }

                var stationName = string.IsNullOrWhiteSpace(_stationNameBox.Text) ? Environment.MachineName : _stationNameBox.Text.Trim();
                AppendLog($"Creating station '{stationName}' ...");
                var createResp = await http.PostAsJsonAsync("api/v1/stations", new { name = stationName, connection_type = "usb_agent" });
                if (!createResp.IsSuccessStatusCode)
                {
                    var body = await createResp.Content.ReadAsStringAsync();
                    throw new InvalidOperationException($"Could not create station '{stationName}' (it may already exist — pick a different name). Server said: {body}");
                }
                using var createdDoc = JsonDocument.Parse(await createResp.Content.ReadAsStringAsync());
                stationId = createdDoc.RootElement.GetProperty("id").GetInt32();

                AppendLog($"Pairing station (id {stationId}) ...");
                var pairResp = await http.PostAsync($"api/v1/stations/{stationId}/pair", content: null);
                pairResp.EnsureSuccessStatusCode();
                using var pairedDoc = JsonDocument.Parse(await pairResp.Content.ReadAsStringAsync());
                apiKey = pairedDoc.RootElement.GetProperty("api_key").GetString()!;

                AppendLog("Station created and paired.");
            }
            else
            {
                if (!int.TryParse(_stationIdBox.Text.Trim(), out stationId) || string.IsNullOrWhiteSpace(_apiKeyBox.Text))
                {
                    throw new InvalidOperationException("Enter a valid Station ID and API key.");
                }
                apiKey = _apiKeyBox.Text.Trim();
            }

            await InstallServiceAndTrayAsync(apiBaseUrl, stationId, apiKey, printerName, SelectedPrintMode);

            AppendLog("");
            AppendLog("Done. Status endpoint: http://127.0.0.1:5990/status");
            MessageBox.Show(this, "ResaPrint client installed successfully.", "ResaPrint Setup", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex)
        {
            AppendLog($"INSTALL FAILED: {ex.Message}");
            MessageBox.Show(this, $"Install failed:\n{ex.Message}\n\nSee the log for details.", "ResaPrint Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            SetBusy(false, "Ready.");
        }
    }

    private async Task InstallServiceAndTrayAsync(string apiBaseUrl, int stationId, string apiKey, string printerName, string printMode)
    {
        var sourceDir = Path.GetDirectoryName(Application.ExecutablePath)!;
        var sourceAgentExe = Path.Combine(sourceDir, "ResaPrint.Agent.exe");
        var sourceTrayExe = Path.Combine(sourceDir, "ResaPrint.Tray.exe");

        if (!File.Exists(sourceAgentExe) || !File.Exists(sourceTrayExe))
        {
            throw new FileNotFoundException(
                "ResaPrint.Agent.exe and ResaPrint.Tray.exe must be in the same folder as ResaPrint.Installer.exe " +
                "(they ship together in the release zip) — run this installer from the extracted folder.");
        }

        var installDirAgent = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "ResaPrint", "Agent");
        var installDirTray = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "ResaPrint", "Tray");
        Directory.CreateDirectory(installDirAgent);
        Directory.CreateDirectory(installDirTray);

        AppendLog("Stopping any existing ResaPrintAgent service...");
        await RunProcessAsync("sc.exe", "stop ResaPrintAgent");

        AppendLog("Closing any running Tray process...");
        foreach (var proc in Process.GetProcessesByName("ResaPrint.Tray"))
        {
            try { proc.Kill(); } catch { /* best effort */ }
        }

        var destAgentExe = Path.Combine(installDirAgent, "ResaPrint.Agent.exe");
        var destTrayExe = Path.Combine(installDirTray, "ResaPrint.Tray.exe");
        AppendLog($"Copying Agent to {destAgentExe} ...");
        File.Copy(sourceAgentExe, destAgentExe, overwrite: true);
        AppendLog($"Copying Tray to {destTrayExe} ...");
        File.Copy(sourceTrayExe, destTrayExe, overwrite: true);

        AppendLog("Writing configuration (pairing) ...");
        var configureArgs = $"--configure --api-base-url \"{apiBaseUrl}\" --station-id {stationId} --api-key \"{apiKey}\" --printer-name \"{printerName}\" --print-mode {printMode}";
        var (configExit, configOutput) = await RunProcessAsync(destAgentExe, configureArgs);
        AppendLog(configOutput.Trim());
        if (configExit != 0)
        {
            throw new InvalidOperationException("Writing the Agent configuration failed — see the log above.");
        }

        var (queryExit, _) = await RunProcessAsync("sc.exe", "query ResaPrintAgent");
        if (queryExit != 0)
        {
            AppendLog("Creating ResaPrintAgent service...");
            // start= delayed-auto + depend= Spooler: at boot, a plain
            // auto-start service can launch before the Print Spooler
            // service is ready, making the first print attempt fail.
            // Delayed-auto plus the explicit dependency makes Windows
            // wait for Spooler first, so printing keeps working after
            // every reboot with nobody logged in (obj= LocalSystem is
            // what allows that — no interactive session required).
            var (createExit, createOutput) = await RunProcessAsync(
                "sc.exe", $"create ResaPrintAgent binPath= \"{destAgentExe}\" start= delayed-auto obj= LocalSystem depend= Spooler");
            AppendLog(createOutput.Trim());
            if (createExit != 0)
            {
                throw new InvalidOperationException("Creating the Windows Service failed — see the log above. Are you running this installer as Administrator?");
            }
            await RunProcessAsync("sc.exe", "description ResaPrintAgent \"ResaPrint receipt printing agent\"");
        }
        else
        {
            AppendLog("Updating existing ResaPrintAgent service startup settings...");
            await RunProcessAsync("sc.exe", "config ResaPrintAgent start= delayed-auto depend= Spooler");
        }

        AppendLog("Configuring service recovery (auto-restart on failure)...");
        await RunProcessAsync("sc.exe", "failure ResaPrintAgent reset= 86400 actions= restart/5000/restart/30000/restart/60000");

        AppendLog("Starting ResaPrintAgent service...");
        await RunProcessAsync("sc.exe", "start ResaPrintAgent");

        AppendLog("Registering Tray auto-start (logon scheduled task)...");
        var (taskExit, taskOutput) = await RunProcessAsync(
            "schtasks.exe",
            $"/create /tn \"ResaPrint Tray\" /tr \"\\\"{destTrayExe}\\\"\" /sc onlogon /rl limited /f");
        AppendLog(taskOutput.Trim());
        if (taskExit != 0)
        {
            AppendLog("Warning: could not register the Tray scheduled task — you can start it manually or run installer\\install-tray-task.ps1.");
        }
    }

    private static async Task<(int ExitCode, string Output)> RunProcessAsync(string fileName, string arguments)
    {
        var psi = new ProcessStartInfo(fileName, arguments)
        {
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };

        using var process = Process.Start(psi) ?? throw new InvalidOperationException($"Failed to start {fileName}");
        var stdoutTask = process.StandardOutput.ReadToEndAsync();
        var stderrTask = process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        var output = (await stdoutTask) + (await stderrTask);
        return (process.ExitCode, output);
    }
}
