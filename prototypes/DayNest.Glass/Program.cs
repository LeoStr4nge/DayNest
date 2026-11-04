using System.Diagnostics;
using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Automation;
namespace DayNest.Glass;
internal static class Program {
 // Keep the managed window, callbacks and custom backdrop alive for the message loop.
 static CalendarApp? currentApp;
 [STAThread] static void Main() {
  if(Environment.GetCommandLineArgs().Contains("--self-test")){PrototypeChecks.Run();return;}
  WinRT.ComWrappersSupport.InitializeComWrappers();
  Application.Start(parameters => {
   SynchronizationContext.SetSynchronizationContext(new Microsoft.UI.Dispatching.DispatcherQueueSynchronizationContext(Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread()));
   currentApp = new CalendarApp();
  });
 }
}
sealed record Entry(DateTimeOffset Start, DateTimeOffset End, string Title, string Calendar, bool AllDay, string Notes, string? Handle=null, bool Editable=false, bool Deletable=false, string? PinHandle=null, string? Key=null);
sealed record Pin(string Title, DateTimeOffset Start, string? ActionHandle=null, string? Key=null);
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
 readonly Button monthButton=new(){Content="本月日程"};
 bool monthOverview;
 readonly StackPanel pinned=new(){Spacing=8};
 readonly bool stressMode=Environment.GetCommandLineArgs().Contains("--render-stress");
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
 readonly Button refresh=new(){Content="刷新"};
 readonly Dictionary<string,Result> months=new();
 readonly HashSet<Process> workers=new();
 DateTime selected=DateTime.Today;
 int generation; bool closed;
 protected override void OnLaunched(LaunchActivatedEventArgs args) {
  var saved=PreviewSettings.Load();dark=saved.Dark;glassDensity=saved.Density;glassEnabled=saved.Glass;desktopMode=saved.Desktop;
  if(Environment.GetCommandLineArgs().Contains("--normal-window"))desktopMode=false;
  if(Environment.GetCommandLineArgs().Contains("--desktop-check"))desktopMode=true;
  window=new Window{Title="DayNest · 分层玻璃日历",SystemBackdrop=glass};
  window.Activated+=(_,e)=>{windowActive=e.WindowActivationState!=WindowActivationState.Deactivated;glass.SetActive(desktopMode||windowActive);};
  window.AppWindow.Closing+=(_,e)=>{if(writeBusy){e.Cancel=true;closeAfterWrite=true;}};
  page.RequestedTheme=ElementTheme.Dark;
  var header=new Grid();header.ColumnDefinitions.Add(new ColumnDefinition());header.ColumnDefinitions.Add(new ColumnDefinition{Width=GridLength.Auto});
  var dragRegion=new Grid{Background=Color(0,0,0,0),MinHeight=44};
  dragRegion.Children.Add(new TextBlock{Text="DayNest",FontSize=30,FontWeight=Microsoft.UI.Text.FontWeights.SemiBold});header.Children.Add(dragRegion);
  exitWidget=new Button{Content="×",Width=32,Height=32,Padding=new Thickness(0),VerticalAlignment=VerticalAlignment.Center};
  AutomationProperties.SetName(exitWidget,"退出 DayNest");ToolTipService.SetToolTip(exitWidget,"退出 DayNest");exitWidget.Click+=(_,_)=>window.Close();
  Grid.SetColumn(exitWidget,1);header.Children.Add(exitWidget);page.Children.Add(header);
  var create=new Button{Content="+ 日程",HorizontalAlignment=HorizontalAlignment.Left};
  create.Click+=async(_,_)=>await ShowNewEvent();page.Children.Add(create);
  var actions=new StackPanel{Orientation=Orientation.Horizontal,Spacing=8};
  var today=new Button{Content="今日"}; var settings=new Button{Content="设置"};
  today.Click+=async(_,_)=>{monthOverview=false;calendar.Visibility=Visibility.Collapsed;selected=DateTime.Today;DrawCalendar();await Load(false);};
  monthButton.Click+=async(_,_)=>{monthOverview=true;calendar.Visibility=Visibility.Visible;selected=DateTime.Today;DrawCalendar();await Load(false);};
  settings.Click+=async(_,_)=>await ShowSettings();
  refresh.Click+=async(_,_)=>await Load(true);
  actions.Children.Add(today);actions.Children.Add(monthButton);actions.Children.Add(refresh);actions.Children.Add(settings);page.Children.Add(actions);
  page.Children.Add(pinned);page.Children.Add(calendar);page.Children.Add(status);page.Children.Add(agenda);
  surface=new ScrollViewer{Content=page,HorizontalScrollBarVisibility=ScrollBarVisibility.Disabled};
  rim=new Border{Child=surface,BorderThickness=new Thickness(1),CornerRadius=new CornerRadius(8)};
  window.Content=rim;
  desktopWidget=new DesktopWidget(window,dragRegion,error=>{desktopMode=false;exitWidget.Visibility=Visibility.Collapsed;status.Text=error;},!stressMode&&!Environment.GetCommandLineArgs().Any(a=>a is "--desktop-check" or "--calendar-flow-check"));
  ApplyAppearance();
  window.AppWindow.Resize(new Windows.Graphics.SizeInt32(440,800));
  desktopWidget.RestorePosition();
  window.Closed+=(_,_)=>{desktopWidget?.Dispose();closed=true;StopCalendarLoading();foreach(var p in workers.ToArray())try{if(!p.HasExited)p.Kill(true);}catch{}};
  if(Environment.GetCommandLineArgs().Contains("--calendar-flow-check"))PrepareCalendarFlowCheck();
  window.Activate(); StartCalendarLoading();
  if(Environment.GetCommandLineArgs().Contains("--calendar-flow-check"))RunCalendarFlowCheck();
  if(stressMode)RunRenderStress();
  if(Environment.GetCommandLineArgs().Contains("--desktop-check"))RunDesktopCheck();
 }
 async void RunRenderStress(){
  var origin=window.AppWindow.Position;
  try{
   for(int i=0;i<60&&!closed;i++){
    window.AppWindow.Move(new Windows.Graphics.PointInt32(origin.X+(i%6)*12,origin.Y+(i%4)*8));
    window.AppWindow.Resize(new Windows.Graphics.SizeInt32(440+(i%3)*10,800+(i%2)*12));
    dark=i%2==0;glassEnabled=i%3!=0;glassDensity=.15+(i%6)*.13;ApplyAppearance();
    GC.Collect();GC.WaitForPendingFinalizers();GC.Collect();
    await Task.Delay(150);
   }
   if(!closed){
    window.AppWindow.Move(origin);window.AppWindow.Resize(new Windows.Graphics.SizeInt32(440,800));
    dark=true;glassEnabled=true;glassDensity=.42;ApplyAppearance();
    File.WriteAllText(Path.Combine(AppContext.BaseDirectory,"render-stress.txt"),"PASS: 60 move/resize/theme/material cycles with forced GC");
   }
  }catch(Exception e){
   File.WriteAllText(Path.Combine(AppContext.BaseDirectory,"render-stress.txt"),e.ToString());
   throw;
  }
 }
 static SolidColorBrush Color(byte a,byte r,byte g,byte b)=>new(Windows.UI.Color.FromArgb(a,r,g,b));
 void ApplyAppearance(){
  // The root theme also drives SystemBackdrop; a child-only theme leaves light glass behind white text.
  surface.RequestedTheme=page.RequestedTheme=dark?ElementTheme.Dark:ElementTheme.Light;
  rim.RequestedTheme=surface.RequestedTheme;
  desktopWidget?.SetEnabled(desktopMode);
  desktopMode=desktopWidget?.Enabled??desktopMode;
  exitWidget.Visibility=desktopMode?Visibility.Visible:Visibility.Collapsed;
  glass.SetActive(desktopMode||windowActive);
  window.SystemBackdrop=glassEnabled?glass:null;
  UpdateMaterial();
  surface.Foreground=dark?Color(255,238,243,250):Color(255,28,39,55);
  glass.Update(dark,glassDensity);
  var highlight=new LinearGradientBrush{StartPoint=new Windows.Foundation.Point(0,0),EndPoint=new Windows.Foundation.Point(1,1)};
  highlight.GradientStops.Add(new GradientStop{Offset=0,Color=Windows.UI.Color.FromArgb(dark?(byte)100:(byte)230,255,255,255)});
  highlight.GradientStops.Add(new GradientStop{Offset=.45,Color=Windows.UI.Color.FromArgb(22,255,255,255)});
  highlight.GradientStops.Add(new GradientStop{Offset=1,Color=Windows.UI.Color.FromArgb(dark?(byte)60:(byte)140,255,255,255)});
  rim.BorderBrush=highlight;
  DrawCalendar();
 }
 void UpdateMaterial(){
  glass.Update(dark,glassDensity);
  // A thin luminance veil protects contrast on white wallpaper without hiding the blur.
  if(glassEnabled&&GlassBackdrop.IsSupported){
   var veil=new LinearGradientBrush{StartPoint=new Windows.Foundation.Point(0,0),EndPoint=new Windows.Foundation.Point(0,1)};
   veil.GradientStops.Add(new GradientStop{Offset=0,Color=dark?Windows.UI.Color.FromArgb((byte)(glassDensity*150),14,20,30):Windows.UI.Color.FromArgb((byte)(glassDensity*140),250,251,255)});
   veil.GradientStops.Add(new GradientStop{Offset=1,Color=dark?Windows.UI.Color.FromArgb((byte)(glassDensity*200),14,20,30):Windows.UI.Color.FromArgb((byte)(glassDensity*210),250,251,255)});
   surface.Background=veil;
  }else surface.Background=dark?Color(255,28,31,38):Color(255,242,244,248);
 }
 void DrawCalendar(){
  calendar.Children.Clear();
  var heading=new Grid();heading.ColumnDefinitions.Add(new ColumnDefinition());heading.ColumnDefinitions.Add(new ColumnDefinition{Width=GridLength.Auto});
  heading.Children.Add(new TextBlock{Text=selected.ToString("yyyy 年 M 月"),FontSize=20,VerticalAlignment=VerticalAlignment.Center});
  var navigation=new StackPanel{Orientation=Orientation.Horizontal,Spacing=6};
  foreach(int delta in new[]{-1,1}){
   var arrow=new Button{Content=delta<0?"‹":"›",Width=36,Padding=new Thickness(0)};
   arrow.Click+=async(_,_)=>{monthOverview=true;selected=new DateTime(selected.Year,selected.Month,1).AddMonths(delta);DrawCalendar();await Load(false);};
   navigation.Children.Add(arrow);
  }
  Grid.SetColumn(navigation,1);heading.Children.Add(navigation);calendar.Children.Add(heading);
  var grid=new Grid{RowSpacing=4,ColumnSpacing=3};
  for(int c=0;c<7;c++)grid.ColumnDefinitions.Add(new ColumnDefinition());
  for(int r=0;r<7;r++)grid.RowDefinitions.Add(new RowDefinition{Height=new GridLength(40)});
  string[] days={"一","二","三","四","五","六","日"};
  for(int c=0;c<7;c++){var label=new TextBlock{Text=days[c],Opacity=.7,HorizontalAlignment=HorizontalAlignment.Center,VerticalAlignment=VerticalAlignment.Center};Grid.SetColumn(label,c);grid.Children.Add(label);}
  var first=new DateTime(selected.Year,selected.Month,1);var start=first.AddDays(-((int)first.DayOfWeek+6)%7);
  for(int i=0;i<42;i++){
   var date=start.AddDays(i);bool chosen=date==selected;
   var dayEvents=months.TryGetValue(date.ToString("yyyy-MM"),out var dayData)?(dayData.Events??[]).Count(e=>OccursOn(e,date)):0;
   var dayContent=new StackPanel{Spacing=0,HorizontalAlignment=HorizontalAlignment.Center};
   dayContent.Children.Add(new TextBlock{Text=date.Day.ToString(),HorizontalAlignment=HorizontalAlignment.Center});
   dayContent.Children.Add(new TextBlock{Text=dayEvents>0?"•":"",FontSize=10,Height=8,HorizontalAlignment=HorizontalAlignment.Center});
   var button=new Button{Content=dayContent,HorizontalAlignment=HorizontalAlignment.Stretch,VerticalAlignment=VerticalAlignment.Stretch,Padding=new Thickness(0),CornerRadius=new CornerRadius(10),
    Background=chosen?Color(255,64,126,205):Color(0,0,0,0),
    Foreground=chosen?Color(255,255,255,255):dark?Color(255,238,243,250):Color(255,28,39,55),
    BorderBrush=date==DateTime.Today?Color(255,108,166,239):Color(0,0,0,0),BorderThickness=new Thickness(date==DateTime.Today?1:0),Opacity=date.Month==selected.Month?1:.4};
   var dayName=$"{date:yyyy-MM-dd} · {dayEvents} 项日程";
   ToolTipService.SetToolTip(button,dayName);AutomationProperties.SetName(button,dayName);
   button.Click+=async(_,_)=>{monthOverview=false;selected=date;DrawCalendar();await Load(false);};
   Grid.SetColumn(button,i%7);Grid.SetRow(button,i/7+1);grid.Children.Add(button);
  }
  calendar.Children.Add(grid);
 }
 static string Repo(){var d=new DirectoryInfo(AppContext.BaseDirectory);while(d!=null){if(File.Exists(Path.Combine(d.FullName,"daynest.py")))return d.FullName;d=d.Parent;}throw new DirectoryNotFoundException();}
 internal static bool OccursOn(Entry e,DateTime day)=>e.Start.LocalDateTime.Date<=day.Date&&(e.End>e.Start?e.End.LocalDateTime>day.Date:e.Start.LocalDateTime.Date==day.Date);
 internal static bool OccursInMonth(Entry e,DateTime month){var start=new DateTime(month.Year,month.Month,1);return e.Start.LocalDateTime<start.AddMonths(1)&&(e.End>e.Start?e.End.LocalDateTime>start:e.Start.LocalDateTime>=start);}
 void Render(Result data){
  DrawCalendar();RenderPins(data.Pins??[]);
  agenda.Children.Clear();status.Text=string.Join(" · ",new[]{data.Status,data.Warning}.Where(s=>!string.IsNullOrWhiteSpace(s)));
  agenda.Children.Add(new TextBlock{Text=selected.ToString(monthOverview?"yyyy 年 M 月日程":"M 月 d 日"),FontSize=22});
  var entries=(data.Events??[]).Where(e=>monthOverview?OccursInMonth(e,selected):OccursOn(e,selected)).ToArray();
  foreach(var e in entries){
   var content=new StackPanel{Spacing=6};
   var when=monthOverview?e.Start.LocalDateTime.ToString("M月d日 "):"";
   content.Children.Add(new TextBlock{Text=$"{when}{(e.AllDay?"全天":e.Start.LocalDateTime.ToString("HH:mm"))}  {e.Title}",FontSize=17,TextWrapping=TextWrapping.Wrap});
   content.Children.Add(new TextBlock{Text=e.Calendar,FontSize=12,Opacity=.65});
   if(!string.IsNullOrWhiteSpace(e.Notes))content.Children.Add(new TextBlock{Text=string.Join(" ",e.Notes.Split((char[]?)null,StringSplitOptions.RemoveEmptyEntries)),TextWrapping=TextWrapping.NoWrap,TextTrimming=TextTrimming.CharacterEllipsis,MaxLines=1,Opacity=.8});
   var card=new Button{Content=content,HorizontalAlignment=HorizontalAlignment.Stretch,HorizontalContentAlignment=HorizontalAlignment.Stretch,Padding=new Thickness(14),CornerRadius=new CornerRadius(12),Background=new SolidColorBrush(Windows.UI.Color.FromArgb(18,128,128,128))};
   AutomationProperties.SetName(card,$"查看日程：{e.Title}");
   card.Click+=async(_,_)=>await ShowEventDetails(e);
   agenda.Children.Add(card);
  }
  if(entries.Length==0)agenda.Children.Add(new TextBlock{Text=data.HasCache?(monthOverview?"本月暂无日程":"当天暂无日程"):"暂无完整缓存，联网同步后显示日程",Opacity=.65});
 }
}
