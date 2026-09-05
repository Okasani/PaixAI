from app.avatar.live2d import Live2DAvatarAdapter
from app.core.config import PROJECT_ROOT
from app.core.json_config import AvatarProfile, read_json


class UnityAvatarAdapter(Live2DAvatarAdapter):
    provider_id = "unity"

    def __init__(self) -> None:
        super().__init__()
        self.manifest.display_name = "Unity Cubism stage"
        self.profile = read_json(PROJECT_ROOT / "config" / "avatar.json", AvatarProfile)

    def transform(self, raw_event):
        command = super().transform(raw_event)
        if command is None:
            return None
        payload = command["payload"]
        if command["type"] == "avatar.state":
            payload["motion"] = self.profile.motions.get(payload["motion"], payload["motion"])
        elif command["type"] == "avatar.expression":
            payload["expression"] = self.profile.expressions.get(payload["expression"], payload["expression"])
        return command
