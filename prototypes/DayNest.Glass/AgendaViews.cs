using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;

namespace DayNest.Glass;

sealed partial class CalendarApp
{
    internal static string[] RecentMonths(DateTime today) => new[] { today, today.AddDays(7) }
        .Select(d => d.ToString("yyyy-MM")).Distinct().ToArray();
    readonly Dictionary<string, (Entry[]? Source, EventDayIndex Index)> dayIndexes = new();
    DateTime recentIndexStart;
    Entry[]?[] recentIndexSources = [];
    EventDayIndex recentIndex = EventDayIndex.Empty;

    EventDayIndex MonthIndex(string key)
    {
        if (!months.TryGetValue(key, out var data)) return EventDayIndex.Empty;
        if (!dayIndexes.TryGetValue(key, out var saved) || !ReferenceEquals(saved.Source, data.Events))
        {
            var first = DateTime.ParseExact(key + "-01", "yyyy-MM-dd", System.Globalization.CultureInfo.InvariantCulture);
            saved = (data.Events, EventDayIndex.Build(data.Events ?? [], first, first.AddMonths(1)));
            dayIndexes[key] = saved;
        }
        return saved.Index;
    }

    EventDayIndex RecentIndex()
    {
        var sources = RecentMonths(selected).Select(key => months.GetValueOrDefault(key)?.Events).ToArray();
        if (recentIndexStart != selected.Date || !recentIndexSources.SequenceEqual(sources))
        {
            recentIndex = EventDayIndex.Build(sources.SelectMany(source => source ?? []), selected.Date, selected.Date.AddDays(8), true);
            recentIndexStart = selected.Date; recentIndexSources = sources;
        }
        return recentIndex;
    }

    void ClearMonths()
    {
        months.Clear(); dayIndexes.Clear();
        recentIndex = EventDayIndex.Empty; recentIndexSources = []; recentIndexStart = default;
    }

    Button EventCard(Entry entry, bool includeDate)
    {
        var content = new StackPanel { Spacing = 6 };
        var start = entry.DisplayStart;
        string when = includeDate ? start.ToString(I18n.T("M月d日 ")) : "";
        content.Children.Add(new TextBlock { Text = $"{when}{(entry.AllDay ? I18n.T("全天") : start.ToString("HH:mm"))}  {I18n.FallbackName(entry.Title)}", FontSize = 17, TextWrapping = TextWrapping.Wrap });
        content.Children.Add(new TextBlock { Text = I18n.FallbackName(entry.Calendar), FontSize = 12, Opacity = .65 });
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
        AutomationProperties.SetName(card, I18n.T($"查看日程：{entry.Title}"));
        card.Click += async (_, _) => await ShowEventDetails(entry);
        return card;
    }

    void RenderRecent()
    {
        agenda.Children.Add(new TextBlock { Text = I18n.T("近期日程 · 今天及未来七天"), FontSize = 22 });
        var index = RecentIndex();
        for (int i = 0; i < 8; i++)
        {
            var day = selected.Date.AddDays(i);
            agenda.Children.Add(new TextBlock { Text = day.ToString(I18n.T("M 月 d 日")) + (i == 0 ? I18n.T(" · 今天") : ""), FontSize = 17, Foreground = Brush(palette.AccentInk), Margin = new Thickness(0, 10, 0, 0) });
            var daily = index.On(day);
            foreach (var entry in daily) agenda.Children.Add(EventCard(entry, false));
            if (daily.Count == 0)
            {
                bool complete = months.TryGetValue(day.ToString("yyyy-MM"), out var data) && data.HasCache;
                agenda.Children.Add(new TextBlock { Text = complete ? I18n.T("无日程") : I18n.T("该月份尚未完成同步"), Opacity = .65 });
            }
        }
    }

    void StoreMonth(string key, Result data)
    {
        months[key] = data;
        _ = MonthIndex(key);
        foreach (string other in months.Keys.ToArray())
            if (!(months[other].Pins ?? []).SequenceEqual(data.Pins ?? [])) months[other] = months[other] with { Pins = data.Pins };
    }
}
