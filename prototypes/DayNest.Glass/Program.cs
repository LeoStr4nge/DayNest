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
  WinRT.ComWrappersSupport.InitializeComWrappers();
  Application.Start(parameters => {
   SynchronizationContext.SetSynchronizationContext(new Microsoft.UI.Dispatching.DispatcherQueueSynchronizationContext(Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread()));
   currentApp = new CalendarApp();
  });
 }
}
sealed record Entry(DateTimeOffset Start, DateTimeOffset End, string Title, string Calendar, bool AllDay, string Notes);
sealed record Result(Entry[]? Events, string? Status, string? Error);
sealed class CalendarApp : Application {
 public CalendarApp(){
  UnhandledException+=(_,e)=>{
   try{File.AppendAllText(Path.Combine(AppContext.BaseDirectory,"render-errors.log"),$"{DateTimeOffset.Now:O} HRESULT=0x{e.Exception.HResult:X8}\n{e.Exception}\n");}catch{}
  };
 }
 Window window=null!;
 readonly StackPanel page=new(){Padding=new Thickness(24),Spacing=16};
 readonly StackPanel agenda=new(){Spacing=10};
 readonly TextBlock status=new(){FontSize=12,Opacity=.7,TextWrapping=TextWrapping.Wrap};
 readonly StackPanel calendar=new(){Spacing=12};
 ScrollViewer surface=null!;
 readonly GlassBackdrop glass=new();
 Border rim=null!;
 double glassDensity=.42;
 bool dark=true;
 readonly Button refresh=new(){Content="刷新本月"};
 readonly Dictionary<string,Result> months=new();
 readonly HashSet<Process> workers=new();
 DateTime selected=DateTime.Today;
 int generation; bool closed;
 protected override void OnLaunched(LaunchActivatedEventArgs args) {
  window=new Window{Title="DayNest · 分层玻璃日历",SystemBackdrop=glass};
  window.Activated+=(_,e)=>glass.SetActive(e.WindowActivationState!=WindowActivationState.Deactivated);
  page.RequestedTheme=ElementTheme.Dark;
  page.Children.Add(new TextBlock{Text="DayNest",FontSize=30,FontWeight=Microsoft.UI.Text.FontWeights.SemiBold});
  var actions=new StackPanel{Orientation=Orientation.Horizontal,Spacing=8};
  var today=new Button{Content="今天"}; var theme=new Button{Content="浅色 / 深色"};
  today.Click+=async(_,_)=>{selected=DateTime.Today;DrawCalendar();await Load(false);};
  theme.Click+=(_,_)=>{dark=!dark;ApplyAppearance();};
  refresh.Click+=async(_,_)=>await Load(true);
  actions.Children.Add(today);actions.Children.Add(refresh);actions.Children.Add(theme);page.Children.Add(actions);
  var glassControls=new Grid{ColumnSpacing=12};
  glassControls.ColumnDefinitions.Add(new ColumnDefinition{Width=GridLength.Auto});
  glassControls.ColumnDefinitions.Add(new ColumnDefinition());
  var densityLabel=new TextBlock{Text="玻璃浓度 42%",FontSize=12,VerticalAlignment=VerticalAlignment.Center};
  var density=new Slider{Minimum=15,Maximum=80,Value=42,StepFrequency=1,MinWidth=140};
  AutomationProperties.SetName(density,"玻璃浓度");
  density.ValueChanged+=(_,e)=>{glassDensity=e.NewValue/100;densityLabel.Text=$"玻璃浓度 {e.NewValue:0}%";UpdateMaterial();};
  Grid.SetColumn(density,1);glassControls.Children.Add(densityLabel);glassControls.Children.Add(density);page.Children.Add(glassControls);
  page.Children.Add(calendar);page.Children.Add(status);page.Children.Add(agenda);
  surface=new ScrollViewer{Content=page,HorizontalScrollBarVisibility=ScrollBarVisibility.Disabled};
  rim=new Border{Child=surface,BorderThickness=new Thickness(1),CornerRadius=new CornerRadius(8)};
  window.Content=rim;ApplyAppearance();
  window.AppWindow.Resize(new Windows.Graphics.SizeInt32(440,800));
  window.Closed+=(_,_)=>{closed=true;generation++;foreach(var p in workers.ToArray())try{if(!p.HasExited)p.Kill(true);}catch{}};
  window.Activate(); _=Load(false);
  if(Environment.GetCommandLineArgs().Contains("--render-stress"))RunRenderStress();
 }
 async void RunRenderStress(){
  var origin=window.AppWindow.Position;
  try{
   for(int i=0;i<60&&!closed;i++){
    window.AppWindow.Move(new Windows.Graphics.PointInt32(origin.X+(i%6)*12,origin.Y+(i%4)*8));
    window.AppWindow.Resize(new Windows.Graphics.SizeInt32(440+(i%3)*10,800+(i%2)*12));
    dark=i%2==0;glassDensity=.15+(i%6)*.13;ApplyAppearance();
    GC.Collect();GC.WaitForPendingFinalizers();GC.Collect();
    await Task.Delay(150);
   }
   if(!closed){
    window.AppWindow.Move(origin);window.AppWindow.Resize(new Windows.Graphics.SizeInt32(440,800));
    dark=true;glassDensity=.42;ApplyAppearance();
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
  if(GlassBackdrop.IsSupported){
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
   arrow.Click+=async(_,_)=>{selected=new DateTime(selected.Year,selected.Month,1).AddMonths(delta);DrawCalendar();await Load(false);};
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
   var button=new Button{Content=date.Day.ToString(),HorizontalAlignment=HorizontalAlignment.Stretch,VerticalAlignment=VerticalAlignment.Stretch,Padding=new Thickness(0),CornerRadius=new CornerRadius(10),
    Background=chosen?Color(255,64,126,205):Color(0,0,0,0),
    Foreground=chosen?Color(255,255,255,255):dark?Color(255,238,243,250):Color(255,28,39,55),
    BorderBrush=date==DateTime.Today?Color(255,108,166,239):Color(0,0,0,0),BorderThickness=new Thickness(date==DateTime.Today?1:0),Opacity=date.Month==selected.Month?1:.4};
   ToolTipService.SetToolTip(button,date.ToString("yyyy-MM-dd"));
   button.Click+=async(_,_)=>{selected=date;DrawCalendar();await Load(false);};
   Grid.SetColumn(button,i%7);Grid.SetRow(button,i/7+1);grid.Children.Add(button);
  }
  calendar.Children.Add(grid);
 }
 static string Repo(){var d=new DirectoryInfo(AppContext.BaseDirectory);while(d!=null){if(File.Exists(Path.Combine(d.FullName,"daynest.py")))return d.FullName;d=d.Parent;}throw new DirectoryNotFoundException();}
 async Task Load(bool sync){
  var key=selected.ToString("yyyy-MM");int token=++generation;
  if(!sync&&months.TryGetValue(key,out var cached)){refresh.IsEnabled=true;Render(cached);return;}
  refresh.IsEnabled=false;status.Text=sync?"正在同步本月…":"正在读取缓存…";
  try{
   var repo=Repo();var python=Path.Combine(repo,".venv","Scripts","python.exe");if(!File.Exists(python))python="python";
   var info=new ProcessStartInfo(python){UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,WorkingDirectory=repo};
   info.ArgumentList.Add("-B");info.ArgumentList.Add(Path.Combine(repo,"prototypes","DayNest.Glass","calendar_bridge.py"));info.ArgumentList.Add(key);if(sync)info.ArgumentList.Add("--refresh");
   using var p=Process.Start(info)??throw new InvalidOperationException();workers.Add(p);string output;
   try{var stdout=p.StandardOutput.ReadToEndAsync();var stderr=p.StandardError.ReadToEndAsync();using var timeout=new CancellationTokenSource(TimeSpan.FromMinutes(2));
    try{await p.WaitForExitAsync(timeout.Token);}catch{if(!p.HasExited)p.Kill(true);throw;}
    output=await stdout;await stderr;if(p.ExitCode!=0)throw new InvalidOperationException();
   }finally{workers.Remove(p);}
   if(closed||token!=generation)return;
   var result=JsonSerializer.Deserialize<Result>(output,new JsonSerializerOptions{PropertyNameCaseInsensitive=true})??throw new InvalidOperationException();
   if(result.Error!=null){status.Text=result.Error;return;}months[key]=result;Render(result);
  }catch{if(!closed&&token==generation)status.Text="读取失败，请检查 Python 环境或网络。";}
  finally{if(!closed&&token==generation)refresh.IsEnabled=true;}
 }
 void Render(Result data){
  agenda.Children.Clear();status.Text=data.Status;
  agenda.Children.Add(new TextBlock{Text=selected.ToString("M 月 d 日"),FontSize=22});
  var entries=(data.Events??[]).Where(e=>e.Start.LocalDateTime.Date<=selected&&(e.End>e.Start?e.End.LocalDateTime>selected:e.Start.LocalDateTime.Date==selected)).ToArray();
  foreach(var e in entries){
   var content=new StackPanel{Spacing=6};
   content.Children.Add(new TextBlock{Text=$"{(e.AllDay?"全天":e.Start.ToString("HH:mm"))}  {e.Title}",FontSize=17,TextWrapping=TextWrapping.Wrap});
   content.Children.Add(new TextBlock{Text=e.Calendar,FontSize=12,Opacity=.65});
   if(!string.IsNullOrWhiteSpace(e.Notes))content.Children.Add(new TextBlock{Text=e.Notes,TextWrapping=TextWrapping.Wrap});
   agenda.Children.Add(new Border{Child=content,Padding=new Thickness(14),CornerRadius=new CornerRadius(12),Background=new SolidColorBrush(Windows.UI.Color.FromArgb(18,128,128,128))});
  }
  if(entries.Length==0)agenda.Children.Add(new TextBlock{Text="当天暂无日程",Opacity=.65});
 }
}
