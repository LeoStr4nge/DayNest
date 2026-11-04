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
            var duplicated = new Result([spanning], "", null, []);
            Check(CalendarApp.RecentEntries([duplicated, duplicated]).Length == 1, "Cross-month recent view must deduplicate spanning events");
            File.WriteAllText(Path.Combine(AppContext.BaseDirectory, "self-test.txt"), "PASS: theme/accent contrast and persistence, startup quoting/enable/disable/rollback, appearance/position recovery, atomic save, cache expiry and cross-year/day/month views");
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
