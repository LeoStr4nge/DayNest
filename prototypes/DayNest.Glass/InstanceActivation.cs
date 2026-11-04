using System.Runtime.InteropServices;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Windowing;

namespace DayNest.Glass;

sealed partial class CalendarApp
{
    readonly DispatcherQueue uiDispatcher = DispatcherQueue.GetForCurrentThread();
    bool pendingActivation, pendingNormalWindow;
    bool windowReady;
    Action? normalWindowRequested;
    int activationCount;
    Microsoft.UI.Xaml.Controls.ContentDialog? instanceCheckDialog;

    internal bool RequestActivation(bool normalWindow)
    {
        if (Volatile.Read(ref closed)) return false;
        return uiDispatcher.TryEnqueue(() =>
        {
            if (closed) return;
            if (!windowReady) { pendingActivation = true; pendingNormalWindow |= normalWindow; return; }
            ActivateExistingWindow(normalWindow);
        });
    }

    void CompleteInstanceStartup()
    {
        windowReady = true;
        if (pendingActivation) ActivateExistingWindow(pendingNormalWindow);
        pendingActivation = pendingNormalWindow = false;
        if (InstanceChecks.IsWindowCheck)
        {
            if (Environment.GetCommandLineArgs().Contains("--instance-open-settings-check")) _ = OpenWindowCheckSettings();
            if (Environment.GetCommandLineArgs().Contains("--instance-start-minimized") && window.AppWindow.Presenter is OverlappedPresenter presenter) presenter.Minimize();
            _ = CloseWindowCheckLater();
        }
        WriteInstanceWindowReport();
    }

    void ActivateExistingWindow(bool normalWindow)
    {
        if (normalWindow)
        {
            desktopMode = false;
            normalWindowRequested?.Invoke();
            ApplyAppearance();
        }
        if (window.AppWindow.Presenter is OverlappedPresenter presenter && presenter.State == OverlappedPresenterState.Minimized)
            presenter.Restore();
        window.Activate();
        SetForegroundWindow(WinRT.Interop.WindowNative.GetWindowHandle(window));
        activationCount++;
        WriteInstanceWindowReport();
        if (InstanceChecks.IsWindowCheck && normalWindow && Environment.GetCommandLineArgs().Contains("--instance-open-settings-check"))
            uiDispatcher.TryEnqueue(() => instanceCheckDialog?.Hide());
    }

    async Task CloseWindowCheckLater()
    {
        await Task.Delay(TimeSpan.FromSeconds(8));
        if (!closed) window.Close();
    }

    async Task OpenWindowCheckSettings()
    {
        // The normal entry opens settings after a click. Wait for initial
        // layout here rather than showing a popup inside OnLaunched itself.
        await Task.Delay(300);
        if (!closed) { _ = ShowSettings(); WriteInstanceWindowReport(); }
    }

    void WriteInstanceWindowReport()
    {
        if (!InstanceChecks.IsWindowCheck) return;
        InstanceChecks.WriteWindowReport(new
        {
            pid = Environment.ProcessId, activationCount, desktop = desktopWidget?.Enabled ?? desktopMode,
            shownInSwitchers = window.AppWindow.IsShownInSwitchers,
            minimized = desktopWidget?.IsMinimized, visible = desktopWidget?.IsVisible,
            settingsOpen, detailsOpen, writeBusy
        });
    }

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)] static extern bool SetForegroundWindow(nint hwnd);
}
