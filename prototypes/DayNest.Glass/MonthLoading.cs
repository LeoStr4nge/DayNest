using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Microsoft.UI.Xaml;

namespace DayNest.Glass;

static class MonthPolicy
{
    public static readonly TimeSpan RefreshInterval = TimeSpan.FromMinutes(10);
    public static bool Fresh(Result data, DateTimeOffset now) => data.HasCache &&
        now.ToUnixTimeMilliseconds() / 1000d - data.SyncedAt is >= 0 and < 600;
    public static string[] Neighbors(DateTime month) => new[] { month.AddMonths(-1), month.AddMonths(1) }
        .Select(d => d.ToString("yyyy-MM")).Where(k => k != month.ToString("yyyy-MM")).Distinct().ToArray();
}

sealed class CalendarReadException(string message) : Exception(message);

sealed partial class CalendarApp
{
    readonly SemaphoreSlim bridgeGate = new(1, 1);
    CancellationTokenSource? prefetchCancellation;
    readonly DispatcherTimer syncTimer = new() { Interval = MonthPolicy.RefreshInterval };
    readonly DispatcherTimer dayTimer = new() { Interval = TimeSpan.FromMinutes(1) };
    DateTime lastToday = DateTime.Today;
    Task? startupLoad;
    Func<string, bool, CancellationToken, Task<Result>>? monthReaderOverride;
    bool AutomaticNetwork => !stressMode && !Environment.GetCommandLineArgs().Any(a =>
        a is "--desktop-check" or "--offline-preview");

    void StartCalendarLoading()
    {
        syncTimer.Tick += async (_, _) => await AutoSync();
        dayTimer.Tick += async (_, _) =>
        {
            if (closed || writeBusy || settingsOpen || detailsOpen) return;
            if (lastToday != DateTime.Today)
            {
                lastToday = DateTime.Today;
                if (calendar.Visibility == Visibility.Collapsed) { selected = lastToday; await Load(false); return; }
                DrawCalendar();
                await Load(false); return;
            }
            if (months.TryGetValue(selected.ToString("yyyy-MM"), out var data)) RenderPins(data.Pins ?? []);
        };
        if (AutomaticNetwork) syncTimer.Start();
        dayTimer.Start();
        startupLoad = Load(true); // Render disk cache first, then always refresh at startup.
    }

    async Task AutoSync()
    {
        if (!closed && !writeBusy && !settingsOpen && !detailsOpen && requestCancellation == null) await Load(true);
    }

    void CancelMonthRequests()
    {
        generation++;
        requestCancellation?.Cancel();
        prefetchCancellation?.Cancel();
        if (!closed) SetRefreshBusy(false);
        if (!closed) refresh.IsEnabled = !writeBusy;
    }

    void StopCalendarLoading()
    {
        syncTimer.Stop(); dayTimer.Stop(); CancelMonthRequests();
    }

    // One process at a time, including writes. A cancelled read is fully reaped
    // before releasing the gate, so its Windows mutex cannot block the write.
    async Task<JsonElement> BridgeRequest(string command, object? payload = null,
        CancellationToken cancellation = default, bool sync = false, bool syncPins = true)
    {
        if (InstanceChecks.IsWindowCheck)
        {
            if (command != "get-account") throw new InvalidOperationException("Instance checks cannot access the calendar bridge.");
            return JsonSerializer.SerializeToElement(new { username = "", provider = "icloud", discovery_url = "", calendar_home_url = "", trusted_origins = Array.Empty<string>(), hasPassword = false });
        }
        await bridgeGate.WaitAsync(cancellation);
        try
        {
            if (closed) throw new OperationCanceledException();
            var info = BridgeLaunch();
            info.UseShellExecute = false; info.CreateNoWindow = true;
            info.RedirectStandardInput = true; info.RedirectStandardOutput = true; info.RedirectStandardError = true;
            info.StandardInputEncoding = new UTF8Encoding(false);
            info.ArgumentList.Add(command);
            if (sync) info.ArgumentList.Add("--refresh");
            if (!syncPins) info.ArgumentList.Add("--no-pin-sync");
            using var process = Process.Start(info) ?? throw new InvalidOperationException();
            workers.Add(process);
            try
            {
                var stdout = process.StandardOutput.ReadToEndAsync();
                var stderr = process.StandardError.ReadToEndAsync();
                if (payload != null) await process.StandardInput.WriteAsync(JsonSerializer.Serialize(payload));
                process.StandardInput.Close();
                using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
                timeout.CancelAfter(TimeSpan.FromSeconds(command is "save-account" or "get-account" or "add-pin" or "remove-pin" or "prune-expired-pins" ? 20 : 120));
                try { await process.WaitForExitAsync(timeout.Token); }
                catch
                {
                    if (!process.HasExited) process.Kill(true);
                    await process.WaitForExitAsync();
                    await Task.WhenAll(stdout, stderr);
                    throw;
                }
                string output = await stdout; await stderr;
                if (process.ExitCode != 0) throw new InvalidOperationException();
                using var document = JsonDocument.Parse(output);
                return document.RootElement.Clone();
            }
            finally { workers.Remove(process); }
        }
        finally { bridgeGate.Release(); }
    }

    static ProcessStartInfo BridgeLaunch()
    {
        string bundled = Path.Combine(AppContext.BaseDirectory, "backend", "DayNest.Bridge.exe");
        if (File.Exists(bundled)) return new ProcessStartInfo(bundled) { WorkingDirectory = AppContext.BaseDirectory };
        string repo = Repo();
        string python = Path.Combine(repo, ".venv", "Scripts", "python.exe");
        if (!File.Exists(python)) python = "python";
        var info = new ProcessStartInfo(python) { WorkingDirectory = repo };
        info.ArgumentList.Add("-B");
        info.ArgumentList.Add(Path.Combine(repo, "prototypes", "DayNest.Glass", "calendar_bridge.py"));
        return info;
    }

    async Task<Result> ReadMonth(string key, bool sync, CancellationToken cancellation, bool syncPins = true)
    {
        if (monthReaderOverride != null) return await monthReaderOverride(key, sync, cancellation);
        var json = await BridgeRequest(key, cancellation: cancellation, sync: sync, syncPins: syncPins);
        var data = json.Deserialize<Result>(new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
            ?? throw new InvalidOperationException();
        data = data with { Status = data.Status is null ? null : I18n.T(data.Status),
            Error = data.Error is null ? null : I18n.T(data.Error),
            Warning = data.Warning is null ? null : I18n.T(data.Warning) };
        if (data.Error != null) throw new CalendarReadException(data.Error);
        return data;
    }

    async Task Load(bool sync)
    {
        if (writeBusy || closed) return;
        CancelMonthRequests();
        int token = generation;
        string key = selected.ToString("yyyy-MM");
        using var request = new CancellationTokenSource(); requestCancellation = request;
        bool prefetch = false;
        SetRefreshBusy(true);
        refresh.IsEnabled = false;
        if (months.TryGetValue(key, out var data)) Render(data);
        else { agenda.Children.Clear(); status.Text = I18n.T("正在读取本地缓存…"); }
        try
        {
            if (data == null)
            {
                data = await ReadMonth(key, false, request.Token);
                if (closed || token != generation) return;
                StoreMonth(key, data); Render(data);
            }
            if (AutomaticNetwork && data.Configured && (sync || !MonthPolicy.Fresh(data, DateTimeOffset.UtcNow)))
            {
                status.Text = data.HasCache ? I18n.T("显示缓存 · 正在同步…") : I18n.T("正在同步本月日程…");
                var latest = await ReadMonth(key, true, request.Token);
                if (closed || token != generation) return;
                data = latest; StoreMonth(key, latest); Render(latest);
            }
            if (recentOverview)
            {
                foreach (string other in RecentMonths(selected).Where(k => k != key))
                {
                    if (!months.TryGetValue(other, out var next))
                    {
                        next = await ReadMonth(other, false, request.Token);
                        if (closed || token != generation) return;
                        StoreMonth(other, next); Render(months[key]);
                    }
                    if (AutomaticNetwork && next.Configured && (sync || !MonthPolicy.Fresh(next, DateTimeOffset.UtcNow)))
                    {
                        next = await ReadMonth(other, true, request.Token, false);
                        if (closed || token != generation) return;
                        StoreMonth(other, next); Render(months[key]);
                    }
                }
            }
            prefetch = calendar.Visibility == Visibility.Visible && data.Configured && AutomaticNetwork;
            TrimMonthMemory();
        }
        catch (OperationCanceledException) when (request.IsCancellationRequested) { }
        catch (Exception error)
        {
            if (!closed && token == generation)
                status.Text = (data?.HasCache == true ? I18n.T("同步失败，保留缓存 · ") : I18n.T("未能同步 · ")) +
                    (error is CalendarReadException ? error.Message : I18n.T("请检查网络及日历账户后重试。"));
        }
        finally
        {
            if (!closed && token == generation)
            {
                try { await RemoveExpiredPins(request.Token); }
                catch (OperationCanceledException) when (request.IsCancellationRequested) { }
                catch { status.Text += I18n.T(" · 过期倒计时暂时无法移除，请稍后刷新。"); }
            }
            if (ReferenceEquals(requestCancellation, request)) requestCancellation = null;
            if (!closed && token == generation)
            {
                SetRefreshBusy(false);
                refresh.IsEnabled = true;
                if (prefetch && calendar.Visibility == Visibility.Visible && !settingsOpen && !detailsOpen) _ = PrefetchMonths(selected, token);
            }
        }
    }

    async Task PrefetchMonths(DateTime center, int token)
    {
        using var request = new CancellationTokenSource(); prefetchCancellation = request;
        try
        {
            foreach (string key in MonthPolicy.Neighbors(center))
            {
                request.Token.ThrowIfCancellationRequested();
                if (closed || token != generation || calendar.Visibility != Visibility.Visible || writeBusy || settingsOpen || detailsOpen) return;
                try
                {
                    if (!months.TryGetValue(key, out var data)) data = await ReadMonth(key, false, request.Token);
                    if (data.Configured && !MonthPolicy.Fresh(data, DateTimeOffset.UtcNow)) data = await ReadMonth(key, true, request.Token, false);
                    if (closed || token != generation) return;
                    StoreMonth(key, data); DrawCalendar(); RenderPins(data.Pins ?? []);
                }
                catch (OperationCanceledException) when (request.IsCancellationRequested) { return; }
                catch { /* A failed neighbor never replaces the visible month's status or cache. */ }
            }
            TrimMonthMemory();
        }
        finally { if (ReferenceEquals(prefetchCancellation, request)) prefetchCancellation = null; }
    }

    void TrimMonthMemory()
    {
        var today = new DateTime(DateTime.Today.Year, DateTime.Today.Month, 1);
        var keep = Enumerable.Range(-6, 13).Select(i => today.AddMonths(i).ToString("yyyy-MM"))
            .Concat(MonthPolicy.Neighbors(selected)).Append(selected.ToString("yyyy-MM")).ToHashSet();
        foreach (string key in months.Keys.Where(k => !keep.Contains(k)).ToArray())
        {
            months.Remove(key); dayIndexes.Remove(key);
        }
    }
}
