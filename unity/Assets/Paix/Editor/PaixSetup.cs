using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Paix.Editor
{
    public static class PaixSetup
    {
        [MenuItem("Paix/Enable installed Cubism SDK")]
        public static void EnableCubism()
        {
            if (!Directory.Exists("Assets/Live2D/Cubism")) throw new System.InvalidOperationException("Import the official Cubism SDK first.");
            var group = BuildTargetGroup.Standalone;
            var symbols = PlayerSettings.GetScriptingDefineSymbolsForGroup(group).Split(';').ToList();
            if (!symbols.Contains("PAIX_CUBISM")) symbols.Add("PAIX_CUBISM");
            PlayerSettings.SetScriptingDefineSymbolsForGroup(group, string.Join(";", symbols));
        }
        [MenuItem("Paix/Create stage from selected model prefab")]
        public static void CreateStage()
        {
            var selected = Selection.activeGameObject;
            if (selected == null || !PrefabUtility.IsPartOfPrefabAsset(selected))
                throw new System.InvalidOperationException("Select the imported licensed model prefab in the Project window.");
            if (!EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo()) return;
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var model = (GameObject)PrefabUtility.InstantiatePrefab(selected, scene);
            var root = new GameObject("Paix stage");
            var driver = model.GetComponent<CubismDriver>() ?? model.AddComponent<CubismDriver>();
            driver.Model = model;
            var directory = Path.GetDirectoryName(AssetDatabase.GetAssetPath(selected));
            driver.Motions = AssetDatabase.FindAssets("t:AnimationClip", new[] { directory })
                .Select(guid => AssetDatabase.LoadAssetAtPath<AnimationClip>(AssetDatabase.GUIDToAssetPath(guid)))
                .Where(clip => clip != null).Select(clip => new MotionBinding { Name = clip.name, Clip = clip }).ToArray();
            root.AddComponent<PaixStage>().Driver = driver;
            var camera = new GameObject("Camera").AddComponent<Camera>();
            camera.orthographic = true;
            camera.backgroundColor = new Color(.06f, .065f, .09f);
            var renderers = model.GetComponentsInChildren<Renderer>();
            var bounds = new Bounds(model.transform.position, Vector3.one * 3);
            if (renderers.Length > 0) { bounds = renderers[0].bounds; foreach (var renderer in renderers) bounds.Encapsulate(renderer.bounds); }
            camera.orthographicSize = Mathf.Max(.5f, bounds.extents.y * 1.12f);
            camera.transform.position = new Vector3(bounds.center.x, bounds.center.y, -10);
            Application.targetFrameRate = 60;
            Directory.CreateDirectory("Assets/Scenes");
            EditorSceneManager.SaveScene(scene, "Assets/Scenes/Paix.unity");
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene("Assets/Scenes/Paix.unity", true) };
        }
        [MenuItem("Paix/Build Windows stage")]
        public static void BuildWindows()
        {
            if (!File.Exists("Assets/Scenes/Paix.unity")) throw new System.InvalidOperationException("Create the stage first.");
            Directory.CreateDirectory("Builds");
            var report = BuildPipeline.BuildPlayer(new[] { "Assets/Scenes/Paix.unity" }, "Builds/Paix.exe", BuildTarget.StandaloneWindows64, BuildOptions.None);
            if (report.summary.result != UnityEditor.Build.Reporting.BuildResult.Succeeded)
                throw new System.InvalidOperationException("Unity build failed.");
        }
    }
}
