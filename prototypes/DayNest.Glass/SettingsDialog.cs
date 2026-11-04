using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Automation;

namespace DayNest.Glass;

sealed partial class CalendarApp
{
    bool settingsOpen;

    Task<JsonElement> AccountRequest(string command, object? payload = null) => BridgeRequest(command, payload);

    async Task ShowSettings()
    {
        if (settingsOpen || detailsOpen || writeBusy || closed) return;
        settingsOpen = true;
        CancelMonthRequests();
        var original = new Appearance(dark, glassDensity, glassEnabled, desktopMode);
        bool appearanceSaved = false, accountSaved = false, saving = false, accountLoaded = false;
        var message = new TextBlock { TextWrapping = TextWrapping.Wrap, FontSize = 13 };
        var dialog = new ContentDialog
        {
            Title = "设置 · DayNest", XamlRoot = page.XamlRoot,
            RequestedTheme = dark ? ElementTheme.Dark : ElementTheme.Light,
            PrimaryButtonText = "保存外观", CloseButtonText = "取消",
            DefaultButton = ContentDialogButton.Primary
        };
        bool isAccount = false;
        var tabs = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        var appearanceTab = new Button { Content = "外观与个性化" };
        var accountTab = new Button { Content = "日历账户" };
        tabs.Children.Add(appearanceTab); tabs.Children.Add(accountTab);
        var appearance = new StackPanel { Spacing = 16, Padding = new Thickness(0, 10, 0, 12) };
        var theme = new ComboBox { Header = "界面主题", HorizontalAlignment = HorizontalAlignment.Stretch };
        theme.Items.Add("深色"); theme.Items.Add("浅色"); theme.SelectedIndex = dark ? 0 : 1;
        var glassToggle = new ToggleSwitch { Header = "毛玻璃效果", IsOn = glassEnabled };
        var desktopToggle = new ToggleSwitch { Header = "桌面小组件模式", IsOn = desktopMode };
        var densityLabel = new TextBlock { Text = $"玻璃浓度 {glassDensity * 100:0}%" };
        var density = new Slider { Minimum = 15, Maximum = 80, Value = glassDensity * 100, StepFrequency = 1 };
        AutomationProperties.SetName(density, "玻璃浓度");
        appearance.Children.Add(theme); appearance.Children.Add(desktopToggle); appearance.Children.Add(glassToggle);
        appearance.Children.Add(new TextBlock { Text = "桌面模式下拖动 DayNest 标题调整位置，Win+D 后仍显示；关闭此选项恢复普通窗口。", TextWrapping = TextWrapping.Wrap, Opacity = .75 });
        appearance.Children.Add(densityLabel); appearance.Children.Add(density);
        appearance.Children.Add(new TextBlock { Text = "即时预览；保存后下次启动沿用。取消会恢复原来的外观。", TextWrapping = TextWrapping.Wrap, Opacity = .75 });
        void Preview()
        {
            dark = theme.SelectedIndex == 0; glassEnabled = glassToggle.IsOn; glassDensity = density.Value / 100;
            desktopMode = desktopToggle.IsOn;
            density.IsEnabled = glassEnabled;
            densityLabel.Text = $"玻璃浓度 {density.Value:0}%";
            ApplyAppearance();
            dialog.RequestedTheme = dark ? ElementTheme.Dark : ElementTheme.Light;
        }
        theme.SelectionChanged += (_, _) => Preview();
        glassToggle.Toggled += (_, _) => Preview();
        desktopToggle.Toggled += (_, _) => Preview();
        density.ValueChanged += (_, _) => Preview();
        density.IsEnabled = glassEnabled;

        var account = new StackPanel { Spacing = 12, Padding = new Thickness(0, 10, 0, 12) };
        var provider = new ComboBox { Header = "日历服务", HorizontalAlignment = HorizontalAlignment.Stretch };
        provider.Items.Add("iCloud"); provider.Items.Add("自定义 CalDAV"); provider.SelectedIndex = 0;
        var discovery = new TextBox { Header = "发现地址", PlaceholderText = "https://calendar.example/.well-known/caldav" };
        var home = new TextBox { Header = "日历目录（可选）" };
        var trusted = new TextBox { Header = "可信地址（可选）", PlaceholderText = "多个 HTTPS 来源用逗号分隔" };
        var custom = new StackPanel { Spacing = 12, Visibility = Visibility.Collapsed };
        custom.Children.Add(discovery); custom.Children.Add(home); custom.Children.Add(trusted);
        provider.SelectionChanged += (_, _) => custom.Visibility = provider.SelectedIndex == 1 ? Visibility.Visible : Visibility.Collapsed;
        var username = new TextBox { Header = "账户名或邮箱" };
        var password = new PasswordBox { Header = "日历密码", PasswordRevealMode = PasswordRevealMode.Hidden };
        var hint = new TextBlock { Text = "iCloud 使用 App 专用密码。密码留空可保留已有密码；更换账户或服务时需重新填写。", TextWrapping = TextWrapping.Wrap, Opacity = .75 };
        account.Children.Add(provider); account.Children.Add(custom); account.Children.Add(username);
        account.Children.Add(password); account.Children.Add(hint);
        var appearancePage = new ScrollViewer { Content = appearance, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled };
        var accountPage = new ScrollViewer { Content = account, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, Visibility = Visibility.Collapsed };
        // Both modules share one viewport so their different desired sizes do
        // not move the dialog or footer when switching pages/services.
        var viewport = new Grid();
        viewport.Children.Add(appearancePage); viewport.Children.Add(accountPage);
        void SelectPage(bool accountSelected)
        {
            isAccount = accountSelected;
            appearancePage.Visibility = isAccount ? Visibility.Collapsed : Visibility.Visible;
            accountPage.Visibility = isAccount ? Visibility.Visible : Visibility.Collapsed;
            dialog.PrimaryButtonText = isAccount ? "保存并同步" : "保存外观";
            message.Text = "";
        }
        appearanceTab.Click += (_, _) => SelectPage(false);
        accountTab.Click += (_, _) => SelectPage(true);
        var body = new StackPanel { Spacing = 12 };
        var messageArea = new ScrollViewer { Content = message, Height = 48, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled };
        body.Children.Add(tabs); body.Children.Add(viewport); body.Children.Add(messageArea); dialog.Content = body;
        var layoutRoot = page.XamlRoot;
        void SizeContent()
        {
            body.Width = Math.Max(200, Math.Min(420, layoutRoot.Size.Width - 64));
            viewport.Height = Math.Max(120, Math.Min(390, layoutRoot.Size.Height - 320));
        }
        void RootChanged(XamlRoot _, XamlRootChangedEventArgs args) => SizeContent();
        SizeContent();
        layoutRoot.Changed += RootChanged;
        try
        {
            try
            {
                var config = await AccountRequest("get-account");
                if (config.TryGetProperty("error", out _)) throw new InvalidOperationException();
                username.Text = config.GetProperty("username").GetString() ?? "";
                discovery.Text = config.GetProperty("discovery_url").GetString() ?? "";
                home.Text = config.GetProperty("calendar_home_url").GetString() ?? "";
                var origins = config.GetProperty("trusted_origins");
                trusted.Text = origins.ValueKind == JsonValueKind.Array ? string.Join(", ", origins.EnumerateArray().Select(v => v.GetString())) : origins.GetString() ?? "";
                provider.SelectedIndex = config.GetProperty("provider").GetString() == "custom" ? 1 : 0;
                password.PlaceholderText = config.GetProperty("hasPassword").GetBoolean() ? "已保存密码；留空保留" : "请输入日历密码";
                accountLoaded = true;
            }
            catch { message.Text = "账户信息暂时无法读取，请检查 Python 环境后重试。外观仍可单独保存。"; }
            if (closed) return;
            dialog.CloseButtonClick += (_, e) => e.Cancel = saving;
            dialog.Closing += (_, e) => { if (saving) e.Cancel = true; };
            dialog.PrimaryButtonClick += async (_, e) =>
            {
                e.Cancel = true;
                if (!isAccount)
                {
                    try
                    {
                        PreviewSettings.Save(new Appearance(dark, glassDensity, glassEnabled, desktopMode));
                        appearanceSaved = true; e.Cancel = false;
                    }
                    catch { message.Text = "外观保存失败，请检查本地文件权限后重试。"; }
                    return;
                }
                if (!accountLoaded) { message.Text = "请关闭设置后重试读取账户信息。"; return; }
                var deferral = e.GetDeferral();
                saving = true; appearanceTab.IsEnabled = accountTab.IsEnabled = accountPage.IsEnabled = false; dialog.IsPrimaryButtonEnabled = false;
                CancelMonthRequests(); refresh.IsEnabled = false;
                try
                {
                    var response = await AccountRequest("save-account", new
                    {
                        username = username.Text, password = password.Password,
                        provider = provider.SelectedIndex == 1 ? "custom" : "icloud",
                        discovery_url = discovery.Text.Trim(), calendar_home_url = home.Text.Trim(), trusted_origins = trusted.Text.Trim()
                    });
                    if (response.TryGetProperty("error", out var error)) message.Text = error.GetString();
                    else
                    {
                        password.Password = ""; accountSaved = true;
                        months.Clear(); agenda.Children.Clear(); pinned.Children.Clear(); DrawCalendar();
                        e.Cancel = false;
                    }
                }
                catch { message.Text = "账户保存失败，请检查 Python 环境及文件权限后重试。"; }
                finally
                {
                    saving = false; appearanceTab.IsEnabled = accountTab.IsEnabled = accountPage.IsEnabled = true; dialog.IsPrimaryButtonEnabled = true;
                    refresh.IsEnabled = true; deferral.Complete();
                }
            };
            await dialog.ShowAsync();
        }
        finally
        {
            layoutRoot.Changed -= RootChanged;
            password.Password = "";
            if (!appearanceSaved && !closed)
            {
                dark = original.Dark; glassDensity = original.Density; glassEnabled = original.Glass;
                desktopMode = original.Desktop; ApplyAppearance();
            }
            settingsOpen = false;
        }
        if (!closed) await Load(accountSaved);
    }
}
