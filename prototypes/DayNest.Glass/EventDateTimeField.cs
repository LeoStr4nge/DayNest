using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Automation;

namespace DayNest.Glass;

// Read-only summary until editing is requested; native flyouts handle input.
sealed class EventDateTimeField
{
    public StackPanel View { get; } = new() { Spacing = 6 };
    readonly TextBlock summary = new();
    readonly Grid editor = new() { ColumnSpacing = 10, Visibility = Visibility.Collapsed };
    readonly CalendarDatePicker date;
    readonly Button time;
    readonly TimePickerFlyout timePicker;
    TimeSpan selectedTime;
    public event Action? Changed;
    public bool TimeEnabled
    {
        set => time.IsEnabled = value;
    }

    public EventDateTimeField(string label, DateTime value, bool dateOnly = false)
    {
        date = new CalendarDatePicker { Date = new DateTimeOffset(value), MinWidth = 0, HorizontalAlignment = HorizontalAlignment.Stretch, Language = I18n.Language };
        selectedTime = value.TimeOfDay;
        time = new Button { Content = value.ToString("HH:mm"), Width = 124, HorizontalAlignment = HorizontalAlignment.Stretch };
        timePicker = new TimePickerFlyout { Time = selectedTime, ClockIdentifier = "24HourClock", MinuteIncrement = 1 };
        AutomationProperties.SetName(date, label + I18n.T("日期"));
        AutomationProperties.SetName(time, label + I18n.T("时间"));
        View.Children.Add(new TextBlock { Text = label });
        summary.Text = value.ToString(I18n.T(dateOnly ? "yyyy 年 M 月 d 日" : "yyyy 年 M 月 d 日 HH:mm"));
        View.Children.Add(summary);
        editor.ColumnDefinitions.Add(new ColumnDefinition());
        editor.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        Grid.SetColumn(time, 1); editor.Children.Add(date); editor.Children.Add(time);
        View.Children.Add(editor);
        date.DateChanged += (_, _) => Changed?.Invoke();
        time.Click += (_, _) => { timePicker.Time = selectedTime; timePicker.ShowAt(time); };
        timePicker.TimePicked += (_, args) =>
        {
            selectedTime = args.NewTime; time.Content = selectedTime.ToString(@"hh\:mm");
            Changed?.Invoke();
        };
    }

    public void BeginEdit()
    {
        summary.Visibility = Visibility.Collapsed;
        editor.Visibility = Visibility.Visible;
    }

    public bool TryGetValue(out DateTime value)
    {
        value = default;
        if (date.Date is not { } selectedDate) return false;
        value = DateTime.SpecifyKind(selectedDate.Date + selectedTime, DateTimeKind.Unspecified);
        return true;
    }

    public void SetValue(DateTime value)
    {
        date.Date = new DateTimeOffset(value);
        selectedTime = value.TimeOfDay;
        time.Content = value.ToString("HH:mm");
    }
}
