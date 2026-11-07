using Microsoft.Win32;

namespace DayNest.Glass;

interface IStartupEntry
{
    string? Read();
    void Write(string? command);
}

sealed class RegistryStartupEntry : IStartupEntry
{
    const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    public string? Read() { using var key = Registry.CurrentUser.OpenSubKey(RunKey); return key?.GetValue("DayNest") as string; }
    public void Write(string? command)
    {
        using var key = Registry.CurrentUser.CreateSubKey(RunKey);
        if (command == null) key.DeleteValue("DayNest", false);
        else key.SetValue("DayNest", command, RegistryValueKind.String);
    }
}

static class StartupRegistration
{
    public static string Command(string? exe = null)
    {
        string path = Path.GetFullPath(exe ?? Environment.ProcessPath ?? throw new IOException(I18n.T("无法确定程序路径。")));
        if (path.Contains('"') || path.Contains('\n') || path.Contains('\r') || !path.EndsWith(".exe", StringComparison.OrdinalIgnoreCase))
            throw new IOException("程序路径无效，无法设置自动启动。");
        return '"' + path + "\" --autostart";
    }
    public static bool Enabled(IStartupEntry? entry = null) => !string.IsNullOrWhiteSpace((entry ?? new RegistryStartupEntry()).Read());
    public static void RefreshPath(IStartupEntry? entry = null, string? exe = null)
    {
        entry ??= new RegistryStartupEntry(); string command = Command(exe);
        if (entry.Read() != command) entry.Write(command);
    }
    public static void Save(Appearance settings, string? path = null, IStartupEntry? entry = null, string? exe = null)
    {
        entry ??= new RegistryStartupEntry();
        string? before = entry.Read(); string? next = settings.AutoStart == true ? Command(exe) : null;
        bool changed = before != next;
        if (changed) entry.Write(next);
        try { PreviewSettings.Save(settings, path); }
        catch
        {
            if (changed)
            {
                try { entry.Write(before); }
                catch (Exception error) { throw new IOException(I18n.T("外观保存失败，且自动启动状态未能恢复，请检查设置后重试。"), error); }
            }
            throw;
        }
    }
}
