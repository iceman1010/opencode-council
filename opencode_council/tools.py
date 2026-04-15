"""CLI tool discovery system for OpenCode-Council."""

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DiscoveredTool:
    """Represents a discovered opencode-compatible CLI tool."""

    name: str
    command: str
    path: str
    version: str = ""
    available_models: list[str] = field(default_factory=list)
    authenticated_providers: list[str] = field(default_factory=list)
    enabled: bool = True

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "command": self.command,
            "path": self.path,
            "version": self.version,
            "available_models": self.available_models,
            "enabled": self.enabled,
        }


KNOWN_TOOLS = ["opencode", "kilo"]


class ToolDiscovery:
    """Discovers and manages opencode-compatible CLI tools."""

    def __init__(self):
        self.tools: dict[str, DiscoveredTool] = {}

    def which(self, command: str) -> Optional[str]:
        """Find the full path of a command using shutil.which."""
        return shutil.which(command)

    def discover_all(self) -> dict[str, DiscoveredTool]:
        """Discover all known opencode-compatible tools."""
        self.tools = {}
        for tool_name in KNOWN_TOOLS:
            tool = self.discover_tool(tool_name)
            if tool:
                self.tools[tool_name] = tool
        return self.tools

    def discover_tool(self, tool_name: str) -> Optional[DiscoveredTool]:
        """Discover a specific tool by name."""
        tool_path = self.which(tool_name)
        if not tool_path:
            return None

        version = self._get_version(tool_name, tool_path)
        available_models = self._get_models(tool_name)
        authenticated = self._get_authenticated(tool_name)

        return DiscoveredTool(
            name=tool_name,
            command=tool_name,
            path=tool_path,
            version=version,
            available_models=available_models,
            authenticated_providers=authenticated,
            enabled=True,
        )

    def _get_version(self, command: str, tool_path: str) -> str:
        """Get tool version."""
        try:
            result = subprocess.run(
                [command, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass
        return "unknown"

    def _get_models(self, command: str) -> list[str]:
        """Get available models for a tool."""
        try:
            result = subprocess.run(
                [command, "models"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                models = []
                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    if line and not line.startswith(" "):
                        models.append(line)
                return models
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass
        return []

    def _get_authenticated(self, command: str) -> list[str]:
        """Get authenticated providers for a tool."""
        try:
            result = subprocess.run(
                [command, "auth", "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                providers = []
                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    if line and not line.startswith(" "):
                        providers.append(line)
                return providers
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass
        return []

    def to_config_dict(self) -> dict:
        """Convert tools to configuration dictionary."""
        config = {"tools": {}}
        for name, tool in self.tools.items():
            config["tools"][name] = tool.to_dict()
        return config


def discover_tools() -> dict[str, DiscoveredTool]:
    """Convenience function to discover all tools."""
    discovery = ToolDiscovery()
    return discovery.discover_all()