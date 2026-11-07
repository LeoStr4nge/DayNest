using System.Globalization;
using System.Text.Json;

namespace DayNest.Glass;

sealed partial class CalendarApp
{
    void PrepareDemoData()
    {
        monthReaderOverride = (key, _, cancellation) =>
        {
            cancellation.ThrowIfCancellationRequested();
            return Task.FromResult(DemoMonth(key));
        };
    }

    static string DemoText(string zh, string en, string ja) => I18n.Language switch
    {
        "en-US" => en,
        "ja-JP" => ja,
        _ => zh
    };

    static Result DemoMonth(string key)
    {
        var first = DateTime.ParseExact(key + "-01", "yyyy-MM-dd", CultureInfo.InvariantCulture);
        var today = DateTime.Today;
        string calendar = DemoText("演示日历", "Sample calendar", "サンプルカレンダー");
        Entry Make(DateTime day, int hour, int minute, int durationMinutes, string title, string note) =>
            new(new DateTimeOffset(day.AddHours(hour).AddMinutes(minute)),
                new DateTimeOffset(day.AddHours(hour).AddMinutes(minute).AddMinutes(durationMinutes)),
                title, calendar, false, note, Key: "demo-" + day.ToString("yyyyMMdd", CultureInfo.InvariantCulture) + "-" + hour);

        var entries = new List<Entry>
        {
            Make(first.AddDays(3), 11, 0, 60,
                DemoText("整理本月计划", "Plan the month", "今月の予定を整理"),
                DemoText("列出本月想完成的三件事", "Pick three things to finish this month", "今月取り組むことを三つ決める")),
            Make(first.AddDays(11), 15, 0, 90,
                DemoText("周末咖啡时间", "Weekend coffee", "週末のカフェ時間"),
                DemoText("试试街角的新咖啡店", "Try the new café around the corner", "近所の新しいカフェへ")),
            Make(first.AddDays(19), 10, 30, 60,
                DemoText("项目回顾", "Project review", "プロジェクトの振り返り"),
                DemoText("记录进展和下一步想法", "Review progress and next steps", "進捗と次の予定を確認"))
        };
        if (first.Year == today.Year && first.Month == today.Month)
        {
            entries.Add(Make(today, 9, 30, 45,
                DemoText("晨间计划", "Morning planning", "朝の予定を確認"),
                DemoText("安排今天最重要的事", "Plan the most important task for today", "今日の大切な予定を整理")));
            entries.Add(Make(today, 14, 0, 60,
                DemoText("设计讨论", "Design discussion", "デザインの打ち合わせ"),
                DemoText("交流界面和交互的想法", "Share ideas about the interface", "画面と操作について相談")));
            entries.Add(Make(today, 18, 30, 90,
                DemoText("和朋友晚餐", "Dinner with friends", "友人と夕食"),
                DemoText("下班后放松一下", "A relaxing evening after work", "仕事の後にゆっくり過ごす")));
        }
        var trip = Make(today.AddDays(5), 8, 0, 60,
            DemoText("旅行出发", "Trip begins", "旅行へ出発"),
            DemoText("带上相机，享受旅程", "Bring a camera and enjoy the trip", "カメラを持って旅を楽しむ"));
        if (trip.Start.LocalDateTime.Year == first.Year && trip.Start.LocalDateTime.Month == first.Month)
            entries.Add(trip);
        var pin = new Pin(trip.Title, trip.Start, Key: trip.Key, Notes: trip.Notes, Event: trip);
        return new Result(entries.OrderBy(e => e.Start).ToArray(),
            DemoText("演示数据 · 离线", "Sample data · Offline", "サンプルデータ · オフライン"),
            null, [pin], true, true, DateTimeOffset.UtcNow.ToUnixTimeSeconds());
    }

    static JsonElement DemoBridgeResponse(string command) => command switch
    {
        "get-account" => JsonSerializer.SerializeToElement(new
        {
            username = "", provider = "icloud", discovery_url = "", calendar_home_url = "",
            trusted_origins = Array.Empty<string>(), hasPassword = false
        }),
        "get-calendars" => JsonSerializer.SerializeToElement(new
        {
            calendars = new[] { new { name = DemoText("演示日历", "Sample calendar", "サンプルカレンダー"), handle = "demo" } }
        }),
        _ => throw new InvalidOperationException("Demo mode cannot write or access calendar data.")
    };
}
