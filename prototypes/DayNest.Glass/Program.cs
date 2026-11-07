using System.Diagnostics;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Automation;
namespace DayNest.Glass;
internal static class Program {
 // Keep the managed window, callbacks and custom backdrop alive for the message loop.
 static CalendarApp? currentApp;
 [STAThread] static int Main() {
  var args=Environment.GetCommandLineArgs();
  if(args.Contains("--self-test")){
   try{PrototypeChecks.Run();return 0;}
   catch(Exception error){File.WriteAllText(Path.Combine(AppContext.BaseDirectory,"self-test.txt"),"FAIL: "+error);return 1;}
  }
  if(args.Contains("--instance-probe"))return InstanceChecks.RunProbe(args);
  if(args.Contains("--features-check")&&!InstanceChecks.IsWindowCheck)return 2;
  bool demo=args.Contains("--demo");
  var selectedLanguage = args.Contains("--i18n-check-ja") ? "ja-JP" : args.Contains("--i18n-check") ? "en-US" :
   InstanceChecks.IsWindowCheck || demo ? "zh-CN" : PreviewSettings.Load().Language;
  I18n.Language = selectedLanguage is "en-US" or "ja-JP" ? selectedLanguage : "zh-CN";
  System.Globalization.CultureInfo.DefaultThreadCurrentCulture = I18n.Culture;
  System.Globalization.CultureInfo.CurrentCulture = I18n.Culture;
  SingleInstance? instance;
  try { instance=SingleInstance.RegisterOrRedirect(args.Contains("--normal-window"),
   demo ? "9725f7f6-71f5-444c-9d3a-1ad58aca4dd0" : InstanceChecks.WindowScope(args)); }
  catch(Exception error) when(error is IOException or UnauthorizedAccessException or System.ComponentModel.Win32Exception or InvalidOperationException) {
   InstanceChecks.StartupFailure(error);return 1;
  }
  if(instance==null)return 0;
  using(instance){
  WinRT.ComWrappersSupport.InitializeComWrappers();
  Application.Start(parameters => {
   SynchronizationContext.SetSynchronizationContext(new Microsoft.UI.Dispatching.DispatcherQueueSynchronizationContext(Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread()));
   currentApp = new CalendarApp();
   instance.SetActivationHandler(currentApp.RequestActivation);
  });
  }
  return 0;
 }
}
sealed record Entry(DateTimeOffset Start, DateTimeOffset End, string Title, string Calendar, bool AllDay, string Notes, string? Handle=null, bool Editable=false, bool Deletable=false, string? PinHandle=null, string? Key=null);
sealed record Pin(string Title, DateTimeOffset Start, string? ActionHandle=null, string? Key=null, string Notes="", Entry? Event=null);
sealed record Result(Entry[]? Events, string? Status, string? Error, Pin[]? Pins,
 bool HasCache=false, bool Configured=false, double SyncedAt=0, string? Warning=null);
public sealed partial class CalendarApp : Application {
 public CalendarApp(){
  UnhandledException+=(_,e)=>{
   try{File.AppendAllText(Path.Combine(AppContext.BaseDirectory,"render-errors.log"),$"{DateTimeOffset.Now:O} HRESULT=0x{e.Exception.HResult:X8}\n{e.Exception}\n");}catch{}
  };
  InitializeComponent();
 }
 Window window=null!;
 readonly StackPanel page=new(){Padding=new Thickness(24),Spacing=16};
 readonly StackPanel agenda=new(){Spacing=10};
 readonly TextBlock status=new(){FontSize=12,Opacity=.7,TextWrapping=TextWrapping.Wrap};
 readonly StackPanel calendar=new(){Spacing=12,Visibility=Visibility.Collapsed};
 readonly Button monthButton=new(){Content=I18n.T("本月日程")};
 bool monthOverview;
 bool recentOverview;
 readonly StackPanel pinned=new(){Spacing=8};
 readonly bool stressMode=Environment.GetCommandLineArgs().Contains("--render-stress");
 readonly bool demoMode=Environment.GetCommandLineArgs().Contains("--demo");
 CancellationTokenSource? requestCancellation;
 ScrollViewer surface=null!;
 readonly GlassBackdrop glass=new();
 Border rim=null!;
 double glassDensity=.42;
 bool dark=true;
 bool glassEnabled=true;
 bool desktopMode=true;
 bool windowActive;
 DesktopWidget? desktopWidget;
 Button exitWidget=null!;
 Grid widgetBar=null!;
 readonly List<Border> dragLines=new();
 readonly Button refresh=new(){Content=I18n.T("刷新")};
 readonly Dictionary<string,Result> months=new();
 readonly HashSet<Process> workers=new();
 DateTime selected=DateTime.Today;
 int generation; bool closed;
 protected override void OnLaunched(LaunchActivatedEventArgs args) {
  ReadAppearance(InstanceChecks.IsWindowCheck || demoMode
   ? new Appearance(Language: I18n.Language)
   : PreviewSettings.Load(),true);
  todayButton.Content=I18n.T("今日");recentButton.Content=I18n.T("近期");refresh.Content=I18n.T("刷新");
  if(Environment.GetCommandLineArgs().Contains("--normal-window"))desktopMode=false;
  if(Environment.GetCommandLineArgs().Contains("--desktop-check"))desktopMode=true;
  window=new Window{Title=I18n.T("DayNest · 分层玻璃日历"),SystemBackdrop=glass};
  window.Activated+=(_,e)=>{windowActive=e.WindowActivationState!=WindowActivationState.Deactivated;glass.SetActive((desktopWidget?.Enabled??desktopMode)||windowActive);};
  window.AppWindow.Closing+=(_,e)=>{if(writeBusy){e.Cancel=true;closeAfterWrite=true;}};
  page.RequestedTheme=ElementTheme.Dark;page.Language=language;
  widgetBar=new Grid{MinHeight=36};widgetBar.ColumnDefinitions.Add(new ColumnDefinition());widgetBar.ColumnDefinitions.Add(new ColumnDefinition{Width=new GridLength(40)});
  var dragRegion=new Grid{Background=Color(0,0,0,0),MinHeight=36};
  var grip=new StackPanel{Spacing=4,Width=24,HorizontalAlignment=HorizontalAlignment.Center,VerticalAlignment=VerticalAlignment.Center,Margin=new Thickness(40,0,0,0),Opacity=.65};
  for(int i=0;i<3;i++){var line=new Border{Height=2,CornerRadius=new CornerRadius(1)};dragLines.Add(line);grip.Children.Add(line);}
  dragRegion.Children.Add(grip);widgetBar.Children.Add(dragRegion);
  AutomationProperties.SetName(dragRegion,I18n.T("拖动窗口"));ToolTipService.SetToolTip(dragRegion,I18n.T("按住顶部横线区域拖动窗口"));
  page.Children.Add(new TextBlock{Text="DayNest",FontSize=30,FontWeight=Microsoft.UI.Text.FontWeights.SemiBold});
  exitWidget=new Button{Content="×",Width=28,Height=28,Padding=new Thickness(0),BorderThickness=new Thickness(0),Background=Color(0,0,0,0),VerticalAlignment=VerticalAlignment.Center,HorizontalAlignment=HorizontalAlignment.Left};
  AutomationProperties.SetName(exitWidget,I18n.T("退出 DayNest"));ToolTipService.SetToolTip(exitWidget,I18n.T("退出 DayNest"));exitWidget.Click+=(_,_)=>window.Close();
  Grid.SetColumn(exitWidget,1);widgetBar.Children.Add(exitWidget);
  var create=new Button{Content=I18n.T("+ 日程"),HorizontalAlignment=HorizontalAlignment.Left};
  create.Click+=async(_,_)=>await ShowNewEvent();
  var settings=new Button{Content=I18n.T("设置"),HorizontalAlignment=HorizontalAlignment.Right};
  var commandRow=new Grid();
  commandRow.ColumnDefinitions.Add(new ColumnDefinition());
  commandRow.ColumnDefinitions.Add(new ColumnDefinition{Width=GridLength.Auto});
  commandRow.Children.Add(create);Grid.SetColumn(settings,1);commandRow.Children.Add(settings);
  page.Children.Add(commandRow);
  var actions=new StackPanel{Orientation=Orientation.Horizontal,Spacing=8};
  ToolTipService.SetToolTip(recentButton,I18n.T("查看今天及未来七天的日程"));
  todayButton.Click+=async(_,_)=>{recentOverview=false;monthOverview=false;calendar.Visibility=Visibility.Collapsed;selected=DateTime.Today;DrawCalendar(true);await Load(false);};
  recentButton.Click+=async(_,_)=>{recentOverview=true;monthOverview=false;calendar.Visibility=Visibility.Collapsed;selected=DateTime.Today;DrawCalendar(true);await Load(false);};
  monthButton.Click+=async(_,_)=>{recentOverview=false;monthOverview=true;calendar.Visibility=Visibility.Visible;selected=DateTime.Today;DrawCalendar(true);await Load(false);};
  settings.Click+=async(_,_)=>await ShowSettings();
  refresh.Click+=async(_,_)=>await Load(true);
  actions.Children.Add(CreateViewSelector());actions.Children.Add(refresh);page.Children.Add(actions);
  UpdateViewSelector();SetRefreshBusy(false);
  page.Children.Add(pinned);page.Children.Add(calendar);page.Children.Add(status);page.Children.Add(agenda);
  surface=new ScrollViewer{Content=page,HorizontalScrollBarVisibility=ScrollBarVisibility.Disabled};
  var layout=new Grid();layout.RowDefinitions.Add(new RowDefinition{Height=GridLength.Auto});layout.RowDefinitions.Add(new RowDefinition());
  layout.Children.Add(widgetBar);Grid.SetRow(surface,1);layout.Children.Add(surface);
  rim=new Border{Child=layout,BorderThickness=new Thickness(1),CornerRadius=new CornerRadius(8)};
  window.Content=rim;
  desktopWidget=new DesktopWidget(window,dragRegion,error=>{desktopMode=false;exitWidget.Visibility=Visibility.Collapsed;status.Text=error;},!DiagnosticMode);
  ApplyAppearance();
  window.AppWindow.Resize(new Windows.Graphics.SizeInt32(440,800));
  if(!InstanceChecks.IsWindowCheck && !demoMode)desktopWidget.RestorePosition();
  window.Closed+=(_,_)=>{desktopWidget?.Dispose();closed=true;StopCalendarLoading();foreach(var p in workers.ToArray())try{if(!p.HasExited)p.Kill(true);}catch{}};
  if(InstanceChecks.IsWindowCheck)PrepareCalendarFlowCheck();
  if(Environment.GetCommandLineArgs().Contains("--calendar-flow-check"))PrepareCalendarFlowCheck();
  if(demoMode)PrepareDemoData();
  window.Activate(); StartCalendarLoading();
  if(Environment.GetCommandLineArgs().Contains("--calendar-flow-check"))RunCalendarFlowCheck();
  if(stressMode)RunRenderStress();
  if(Environment.GetCommandLineArgs().Contains("--desktop-check"))RunDesktopCheck();
  CompleteInstanceStartup();
  if(Environment.GetCommandLineArgs().Contains("--features-check"))RunFeaturesCheck();
 }
 async void RunRenderStress(){
  var origin=window.AppWindow.Position;
  try{
   for(int i=0;i<60&&!closed;i++){
    window.AppWindow.Move(new Windows.Graphics.PointInt32(origin.X+(i%6)*12,origin.Y+(i%4)*8));
    window.AppWindow.Resize(new Windows.Graphics.SizeInt32(440+(i%3)*10,800+(i%2)*12));
    themeId=Themes.All[i%Themes.All.Length].Id;glassEnabled=i%3!=0;glassDensity=.15+(i%6)*.13;ApplyAppearance();
    GC.Collect();GC.WaitForPendingFinalizers();GC.Collect();
    await Task.Delay(150);
   }
   if(!closed){
    window.AppWindow.Move(origin);window.AppWindow.Resize(new Windows.Graphics.SizeInt32(440,800));
    themeId="midnight";glassEnabled=true;glassDensity=.42;ApplyAppearance();
    File.WriteAllText(Path.Combine(AppContext.BaseDirectory,"render-stress.txt"),"PASS: 60 move/resize/theme/material cycles with forced GC");
    window.Close();
   }
  }catch(Exception e){
   File.WriteAllText(Path.Combine(AppContext.BaseDirectory,"render-stress.txt"),e.ToString());
   throw;
  }
 }
 static SolidColorBrush Color(byte a,byte r,byte g,byte b)=>new(Windows.UI.Color.FromArgb(a,r,g,b));
 void ApplyAppearance(){
  palette=Themes.Get(themeId,accentColor);dark=palette.Preset.Dark;ApplyThemeResources();
  // The root theme also drives SystemBackdrop; a child-only theme leaves light glass behind white text.
  surface.RequestedTheme=page.RequestedTheme=dark?ElementTheme.Dark:ElementTheme.Light;
  rim.RequestedTheme=surface.RequestedTheme;
  // Keep a stable popup host while editing; apply title bar/frame changes
  // after the ContentDialog has closed.
  if(!settingsOpen&&!detailsOpen){
   desktopWidget?.SetEnabled(desktopMode);
   desktopMode=desktopWidget?.Enabled??desktopMode;
  }
  bool actualDesktop=desktopWidget?.Enabled??desktopMode;
  widgetBar.Visibility=actualDesktop?Visibility.Visible:Visibility.Collapsed;
  page.Padding=new Thickness(24,actualDesktop?8:24,24,24);
  foreach(var line in dragLines)line.Background=Brush(palette.Text);
  exitWidget.Visibility=actualDesktop?Visibility.Visible:Visibility.Collapsed;
  glass.SetActive(actualDesktop||windowActive);
  window.SystemBackdrop=glassEnabled?glass:null;
  UpdateMaterial();
  surface.Foreground=Brush(palette.Text);
  glass.Update(dark,glassDensity,palette.Background);
  var highlight=new LinearGradientBrush{StartPoint=new Windows.Foundation.Point(0,0),EndPoint=new Windows.Foundation.Point(1,1)};
  highlight.GradientStops.Add(new GradientStop{Offset=0,Color=Windows.UI.Color.FromArgb(dark?(byte)100:(byte)230,255,255,255)});
  highlight.GradientStops.Add(new GradientStop{Offset=.45,Color=Windows.UI.Color.FromArgb(22,255,255,255)});
  highlight.GradientStops.Add(new GradientStop{Offset=1,Color=Windows.UI.Color.FromArgb(dark?(byte)60:(byte)140,255,255,255)});
  rim.BorderBrush=highlight;
  if(months.TryGetValue(selected.ToString("yyyy-MM"),out var visible))Render(visible);else DrawCalendar();
 }
 void UpdateMaterial(){
  glass.Update(dark,glassDensity,palette.Background);
  // A thin luminance veil protects contrast on white wallpaper without hiding the blur.
  if(glassEnabled&&GlassBackdrop.IsSupported){
   var veil=new LinearGradientBrush{StartPoint=new Windows.Foundation.Point(0,0),EndPoint=new Windows.Foundation.Point(0,1)};
   veil.GradientStops.Add(new GradientStop{Offset=0,Color=Tint((byte)(glassDensity*150),palette.Background).Color});
   veil.GradientStops.Add(new GradientStop{Offset=1,Color=Tint((byte)(glassDensity*200),palette.Background).Color});
   rim.Background=veil;
  }else rim.Background=Brush(palette.Background);
  surface.Background=Color(0,0,0,0);
 }
 void DrawCalendar(bool animateSelection=false){
  UpdateViewSelector(animateSelection);
  if(calendar.Visibility!=Visibility.Visible)return;
  calendar.Children.Clear();
  var heading=new Grid();heading.ColumnDefinitions.Add(new ColumnDefinition());heading.ColumnDefinitions.Add(new ColumnDefinition{Width=GridLength.Auto});
  heading.Children.Add(new TextBlock{Text=selected.ToString(I18n.T("yyyy 年 M 月")),FontSize=20,VerticalAlignment=VerticalAlignment.Center});
  var navigation=new StackPanel{Orientation=Orientation.Horizontal,Spacing=6};
  foreach(int delta in new[]{-1,1}){
   var arrow=new Button{Content=delta<0?"‹":"›",Width=36,Padding=new Thickness(0)};
   arrow.Click+=async(_,_)=>{recentOverview=false;monthOverview=true;selected=new DateTime(selected.Year,selected.Month,1).AddMonths(delta);DrawCalendar(true);await Load(false);};
   navigation.Children.Add(arrow);
  }
  Grid.SetColumn(navigation,1);heading.Children.Add(navigation);calendar.Children.Add(heading);
  var grid=new Grid{RowSpacing=4,ColumnSpacing=3};
  for(int c=0;c<7;c++)grid.ColumnDefinitions.Add(new ColumnDefinition());
  for(int r=0;r<7;r++)grid.RowDefinitions.Add(new RowDefinition{Height=new GridLength(40)});
  string[] days={I18n.T("一"),I18n.T("二"),I18n.T("三"),I18n.T("四"),I18n.T("五"),I18n.T("六"),I18n.T("日")};
  if(I18n.Language=="ja-JP")days=[days[6],days[0],days[1],days[2],days[3],days[4],days[5]];
  for(int c=0;c<7;c++){var label=new TextBlock{Text=days[c],Opacity=.7,HorizontalAlignment=HorizontalAlignment.Center,VerticalAlignment=VerticalAlignment.Center};Grid.SetColumn(label,c);grid.Children.Add(label);}
  var first=new DateTime(selected.Year,selected.Month,1);
  int firstDayOfWeek=I18n.Language=="ja-JP"?(int)DayOfWeek.Sunday:(int)DayOfWeek.Monday;
  var start=first.AddDays(-(((int)first.DayOfWeek-firstDayOfWeek+7)%7));
  for(int i=0;i<42;i++){
   var date=start.AddDays(i);bool chosen=date==selected;
   var dayEvents=MonthIndex(date.ToString("yyyy-MM")).On(date).Count;
   var dayContent=new StackPanel{Spacing=0,HorizontalAlignment=HorizontalAlignment.Center};
   dayContent.Children.Add(new TextBlock{Text=date.Day.ToString(),HorizontalAlignment=HorizontalAlignment.Center});
   dayContent.Children.Add(new TextBlock{Text=dayEvents>0?"•":"",FontSize=10,Height=8,HorizontalAlignment=HorizontalAlignment.Center});
   var button=new Button{Content=dayContent,HorizontalAlignment=HorizontalAlignment.Stretch,VerticalAlignment=VerticalAlignment.Stretch,Padding=new Thickness(0),CornerRadius=new CornerRadius(10),
    Background=chosen?Brush(palette.Accent):Color(0,0,0,0),
    Foreground=Brush(chosen?palette.OnAccent:palette.Text),
    BorderBrush=date==DateTime.Today?Brush(palette.AccentInk):Color(0,0,0,0),BorderThickness=new Thickness(date==DateTime.Today?1:0),Opacity=date.Month==selected.Month?1:.4};
   var dayName=I18n.T($"{date:yyyy-MM-dd} · {dayEvents} 项日程");
   ToolTipService.SetToolTip(button,dayName);AutomationProperties.SetName(button,dayName);
   button.Click+=async(_,_)=>{recentOverview=false;monthOverview=false;selected=date;DrawCalendar(true);await Load(false);};
   Grid.SetColumn(button,i%7);Grid.SetRow(button,i/7+1);grid.Children.Add(button);
  }
  calendar.Children.Add(grid);
 }
 static string Repo(){var d=new DirectoryInfo(AppContext.BaseDirectory);while(d!=null){if(File.Exists(Path.Combine(d.FullName,"daynest.py")))return d.FullName;d=d.Parent;}throw new DirectoryNotFoundException();}
 internal static bool OccursOn(Entry e,DateTime day)=>e.Start.LocalDateTime.Date<=day.Date&&(e.End>e.Start?e.End.LocalDateTime>day.Date:e.Start.LocalDateTime.Date==day.Date);
 internal static bool OccursInMonth(Entry e,DateTime month){var start=new DateTime(month.Year,month.Month,1);return e.Start.LocalDateTime<start.AddMonths(1)&&(e.End>e.Start?e.End.LocalDateTime>start:e.Start.LocalDateTime>=start);}
 void Render(Result data){
  DrawCalendar();RenderPins(data.Pins??[]);
  agenda.Children.Clear();status.Text=string.Join(" · ",new[]{data.Status,data.Warning,startupNotice}.Where(s=>!string.IsNullOrWhiteSpace(s)));
  if(recentOverview){RenderRecent();return;}
  agenda.Children.Add(new TextBlock{Text=selected.ToString(monthOverview?I18n.T("yyyy 年 M 月日程"):I18n.T("M 月 d 日")),FontSize=22});
  IReadOnlyList<Entry> entries=monthOverview?(data.Events??[]).Where(e=>OccursInMonth(e,selected)).ToArray():MonthIndex(selected.ToString("yyyy-MM")).On(selected);
  foreach(var e in entries)agenda.Children.Add(EventCard(e,monthOverview));
  if(entries.Count==0)agenda.Children.Add(new TextBlock{Text=data.HasCache?(monthOverview?I18n.T("本月暂无日程"):I18n.T("当天暂无日程")):I18n.T("暂无完整缓存，联网同步后显示日程"),Opacity=.65});
 }
}
