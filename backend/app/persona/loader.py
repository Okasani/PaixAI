from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, StrictUndefined
from pydantic import AliasChoices, BaseModel, Field, field_validator

from app.core.config import Settings


class IdentityConfig(BaseModel):
    name: str = "Paix"
    age_presentation: int = 25
    identity_type: str = "AI companion"
    height_cm: int = 170
    weight_kg: int = 60
    roles: list[str] = Field(default_factory=list)
    self_awareness: dict[str, bool] = Field(default_factory=lambda: {"knows_she_is_ai": True})


class TraitsConfig(BaseModel):
    warmth: float = 0.90
    attentiveness: float = 0.95
    affection: float = 0.70
    playfulness: float = 0.55
    initiative: float = 0.75
    curiosity: float = 0.80
    emotional_expressiveness: float = 0.65
    sass: float = 0.20
    formality: float = 0.45
    technical_rigor: float = 0.95

    @field_validator("*", mode="after")
    @classmethod
    def bounded(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("trait values must be between 0 and 1")
        return value


class BehaviorConfig(BaseModel):
    core_instructions: str
    adaptation: dict[str, str] = Field(default_factory=dict)
    safety: list[str] = Field(default_factory=list)


class RelationshipConfig(BaseModel):
    user_name: str = "Poom"
    description: str = Field(
        "A continuing, trusting collaboration that grows through shared work and conversation.",
        validation_alias=AliasChoices("description", "relationship_summary", "summary"),
    )
    preferences: dict[str, Any] = Field(default_factory=dict)
    boundaries: list[str] = Field(default_factory=list)


class PersonaBundle(BaseModel):
    identity: IdentityConfig
    traits: TraitsConfig
    behavior: BehaviorConfig
    relationship: RelationshipConfig
    template: str


class PersonaLoader:
    def __init__(self, settings: Settings) -> None:
        self.directory = settings.persona_dir
        self._environment = Environment(
            undefined=StrictUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True
        )

    def _yaml(self, name: str) -> dict[str, Any]:
        path = self.directory / f"{name}.yaml"
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path.name} must contain a YAML object")
        return data

    def load(self) -> PersonaBundle:
        template_path = self.directory / "prompt_template.jinja2"
        return PersonaBundle(
            identity=IdentityConfig.model_validate(self._yaml("identity")),
            traits=TraitsConfig.model_validate(self._yaml("traits")),
            behavior=BehaviorConfig.model_validate(self._yaml("behavior")),
            relationship=RelationshipConfig.model_validate(self._yaml("relationship")),
            template=template_path.read_text(encoding="utf-8"),
        )

    def render(self, bundle: PersonaBundle, components: dict[str, Any]) -> str:
        template = self._environment.from_string(bundle.template)
        return template.render(**deepcopy(components)).strip()

    def raw_files(self) -> dict[str, Any]:
        bundle = self.load()
        return bundle.model_dump()

    def repository_defaults(self) -> dict[str, dict[str, Any]]:
        defaults_directory = self.directory / "defaults"
        result: dict[str, dict[str, Any]] = {}
        for section in ("identity", "traits", "behavior", "relationship"):
            path = defaults_directory / f"{section}.yaml"
            if not path.is_file():
                raise ValueError(f"Repository default is missing: {path.name}")
            with path.open("r", encoding="utf-8") as handle:
                value = yaml.safe_load(handle) or {}
            if not isinstance(value, dict):
                raise ValueError(f"Repository default must be a YAML object: {path.name}")
            result[section] = self.validate_update(section, value)
        return result

    def validate_update(self, kind: str, value: dict[str, Any]) -> dict[str, Any]:
        models = {
            "identity": IdentityConfig,
            "traits": TraitsConfig,
            "behavior": BehaviorConfig,
            "relationship": RelationshipConfig,
        }
        if kind not in models:
            raise ValueError(f"Unknown persona section: {kind}")
        return models[kind].model_validate(value).model_dump()

    @staticmethod
    def safe_path(directory: Path, kind: str) -> Path:
        if kind not in {"identity", "traits", "behavior", "relationship"}:
            raise ValueError("Unsupported persona section")
        return directory / f"{kind}.yaml"
