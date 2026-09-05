using System;
using System.Collections.Generic;

namespace Paix
{
    public interface IAvatarDriver
    {
        void Parameter(string id, float value);
        void Motion(string name);
        void Expression(string name, float intensity);
    }

    public sealed class AvatarController
    {
        readonly IAvatarDriver driver;
        readonly Random random;
        readonly Dictionary<string, long> sequences = new Dictionary<string, long>();
        readonly Queue<string> sessions = new Queue<string>();
        string activeSession, activeTurn;
        AvatarCommand pending;
        float now, holdUntil, mouthUntil, mouthTarget, nextBlink = 2.5f, blinkStart = -1, nextGaze = 2;
        float gazeX, gazeY, targetX, targetY;
        public string State { get; private set; } = "idle";
        public string Motion { get; private set; } = "idle";
        public string Expression { get; private set; } = "neutral";
        public float Mouth { get; private set; }

        public AvatarController(IAvatarDriver driver, int seed = 4) { this.driver = driver; random = new Random(seed); }
        public bool Apply(AvatarCommand command)
        {
            if (sequences.TryGetValue(command.Session, out var previous) && command.Sequence <= previous) return false;
            if (!sequences.ContainsKey(command.Session))
            {
                sessions.Enqueue(command.Session);
                if (sessions.Count > 64) sequences.Remove(sessions.Dequeue());
            }
            sequences[command.Session] = command.Sequence;
            if (activeSession != command.Session) { Reset(); activeSession = command.Session; }
            if (command.Type == "avatar.state")
            {
                activeTurn = command.Turn;
                if (State == "interrupted" && command.State == "idle" && now < holdUntil)
                { pending = command; return true; }
                pending = null;
                ApplyState(command);
                holdUntil = now + command.Hold / 1000;
            }
            else if (command.Type == "avatar.expression")
            {
                if (activeTurn != null && activeTurn != command.Turn) return false;
                Expression = command.Expression;
                driver.Expression(Expression, command.Intensity);
            }
            else
            {
                if (activeTurn != command.Turn || State != "speaking") return false;
                mouthTarget = command.Mouth;
                mouthUntil = now + Math.Max(.08f, Math.Min(1, command.Duration / 1000) + .04f);
            }
            return true;
        }
        void ApplyState(AvatarCommand command)
        {
            State = command.State;
            Motion = command.Motion;
            driver.Motion(Motion);
            if (State != "speaking") { Mouth = mouthTarget = 0; driver.Parameter("ParamMouthOpenY", 0); }
        }
        public void Reset()
        {
            pending = null;
            activeTurn = null;
            State = "idle";
            Mouth = mouthTarget = 0;
            driver.Parameter("ParamMouthOpenY", 0);
        }
        public void Tick(float delta)
        {
            delta = Math.Max(0, Math.Min(.1f, delta));
            now += delta;
            if (pending != null && now >= holdUntil) { ApplyState(pending); pending = null; }
            if (now >= mouthUntil) mouthTarget = 0;
            Mouth += (mouthTarget - Mouth) * (1 - (float)Math.Exp(-delta * (mouthTarget > Mouth ? 28 : 16)));
            driver.Parameter("ParamMouthOpenY", Mouth);
            if (now >= nextBlink && blinkStart < 0) blinkStart = now;
            float eye = 1;
            if (blinkStart >= 0)
            {
                var progress = (now - blinkStart) / .18f;
                if (progress >= 1) { blinkStart = -1; nextBlink = now + 2.2f + (float)random.NextDouble() * 3.2f; }
                else eye = progress < .45f ? 1 - progress / .45f : (progress - .45f) / .55f;
            }
            driver.Parameter("ParamEyeLOpen", eye); driver.Parameter("ParamEyeROpen", eye);
            if (now >= nextGaze)
            {
                targetX = ((float)random.NextDouble() * 2 - 1) * .72f;
                targetY = ((float)random.NextDouble() * 2 - 1) * .48f;
                nextGaze = now + 1.8f + (float)random.NextDouble() * 2.6f;
            }
            float smoothing = 1 - (float)Math.Exp(-delta * 1.5f);
            gazeX += (targetX - gazeX) * smoothing; gazeY += (targetY - gazeY) * smoothing;
            driver.Parameter("ParamEyeBallX", gazeX); driver.Parameter("ParamEyeBallY", gazeY);
            driver.Parameter("ParamAngleX", gazeX * 4.5f); driver.Parameter("ParamAngleY", gazeY * 3.2f);
            float energy = State == "speaking" ? 1.35f : State == "thinking" ? .72f : 1;
            driver.Parameter("ParamBreath", .5f + (float)Math.Sin(now * 1.65) * .5f);
            driver.Parameter("ParamBodyAngleX", (float)Math.Sin(now * .72) * 1.6f * energy);
            driver.Parameter("ParamAngleZ", (float)Math.Sin(now * .54) * 1.15f * energy);
        }
    }
}
