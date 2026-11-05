using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Animation;
using Windows.UI.ViewManagement;

namespace DayNest.Glass;

sealed partial class CalendarApp
{
    const double ViewSlotWidth = 78;
    readonly Button todayButton = new() { Content = "今日" };
    readonly Button recentButton = new() { Content = "近期" };
    Border viewTrack = null!;
    Border viewThumb = null!;
    TranslateTransform viewThumbOffset = null!;
    Storyboard? viewThumbAnimation;
    int shownView = -1;
    ProgressRing? refreshSpinner;

    Border CreateViewSelector()
    {
        monthButton.Content = "本月";
        viewThumbOffset = new TranslateTransform();
        viewThumb = new Border
        {
            Width = 46, Height = 46, CornerRadius = new CornerRadius(23),
            Margin = new Thickness((ViewSlotWidth - 46) / 2, 0, 0, 0),
            HorizontalAlignment = HorizontalAlignment.Left,
            VerticalAlignment = VerticalAlignment.Center,
            RenderTransform = viewThumbOffset,
            IsHitTestVisible = false
        };
        var content = new Grid();
        content.Children.Add(viewThumb);
        var labels = new Grid();
        for (int i = 0; i < 3; i++) labels.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(ViewSlotWidth) });
        var buttons = new[] { todayButton, recentButton, monthButton };
        for (int i = 0; i < buttons.Length; i++)
        {
            var button = buttons[i];
            button.Style = (Style)Resources["ViewSelectorButtonStyle"];
            button.HorizontalAlignment = HorizontalAlignment.Stretch;
            button.VerticalAlignment = VerticalAlignment.Stretch;
            button.Padding = new Thickness(0);
            button.BorderThickness = new Thickness(0);
            button.Background = Color(0, 0, 0, 0);
            button.FontSize = 13;
            Grid.SetColumn(button, i);
            labels.Children.Add(button);
        }
        content.Children.Add(labels);
        viewTrack = new Border
        {
            Width = ViewSlotWidth * 3, Height = 50, CornerRadius = new CornerRadius(25),
            BorderThickness = new Thickness(1), Child = content
        };
        return viewTrack;
    }

    void UpdateViewSelector(bool animate = false)
    {
        int position = recentOverview ? 1 : calendar.Visibility == Visibility.Visible ? 2 : 0;
        if (shownView != position)
        {
            shownView = position;
            double target = position * ViewSlotWidth;
            double start = viewThumbOffset.X;
            viewThumbAnimation?.Stop();
            // Keep the underlying value at the destination so the last animation frame cannot flash at the old slot.
            viewThumbOffset.X = target;
            if (animate && new UISettings().AnimationsEnabled)
            {
                var slide = new DoubleAnimation
                {
                    From = start, To = target,
                    Duration = new Duration(TimeSpan.FromMilliseconds(220)),
                    FillBehavior = FillBehavior.Stop,
                    EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
                };
                Storyboard.SetTarget(slide, viewThumbOffset);
                Storyboard.SetTargetProperty(slide, nameof(TranslateTransform.X));
                var storyboard = new Storyboard();
                storyboard.Children.Add(slide);
                viewThumbAnimation = storyboard;
                storyboard.Completed += (_, _) =>
                {
                    if (!ReferenceEquals(viewThumbAnimation, storyboard)) return;
                    viewThumbOffset.X = target;
                    viewThumbAnimation = null;
                };
                storyboard.Begin();
            }
        }
        viewTrack.Background = Tint(90, palette.Card);
        viewTrack.BorderBrush = Tint(55, palette.Text);
        viewThumb.Background = Brush(palette.Accent);
        var buttons = new[] { todayButton, recentButton, monthButton };
        string[] names = ["今日", "近期日程：今天及未来七天", "本月日程"];
        for (int i = 0; i < buttons.Length; i++)
        {
            buttons[i].Foreground = Brush(i == position ? palette.OnAccent : palette.Text);
            AutomationProperties.SetName(buttons[i], i == position ? names[i] + "，当前视图" : names[i]);
        }
    }

    void SetRefreshBusy(bool busy)
    {
        refreshSpinner ??= new ProgressRing { Width = 16, Height = 16 };
        refreshSpinner.IsActive = busy;
        refresh.Content = busy ? refreshSpinner : "刷新";
        AutomationProperties.SetName(refresh, busy ? "正在刷新日历" : "刷新日历");
        ToolTipService.SetToolTip(refresh, busy ? "正在读取日历" : "刷新当前日历");
    }
}
