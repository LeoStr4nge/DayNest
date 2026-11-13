namespace DayNest.Glass;

static class PrototypeChecks
{
    public static void Run()
    {
        static void Check(bool condition, string message)
        {
            if (!condition) throw new InvalidOperationException(message);
        }
        var directory = Path.Combine(Path.GetTempPath(), "daynest-preview-check-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        string path = Path.Combine(directory, "settings.json");
        try
        {
            Check(PreviewSettings.Load(path) == new Appearance(), "Missing settings must use defaults");
            File.WriteAllText(path, "{broken");
            Check(PreviewSettings.Load(path) == new Appearance(), "Corrupt settings must recover");
            File.WriteAllText(path, "{\"Dark\":false,\"Density\":0.38,\"Glass\":true}");
            Check(PreviewSettings.Load(path) == new Appearance(false, .38, true, true), "Existing appearance settings must default to desktop mode");
            Check(PreviewSettings.Load(path).RemoveExpiredPins, "Existing settings must default to removing expired countdowns");
            Check(PreviewSettings.Load(path).Language == "zh-CN", "Existing settings must default to Simplified Chinese");
            PreviewSettings.Save(new Appearance(Language: "en-US"), path);
            Check(PreviewSettings.Load(path).Language == "en-US", "English language choice must survive restart");
            I18n.Language = "en-US";
            Check(I18n.T("设置") == "Settings" && I18n.T("还有 3 天") == "3 days left" &&
                I18n.T("认证失败：请检查日历账户和密码，部分服务需要使用应用专用密码").StartsWith("Authentication failed"),
                "English interface and bridge messages must translate");
            Check(new DateTime(2026, 11, 7).ToString(I18n.T("yyyy 年 M 月日程"), I18n.Culture) == "November 2026 events",
                "English month heading must format as a readable date");
            Check(I18n.T("确定删除“Example”？\n\n此操作会从日历服务中删除日程，其他设备也会同步删除。").Contains("other devices"),
                "English delete confirmation must translate its dynamic title");
            Check(!I18n.T("部分固定项暂未能更新，已保留上次数据。 日程已同步，但缓存保存失败；重启后需要重新同步。").Any(c => c is >= '\u4e00' and <= '\u9fff'),
                "Combined bridge warnings must translate completely");
            Check(I18n.TranslationKeysMatch, "English and Japanese translation keys must stay in sync");
            PreviewSettings.Save(new Appearance(Language: "ja-JP"), path);
            Check(PreviewSettings.Load(path).Language == "ja-JP", "Japanese language choice must survive restart");
            I18n.Language = "ja-JP";
            Check(I18n.T("今日") == "今日" && I18n.T("近期") == "今後" && I18n.T("还有 3 天") == "あと3日" &&
                I18n.T("认证失败：请检查日历账户和密码，部分服务需要使用应用专用密码").StartsWith("認証できませんでした"),
                "Japanese calendar terms and bridge messages must translate");
            Check(new DateTime(2026, 11, 7).ToString(I18n.T("yyyy 年 M 月日程"), I18n.Culture) == "2026年11月の予定",
                "Japanese month heading must use local date order");
            Check(I18n.T("已同步 · 12:34") == "同期済み · 12:34" &&
                I18n.T("确定删除“Example”？\n\n此操作会从日历服务中删除日程，其他设备也会同步删除。").Contains("ほかのデバイス"),
                "Dynamic Japanese status and confirmation messages must translate");
            Check(I18n.Culture.DateTimeFormat.FirstDayOfWeek == DayOfWeek.Sunday,
                "Japanese calendar should begin on Sunday");
            I18n.Language = "zh-CN";
            PreviewSettings.Save(new Appearance(false, .67, false, false), path);
            Check(PreviewSettings.Load(path) == new Appearance(false, .67, false, false), "Theme, glass, desktop mode and density must survive restart");
            PreviewSettings.Save(new Appearance(RemoveExpiredPins: false), path);
            Check(!PreviewSettings.Load(path).RemoveExpiredPins, "Keeping expired countdowns must survive restart");
            var pinDay = new DateTime(2026, 11, 5);
            var pinDates = new[] { -1, 0, 1 }.Select(offset => new Pin(offset.ToString(), new DateTimeOffset(pinDay.AddDays(offset), TimeZoneInfo.Local.GetUtcOffset(pinDay)))).ToArray();
            Check(CalendarApp.VisiblePins(pinDates, true, pinDay).Select(pin => pin.Title).SequenceEqual(new[] { "0", "1" }), "Only days before today may disappear");
            Check(CalendarApp.VisiblePins(pinDates, false, pinDay).Length == 3, "Disabled cleanup must keep past countdowns visible");
            File.WriteAllText(path, "{\"Dark\":false,\"Density\":20}");
            Check(PreviewSettings.Load(path) == new Appearance(), "Invalid density must recover");
            Check(Directory.GetFiles(directory, "*.tmp").Length == 0, "Atomic save must clean temporary files");
            foreach (var preset in Themes.All)
            {
                foreach (string? custom in new string?[] { null, "#000000", "#ffffff", "#777777", "#00ff00", "#ff00ff" })
                {
                    var palette = Themes.Get(preset.Id, custom);
                    Check(Themes.Contrast(palette.Accent, palette.OnAccent) >= 4.5, "Selected text must remain readable with every accent");
                    Check(Themes.Contrast(palette.AccentInk, palette.Background) >= 4.5, "Accent text must remain readable on the theme background");
                }
            }
            Check(Themes.Id(null, false) == "paper" && Themes.Id("bad", true) == "midnight", "Legacy light/dark and corrupt theme names must recover");
            Check(!Themes.ValidColor("#00zz00") && !Themes.ValidColor("red") && !Themes.ValidColor("#fffff "), "Invalid colors must not reach the UI");
            var startup = new CheckStartupEntry { Value = "old startup command" };
            string executable = Path.Combine(directory, "folder with spaces", "DayNest.Glass.exe");
            var personalized = new Appearance(false, .53, true, false, "sand", "#123456", true);
            StartupRegistration.Save(personalized, path, startup, executable);
            Check(startup.Value == $"\"{executable}\" --autostart", "Startup path must be quoted and point to the WinUI executable");
            Check(PreviewSettings.Load(path) == personalized, "Theme, custom color and startup preference must persist together");
            int changes = startup.Changes;
            StartupRegistration.RefreshPath(startup, executable);
            Check(startup.Changes == changes, "Unchanged startup command must not be rewritten");
            StartupRegistration.Save(personalized with { AutoStart = false }, path, startup, executable);
            Check(startup.Value == null, "Disabling startup must remove only the app's entry");
            string before = File.ReadAllText(path);
            startup.Fail = true;
            try { StartupRegistration.Save(personalized, path, startup, executable); throw new InvalidOperationException("Registry failure accepted"); }
            catch (UnauthorizedAccessException) { }
            Check(File.ReadAllText(path) == before, "Registry failure must preserve saved appearance");
            startup.Fail = false; startup.Value = "previous command";
            try { StartupRegistration.Save(personalized, directory, startup, executable); throw new InvalidOperationException("Disk failure accepted"); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
            Check(startup.Value == "previous command", "Disk failure must roll back the startup entry");
            Check(CalendarApp.RecentMonths(new DateTime(2026, 12, 29)).SequenceEqual(new[] { "2026-12", "2027-01" }), "Recent view must span a year boundary");
            string positionPath = Path.Combine(directory, "position.json");
            Check(WidgetPlacement.Load(positionPath) == new WidgetPosition(), "Missing position must recover");
            WidgetPlacement.Save(new WidgetPosition(-1200, 90), positionPath);
            Check(WidgetPlacement.Load(positionPath) == new WidgetPosition(-1200, 90), "Negative monitor coordinates must persist");
            File.WriteAllText(positionPath, "{bad");
            Check(WidgetPlacement.Load(positionPath) == new WidgetPosition(), "Invalid position must recover");
            var now = DateTimeOffset.UtcNow;
            var loaded = new Result([], "cached", null, [], true, true, now.ToUnixTimeSeconds());
            Check(MonthPolicy.Fresh(loaded, now.AddMinutes(9)), "Recent complete month should not re-fetch on every click");
            Check(!MonthPolicy.Fresh(loaded, now.AddMinutes(10)), "Month must refresh after ten minutes");
            Check(!MonthPolicy.Fresh(loaded with { HasCache = false }, now), "Partial recent-event cache must trigger full-month load");
            Check(!MonthPolicy.Fresh(loaded, now.AddMinutes(-1)), "Clock rollback must not freeze cached data");
            Check(MonthPolicy.Neighbors(new DateTime(2026, 12, 15)).Contains("2027-01"), "Prefetch must cross year boundaries");

            var day = new DateTime(2026, 11, 4);
            DateTimeOffset At(DateTime time) => new(time, TimeZoneInfo.Local.GetUtcOffset(time));
            var overnight = new Entry(At(day.AddDays(-1).AddHours(23)), At(day.AddHours(1)), "test", "test", false, "");
            Check(CalendarApp.OccursOn(overnight, day), "Overnight event must mark both days");
            var midnight = overnight with { End = At(day) };
            Check(!CalendarApp.OccursOn(midnight, day), "Exclusive midnight end must not mark the next day");
            var instant = overnight with { Start = At(day.AddHours(9)), End = At(day.AddHours(9)) };
            Check(CalendarApp.OccursOn(instant, day), "Zero-duration event must remain visible");
            var monthStart = new DateTime(2026, 11, 1);
            var spanning = overnight with { Start = At(monthStart.AddHours(-1)), End = At(monthStart.AddHours(1)) };
            Check(CalendarApp.OccursInMonth(spanning, monthStart), "Monthly view must include events crossing into the month");
            Check(!CalendarApp.OccursInMonth(spanning with { End = At(monthStart) }, monthStart), "Monthly view must exclude events ending at its start");
            var deduped = EventDayIndex.Build([spanning, spanning], monthStart, monthStart.AddDays(8), true);
            Check(deduped.On(monthStart).Count == 1, "Cross-month recent view must deduplicate spanning events");
            var longEvent = overnight with { Start = At(day.AddYears(-5)), End = At(day.AddYears(5)), Key = "long" };
            var allDay = overnight with { Start = At(day), End = At(day.AddDays(2)), AllDay = true, Key = "all-day" };
            var backwards = instant with { End = instant.Start.AddHours(-1), Key = "backwards" };
            var entries = new List<Entry> { overnight, midnight, instant, spanning, longEvent, allDay, backwards };
            var random = new Random(42);
            for (int i = 0; i < 500; i++)
            {
                var start = At(monthStart.AddDays(random.Next(-30, 65)).AddMinutes(random.Next(1440)));
                entries.Add(new(start, start.AddMinutes(random.Next(-60, 6000)), $"event-{i}", "test", false, "", Key: $"event-{i}"));
            }
            foreach (var first in new[] { monthStart.AddMonths(-1), monthStart, monthStart.AddMonths(1) })
            {
                var end = first.AddMonths(1);
                var index = EventDayIndex.Build(entries, first, end);
                for (var date = first; date < end; date = date.AddDays(1))
                {
                    var expected = entries.Where(e => CalendarApp.OccursOn(e, date)).OrderBy(e => e.Start).ThenBy(e => e.Title);
                    Check(index.On(date).SequenceEqual(expected), "Date index must match occurrence rules, ordering and long/overnight/instant/all-day events");
                }
                Check(index.On(first.AddDays(-1)).Count == 0 && index.On(end).Count == 0, "Date index must be bounded to its requested range");
            }
            var boundary = new DateTime(2026, 12, 31);
            var yearEvent = instant with { Start = At(boundary.AddHours(23)), End = At(boundary.AddDays(1).AddHours(1)) };
            var yearIndex = EventDayIndex.Build([yearEvent], boundary, boundary.AddDays(8));
            Check(yearIndex.On(boundary).Count == 1 && yearIndex.On(boundary.AddDays(1)).Count == 1, "Date index must span year boundaries");
            Check(EventDayIndex.Build([allDay], day, day.AddDays(3)).On(day.AddDays(2)).Count == 0, "Exclusive all-day end must not mark the next day");
            var offset = TimeSpan.FromHours(TimeZoneInfo.Local.GetUtcOffset(boundary) < TimeSpan.Zero ? 14 : -12);
            var allDayAtBoundary = allDay with { Start = new DateTimeOffset(boundary, offset), End = new DateTimeOffset(boundary.AddDays(1), offset) };
            var allDayIndex = EventDayIndex.Build([allDayAtBoundary], boundary.AddDays(-1), boundary.AddDays(2));
            Check(allDayIndex.On(boundary).Count == 1 && allDayIndex.On(boundary.AddDays(-1)).Count == 0 &&
                allDayIndex.On(boundary.AddDays(1)).Count == 0 && CalendarApp.OccursInMonth(allDayAtBoundary, boundary) &&
                !CalendarApp.OccursInMonth(allDayAtBoundary, boundary.AddDays(1)), "All-day views must use calendar dates regardless of the stored offset");
            Check(MonthPolicy.Neighbors(DateTime.Today.AddMonths(12)).Length == 2 && !MonthPolicy.Neighbors(DateTime.Today.AddMonths(12)).Contains(DateTime.Today.ToString("yyyy-MM")), "Remote month prefetch must not request the unrelated current month");
            File.WriteAllText(Path.Combine(AppContext.BaseDirectory, "self-test.txt"), "PASS: theme/accent contrast and persistence, startup rollback, appearance/position recovery, cache expiry, bounded date index equivalence for 507 events, midnight/all-day/instant/cross-year handling and recent deduplication");
        }
        finally
        {
            foreach (string file in Directory.GetFiles(directory)) File.Delete(file);
            Directory.Delete(directory);
        }
    }

    sealed class CheckStartupEntry : IStartupEntry
    {
        public string? Value;
        public bool Fail;
        public int Changes;
        public string? Read() => Value;
        public void Write(string? command)
        {
            if (Fail) throw new UnauthorizedAccessException("simulated registry failure");
            Value = command; Changes++;
        }
    }
}
