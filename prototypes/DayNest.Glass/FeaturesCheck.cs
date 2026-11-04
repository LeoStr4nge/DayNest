using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace DayNest.Glass;

sealed partial class CalendarApp
{
    Action<string, string?, bool>? featureAppearancePreview;
    ContentDialog? featureDetailsDialog;

    async void RunFeaturesCheck()
    {
        static void Check(bool valid, string message) { if (!valid) throw new InvalidOperationException(message); }
        string report;
        try
        {
            await Task.Delay(350); // Initial XAML layout must exist before opening dialogs.
            await (startupLoad ?? Task.CompletedTask);
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
            featureAppearancePreview!("sand", "#123456", true);
            await Task.Delay(50);
            Check(themeId == "sand" && !dark && accentColor == "#123456" && autoStart, "Preset/color/startup preview did not reach application state");
            instanceCheckDialog!.Hide(); await settingsTask;
            Check(!settingsOpen && CurrentAppearance() == original, "Cancel must restore theme, accent and startup draft");
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
            Check(agenda.Children.OfType<TextBlock>().Count(t => t.Text.Contains(" 月 ") && t.Text.Contains(" 日")) == 8, "Recent view must show exactly eight day groups");
            report = "PASS: six live themes/native accents, custom color/startup preview cancellation, pin notes/details, eight-day cross-year recent view and two-month loading";
        }
        catch (Exception error) { report = "FAIL: " + error; }
        File.WriteAllText(Path.Combine(AppContext.BaseDirectory, "features-check.txt"), report);
        window.Close();
    }
}
