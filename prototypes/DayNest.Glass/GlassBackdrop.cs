using Microsoft.UI.Composition;
using Microsoft.UI.Composition.SystemBackdrops;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;

namespace DayNest.Glass;

// Pane's separate tint/luminosity controls informed this material. This uses
// the supported WinUI controller rather than Pane's dual-HWND Composition host.
sealed class GlassBackdrop : SystemBackdrop
{
    DesktopAcrylicController? controller;
    readonly SystemBackdropConfiguration configuration = new() { IsInputActive = true };
    bool dark = true;
    double density = .42;

    public static bool IsSupported => DesktopAcrylicController.IsSupported();

    public void SetActive(bool active) => configuration.IsInputActive = active;

    public void Update(bool isDark, double tintDensity)
    {
        dark = isDark;
        density = Math.Clamp(tintDensity, .15, .8);
        Apply();
    }

    protected override void OnTargetConnected(ICompositionSupportsSystemBackdrop target, XamlRoot root)
    {
        base.OnTargetConnected(target, root);
        if (!IsSupported) return;
        controller = new DesktopAcrylicController { Kind = DesktopAcrylicKind.Base };
        controller.SetSystemBackdropConfiguration(configuration);
        controller.AddSystemBackdropTarget(target);
        Apply();
    }

    void Apply()
    {
        if (controller == null) return;
        configuration.Theme = dark ? SystemBackdropTheme.Dark : SystemBackdropTheme.Light;
        controller.TintColor = dark ? Windows.UI.Color.FromArgb(255, 28, 28, 32)
                                    : Windows.UI.Color.FromArgb(255, 246, 246, 248);
        controller.TintOpacity = (float)density;
        // Tune luminance separately; never cover the material with an opaque XAML page.
        controller.LuminosityOpacity = dark ? .28f : .38f;
        controller.FallbackColor = dark ? Windows.UI.Color.FromArgb(255, 28, 31, 38)
                                       : Windows.UI.Color.FromArgb(255, 242, 244, 248);
    }

    protected override void OnDefaultSystemBackdropConfigurationChanged(
        ICompositionSupportsSystemBackdrop target, XamlRoot root)
    {
        // Own the configuration for the entire connection: querying the base
        // default configuration here can reject targets during XAML transitions.
        // Theme and activation are supplied explicitly by CalendarApp.
    }

    protected override void OnTargetDisconnected(ICompositionSupportsSystemBackdrop target)
    {
        controller?.RemoveSystemBackdropTarget(target);
        controller?.Dispose();
        controller = null;
        base.OnTargetDisconnected(target);
    }
}
