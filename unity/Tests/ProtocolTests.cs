using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using Paix;

public static class ProtocolTests
{
    sealed class Driver : IAvatarDriver
    {
        public readonly Dictionary<string, float> Values = new Dictionary<string, float>();
        public void Parameter(string id, float value) { Values[id] = value; }
        public void Motion(string name) { }
        public void Expression(string name, float intensity) { }
    }
    static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }
    static string Event(string type, long sequence, JObject payload) => new JObject {
        ["type"] = type, ["session_id"] = "s", ["turn_id"] = "t", ["sequence"] = sequence,
        ["timestamp"] = "2026-09-05T00:00:00Z", ["payload"] = payload
    }.ToString();
    public static void Main() { Run(); }
    public static void Run()
    {
        var speaking = Event("avatar.state", 1, new JObject { ["state"] = "speaking", ["motion"] = "speaking" });
        Check(AvatarProtocol.TryParse(speaking, out var command), "valid state");
        var driver = new Driver(); var controller = new AvatarController(driver);
        Check(controller.Apply(command), "first command");
        Check(!controller.Apply(command), "stale sequence");
        var lipsync = Event("avatar.lipsync", 2, new JObject { ["mouth_open"] = .8, ["duration_ms"] = 100, ["source"] = "pcm_amplitude" });
        Check(AvatarProtocol.TryParse(lipsync, out command), "valid lipsync");
        Check(controller.Apply(command), "current-turn lipsync"); controller.Tick(.05f);
        Check(controller.Mouth > 0, "mouth opens");
        for (int i = 0; i < 40; i++) controller.Tick(.05f);
        Check(controller.Mouth < .001f, "mouth expires");
        Check(driver.Values.ContainsKey("ParamBreath") && driver.Values.ContainsKey("ParamEyeBallX"), "idle animation");
        var interrupted = Event("avatar.state", 3, new JObject { ["state"] = "interrupted", ["motion"] = "interrupted", ["hold_ms"] = 450 });
        Check(AvatarProtocol.TryParse(interrupted, out command), "interruption"); controller.Apply(command);
        var idle = Event("avatar.state", 4, new JObject { ["state"] = "idle", ["motion"] = "idle" });
        AvatarProtocol.TryParse(idle, out command); controller.Apply(command);
        Check(controller.State == "interrupted", "hold interruption");
        for (int i = 0; i < 10; i++) controller.Tick(.05f);
        Check(controller.State == "idle", "release interruption");
        Check(!AvatarProtocol.TryParse(speaking.Replace("Z\"", "+07:00\""), out command), "reject non-UTC");
        Check(!AvatarProtocol.TryParse(speaking.Replace("\"sequence\": 1", "\"sequence\": -1"), out command), "reject negative sequence");
        var privateEvent = JObject.Parse(speaking); privateEvent["payload"]["text"] = "private";
        Check(!AvatarProtocol.TryParse(privateEvent.ToString(), out command), "reject private fields");
        Check(!AvatarProtocol.TryParse("{bad", out command), "reject malformed JSON");
        Check(!AvatarProtocol.TryParse(speaking + speaking, out command), "reject trailing object");
        Check(!AvatarProtocol.TryParse(lipsync.Replace("0.8", "2.0"), out command), "reject out-of-range mouth");
        controller.Reset(); Check(controller.Mouth == 0 && controller.State == "idle", "disconnect closes mouth");
        Console.WriteLine("Unity protocol/controller checks passed.");
    }
}
