using System.Reflection;
using System.Runtime.InteropServices;

namespace DayNest.Glass;

sealed partial class CalendarApp
{
    // Explicit developer check: uses the Shell Show Desktop API, then restores
    // the previous desktop state. It never synthesizes Windows-key shortcuts.
    async void RunDesktopCheck()
    {
        object? shell = null;
        int toggles = 0;
        string result;
        try
        {
            await Task.Delay(1000);
            if (desktopWidget?.Enabled != true) throw new InvalidOperationException("Desktop mode is not enabled");
            Type shellType = Type.GetTypeFromProgID("Shell.Application") ?? throw new InvalidOperationException("Explorer unavailable");
            shell = Activator.CreateInstance(shellType) ?? throw new InvalidOperationException("Explorer unavailable");
            for (int i = 0; i < 3; i++)
            {
                shellType.InvokeMember("ToggleDesktop", BindingFlags.InvokeMethod, null, shell, null); toggles++;
                await Task.Delay(1500);
                if (!desktopWidget.IsVisible) throw new InvalidOperationException($"Window hidden/minimized/cloaked after Show Desktop cycle {i + 1}");
                shellType.InvokeMember("ToggleDesktop", BindingFlags.InvokeMethod, null, shell, null); toggles++;
                await Task.Delay(700);
            }
            desktopWidget.SetEnabled(false);
            if (!window.AppWindow.IsShownInSwitchers || !desktopWidget.IsVisible)
                throw new InvalidOperationException("Normal-window recovery failed");
            desktopWidget.SetEnabled(true);
            if (!desktopWidget.Enabled || window.AppWindow.IsShownInSwitchers)
                throw new InvalidOperationException("Desktop-mode re-enable failed");
            result = "PASS: three Shell Show Desktop/restore cycles, widget visible/not minimized/not cloaked; normal-window recovery and re-enable passed";
        }
        catch (Exception error) { result = "FAIL: " + error; }
        finally
        {
            if (shell != null)
            {
                if (toggles % 2 != 0)
                    shell.GetType().InvokeMember("ToggleDesktop", BindingFlags.InvokeMethod, null, shell, null);
                Marshal.FinalReleaseComObject(shell);
            }
        }
        File.WriteAllText(Path.Combine(AppContext.BaseDirectory, "desktop-check.txt"), result);
        window.Close();
    }
}
