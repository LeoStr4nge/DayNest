using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace DayNest.Glass;

sealed partial class CalendarApp
{
    Action<string, string?, bool>? featureAppearancePreview;
    ContentDialog? featureDetailsDialog;
    ContentDialog? featureNewEventDialog;

    async void RunFeaturesCheck()
    {
        static void Check(bool valid, string message) { if (!valid) throw new InvalidOperationException(message); }
        string report;
        try
        {
            await Task.Delay(350); // Initial XAML layout must exist before opening dialogs.
            await (startupLoad ?? Task.CompletedTask);
            if (I18n.Language == "ja-JP")
            {
                monthOverview = true; calendar.Visibility = Visibility.Visible; DrawCalendar();
                var monthGrid = calendar.Children.OfType<Grid>().Last();
                Check(monthGrid.Children.OfType<TextBlock>().Any(label =>
                    Grid.GetRow(label) == 0 && Grid.GetColumn(label) == 0 && label.Text == "日"),
                    "Japanese month view must start with Sunday");
                monthOverview = false; calendar.Visibility = Visibility.Collapsed; DrawCalendar();
            }
            var commandRow = page.Children.OfType<Grid>().FirstOrDefault(row =>
                row.Children.OfType<Button>().Any(button => Equals(button.Content, I18n.T("+ 日程"))) &&
                row.Children.OfType<Button>().Any(button => Equals(button.Content, I18n.T("设置"))));
            Check(commandRow != null && page.Children.OfType<StackPanel>().Any(row =>
                row.Orientation == Orientation.Horizontal && row.Children.Count == 2 &&
                row.Children.OfType<Button>().Any(button => ReferenceEquals(button, refresh))),
                "Settings must share the new-event row, leaving only view selection and refresh below");
            var settingsButton = commandRow!.Children.OfType<Button>().Single(button => Equals(button.Content, I18n.T("设置")));
            double settingsLeft = settingsButton.TransformToVisual(page).TransformPoint(new Windows.Foundation.Point(0, 0)).X;
            SetRefreshBusy(true); await Task.Delay(40);
            SetRefreshBusy(false); await Task.Delay(40);
            Check(Math.Abs(settingsButton.TransformToVisual(page).TransformPoint(new Windows.Foundation.Point(0, 0)).X - settingsLeft) < .1 &&
                settingsButton.TransformToVisual(page).TransformPoint(new Windows.Foundation.Point(settingsButton.ActualWidth, 0)).X <= page.ActualWidth + 1,
                "Settings must fit inside the window after refresh");
            Check(refresh.TransformToVisual(page).TransformPoint(new Windows.Foundation.Point(refresh.ActualWidth, 0)).X <= page.ActualWidth + 1,
                "Refresh must fit beside the localized view selector");
            Check(viewThumbWidths.Length == 3 && viewSlotWidths.Length == 3 &&
                Enumerable.Range(0, 3).All(i => viewSlotWidths[i] >= viewThumbWidths[i] + 8) &&
                Math.Abs(viewTrack.Width - viewSlotWidths.Sum()) < .1,
                "View selector highlight must fit every localized label");
            if (I18n.Language == "en-US")
                Check(viewThumbWidths[1] > 46, "Upcoming must widen the selection highlight");
            recentOverview = true; UpdateViewSelector(true);
            await Task.Delay(280);
            Check(Math.Abs(viewThumb.Width - viewThumbWidths[1]) < .1 &&
                Math.Abs(viewThumbOffset.X - ViewThumbTarget(1)) < .1,
                "Animated selection must finish at the centered pill");
            recentOverview = false; UpdateViewSelector(true);
            await Task.Delay(280);
            for (int i = 0; i < 100 && prefetchCancellation != null; i++) await Task.Delay(10);
            foreach (var preset in Themes.All)
            {
                themeId = preset.Id; accentColor = null; ApplyAppearance();
                Check(dark == preset.Dark && ((SolidColorBrush)surface.Foreground).Color == Themes.Parse(preset.Text), "Theme text/root state mismatch");
                Check(((SolidColorBrush)Resources["AccentFillColorDefaultBrush"]).Color == Themes.Parse(preset.Accent), "Native control accent mismatch");
                await Task.Delay(35);
            }
            themeId = "forest"; accentColor = null; ApplyAppearance();
            var original = CurrentAppearance();
            var settingsTask = ShowSettings();
            await Task.Delay(80);
            Check(settingsOpen && instanceCheckDialog != null && featureAppearancePreview != null, "Settings did not open");
            var settingsBody = (StackPanel)instanceCheckDialog!.Content;
            var settingsViewport = (Grid)settingsBody.Children[1];
            var appearanceFields = (StackPanel)((ScrollViewer)settingsViewport.Children[0]).Content;
            var languageChoice = (ComboBox)appearanceFields.Children[0];
            Check(languageChoice.Items.Count == 3 && languageChoice.SelectedIndex ==
                (I18n.Language switch { "en-US" => 1, "ja-JP" => 2, _ => 0 }),
                "Settings must show and select all three display languages");
            featureAppearancePreview!("sand", "#123456", true);
            await Task.Delay(50);
            Check(themeId == "sand" && !dark && accentColor == "#123456" && autoStart, "Preset/color/startup preview did not reach application state");
            instanceCheckDialog!.Hide(); await settingsTask;
            Check(!settingsOpen && CurrentAppearance() == original, "Cancel must restore theme, accent and startup draft");
            var newEventTask = ShowNewEvent();
            Check(featureNewEventDialog != null, "New event form did not open");
            var eventFields = (StackPanel)((ScrollViewer)featureNewEventDialog!.Content).Content;
            var allDay = eventFields.Children.OfType<CheckBox>().Single();
            var dateTimeEditors = eventFields.Children.OfType<StackPanel>()
                .Select(field => field.Children.OfType<Grid>().Single()).ToArray();
            var dates = dateTimeEditors.Select(editor => editor.Children.OfType<CalendarDatePicker>().Single()).ToArray();
            var times = dateTimeEditors.Select(editor => editor.Children.OfType<Button>().Single()).ToArray();
            Check(allDay.IsChecked == false && times.All(button => button.IsEnabled), "Timed input must be enabled by default");
            var originalTimes = times.Select(button => button.Content).ToArray();
            allDay.IsChecked = true;
            Check(times.All(button => !button.IsEnabled) && dates.All(picker => picker.IsEnabled),
                "All-day mode must disable only the time controls");
            var originalEnd = dates[1].Date!.Value.Date;
            dates[0].Date = dates[0].Date!.Value.AddDays(2);
            Check(dates[1].Date!.Value.Date == originalEnd.AddDays(2), "Moving an all-day start must preserve the number of days");
            allDay.IsChecked = false;
            Check(times.All(button => button.IsEnabled) && times.Select(button => button.Content).SequenceEqual(originalTimes),
                "Returning to timed mode must restore the time controls and their values");
            featureNewEventDialog!.Hide(); await newEventTask;
            Check(!detailsOpen, "New event form must close without mutations");
            string key = selected.ToString("yyyy-MM");
            var entry = new Entry(DateTimeOffset.Now.AddDays(2), DateTimeOffset.Now.AddDays(2).AddHours(1), "Pinned test", "Test", false, "full\nnotes", Key: "test-pin");
            var pin = new Pin(entry.Title, entry.Start, Key: entry.Key, Notes: entry.Notes, Event: entry);
            StoreMonth(key, months[key] with { Pins = [pin] }); Render(months[key]);
            var pinContent = (StackPanel)((Button)pinned.Children[0]).Content;
            Check(pinContent.Children.OfType<TextBlock>().Any(t => t.MaxLines == 1 && t.TextTrimming == TextTrimming.CharacterEllipsis), "Pinned notes must use one-line ellipsis");
            var detailTask = ShowEventDetails(pin.Event!);
            await Task.Delay(60);
            Check(detailsOpen && featureDetailsDialog != null, "Pinned event detail did not open");
            featureDetailsDialog!.Hide(); await detailTask;
            Check(!detailsOpen, "Detail must close without mutations");
            recentOverview = true; monthOverview = false; selected = new DateTime(2026, 12, 29);
            calendar.Visibility = Visibility.Collapsed; await Load(true);
            Check(RecentMonths(selected).All(k => months.TryGetValue(k, out var data) && data.HasCache), "Recent view must load both months across a year boundary");
            Check(Enumerable.Range(0, 8).All(i => agenda.Children.OfType<TextBlock>().Any(t =>
                t.Text.StartsWith(selected.AddDays(i).ToString(I18n.T("M 月 d 日"), I18n.Culture)))),
                "Recent view must show exactly eight day groups");
            report = "PASS: six live themes/native accents, custom color/startup preview cancellation, all-day form controls, pin notes/details, eight-day cross-year recent view and two-month loading";
        }
        catch (Exception error) { report = "FAIL: " + error; }
        File.WriteAllText(Path.Combine(AppContext.BaseDirectory, "features-check.txt"), report);
        window.Close();
    }
}
