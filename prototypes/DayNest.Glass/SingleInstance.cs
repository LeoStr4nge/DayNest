using System.Diagnostics;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace DayNest.Glass;

// The WinUI lifetime lock is separate from Python's short-lived write lock.
// Hold the named object until Application.Start returns; no thread ownership
// is needed, and Windows releases it even if the process crashes.
sealed class SingleInstance : IDisposable
{
    readonly Mutex lifetime;
    readonly string pipeName;
    readonly CancellationTokenSource stop = new();
    readonly object gate = new();
    readonly Task listener;
    Func<bool, bool>? activation;
    bool pending, pendingNormal;

    static string Key(string? testScope)
    {
        using var identity = WindowsIdentity.GetCurrent();
        using var process = Process.GetCurrentProcess();
        string user = identity.User?.Value ?? throw new InvalidOperationException(I18n.T("无法读取 Windows 用户身份。"));
        string hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(user)))[..16];
        string prefix = testScope == null ? "DayNest.Glass" : "DayNest.Glass.Check." + Guid.Parse(testScope).ToString("N");
        return prefix + "." + hash + "." + process.SessionId;
    }

    SingleInstance(Mutex lifetime, string name)
    {
        this.lifetime = lifetime; pipeName = name;
        // Create the first server synchronously: startup fails closed if the
        // private activation channel cannot be opened.
        var server = NewServer();
        listener = Listen(server);
    }

    public static bool TryRegister(out SingleInstance? instance, string? testScope = null)
    {
        string key = Key(testScope);
        var mutex = new Mutex(false, "Local\\" + key, out bool created);
        if (!created) { mutex.Dispose(); instance = null; return false; }
        try { instance = new SingleInstance(mutex, key); return true; }
        catch { mutex.Dispose(); throw; }
    }

    public static SingleInstance? RegisterOrRedirect(bool normalWindow, string? testScope = null)
    {
        if (TryRegister(out var instance, testScope)) return instance;
        if (NotifyExisting(normalWindow, testScope).GetAwaiter().GetResult()) return null;
        // The owner may have exited while the second process was connecting.
        for (int attempt = 0; attempt < 5; attempt++)
        {
            if (TryRegister(out instance, testScope)) return instance;
            Thread.Sleep(100);
        }
        throw new IOException(I18n.T("DayNest 已在运行，但暂时无法显示窗口。请稍后重试。"));
    }

    public void SetActivationHandler(Func<bool, bool> handler)
    {
        bool notify, normal;
        lock (gate)
        {
            activation = handler; notify = pending; normal = pendingNormal;
            pending = pendingNormal = false;
        }
        if (notify) handler(normal);
    }

    bool Deliver(bool normal)
    {
        Func<bool, bool>? handler;
        lock (gate)
        {
            handler = activation;
            if (handler == null) { pending = true; pendingNormal |= normal; return true; }
        }
        try { return handler(normal); }
        catch (Exception error) when (error is COMException or ObjectDisposedException or InvalidOperationException) { return false; }
    }

    NamedPipeServerStream NewServer() => new(pipeName, PipeDirection.InOut, 1,
        PipeTransmissionMode.Byte, PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);

    async Task Listen(NamedPipeServerStream server)
    {
        while (!stop.IsCancellationRequested)
        {
            using (server)
            {
                try
                {
                    await server.WaitForConnectionAsync(stop.Token).ConfigureAwait(false);
                    using var timeout = CancellationTokenSource.CreateLinkedTokenSource(stop.Token);
                    timeout.CancelAfter(TimeSpan.FromSeconds(2));
                    byte[] request = new byte[1];
                    int count = await server.ReadAsync(request, timeout.Token).ConfigureAwait(false);
                    bool accepted = count == 1 && request[0] <= 1 && Deliver(request[0] == 1);
                    await server.WriteAsync(new byte[] { accepted ? (byte)1 : (byte)0 }, timeout.Token).ConfigureAwait(false);
                }
                catch (Exception error) when (error is IOException or OperationCanceledException or UnauthorizedAccessException) { }
            }
            if (stop.IsCancellationRequested) return;
            try { server = NewServer(); }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException) { return; }
        }
    }

    public static async Task<bool> NotifyExisting(bool normalWindow, string? testScope = null)
    {
        try
        {
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5));
            using var client = new NamedPipeClientStream(".", Key(testScope), PipeDirection.InOut,
                PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly);
            await client.ConnectAsync(timeout.Token).ConfigureAwait(false);
            // Transfer the user-initiated launch's foreground permission to
            // the existing process; the UI still respects Windows focus rules.
            if (GetNamedPipeServerProcessId(client.SafePipeHandle, out uint pid)) AllowSetForegroundWindow(pid);
            await client.WriteAsync(new byte[] { normalWindow ? (byte)1 : (byte)0 }, timeout.Token).ConfigureAwait(false);
            byte[] reply = new byte[1];
            return await client.ReadAsync(reply, timeout.Token).ConfigureAwait(false) == 1 && reply[0] == 1;
        }
        catch (Exception error) when (error is IOException or OperationCanceledException or UnauthorizedAccessException) { return false; }
    }

    public void Dispose()
    {
        stop.Cancel();
        try { listener.GetAwaiter().GetResult(); }
        finally { stop.Dispose(); lifetime.Dispose(); }
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)] static extern bool GetNamedPipeServerProcessId(SafePipeHandle pipe, out uint pid);
    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)] static extern bool AllowSetForegroundWindow(uint processId);
}
