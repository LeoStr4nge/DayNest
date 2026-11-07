using System.Text.Json;

namespace DayNest.Glass;

sealed record Appearance(bool Dark = true, double Density = .42, bool Glass = true, bool Desktop = true,
    string? Theme = null, string? Accent = null, bool? AutoStart = null, bool RemoveExpiredPins = true,
    string Language = "zh-CN");

static class PreviewSettings
{
    public static string FilePath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DayNest", "glass-preview.json");

    public static Appearance Load(string? path = null)
    {
        try
        {
            var saved = JsonSerializer.Deserialize<Appearance>(File.ReadAllText(path ?? FilePath));
            if (saved != null && double.IsFinite(saved.Density) && saved.Density is >= .15 and <= .8)
                return saved;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException) { }
        return new Appearance();
    }

    public static void Save(Appearance value, string? path = null)
    {
        path ??= FilePath;
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            File.WriteAllText(temporary, JsonSerializer.Serialize(value));
            File.Move(temporary, path, overwrite: true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}
