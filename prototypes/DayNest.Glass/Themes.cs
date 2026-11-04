using Windows.UI;

namespace DayNest.Glass;

sealed record ThemePreset(string Id, string Name, string Background, string Card, string Text, string Accent, bool Dark);
sealed record ThemePalette(ThemePreset Preset, Color Background, Color Card, Color Text, Color Accent, Color AccentInk, Color OnAccent);

static class Themes
{
    public static readonly ThemePreset[] All = [
        new("midnight", "午夜蓝", "#101923", "#1a2836", "#e8eff7", "#84d0ff", true),
        new("forest", "松林绿", "#111e1b", "#1b302a", "#e7f2ec", "#8cdbb4", true),
        new("plum", "暮光紫", "#1b1726", "#2b243b", "#eee9f7", "#c8adff", true),
        new("rose", "暖玫瑰", "#23191e", "#35262e", "#f6e9ee", "#f2adc7", true),
        new("paper", "云雾白", "#f3f5f8", "#ffffff", "#263445", "#326ca8", false),
        new("sand", "暖砂米", "#f5f0e7", "#fffcf5", "#463c30", "#94612d", false)
    ];
    public static string Id(string? id, bool dark) => All.FirstOrDefault(t => t.Id == id)?.Id ?? (dark ? "midnight" : "paper");
    public static bool ValidColor(string? value) => value?.Length == 7 && value[0] == '#' && value.Skip(1).All(Uri.IsHexDigit);
    public static Color Parse(string hex) => Color.FromArgb(255, Convert.ToByte(hex.Substring(1, 2), 16), Convert.ToByte(hex.Substring(3, 2), 16), Convert.ToByte(hex.Substring(5, 2), 16));
    public static string Hex(Color color) => $"#{color.R:x2}{color.G:x2}{color.B:x2}";
    public static double Luminance(Color color)
    {
        double Channel(byte c) { double v = c / 255d; return v <= .04045 ? v / 12.92 : Math.Pow((v + .055) / 1.055, 2.4); }
        return .2126 * Channel(color.R) + .7152 * Channel(color.G) + .0722 * Channel(color.B);
    }
    public static double Contrast(Color a, Color b) => (Math.Max(Luminance(a), Luminance(b)) + .05) / (Math.Min(Luminance(a), Luminance(b)) + .05);
    public static Color Mix(Color a, Color b, double amount) => Color.FromArgb(255,
        (byte)Math.Round(a.R * (1 - amount) + b.R * amount), (byte)Math.Round(a.G * (1 - amount) + b.G * amount), (byte)Math.Round(a.B * (1 - amount) + b.B * amount));
    public static ThemePalette Get(string id, string? custom = null)
    {
        var theme = All.FirstOrDefault(t => t.Id == id) ?? All[0];
        var bg = Parse(theme.Background); var text = Parse(theme.Text);
        var accent = Parse(ValidColor(custom) ? custom! : theme.Accent);
        var ink = accent;
        for (int i = 0; i <= 20; i++) { ink = Mix(accent, text, i / 20d); if (Contrast(ink, bg) >= 4.5) break; }
        var onAccent = Luminance(accent) > .179 ? Parse("#000000") : Parse("#ffffff");
        return new(theme, bg, Parse(theme.Card), text, accent, ink, onAccent);
    }
}
