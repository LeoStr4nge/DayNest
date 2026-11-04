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
            PreviewSettings.Save(new Appearance(false, .67, false, false), path);
            Check(PreviewSettings.Load(path) == new Appearance(false, .67, false, false), "Theme, glass, desktop mode and density must survive restart");
            File.WriteAllText(path, "{\"Dark\":false,\"Density\":20}");
            Check(PreviewSettings.Load(path) == new Appearance(), "Invalid density must recover");
            Check(Directory.GetFiles(directory, "*.tmp").Length == 0, "Atomic save must clean temporary files");
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
            File.WriteAllText(Path.Combine(AppContext.BaseDirectory, "self-test.txt"), "PASS: appearance/desktop-mode/position persistence and recovery, atomic save, cache expiry/clock rollback, cross-year prefetch and day/month event dates");
        }
        finally
        {
            foreach (string file in Directory.GetFiles(directory)) File.Delete(file);
            Directory.Delete(directory);
        }
    }
}
