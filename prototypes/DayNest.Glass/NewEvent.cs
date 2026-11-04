using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace DayNest.Glass;

sealed record CalendarChoice(string Name, string Handle);

sealed partial class CalendarApp
{
    async Task ShowNewEvent()
    {
        if (detailsOpen || settingsOpen || writeBusy || closed) return;
        detailsOpen = true; CancelMonthRequests();
        bool saving = false, created = false;
        string requestId = Guid.NewGuid().ToString("D");
        var now = DateTime.Now;
        var initial = selected.Date == now.Date
            ? new DateTime(now.Year, now.Month, now.Day, now.Hour, 0, 0).AddHours(1)
            : selected.Date.AddHours(9);
        var title = new TextBox { Header = "日程标题", PlaceholderText = "准备安排什么？" };
        var calendarChoice = new ComboBox { Header = "保存到日历", DisplayMemberPath = "Name", HorizontalAlignment = HorizontalAlignment.Stretch };
        var start = new EventDateTimeField("开始", initial);
        var end = new EventDateTimeField("结束", initial.AddHours(1));
        start.BeginEdit(); end.BeginEdit();
        var notes = new TextBox { Header = "备注", AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, MinHeight = 90 };
        var message = new TextBlock { Text = "正在读取可用日历…", TextWrapping = TextWrapping.Wrap };
        var retry = new Button { Content = "重新读取日历", Visibility = Visibility.Collapsed };
        var body = new StackPanel { Spacing = 12, Width = Math.Max(220, Math.Min(420, page.XamlRoot.Size.Width - 96)) };
        body.Children.Add(title); body.Children.Add(calendarChoice); body.Children.Add(start.View); body.Children.Add(end.View);
        body.Children.Add(notes); body.Children.Add(message); body.Children.Add(retry);
        var form = new ScrollViewer { Content = body, MaxHeight = Math.Max(180, Math.Min(440, page.XamlRoot.Size.Height - 240)) };
        var dialog = new ContentDialog
        {
            Title = "添加日程", XamlRoot = page.XamlRoot, RequestedTheme = dark ? ElementTheme.Dark : ElementTheme.Light,
            Content = form,
            PrimaryButtonText = "添加到日历", CloseButtonText = "取消", DefaultButton = ContentDialogButton.Close,
            IsPrimaryButtonEnabled = false
        };
        DateTime previousStart = initial;
        start.Changed += () =>
        {
            if (!start.TryGetValue(out var next)) return;
            if (end.TryGetValue(out var finish) && finish > previousStart)
            {
                try { end.SetValue(finish + (next - previousStart)); }
                catch (ArgumentOutOfRangeException) { message.Text = "请选择有效的结束日期。"; }
            }
            previousStart = next;
        };
        using var readCancellation = new CancellationTokenSource();
        async Task ReadCalendars()
        {
            retry.IsEnabled = false; dialog.IsPrimaryButtonEnabled = false; message.Text = "正在读取可用日历…";
            try
            {
                var result = await BridgeRequest("get-calendars", new { cachedOnly = !AutomaticNetwork }, readCancellation.Token);
                if (readCancellation.IsCancellationRequested || closed) return;
                if (result.TryGetProperty("error", out var error)) { message.Text = error.GetString(); return; }
                var choices = result.GetProperty("calendars").Deserialize<CalendarChoice[]>(new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? [];
                calendarChoice.ItemsSource = choices;
                calendarChoice.SelectedIndex = choices.Length == 0 ? -1 : 0;
                dialog.IsPrimaryButtonEnabled = choices.Length > 0;
                message.Text = choices.Length > 0 ? "添加单次日程；调整开始时间会保留原有时长。" : "未找到日历，请先检查账户设置并同步。";
            }
            catch (OperationCanceledException) when (readCancellation.IsCancellationRequested) { }
            catch { if (!closed) message.Text = "未能读取日历，请检查网络和日历账户后重试。"; }
            finally
            {
                if (!closed && !readCancellation.IsCancellationRequested)
                { retry.IsEnabled = true; retry.Visibility = dialog.IsPrimaryButtonEnabled ? Visibility.Collapsed : Visibility.Visible; }
            }
        }
        retry.Click += async (_, _) => await ReadCalendars();
        dialog.Closing += (_, e) => { if (saving) e.Cancel = true; };
        dialog.PrimaryButtonClick += async (_, e) =>
        {
            e.Cancel = true;
            if (calendarChoice.SelectedItem is not CalendarChoice target) { message.Text = "请选择保存到哪个日历。"; return; }
            if (string.IsNullOrWhiteSpace(title.Text)) { message.Text = "日程标题不能为空。"; return; }
            if (!start.TryGetValue(out var begin) || !end.TryGetValue(out var finish) || finish <= begin ||
                TimeZoneInfo.Local.IsInvalidTime(begin) || TimeZoneInfo.Local.IsInvalidTime(finish))
            { message.Text = "请选择有效的日期时间，结束时间必须晚于开始时间。"; return; }
            var deferral = e.GetDeferral(); saving = true; dialog.IsPrimaryButtonEnabled = false; form.IsEnabled = false;
            try
            {
                created = await WriteEvent("create-event", new
                {
                    handle = target.Handle, requestId, title = title.Text.Trim(), notes = notes.Text,
                    start = new DateTimeOffset(begin, TimeZoneInfo.Local.GetUtcOffset(begin)).ToString("O"),
                    end = new DateTimeOffset(finish, TimeZoneInfo.Local.GetUtcOffset(finish)).ToString("O")
                }, message);
                if (created)
                {
                    selected = begin.Date;
                    if (selected != DateTime.Today) { monthOverview = false; calendar.Visibility = Visibility.Visible; }
                    e.Cancel = false;
                }
            }
            finally
            {
                saving = false; dialog.IsPrimaryButtonEnabled = true; form.IsEnabled = true;
                deferral.Complete(); FinishWrite();
            }
        };
        try
        {
            _ = ReadCalendars();
            if (!closed) await dialog.ShowAsync();
        }
        finally { readCancellation.Cancel(); detailsOpen = false; }
        if (created && !closed)
        {
            months.Clear(); DrawCalendar(); await Load(true);
            if (writeWarning != null) status.Text += " · " + writeWarning;
        }
        else if (!closed) await Load(false);
    }
}
