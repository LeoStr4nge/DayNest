using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace DayNest.Glass;

sealed partial class CalendarApp
{
    string themeId = "midnight";
    string? accentColor;
    bool autoStart;
    bool removeExpiredPins = true;
    string language = "zh-CN";
    string? startupNotice;
    ThemePalette palette = Themes.Get("midnight");
    bool DiagnosticMode => InstanceChecks.IsWindowCheck || stressMode || Environment.GetCommandLineArgs().Any(a =>
        a is "--calendar-flow-check" or "--desktop-check" or "--features-check" or "--offline-preview");
    Appearance CurrentAppearance() => new(dark, glassDensity, glassEnabled, desktopMode, themeId, accentColor, autoStart, removeExpiredPins, language);
    void ReadAppearance(Appearance saved, bool initial = false)
    {
        dark = saved.Dark; glassDensity = saved.Density; glassEnabled = saved.Glass; desktopMode = saved.Desktop;
        themeId = Themes.Id(saved.Theme, saved.Dark); accentColor = Themes.ValidColor(saved.Accent) ? saved.Accent : null;
        autoStart = saved.AutoStart ?? false;
        removeExpiredPins = saved.RemoveExpiredPins;
        language = saved.Language == "en-US" ? "en-US" : "zh-CN";
        if (initial) I18n.Language = language;
        if (initial && !DiagnosticMode)
        {
            try
            {
                if (saved.AutoStart == null) autoStart = StartupRegistration.Enabled();
                if (saved.AutoStart == true) StartupRegistration.RefreshPath();
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or System.Security.SecurityException)
            { startupNotice = I18n.T("自动启动设置暂时无法读取或更新，请在设置中重试。"); }
        }
    }

    static SolidColorBrush Brush(Color color) => new(color);
    static SolidColorBrush Tint(byte alpha, Color color) => Brush(Windows.UI.Color.FromArgb(alpha, color.R, color.G, color.B));
    void ApplyThemeResources()
    {
        var resources = Resources;
        void Set(string key, Color color)
        {
            if (resources.ContainsKey(key) && resources[key] is SolidColorBrush brush) brush.Color = color;
            else resources[key] = Brush(color);
        }
        foreach (string key in new[] { "AccentFillColorDefaultBrush", "AccentFillColorSecondaryBrush", "AccentFillColorTertiaryBrush", "SystemControlHighlightAccentBrush" }) Set(key, palette.Accent);
        Set("AccentTextFillColorPrimaryBrush", palette.AccentInk);
        Set("TextOnAccentFillColorPrimaryBrush", palette.OnAccent);
        Set("TextOnAccentFillColorSecondaryBrush", palette.OnAccent);
        Set("TextFillColorPrimaryBrush", palette.Text);
        Set("TextFillColorSecondaryBrush", Windows.UI.Color.FromArgb(195, palette.Text.R, palette.Text.G, palette.Text.B));
        resources["SystemAccentColor"] = palette.Accent;
    }
}
