using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
#if PAIX_CUBISM
using Live2D.Cubism.Core;
using Live2D.Cubism.Framework;
using Live2D.Cubism.Framework.Expression;
using Live2D.Cubism.Framework.Motion;
#endif

namespace Paix
{
    [Serializable] public sealed class MotionBinding { public string Name; public AnimationClip Clip; public bool Loop = true; }
    public sealed class CubismDriver : MonoBehaviour, IAvatarDriver
#if PAIX_CUBISM
        , ICubismUpdatable
#endif
    {
        public GameObject Model;
        public MotionBinding[] Motions = Array.Empty<MotionBinding>();
        public string Status { get; private set; } = "model_missing";
        public string MotionStatus { get; private set; } = "unavailable";
        public string ExpressionStatus { get; private set; } = "unavailable";
#if PAIX_CUBISM
        readonly Dictionary<string, float> pendingParameters = new Dictionary<string, float>();
        readonly Dictionary<string, CubismParameter> parameters = new Dictionary<string, CubismParameter>();
        CubismMotionController motion;
        CubismExpressionController expression;
#endif
        void Awake()
        {
#if PAIX_CUBISM
            if (Model == null) return;
            var model = Model.GetComponent<CubismModel>();
            if (model == null) return;
            foreach (var parameter in model.Parameters) parameters[parameter.Id] = parameter;
            motion = Model.GetComponent<CubismMotionController>();
            expression = Model.GetComponent<CubismExpressionController>();
            Status = "ready";
#else
            Status = "cubism_sdk_required";
#endif
        }
        public void Parameter(string id, float value)
        {
#if PAIX_CUBISM
            pendingParameters[id] = value;
#endif
        }
#if PAIX_CUBISM
        public int ExecutionOrder => CubismUpdateExecutionOrder.CubismPhysicsController - 1;
        public bool NeedsUpdateOnEditing => false;
        public bool HasUpdateController { get; set; }
        public void OnLateUpdate()
        {
            if (!enabled) return;
            foreach (var entry in pendingParameters)
                if (parameters.TryGetValue(entry.Key, out var parameter))
                    parameter.Value = Mathf.Clamp(entry.Value, parameter.MinimumValue, parameter.MaximumValue);
        }
#endif
        public void Motion(string name)
        {
#if PAIX_CUBISM
            var binding = Motions.FirstOrDefault(item => item.Name == name);
            if (motion == null || binding?.Clip == null) { MotionStatus = "unmapped"; return; }
            motion.PlayAnimation(binding.Clip, 0, CubismMotionPriority.PriorityForce, binding.Loop);
            MotionStatus = "clip:" + Array.IndexOf(Motions, binding);
#endif
        }
        public void Expression(string name, float intensity)
        {
#if PAIX_CUBISM
            var expressions = expression?.ExpressionsList?.CubismExpressionObjects;
            if (expressions == null) { ExpressionStatus = "unmapped"; return; }
            int index = Array.FindIndex(expressions, item => item != null && item.name == name);
            if (index < 0) { ExpressionStatus = "unmapped"; return; }
            expression.CurrentExpressionIndex = index;
            ExpressionStatus = "index:" + index;
#endif
        }
    }
}
