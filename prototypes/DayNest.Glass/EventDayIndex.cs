namespace DayNest.Glass;

// Index only the requested date range, so even a multi-year event has bounded cost.
sealed class EventDayIndex
{
    public static readonly EventDayIndex Empty = new(new());
    readonly Dictionary<DateTime, Entry[]> days;

    EventDayIndex(Dictionary<DateTime, Entry[]> days) => this.days = days;

    public IReadOnlyList<Entry> On(DateTime day) => days.GetValueOrDefault(day.Date) ?? [];

    public static EventDayIndex Build(IEnumerable<Entry> entries, DateTime first, DateTime end, bool deduplicate = false)
    {
        first = first.Date; end = end.Date;
        var grouped = new Dictionary<DateTime, List<Entry>>();
        if (deduplicate) entries = entries.DistinctBy(e => e.Key ?? $"{e.Calendar}|{e.Start:O}|{e.End:O}|{e.Title}");
        foreach (var entry in entries.OrderBy(e => e.Start).ThenBy(e => e.Title))
        {
            var start = entry.Start.LocalDateTime.Date;
            var last = entry.End > entry.Start ? entry.End.LocalDateTime.Date : start;
            if (entry.End > entry.Start && entry.End.LocalDateTime.TimeOfDay == TimeSpan.Zero) last = last.AddDays(-1);
            var day = start > first ? start : first;
            for (; day < end && day <= last; day = day.AddDays(1))
            {
                if (!grouped.TryGetValue(day, out var daily)) grouped[day] = daily = new();
                daily.Add(entry);
            }
        }
        return new(grouped.ToDictionary(pair => pair.Key, pair => pair.Value.ToArray()));
    }
}
