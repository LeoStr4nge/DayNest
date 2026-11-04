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
            PreviewSettings.Save(new Appearance(false, .67), path);
            Check(PreviewSettings.Load(path) == new Appearance(false, .67), "Appearance must survive restart");
            File.WriteAllText(path, "{\"Dark\":false,\"Density\":20}");
            Check(PreviewSettings.Load(path) == new Appearance(), "Invalid density must recover");
            Check(Directory.GetFiles(directory, "*.tmp").Length == 0, "Atomic save must clean temporary files");

            var day = new DateTime(2026, 11, 4);
            DateTimeOffset At(DateTime time) => new(time, TimeZoneInfo.Local.GetUtcOffset(time));
            var overnight = new Entry(At(day.AddDays(-1).AddHours(23)), At(day.AddHours(1)), "test", "test", false, "");
            Check(CalendarApp.OccursOn(overnight, day), "Overnight event must mark both days");
            var midnight = overnight with { End = At(day) };
            Check(!CalendarApp.OccursOn(midnight, day), "Exclusive midnight end must not mark the next day");
            var instant = overnight with { Start = At(day.AddHours(9)), End = At(day.AddHours(9)) };
            Check(CalendarApp.OccursOn(instant, day), "Zero-duration event must remain visible");
            File.WriteAllText(Path.Combine(AppContext.BaseDirectory, "self-test.txt"), "PASS: appearance persistence/recovery, atomic save, overnight/midnight/instant event dates");
        }
        finally
        {
            foreach (string file in Directory.GetFiles(directory)) File.Delete(file);
            Directory.Delete(directory);
        }
    }
}
