using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace Paix
{
    // All network input is parsed off the renderer boundary and applied only on Unity's main thread.
    [DefaultExecutionOrder(9000)]
    public sealed class PaixStage : MonoBehaviour
    {
        public string Endpoint = "ws://127.0.0.1:8765";
        public bool Diagnostics = true;
        public CubismDriver Driver;
        readonly ConcurrentQueue<AvatarCommand> commands = new ConcurrentQueue<AvatarCommand>();
        CancellationTokenSource cancellation;
        ClientWebSocket socket;
        AvatarController controller;
        CubismDriver driver;
        volatile bool connected;
        volatile string safeError = "none";
        int queued;
        bool wasConnected;

        void Start()
        {
            driver = Driver != null ? Driver : GetComponent<CubismDriver>() ?? gameObject.AddComponent<CubismDriver>();
            controller = new AvatarController(driver);
            if (!IsLoopback(Endpoint)) { safeError = "invalid_endpoint"; return; }
            cancellation = new CancellationTokenSource();
            _ = ConnectLoop(cancellation.Token);
        }
        public static bool IsLoopback(string endpoint)
        {
            if (!Uri.TryCreate(endpoint, UriKind.Absolute, out var uri) || uri.Scheme != "ws" ||
                uri.UserInfo.Length != 0 || uri.Query.Length != 0 || uri.Fragment.Length != 0) return false;
            return uri.Host == "localhost" || (IPAddress.TryParse(uri.Host.Trim('[', ']'), out var ip) && IPAddress.IsLoopback(ip));
        }
        async Task ConnectLoop(CancellationToken token)
        {
            while (!token.IsCancellationRequested)
            {
                try
                {
                    using (var client = new ClientWebSocket())
                    {
                        socket = client;
                        client.Options.Proxy = null;
                        using (var timeout = CancellationTokenSource.CreateLinkedTokenSource(token))
                        {
                            timeout.CancelAfter(5000);
                            await client.ConnectAsync(new Uri(Endpoint), timeout.Token);
                        }
                        connected = true; safeError = "none";
                        var buffer = new byte[4096];
                        while (client.State == WebSocketState.Open && !token.IsCancellationRequested)
                        {
                            using (var message = new MemoryStream())
                            {
                                WebSocketReceiveResult frame;
                                do
                                {
                                    frame = await client.ReceiveAsync(new ArraySegment<byte>(buffer), token);
                                    if (frame.MessageType != WebSocketMessageType.Text || message.Length + frame.Count > 4096)
                                        throw new InvalidDataException();
                                    message.Write(buffer, 0, frame.Count);
                                } while (!frame.EndOfMessage);
                                if (!AvatarProtocol.TryParse(new UTF8Encoding(false, true).GetString(message.ToArray()), out var command))
                                { safeError = "invalid_event"; continue; }
                                if (Interlocked.Increment(ref queued) > 128)
                                { Interlocked.Decrement(ref queued); throw new InvalidDataException(); }
                                commands.Enqueue(command);
                            }
                        }
                    }
                }
                catch (OperationCanceledException) { safeError = "disconnected"; }
                catch (Exception) { safeError = "connection_failed"; }
                finally { connected = false; socket = null; }
                try { await Task.Delay(1500, token); } catch (OperationCanceledException) { break; }
            }
        }
        void Update()
        {
            if (controller == null) return;
            if (!connected)
            {
                if (wasConnected) controller.Reset();
                while (commands.TryDequeue(out _)) Interlocked.Decrement(ref queued);
            }
            else while (commands.TryDequeue(out var command))
            {
                Interlocked.Decrement(ref queued);
                controller.Apply(command);
            }
            wasConnected = connected;
            controller.Tick(Time.unscaledDeltaTime);
        }
        void OnGUI()
        {
            if (!Diagnostics || controller == null) return;
            // No received text, asset paths, or exception messages are displayed.
            GUI.Box(new Rect(12, 12, 320, 175), "Paix diagnostics");
            GUI.Label(new Rect(24, 38, 296, 140),
                $"Connection: {(connected ? "connected" : "disconnected")}\n" +
                $"State: {controller.State}\n" +
                $"Mouth: {controller.Mouth:F2} | FPS: {1f / Mathf.Max(.001f, Time.unscaledDeltaTime):F0}\n" +
                $"Motion: {driver.MotionStatus} | Expression: {driver.ExpressionStatus}\n" +
                $"Model: {driver.Status}\nError: {safeError}");
        }
        void OnDestroy()
        {
            cancellation?.Cancel();
            socket?.Abort();
            controller?.Reset();
            cancellation?.Dispose();
        }
    }
}
