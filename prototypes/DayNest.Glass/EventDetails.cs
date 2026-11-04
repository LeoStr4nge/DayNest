using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace DayNest.Glass;

sealed partial class CalendarApp
{
    bool detailsOpen, writeBusy, closeAfterWrite;
    string? writeWarning;

    async Task<bool> WriteEvent(string command, object payload, TextBlock message)
    {
        writeBusy = true;
        CancelMonthRequests(); writeWarning = null;
        message.Text = command == "delete-event" ? "正在删除日程，请稍候…" : "正在保存日程，请稍候…";
        try
        {
            var response = await AccountRequest(command, payload);
            if (response.TryGetProperty("error", out var error)) { message.Text = error.GetString(); return false; }
            if (!response.TryGetProperty("ok", out var ok) || !ok.GetBoolean()) throw new InvalidOperationException();
            if (response.TryGetProperty("warning", out var warning)) writeWarning = warning.GetString();
            return true;
        }
        catch { message.Text = "未能确认服务器操作结果，请刷新日历确认后再试。"; return false; }
        finally { writeBusy = false; if (!closed) refresh.IsEnabled = true; }
    }

    void FinishWrite()
    {
        if (closeAfterWrite) window.DispatcherQueue.TryEnqueue(() => window.Close());
    }

    async Task ShowEventDetails(Entry entry)
    {
        if (detailsOpen || settingsOpen || writeBusy || closed) return;
        detailsOpen = true;
        CancelMonthRequests();
        bool editing = false, changed = false, saving = false;
        var title = new TextBox { Header = "日程标题", Text = entry.Title, IsReadOnly = true };
        var start = new EventDateTimeField("开始", entry.Start.LocalDateTime);
        var end = new EventDateTimeField("结束", entry.End.LocalDateTime);
        var notes = new TextBox { Header = "备注", Text = entry.Notes, AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, MinHeight = 110, IsReadOnly = true };
        var message = new TextBlock { TextWrapping = TextWrapping.Wrap };
        bool alreadyPinned = entry.Key != null && months.Values.Any(m => (m.Pins ?? []).Any(p => p.Key == entry.Key));
        var pinButton = new Button
        {
            Content = alreadyPinned ? "已固定到桌面" : "固定到桌面",
            IsEnabled = !alreadyPinned && !string.IsNullOrEmpty(entry.PinHandle)
        };
        var body = new StackPanel { Spacing = 12, Width = Math.Max(220, Math.Min(420, page.XamlRoot.Size.Width - 96)) };
        var timeHint = new TextBlock { Text = "点击日期选择月历，时间使用 24 小时制。调整开始时间会同步顺延结束时间，保留当前时长。", TextWrapping = TextWrapping.Wrap, Opacity = .7, Visibility = Visibility.Collapsed };
        DateTime previousStart = entry.Start.LocalDateTime;
        start.Changed += () =>
        {
            if (!editing || !start.TryGetValue(out var next)) return;
            if (end.TryGetValue(out var finish) && finish > previousStart)
            {
                try { end.SetValue(finish + (next - previousStart)); }
                catch (ArgumentOutOfRangeException) { message.Text = "请选择有效的结束日期。"; }
            }
            previousStart = next;
        };
        body.Children.Add(new TextBlock { Text = entry.Calendar + (entry.AllDay ? " · 全天" : ""), Opacity = .7 });
        body.Children.Add(pinButton); body.Children.Add(title); body.Children.Add(start.View); body.Children.Add(end.View); body.Children.Add(timeHint); body.Children.Add(notes); body.Children.Add(message);
        if (!entry.Editable || !entry.Deletable)
            body.Children.Add(new TextBlock { Text = "重复日程请在原日历中处理；全天日程暂不支持编辑。若缺少版本信息，请先刷新日历。", TextWrapping = TextWrapping.Wrap, Opacity = .7 });
        var details = new ContentDialog
        {
            Title = "日程详情", XamlRoot = page.XamlRoot, RequestedTheme = dark ? ElementTheme.Dark : ElementTheme.Light,
            Content = new ScrollViewer { Content = body, MaxHeight = Math.Max(180, Math.Min(440, page.XamlRoot.Size.Height - 240)) },
            PrimaryButtonText = "修改日程", SecondaryButtonText = "删除日程", CloseButtonText = "关闭",
            IsPrimaryButtonEnabled = entry.Editable, IsSecondaryButtonEnabled = entry.Deletable,
            DefaultButton = ContentDialogButton.Close
        };
        details.Closing += (_, e) => { if (saving) e.Cancel = true; };
        pinButton.Click += async (_, _) =>
        {
            saving = true; pinButton.IsEnabled = false;
            details.IsPrimaryButtonEnabled = details.IsSecondaryButtonEnabled = false;
            try
            {
                if (await ChangePin("add-pin", entry.PinHandle, message))
                { alreadyPinned = true; pinButton.Content = "已固定到桌面"; }
            }
            finally
            {
                saving = false; pinButton.IsEnabled = !alreadyPinned;
                details.IsPrimaryButtonEnabled = entry.Editable; details.IsSecondaryButtonEnabled = entry.Deletable;
                FinishWrite();
            }
        };
        details.PrimaryButtonClick += async (_, e) =>
        {
            e.Cancel = true;
            if (!editing)
            {
                editing = true; title.IsReadOnly = notes.IsReadOnly = false;
                start.BeginEdit(); end.BeginEdit(); timeHint.Visibility = Visibility.Visible;
                pinButton.IsEnabled = false;
                details.PrimaryButtonText = "保存修改"; details.CloseButtonText = "取消";
                title.Focus(FocusState.Programmatic);
                return;
            }
            if (string.IsNullOrWhiteSpace(title.Text)) { message.Text = "日程标题不能为空。"; return; }
            if (!start.TryGetValue(out var begin) || !end.TryGetValue(out var finish)
                || finish <= begin || TimeZoneInfo.Local.IsInvalidTime(begin) || TimeZoneInfo.Local.IsInvalidTime(finish))
            { message.Text = "请选择有效的日期时间，结束时间必须晚于开始时间。"; return; }
            var deferral = e.GetDeferral();
            saving = true; details.IsPrimaryButtonEnabled = details.IsSecondaryButtonEnabled = false; body.IsHitTestVisible = false;
            try
            {
                changed = await WriteEvent("edit-event", new
                {
                    handle = entry.Handle, title = title.Text.Trim(), notes = notes.Text,
                    start = new DateTimeOffset(begin, TimeZoneInfo.Local.GetUtcOffset(begin)).ToString("O"),
                    end = new DateTimeOffset(finish, TimeZoneInfo.Local.GetUtcOffset(finish)).ToString("O")
                }, message);
                if (changed) { selected = calendar.Visibility == Visibility.Collapsed ? DateTime.Today : begin.Date; e.Cancel = false; }
            }
            finally
            {
                saving = false; details.IsPrimaryButtonEnabled = entry.Editable; details.IsSecondaryButtonEnabled = entry.Deletable; body.IsHitTestVisible = true;
                deferral.Complete(); FinishWrite();
            }
        };
        try
        {
            while (!closed)
            {
                var result = await details.ShowAsync();
                if (result != ContentDialogResult.Secondary || closed) break;
                var warning = new TextBlock { Text = $"确定删除“{entry.Title}”？\n\n此操作会从日历服务中删除日程，其他设备也会同步删除。", TextWrapping = TextWrapping.Wrap };
                var confirm = new ContentDialog
                {
                    Title = "确认删除日程", XamlRoot = page.XamlRoot, RequestedTheme = details.RequestedTheme,
                    Content = warning, PrimaryButtonText = "删除日程", CloseButtonText = "取消", DefaultButton = ContentDialogButton.Close
                };
                bool deleting = false;
                confirm.Closing += (_, e) => { if (deleting) e.Cancel = true; };
                confirm.PrimaryButtonClick += async (_, e) =>
                {
                    e.Cancel = true; var deferral = e.GetDeferral(); deleting = true; confirm.IsPrimaryButtonEnabled = false;
                    try
                    {
                        changed = await WriteEvent("delete-event", new { handle = entry.Handle, confirmed = true }, warning);
                        if (changed) e.Cancel = false;
                    }
                    finally { deleting = false; confirm.IsPrimaryButtonEnabled = true; deferral.Complete(); FinishWrite(); }
                };
                await confirm.ShowAsync();
                if (changed) break;
            }
        }
        finally { detailsOpen = false; }
        if (changed && !closed)
        {
            months.Clear(); agenda.Children.Clear(); pinned.Children.Clear(); DrawCalendar();
            await Load(true);
            if (writeWarning != null) status.Text += " · " + writeWarning;
        }
        else if (!closed) await Load(false);
    }
}
