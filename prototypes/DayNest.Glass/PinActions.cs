using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Automation;

namespace DayNest.Glass;

sealed partial class CalendarApp
{
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
        pinned.Children.Clear();
        foreach (var pin in pins)
        {
            int days = (pin.Start.LocalDateTime.Date - DateTime.Today).Days;
            string countdown = days == 0 ? "今天" : days > 0 ? $"还有 {days} 天" : $"已过 {-days} 天";
            var text = new TextBlock { Text = $"{pin.Title} · {countdown}", TextWrapping = TextWrapping.Wrap, FontSize = 15 };
            var remove = new MenuFlyoutItem { Text = "取消固定", IsEnabled = !string.IsNullOrEmpty(pin.ActionHandle) };
            var menu = new MenuFlyout(); menu.Items.Add(remove);
            var card = new Button
            {
                Content = text, Padding = new Thickness(12), CornerRadius = new CornerRadius(10),
                Background = Color(24, 110, 160, 230), HorizontalAlignment = HorizontalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Stretch, ContextFlyout = menu
            };
            AutomationProperties.SetName(card, $"固定倒计时：{pin.Title}，{countdown}");
            ToolTipService.SetToolTip(card, "右键可取消固定");
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
