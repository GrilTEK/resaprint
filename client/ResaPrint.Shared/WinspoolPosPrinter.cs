using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace ResaPrint.Shared;

/// <summary>
/// Sends raw ESC/POS bytes to a Windows-installed printer queue via
/// winspool.drv with datatype "RAW", bypassing GDI rendering entirely
/// so the exact byte stream reaches the printer. This is the
/// well-known P/Invoke pattern from Microsoft KB322090
/// (RawPrinterHelper) — boring and widely referenced, appropriate
/// given this runs unattended on hotel infrastructure. Lives in Shared
/// so both ResaPrint.Agent (the actual print loop) and
/// ResaPrint.Installer (the "Test Print" button during setup) can use
/// the same implementation.
/// </summary>
[SupportedOSPlatform("windows")]
public sealed class WinspoolPosPrinter : IPosPrinter
{
    private readonly string _printerName;

    public WinspoolPosPrinter(string printerName)
    {
        _printerName = printerName;
    }

    public Task<PrintResult> PrintAsync(byte[] payload, CancellationToken cancellationToken = default)
    {
        return Task.Run(() => SendBytesToPrinter(_printerName, payload), cancellationToken);
    }

    private static PrintResult SendBytesToPrinter(string printerName, byte[] bytes)
    {
        if (!NativeMethods.OpenPrinter(printerName, out var printerHandle, IntPtr.Zero))
        {
            return new PrintResult(false, $"OpenPrinter failed for '{printerName}' (Win32 error {Marshal.GetLastWin32Error()})");
        }

        try
        {
            var docInfo = new NativeMethods.DocInfo1
            {
                pDocName = "ResaPrint receipt",
                pOutputFile = null,
                pDataType = "RAW",
            };

            if (!NativeMethods.StartDocPrinter(printerHandle, 1, ref docInfo))
            {
                return new PrintResult(false, $"StartDocPrinter failed (Win32 error {Marshal.GetLastWin32Error()})");
            }

            try
            {
                if (!NativeMethods.StartPagePrinter(printerHandle))
                {
                    return new PrintResult(false, $"StartPagePrinter failed (Win32 error {Marshal.GetLastWin32Error()})");
                }

                try
                {
                    var unmanagedBytes = Marshal.AllocCoTaskMem(bytes.Length);
                    try
                    {
                        Marshal.Copy(bytes, 0, unmanagedBytes, bytes.Length);
                        if (!NativeMethods.WritePrinter(printerHandle, unmanagedBytes, bytes.Length, out var written) || written != bytes.Length)
                        {
                            return new PrintResult(false, $"WritePrinter wrote {written}/{bytes.Length} bytes (Win32 error {Marshal.GetLastWin32Error()})");
                        }
                    }
                    finally
                    {
                        Marshal.FreeCoTaskMem(unmanagedBytes);
                    }
                }
                finally
                {
                    NativeMethods.EndPagePrinter(printerHandle);
                }
            }
            finally
            {
                NativeMethods.EndDocPrinter(printerHandle);
            }

            return new PrintResult(true, null);
        }
        finally
        {
            NativeMethods.ClosePrinter(printerHandle);
        }
    }

    private static class NativeMethods
    {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        public struct DocInfo1
        {
            [MarshalAs(UnmanagedType.LPWStr)] public string pDocName;
            [MarshalAs(UnmanagedType.LPWStr)] public string? pOutputFile;
            [MarshalAs(UnmanagedType.LPWStr)] public string pDataType;
        }

        [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool OpenPrinter(string pPrinterName, out IntPtr phPrinter, IntPtr pDefault);

        [DllImport("winspool.drv", SetLastError = true)]
        public static extern bool ClosePrinter(IntPtr hPrinter);

        [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern bool StartDocPrinter(IntPtr hPrinter, int level, ref DocInfo1 pDocInfo);

        [DllImport("winspool.drv", SetLastError = true)]
        public static extern bool StartPagePrinter(IntPtr hPrinter);

        [DllImport("winspool.drv", SetLastError = true)]
        public static extern bool WritePrinter(IntPtr hPrinter, IntPtr pBytes, int dwCount, out int dwWritten);

        [DllImport("winspool.drv", SetLastError = true)]
        public static extern bool EndPagePrinter(IntPtr hPrinter);

        [DllImport("winspool.drv", SetLastError = true)]
        public static extern bool EndDocPrinter(IntPtr hPrinter);
    }
}
