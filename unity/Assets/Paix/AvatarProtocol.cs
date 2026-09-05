using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Paix
{
    public sealed class AvatarCommand
    {
        public string Type, Session, Turn, State, Motion, Expression;
        public long Sequence;
        public float Mouth, Duration, Hold, Intensity;
    }

    public static class AvatarProtocol
    {
        public static readonly HashSet<string> States = new HashSet<string> {
            "idle", "listening", "transcribing", "thinking", "speaking", "interrupted", "error"
        };
        public static bool TryParse(string json, out AvatarCommand command)
        {
            command = null;
            if (json == null || json.Length > 4096) return false;
            try
            {
                JObject value;
                using (var reader = new JsonTextReader(new System.IO.StringReader(json)))
                {
                    reader.DateParseHandling = DateParseHandling.None;
                    reader.MaxDepth = 8;
                    value = JObject.Load(reader, new JsonLoadSettings { DuplicatePropertyNameHandling = DuplicatePropertyNameHandling.Error });
                    if (reader.Read()) return false;
                }
                if (!HasOnly(value, "type", "session_id", "turn_id", "sequence", "timestamp", "payload")) return false;
                var type = Text(value, "type", 40);
                var session = Text(value, "session_id", 128);
                var turn = Text(value, "turn_id", 128);
                var stamp = Text(value, "timestamp", 50);
                if (type == null || session == null || turn == null || stamp == null ||
                    !stamp.Contains("T") || !(stamp.EndsWith("Z") || stamp.EndsWith("+00:00")) ||
                    !DateTimeOffset.TryParse(stamp, CultureInfo.InvariantCulture, DateTimeStyles.None, out var timestamp) ||
                    timestamp.Offset != TimeSpan.Zero || value["sequence"]?.Type != JTokenType.Integer ||
                    !(value["payload"] is JObject payload)) return false;
                long sequence = value["sequence"].Value<long>();
                if (sequence < 0) return false;
                var result = new AvatarCommand { Type = type, Session = session, Turn = turn, Sequence = sequence };
                switch (type)
                {
                    case "avatar.state":
                        if (!HasOnly(payload, "state", "motion", "transition_ms", "hold_ms")) return false;
                        result.State = Text(payload, "state", 30);
                        result.Motion = Text(payload, "motion", 100);
                        if (!States.Contains(result.State ?? "") || result.Motion == null) return false;
                        result.Hold = Number(payload, "hold_ms", 0, 2000, 0);
                        Number(payload, "transition_ms", 0, 5000, 0);
                        break;
                    case "avatar.expression":
                        if (!HasOnly(payload, "expression", "intensity")) return false;
                        result.Expression = Text(payload, "expression", 100);
                        if (result.Expression == null) return false;
                        result.Intensity = Number(payload, "intensity", 0, 1);
                        break;
                    case "avatar.lipsync":
                        if (!HasOnly(payload, "mouth_open", "duration_ms", "source")) return false;
                        var source = Text(payload, "source", 30);
                        if (source != "pcm_amplitude" && source != "speech_activity") return false;
                        result.Mouth = Number(payload, "mouth_open", 0, 1);
                        result.Duration = Number(payload, "duration_ms", 0, 600000);
                        break;
                    default: return false;
                }
                command = result;
                return true;
            }
            catch (Exception error) when (error is JsonException || error is ArgumentException ||
                                          error is FormatException || error is OverflowException || error is InvalidCastException)
            { return false; }
        }
        static bool HasOnly(JObject value, params string[] keys) => value.Properties().All(p => keys.Contains(p.Name));
        static string Text(JObject value, string key, int maximum)
        {
            var token = value[key];
            if (token?.Type != JTokenType.String) return null;
            var text = token.Value<string>();
            return string.IsNullOrWhiteSpace(text) || text.Length > maximum ? null : text;
        }
        static float Number(JObject value, string key, float minimum, float maximum, float? fallback = null)
        {
            var token = value[key];
            if (token == null && fallback.HasValue) return fallback.Value;
            if (token == null || (token.Type != JTokenType.Integer && token.Type != JTokenType.Float)) throw new FormatException();
            var number = token.Value<float>();
            if (float.IsNaN(number) || float.IsInfinity(number) || number < minimum || number > maximum) throw new FormatException();
            return number;
        }
    }
}
