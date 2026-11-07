using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Automation;

namespace DayNest.Glass;

sealed partial class CalendarApp
{
    Pin[]? renderedPins;
    DateTime renderedPinDay;
    string? renderedPinTheme;
    internal static Pin[] VisiblePins(Pin[] pins, bool removeExpired, DateTime today) =>
        removeExpired ? pins.Where(pin => pin.Start.LocalDateTime.Date >= today.Date).ToArray() : pins;

    async Task RemoveExpiredPins(CancellationToken cancellation)
    {
        if (!removeExpiredPins || DiagnosticMode || closed ||
            !months.Values.Any(month => (month.Pins ?? []).Any(pin => pin.Start.LocalDateTime.Date < DateTime.Today))) return;
        var response = await BridgeRequest("prune-expired-pins", cancellation: cancellation);
        if (response.TryGetProperty("error", out _)) throw new InvalidOperationException();
        var pins = response.GetProperty("pins").Deserialize<Pin[]>(new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? [];
        foreach (string key in months.Keys.ToArray()) months[key] = months[key] with { Pins = pins };
        RenderPins(pins);
    }
    async Task<bool> ChangePin(string command, string? handle, TextBlock notice)
    {
        if (writeBusy || closed) return false;
        writeBusy = true;
        CancelMonthRequests(); refresh.IsEnabled = false;
        try
        {
            var response = await AccountRequest(command, new { handle });
            if (response.TryGetProperty("error", out var error)) { notice.Text = error.GetString(); return false; }
            if (!response.TryGetProperty("ok", out var ok) || !ok.GetBoolean()) throw new InvalidOperationException();
            var pins = response.GetProperty("pins").Deserialize<Pin[]>(new JsonSerializerOptions { PropertyNameCaseInsensitive = true }) ?? [];
            foreach (string key in months.Keys.ToArray()) months[key] = months[key] with { Pins = pins };
            RenderPins(pins);
            notice.Text = command == "add-pin" ? "已固定到桌面" : "已取消固定";
            return true;
        }
        catch { notice.Text = "固定项保存失败，请刷新日历后重试。"; return false; }
        finally { writeBusy = false; refresh.IsEnabled = true; }
    }

    void RenderPins(Pin[] pins)
    {
        pins = VisiblePins(pins, removeExpiredPins, DateTime.Today);
        string appearance = themeId + "|" + Themes.Hex(palette.Accent) + "|" + removeExpiredPins;
        if (renderedPinDay == DateTime.Today && renderedPinTheme == appearance &&
            renderedPins != null && renderedPins.SequenceEqual(pins) && pinned.Children.Count == pins.Length) return;
        renderedPins = pins; renderedPinDay = DateTime.Today; renderedPinTheme = appearance;
        pinned.Children.Clear();
        foreach (var pin in pins.OrderBy(p => p.Start))
        {
            int days = (pin.Start.LocalDateTime.Date - DateTime.Today).Days;
            string countdown = days == 0 ? "今天" : days > 0 ? $"还有 {days} 天" : $"已过 {-days} 天";
            var content = new StackPanel { Spacing = 6 };
            content.Children.Add(new TextBlock { Text = pin.Title, TextWrapping = TextWrapping.Wrap, FontSize = 15 });
            content.Children.Add(new TextBlock { Text = countdown, FontSize = 22, Foreground = Brush(palette.AccentInk) });
            if (!string.IsNullOrWhiteSpace(pin.Notes)) content.Children.Add(new TextBlock
            {
                Text = string.Join(" ", pin.Notes.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)),
                MaxLines = 1, TextWrapping = TextWrapping.NoWrap, TextTrimming = TextTrimming.CharacterEllipsis, Opacity = .8
            });
            var remove = new MenuFlyoutItem { Text = "取消固定", IsEnabled = !string.IsNullOrEmpty(pin.ActionHandle) };
            var menu = new MenuFlyout(); menu.Items.Add(remove);
            var card = new Button
            {
                Content = content, Padding = new Thickness(12), CornerRadius = new CornerRadius(10),
                Background = Tint(40, palette.Accent), HorizontalAlignment = HorizontalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Stretch, ContextFlyout = menu
            };
            AutomationProperties.SetName(card, $"固定倒计时：{pin.Title}，{countdown}");
            ToolTipService.SetToolTip(card, "点击查看详情，右键可取消固定");
            if (pin.Event != null) card.Click += async (_, _) => await ShowEventDetails(pin.Event);
            remove.Click += async (_, _) =>
            {
                remove.IsEnabled = false;
                try { await ChangePin("remove-pin", pin.ActionHandle, status); }
                finally { remove.IsEnabled = true; FinishWrite(); }
                if (!closed) await Load(false);
            };
            pinned.Children.Add(card);
        }
    }
}
