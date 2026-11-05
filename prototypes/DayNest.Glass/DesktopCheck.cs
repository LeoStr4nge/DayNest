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
            if (desktopWidget.TopFrameInset != 0) throw new InvalidOperationException($"Native top frame remains: {desktopWidget.TopFrameInset}px");
            var caption = Microsoft.UI.Input.InputNonClientPointerSource.GetForWindowId(window.AppWindow.Id)
                .GetRegionRects(Microsoft.UI.Input.NonClientRegionKind.Caption);
            if (caption.Length == 0) throw new InvalidOperationException("Missing native drag region");
            bool CaptionContains(Microsoft.UI.Xaml.FrameworkElement element)
            {
                var point = element.TransformToVisual(rim).TransformPoint(new Windows.Foundation.Point(element.ActualWidth / 2, element.ActualHeight / 2));
                double scale = element.XamlRoot.RasterizationScale;
                return caption.Any(r => point.X * scale >= r.X && point.X * scale < r.X + r.Width && point.Y * scale >= r.Y && point.Y * scale < r.Y + r.Height);
            }
            if (!CaptionContains(dragLines[1]) || CaptionContains(exitWidget))
                throw new InvalidOperationException("Grip/close hit areas overlap or the grip is not draggable");
            if (desktopWidget.HitTest(1, window.AppWindow.Size.Height / 2) != 10)
                throw new InvalidOperationException("Left resize border no longer responds");
            if (desktopWidget.HitTest(window.AppWindow.Size.Width / 2, 1) != 12)
                throw new InvalidOperationException("Top resize border no longer responds");
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
            if (desktopWidget.TopFrameInset != 0) throw new InvalidOperationException("Native top frame returned after mode switch");
            result = "PASS: zero native top inset, draggable grip with separate close hit area, top/left resize hit tests, three Show Desktop cycles, normal-window recovery and frameless re-enable";
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
