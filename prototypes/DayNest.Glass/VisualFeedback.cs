using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Animation;
using Windows.UI.ViewManagement;

namespace DayNest.Glass;

sealed partial class CalendarApp
{
    const double MinimumViewSlotWidth = 78;
    double[] viewSlotWidths = [];
    double[] viewThumbWidths = [];
    readonly Button todayButton = new() { Content = I18n.T("今日") };
    readonly Button recentButton = new() { Content = I18n.T("近期") };
    Border viewTrack = null!;
    Border viewThumb = null!;
    TranslateTransform viewThumbOffset = null!;
    Storyboard? viewThumbAnimation;
    int shownView = -1;
    ProgressRing? refreshSpinner;

    Border CreateViewSelector()
    {
        monthButton.Content = I18n.T("本月");
        var buttons = new[] { todayButton, recentButton, monthButton };
        viewThumbWidths = buttons.Select(button =>
        {
            var measure = new TextBlock { Text = button.Content?.ToString() ?? "", FontSize = 13,
                FontFamily = button.FontFamily, FontWeight = button.FontWeight };
            measure.Measure(new Windows.Foundation.Size(double.PositiveInfinity, double.PositiveInfinity));
            return Math.Max(46, Math.Ceiling(measure.DesiredSize.Width) + 30);
        }).ToArray();
        viewSlotWidths = viewThumbWidths.Select(width => Math.Max(MinimumViewSlotWidth, width + 8)).ToArray();
        viewThumbOffset = new TranslateTransform();
        viewThumb = new Border
        {
            Width = viewThumbWidths[0], Height = 46, CornerRadius = new CornerRadius(23),
            HorizontalAlignment = HorizontalAlignment.Left,
            VerticalAlignment = VerticalAlignment.Center,
            RenderTransform = viewThumbOffset,
            IsHitTestVisible = false
        };
        var content = new Grid();
        content.Children.Add(viewThumb);
        var labels = new Grid();
        for (int i = 0; i < buttons.Length; i++) labels.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(viewSlotWidths[i]) });
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
            Width = viewSlotWidths.Sum(), Height = 50, CornerRadius = new CornerRadius(25),
            BorderThickness = new Thickness(1), Child = content
        };
        return viewTrack;
    }

    double ViewThumbTarget(int position) => viewSlotWidths.Take(position).Sum() +
        (viewSlotWidths[position] - viewThumbWidths[position]) / 2;

    void UpdateViewSelector(bool animate = false)
    {
        int position = recentOverview ? 1 : calendar.Visibility == Visibility.Visible ? 2 : 0;
        if (shownView != position)
        {
            shownView = position;
            double target = ViewThumbTarget(position);
            double start = viewThumbOffset.X;
            double startWidth = viewThumb.Width;
            viewThumbAnimation?.Stop();
            // Keep the underlying value at the destination so the last animation frame cannot flash at the old slot.
            viewThumbOffset.X = target;
            viewThumb.Width = viewThumbWidths[position];
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
                var resize = new DoubleAnimation
                {
                    From = startWidth, To = viewThumbWidths[position],
                    Duration = slide.Duration, FillBehavior = FillBehavior.Stop,
                    EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut }
                };
                Storyboard.SetTarget(resize, viewThumb);
                Storyboard.SetTargetProperty(resize, nameof(FrameworkElement.Width));
                var storyboard = new Storyboard();
                storyboard.Children.Add(slide);
                storyboard.Children.Add(resize);
                viewThumbAnimation = storyboard;
                storyboard.Completed += (_, _) =>
                {
                    if (!ReferenceEquals(viewThumbAnimation, storyboard)) return;
                    viewThumbOffset.X = target;
                    viewThumb.Width = viewThumbWidths[position];
                    viewThumbAnimation = null;
                };
                storyboard.Begin();
            }
        }
        viewTrack.Background = Tint(90, palette.Card);
        viewTrack.BorderBrush = Tint(55, palette.Text);
        viewThumb.Background = Brush(palette.Accent);
        var buttons = new[] { todayButton, recentButton, monthButton };
        string[] names = [I18n.T("今日"), I18n.T("近期日程：今天及未来七天"), I18n.T("本月日程")];
        for (int i = 0; i < buttons.Length; i++)
        {
            buttons[i].Foreground = Brush(i == position ? palette.OnAccent : palette.Text);
            AutomationProperties.SetName(buttons[i], i == position ? names[i] + I18n.T("，当前视图") : names[i]);
        }
    }

    void SetRefreshBusy(bool busy)
    {
        refreshSpinner ??= new ProgressRing { Width = 16, Height = 16 };
        refreshSpinner.IsActive = busy;
        refresh.Content = busy ? refreshSpinner : I18n.T("刷新");
        AutomationProperties.SetName(refresh, busy ? I18n.T("正在刷新日历") : I18n.T("刷新日历"));
        ToolTipService.SetToolTip(refresh, busy ? I18n.T("正在读取日历") : I18n.T("刷新当前日历"));
    }
}
