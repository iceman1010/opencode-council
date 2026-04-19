"""Configuration management for OpenCode-Council."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from opencode_council.tools import DiscoveredTool, ToolDiscovery


@dataclass
class ToolPreference:
    """Preference for a single tool."""

    command: str
    path: str = ""
    enabled: bool = True


@dataclass
class ToolPreferences:
    """Preferences for tools and model filtering."""

    enabled_tools: list[str] = field(default_factory=list)
    hidden_providers: list[str] = field(default_factory=list)
    hidden_models: list[str] = field(default_factory=list)
    custom_tools: list[ToolPreference] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "enabled_tools": self.enabled_tools,
            "hidden_providers": self.hidden_providers,
            "hidden_models": self.hidden_models,
            "custom_tools": [
                {"command": t.command, "path": t.path, "enabled": t.enabled}
                for t in self.custom_tools
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ToolPreferences":
        """Create from dictionary."""
        return cls(
            enabled_tools=data.get("enabled_tools", []),
            hidden_providers=data.get("hidden_providers", []),
            hidden_models=data.get("hidden_models", []),
            custom_tools=[
                ToolPreference(
                    command=t.get("command", ""),
                    path=t.get("path", ""),
                    enabled=t.get("enabled", True),
                )
                for t in data.get("custom_tools", [])
            ],
        )


@dataclass
class CouncilConfig:
    """Configuration for the council run."""

    tools: dict[str, DiscoveredTool] = field(default_factory=dict)
    selected_models: list[str] = field(default_factory=list)
    default_output_dir: str = "council"
    parallel_execution: bool = True
    max_concurrent_models: int = 4
    auto_refresh_models: bool = True
    theme: str = "dark"
    cache_ttl: int = 60
    debug_logging: bool = True
    tool_preferences: ToolPreferences = field(default_factory=ToolPreferences)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "tools": {name: tool.to_dict() for name, tool in self.tools.items()},
            "selected_models": self.selected_models,
            "preferences": {
                "default_output_dir": self.default_output_dir,
                "parallel_execution": self.parallel_execution,
                "max_concurrent_models": self.max_concurrent_models,
                "auto_refresh_models": self.auto_refresh_models,
                "theme": self.theme,
                "cache_ttl": self.cache_ttl,
                "debug_logging": self.debug_logging,
            },
            "tool_preferences": self.tool_preferences.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CouncilConfig":
        """Create from dictionary."""
        tools = {}
        for name, tool_data in data.get("tools", {}).items():
            tool = DiscoveredTool(
                name=name,
                command=tool_data.get("command", name),
                path=tool_data.get("path", ""),
                version=tool_data.get("version", ""),
                available_models=tool_data.get("available_models", []),
                enabled=tool_data.get("enabled", True),
            )
            tools[name] = tool

        preferences = data.get("preferences", {})
        tool_prefs = ToolPreferences.from_dict(data.get("tool_preferences", {}))

        return cls(
            tools=tools,
            selected_models=data.get("selected_models", []),
            default_output_dir=preferences.get("default_output_dir", "council"),
            parallel_execution=preferences.get("parallel_execution", True),
            max_concurrent_models=preferences.get("max_concurrent_models", 4),
            auto_refresh_models=preferences.get("auto_refresh_models", True),
            theme=preferences.get("theme", "dark"),
            cache_ttl=preferences.get("cache_ttl", 60),
            debug_logging=preferences.get("debug_logging", True),
            tool_preferences=tool_prefs,
        )

    def get_all_models(self) -> list[tuple[str, str]]:
        """Get all available models with tool prefix.

        Returns list of (full_model_name, tool_name) tuples.
        """
        models = []
        for tool_name, tool in self.tools.items():
            if tool.enabled:
                for model in tool.available_models:
                    models.append((model, tool_name))
        return models

    def get_model_info(
        self, full_model_name: str
    ) -> tuple[Optional[DiscoveredTool], Optional[str]]:
        """Get tool and model name from full model name.

        Args:
            full_model_name: Full model name in format "tool/model"

        Returns:
            Tuple of (DiscoveredTool, model_name)
        """
        if "/" not in full_model_name:
            return None, None

        parts = full_model_name.split("/", 1)
        tool_name = parts[0]
        model_name = parts[1] if len(parts) > 1 else ""

        tool = self.tools.get(tool_name)
        return tool, model_name


class ConfigManager:
    """Manages configuration persistence."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or Path("council/config.json")
        self.config: Optional[CouncilConfig] = None

    def load(self) -> CouncilConfig:
        """Load configuration from file."""
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    data = json.load(f)
                self.config = CouncilConfig.from_dict(data)
            except (json.JSONDecodeError, Exception):
                self.config = self._create_default()
        else:
            self.config = self._create_default()

        # Always refresh models if none found
        if not self.config.tools:
            self.config = self._create_default()

        return self.config

    def save(self, config: Optional[CouncilConfig] = None) -> None:
        """Save configuration to file."""
        if config:
            self.config = config
        if self.config is None:
            return

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            json.dump(self.config.to_dict(), f, indent=2)

    def _create_default(self) -> CouncilConfig:
        """Create default configuration with discovered tools."""
        discovery = ToolDiscovery()
        tools = discovery.discover_all()
        return CouncilConfig(tools=tools)

    def create_run_dir(self, output_dir: str) -> Path:
        """Create timestamped run directory."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = Path(output_dir) / timestamp
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir


def load_or_discover_config(config_path: Optional[Path] = None) -> CouncilConfig:
    """Load config or discover tools if config doesn't exist."""
    manager = ConfigManager(config_path)
    return manager.load()
