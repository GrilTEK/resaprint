using System.Runtime.Versioning;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using ResaPrint.Shared.Models;

namespace ResaPrint.Shared.Config;

/// <summary>
/// Reads/writes the Agent's StationConfig, encrypted at rest with
/// DPAPI at LocalMachine scope (not CurrentUser) so the LocalSystem
/// service account can decrypt it regardless of which interactive
/// user is logged on. Default path: %ProgramData%\ResaPrint\agent-config.dat.
/// </summary>
[SupportedOSPlatform("windows")]
public static class DpapiConfigStore
{
    public static string DefaultPath =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "ResaPrint", "agent-config.dat");

    public static void Save(StationConfig config, string? path = null)
    {
        path ??= DefaultPath;
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);

        var json = JsonSerializer.Serialize(config);
        var plainBytes = Encoding.UTF8.GetBytes(json);
        var encrypted = ProtectedData.Protect(plainBytes, optionalEntropy: null, DataProtectionScope.LocalMachine);
        File.WriteAllBytes(path, encrypted);
    }

    public static StationConfig? TryLoad(string? path = null)
    {
        path ??= DefaultPath;
        if (!File.Exists(path))
        {
            return null;
        }

        try
        {
            var encrypted = File.ReadAllBytes(path);
            var plainBytes = ProtectedData.Unprotect(encrypted, optionalEntropy: null, DataProtectionScope.LocalMachine);
            var json = Encoding.UTF8.GetString(plainBytes);
            return JsonSerializer.Deserialize<StationConfig>(json);
        }
        catch (CryptographicException)
        {
            // Config exists but can't be decrypted (e.g. moved to a
            // different machine, or a different service account) —
            // treated as "not configured" rather than crashing.
            return null;
        }
    }
}
