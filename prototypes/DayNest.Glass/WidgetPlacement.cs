using System.Text.Json;

namespace DayNest.Glass;

sealed record WidgetPosition(int X = 60, int Y = 60);

static class WidgetPlacement
{
    static string FilePath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "DayNest", "widget-position.json");

    public static WidgetPosition Load(string? path = null)
    {
        try { return JsonSerializer.Deserialize<WidgetPosition>(File.ReadAllText(path ?? FilePath)) ?? new(); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException) { return new(); }
    }

    public static void Save(WidgetPosition position, string? path = null)
    {
        path ??= FilePath;
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            File.WriteAllText(temporary, JsonSerializer.Serialize(position));
            File.Move(temporary, path, true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}
