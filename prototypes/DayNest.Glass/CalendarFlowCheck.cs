using System.Globalization;
using Microsoft.UI.Xaml;

namespace DayNest.Glass;

sealed partial class CalendarApp
{
    // Exercise the actual async loader/UI and timer callback against an
    // in-memory transport. No Python process, user cache or server is touched.
    readonly Dictionary<string, Result> checkDisk = new();
    readonly List<(string Key, bool Sync)> checkCalls = new();
    string? checkFailure, checkHold;
    TaskCompletionSource? checkStarted;
    bool checkCacheRendered, checkCancelled;

    void PrepareCalendarFlowCheck()
    {
        selected = DateTime.Today;
        string key = selected.ToString("yyyy-MM");
        checkDisk[key] = CheckMonth(key, "Cached item") with { SyncedAt = 1 };
        monthReaderOverride = async (month, sync, cancellation) =>
        {
            checkCalls.Add((month, sync));
            if (!sync)
            {
                await Task.Delay(10, cancellation);
                return checkDisk.GetValueOrDefault(month) ?? new Result([], "missing", null, [], false, true);
            }
            if (month == key && !checkCacheRendered)
                checkCacheRendered = months.TryGetValue(key, out var shown) && shown.Events?[0].Title == "Cached item" && status.Text.Contains("缓存");
            if (month == checkHold)
            {
                checkStarted?.TrySetResult();
                try { await Task.Delay(Timeout.Infinite, cancellation); }
                catch (OperationCanceledException) { checkCancelled = true; throw; }
            }
            await Task.Delay(30, cancellation);
            if (month == checkFailure) throw new CalendarReadException("simulated offline");
            var result = CheckMonth(month, "Server item"); checkDisk[month] = result;
            return result;
        };
    }

    static Result CheckMonth(string month, string title)
    {
        var start = new DateTimeOffset(DateTime.ParseExact(month + "-04", "yyyy-MM-dd", CultureInfo.InvariantCulture).AddHours(9));
        return new Result([new Entry(start, start.AddHours(1), title, "Test", false, "")], "synced", null, [], true, true,
            DateTimeOffset.UtcNow.ToUnixTimeSeconds());
    }

    async void RunCalendarFlowCheck()
    {
        static void Check(bool success, string reason) { if (!success) throw new InvalidOperationException(reason); }
        string report;
        try
        {
            await (startupLoad ?? throw new InvalidOperationException("Startup did not load"));
            Check(checkCacheRendered, "Startup must render disk cache before network completes");
            string current = selected.ToString("yyyy-MM");
            Check(calendar.Visibility == Visibility.Collapsed && prefetchCancellation == null && checkCalls.All(c => c.Key == current), "Collapsed startup must load only the current month without neighbor requests");
            var firstIndex = MonthIndex(current);
            var cached = months[current]; StoreMonth(current, cached with { Pins = [] });
            Check(ReferenceEquals(firstIndex, MonthIndex(current)), "Pin/status-only updates must reuse the event index");
            checkCalls.Clear(); await Load(false);
            Check(!checkCalls.Any(c => c.Sync), "Fresh cached navigation must not issue another network request");
            Check(ReferenceEquals(firstIndex, MonthIndex(current)), "Rendering cached data must reuse the event index");
            await Load(true);
            Check(checkCalls.Any(c => c.Key == current && c.Sync), "Manual refresh must force network even with fresh cache");
            Check(!ReferenceEquals(firstIndex, MonthIndex(current)), "Updated event data must replace the index");
            checkCalls.Clear(); await AutoSync();
            Check(checkCalls.Count == 1 && checkCalls[0] == (current, true) && prefetchCancellation == null, "Collapsed timer refresh must not prefetch neighboring months");

            selected = new DateTime(2026, 12, 29); recentOverview = true;
            checkCalls.Clear(); await Load(true);
            var recentKeys = RecentMonths(selected);
            Check(recentKeys.All(k => months.TryGetValue(k, out var d) && d.HasCache) && checkCalls.All(c => recentKeys.Contains(c.Key)) && prefetchCancellation == null, "Recent view must load only its required months across a year boundary");
            var recentDays = RecentIndex();
            Render(months[selected.ToString("yyyy-MM")]);
            Check(ReferenceEquals(recentDays, RecentIndex()), "Repeated recent rendering must reuse its date index");
            var recentMonth = selected.ToString("yyyy-MM");
            StoreMonth(recentMonth, CheckMonth(recentMonth, "Replaced item"));
            Check(!ReferenceEquals(recentDays, RecentIndex()), "Recent date index must invalidate when a source month changes");

            selected = DateTime.Today.AddMonths(12); current = selected.ToString("yyyy-MM");
            recentOverview = false; calendar.Visibility = Visibility.Visible;
            checkCalls.Clear(); await Load(true);
            for (int i = 0; i < 100 && prefetchCancellation != null; i++) await Task.Delay(20);
            Check(prefetchCancellation == null && MonthPolicy.Neighbors(selected).All(k => months.TryGetValue(k, out var d) && d.HasCache), "Opening the calendar must prefetch adjacent months");
            Check(checkCalls.All(c => c.Key == current || MonthPolicy.Neighbors(selected).Contains(c.Key)), "Expanded calendar must not load unrelated months");
            // Collapse while the first neighboring request is in flight. Its
            // cancellation must prevent the other neighbor from being requested.
            selected = DateTime.Today.AddMonths(18);
            checkHold = MonthPolicy.Neighbors(selected)[0];
            checkStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            checkCalls.Clear(); await Load(true);
            await checkStarted.Task.WaitAsync(TimeSpan.FromSeconds(3));
            calendar.Visibility = Visibility.Collapsed; selected = DateTime.Today;
            await Load(false);
            for (int i = 0; i < 100 && prefetchCancellation != null; i++) await Task.Delay(20);
            Check(checkCancelled && prefetchCancellation == null && !checkCalls.Any(c => c.Key == MonthPolicy.Neighbors(DateTime.Today.AddMonths(18))[1]), "Collapsing calendar must cancel prefetch and skip the remaining neighbor");
            checkHold = null; checkCancelled = false; current = selected.ToString("yyyy-MM");
            var previous = months[current]; checkFailure = current; await Load(true);
            Check(ReferenceEquals(previous, months[current]) && status.Text.Contains("保留缓存"), "Offline refresh must preserve visible complete data");
            checkFailure = null;
            var slowDate = DateTime.Today.AddMonths(5); checkHold = slowDate.ToString("yyyy-MM");
            checkStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            selected = slowDate; var slow = Load(true);
            await checkStarted.Task.WaitAsync(TimeSpan.FromSeconds(3));
            selected = DateTime.Today.AddMonths(6); string newest = selected.ToString("yyyy-MM");
            await Load(true); await slow;
            Check(checkCancelled && months[newest].HasCache && selected.ToString("yyyy-MM") == newest, "Fast navigation must cancel obsolete requests and retain the newest view");
            CancelMonthRequests(); checkHold = null;
            checkCalls.Clear(); writeBusy = true;
            try { await AutoSync(); Check(checkCalls.Count == 0, "Automatic sync must not interrupt a write"); }
            finally { writeBusy = false; }
            await AutoSync();
            Check(checkCalls.Any(c => c.Key == newest && c.Sync), "Timer callback must force a refresh of the visible month");
            var beforeClear = RecentIndex(); ClearMonths();
            Check(dayIndexes.Count == 0 && !ReferenceEquals(beforeClear, RecentIndex()) && RecentIndex().On(selected).Count == 0, "Clearing account/event data must discard every date index");
            report = "PASS: cache-first startup, view-scoped timer/recent/month requests, expanded-only neighbor prefetch, collapse cancellation, date-index reuse/invalidation/clear, offline preservation, rapid navigation and write exclusion";
        }
        catch (Exception error) { report = "FAIL: " + error; }
        File.WriteAllText(Path.Combine(AppContext.BaseDirectory, "calendar-flow-check.txt"), report);
        window.Close();
    }
}
