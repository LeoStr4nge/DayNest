using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;

namespace DayNest.Glass;

// Keep WinUI top-level: parenting its HWND to Explorer can break XAML/backdrops.
// Show Desktop is handled by a small UI-thread poll, like the original Tk app.
sealed class DesktopWidget : IDisposable
{
    readonly Window window;
    readonly UIElement dragRegion;
    readonly nint hwnd;
    readonly uint processId = (uint)Environment.ProcessId;
    readonly DispatcherTimer timer = new() { Interval = TimeSpan.FromMilliseconds(250) };
    readonly Action<string> reportError;
    readonly bool persistPlacement;
    readonly DispatcherTimer placementTimer = new() { Interval = TimeSpan.FromMilliseconds(500) };
    bool? raised;
    public bool Enabled { get; private set; }
    public bool IsMinimized => IsIconic(hwnd);
    public bool IsVisible => IsWindowVisible(hwnd) && !IsMinimized &&
        DwmGetWindowAttribute(hwnd, 14, out int cloaked, sizeof(int)) == 0 && cloaked == 0;

    public DesktopWidget(Window window, UIElement dragRegion, Action<string> reportError, bool persistPlacement = true)
    {
        this.window = window; this.dragRegion = dragRegion; this.reportError = reportError;
        this.persistPlacement = persistPlacement;
        hwnd = WinRT.Interop.WindowNative.GetWindowHandle(window);
        timer.Tick += (_, _) => Poll();
        placementTimer.Tick += (_, _) => { placementTimer.Stop(); SavePosition(); };
        window.AppWindow.Changed += WindowChanged;
        window.AppWindow.Closing += WindowClosing;
    }

    public void RestorePosition()
    {
        var saved = WidgetPlacement.Load();
        var work = DisplayArea.GetFromPoint(new Windows.Graphics.PointInt32(saved.X, saved.Y), DisplayAreaFallback.Nearest).WorkArea;
        var size = window.AppWindow.Size;
        int width = Math.Min(size.Width, Math.Max(200, work.Width - 16));
        int height = Math.Min(size.Height, Math.Max(300, work.Height - 16));
        window.AppWindow.MoveAndResize(new Windows.Graphics.RectInt32(
            Math.Clamp(saved.X, work.X, Math.Max(work.X, work.X + work.Width - width)),
            Math.Clamp(saved.Y, work.Y, Math.Max(work.Y, work.Y + work.Height - height)), width, height));
    }

    void WindowChanged(AppWindow sender, AppWindowChangedEventArgs args)
    {
        if (!persistPlacement || !args.DidPositionChange || IsMinimized) return;
        placementTimer.Stop(); placementTimer.Start();
    }

    void WindowClosing(AppWindow sender, AppWindowClosingEventArgs args) => SavePosition();

    void SavePosition()
    {
        if (!persistPlacement || IsMinimized) return;
        try
        {
            var point = window.AppWindow.Position;
            WidgetPlacement.Save(new WidgetPosition(point.X, point.Y));
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or COMException) { }
    }

    public void SetEnabled(bool enabled)
    {
        if (Enabled == enabled) return;
        try
        {
            if (window.AppWindow.Presenter is not OverlappedPresenter presenter)
                throw new InvalidOperationException("窗口类型不支持桌面模式");
            if (enabled)
            {
                window.ExtendsContentIntoTitleBar = true;
                window.SetTitleBar(dragRegion);
                presenter.IsMinimizable = false; presenter.IsMaximizable = false;
                presenter.SetBorderAndTitleBar(false, false);
                window.AppWindow.IsShownInSwitchers = false;
                SetToolWindow(true);
                Enabled = true; raised = null;
                timer.Start(); Poll();
            }
            else RestoreNormal();
        }
        catch (Exception e) when (e is Win32Exception or InvalidOperationException or COMException)
        {
            RestoreNormal();
            reportError("桌面模式未能启用，已恢复普通窗口。");
        }
    }

    void SetToolWindow(bool enabled)
    {
        int style = GetWindowLongW(hwnd, -20);
        int updated = enabled ? (style | 0x80) & ~0x40000 : (style & ~0x80) | 0x40000;
        Marshal.SetLastPInvokeError(0);
        if (SetWindowLongW(hwnd, -20, updated) == 0 && Marshal.GetLastPInvokeError() != 0)
            throw new Win32Exception(Marshal.GetLastPInvokeError());
        if (!SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x37)) // FRAMECHANGED, NOACTIVATE, NOMOVE/NOSIZE/NOZORDER
            throw new Win32Exception(Marshal.GetLastPInvokeError());
    }

    void RestoreNormal()
    {
        timer.Stop(); Enabled = false; raised = null;
        SetWindowPos(hwnd, new nint(-2), 0, 0, 0, 0, 0x13); // NOTOPMOST, NOACTIVATE
        window.AppWindow.IsShownInSwitchers = true;
        window.SetTitleBar(null);
        window.ExtendsContentIntoTitleBar = false;
        if (window.AppWindow.Presenter is OverlappedPresenter presenter)
        {
            presenter.SetBorderAndTitleBar(true, true);
            presenter.IsMinimizable = true; presenter.IsMaximizable = true;
        }
        SetToolWindow(false);
    }

    void Poll()
    {
        if (!Enabled) return;
        try
        {
            nint foreground = GetForegroundWindow();
            if (foreground == 0) return; // Shell is transitioning: don't steal focus.
            GetWindowThreadProcessId(foreground, out uint owner);
            var name = new StringBuilder(256);
            GetClassNameW(foreground, name, name.Capacity);
            bool desktop = name.ToString() is "Progman" or "WorkerW" or "SHELLDLL_DefView";
            bool show = desktop || owner == processId;
            if (desktop && IsIconic(hwnd))
            {
                // Restore without taking activation away from the desktop.
                ShowWindow(hwnd, 4); raised = null; // SW_SHOWNOACTIVATE
            }
            if (raised != show)
            {
                nint level = show ? new nint(-1) : new nint(1); // TOPMOST / BOTTOM
                if (!SetWindowPos(hwnd, level, 0, 0, 0, 0, 0x53))
                    throw new Win32Exception(Marshal.GetLastPInvokeError());
                raised = show;
            }
        }
        catch (Exception e) when (e is Win32Exception or COMException)
        {
            RestoreNormal();
            reportError("桌面层级处理失败，已恢复普通窗口。");
        }
    }

    public void Dispose()
    {
        timer.Stop();
        placementTimer.Stop();
        window.AppWindow.Changed -= WindowChanged;
        window.AppWindow.Closing -= WindowClosing;
    }

    [DllImport("user32.dll")] static extern nint GetForegroundWindow();
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassNameW(nint window, StringBuilder name, int capacity);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(nint window, out uint processId);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] static extern bool IsIconic(nint window);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] static extern bool IsWindowVisible(nint window);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] static extern bool ShowWindow(nint window, int command);
    [DllImport("user32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool SetWindowPos(nint window, nint after, int x, int y, int width, int height, uint flags);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowLongW(nint window, int index);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern int SetWindowLongW(nint window, int index, int value);
    [DllImport("dwmapi.dll")] static extern int DwmGetWindowAttribute(nint window, int attribute, out int value, int size);
}
