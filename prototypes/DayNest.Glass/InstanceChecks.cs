using System.Runtime.InteropServices;
using System.Text.Json;

namespace DayNest.Glass;

static class InstanceChecks
{
    public static bool IsWindowCheck => Environment.GetCommandLineArgs().Contains("--instance-window-check");

    public static string? WindowScope(string[] args)
    {
        int i = Array.IndexOf(args, "--instance-window-check");
        if (i < 0) return null;
        if (i + 2 >= args.Length || !Guid.TryParse(args[i + 1], out var scope))
            throw new InvalidOperationException("窗口检查参数无效。");
        return scope.ToString("N");
    }

    static void Report(string path, object value)
    {
        string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { File.WriteAllText(temporary, JsonSerializer.Serialize(value)); File.Move(temporary, path, true); }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    public static void WriteWindowReport(object value)
    {
        var args = Environment.GetCommandLineArgs();
        int i = Array.IndexOf(args, "--instance-window-check");
        Report(args[i + 2], value);
    }

    // Headless, isolated, real-process mutex/pipe diagnostic. Never initializes
    // WinUI, reads settings or accesses Python/calendar data.
    public static int RunProbe(string[] args)
    {
        try
        {
            int i = Array.IndexOf(args, "--instance-probe");
            string scope = Guid.Parse(args[i + 1]).ToString("N"), role = args[i + 2], path = args[i + 3];
            if (role == "notify")
            {
                bool delivered = SingleInstance.NotifyExisting(args.Contains("--normal-window"), scope).GetAwaiter().GetResult();
                Report(path, new { delivered }); return delivered ? 0 : 4;
            }
            bool acquired = SingleInstance.TryRegister(out var instance, scope);
            if (role == "try")
            {
                using (instance) Report(path, new { acquired, pid = Environment.ProcessId });
                return acquired ? 0 : 3;
            }
            if (!acquired || instance == null) { Report(path, new { acquired = false }); return 3; }
            using (instance)
            {
                int count = 0; bool normal = false;
                bool Handle(bool requestedNormal)
                {
                    normal |= requestedNormal; count++;
                    Report(path, new { acquired = true, pid = Environment.ProcessId, count, normal }); return true;
                }
                if (role == "hold") instance.SetActivationHandler(Handle);
                else if (role != "hold-late") throw new InvalidOperationException("Invalid probe role");
                Report(path, new { acquired = true, pid = Environment.ProcessId, count, normal });
                string? line;
                while ((line = Console.ReadLine()) != null && line != "exit")
                    if (line == "attach") instance.SetActivationHandler(Handle);
            }
            return 0;
        }
        catch { return 10; }
    }

    public static void StartupFailure(Exception error) => MessageBoxW(0,
        error is IOException ? error.Message : "无法检查 DayNest 是否已运行，已停止启动。请稍后重试。", "DayNest", 0x10);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int MessageBoxW(nint owner, string text, string caption, uint type);
}
