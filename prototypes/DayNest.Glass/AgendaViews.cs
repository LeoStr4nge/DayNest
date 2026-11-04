using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;

namespace DayNest.Glass;

sealed partial class CalendarApp
{
    internal static string[] RecentMonths(DateTime today) => new[] { today, today.AddDays(7) }
        .Select(d => d.ToString("yyyy-MM")).Distinct().ToArray();
    internal static Entry[] RecentEntries(IEnumerable<Result> data) => data.SelectMany(d => d.Events ?? [])
        .DistinctBy(e => e.Key ?? $"{e.Calendar}|{e.Start:O}|{e.End:O}|{e.Title}")
        .OrderBy(e => e.Start).ThenBy(e => e.Title).ToArray();

    Button EventCard(Entry entry, bool includeDate)
    {
        var content = new StackPanel { Spacing = 6 };
        string when = includeDate ? entry.Start.LocalDateTime.ToString("M月d日 ") : "";
        content.Children.Add(new TextBlock { Text = $"{when}{(entry.AllDay ? "全天" : entry.Start.LocalDateTime.ToString("HH:mm"))}  {entry.Title}", FontSize = 17, TextWrapping = TextWrapping.Wrap });
        content.Children.Add(new TextBlock { Text = entry.Calendar, FontSize = 12, Opacity = .65 });
        if (!string.IsNullOrWhiteSpace(entry.Notes)) content.Children.Add(new TextBlock
        {
            Text = string.Join(" ", entry.Notes.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)),
            TextWrapping = TextWrapping.NoWrap, TextTrimming = TextTrimming.CharacterEllipsis, MaxLines = 1, Opacity = .8
        });
        var card = new Button
        {
            Content = content, HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch,
            Padding = new Thickness(14), CornerRadius = new CornerRadius(12), Background = Tint(90, palette.Card)
        };
        AutomationProperties.SetName(card, $"查看日程：{entry.Title}");
        card.Click += async (_, _) => await ShowEventDetails(entry);
        return card;
    }

    void RenderRecent()
    {
        agenda.Children.Add(new TextBlock { Text = "近期日程 · 今天及未来七天", FontSize = 22 });
        var keys = RecentMonths(selected);
        var entries = RecentEntries(keys.Where(months.ContainsKey).Select(k => months[k]));
        for (int i = 0; i < 8; i++)
        {
            var day = selected.Date.AddDays(i);
            agenda.Children.Add(new TextBlock { Text = day.ToString("M 月 d 日") + (i == 0 ? " · 今天" : ""), FontSize = 17, Foreground = Brush(palette.AccentInk), Margin = new Thickness(0, 10, 0, 0) });
            var daily = entries.Where(e => OccursOn(e, day)).ToArray();
            foreach (var entry in daily) agenda.Children.Add(EventCard(entry, false));
            if (daily.Length == 0)
            {
                bool complete = months.TryGetValue(day.ToString("yyyy-MM"), out var data) && data.HasCache;
                agenda.Children.Add(new TextBlock { Text = complete ? "无日程" : "该月份尚未完成同步", Opacity = .65 });
            }
        }
    }

    void StoreMonth(string key, Result data)
    {
        months[key] = data;
        foreach (string other in months.Keys.ToArray())
            if (!(months[other].Pins ?? []).SequenceEqual(data.Pins ?? [])) months[other] = months[other] with { Pins = data.Pins };
    }
}
