"""CLI tool discovery system for OpenCode-Council."""

import json
import os
import shutil
import subprocess
import time
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

CACHE_DIR = Path.home() / ".cache" / "opencode-council"
CACHE_FILE = CACHE_DIR / "tools_cache.json"
CACHE_TTL = 3600


def _load_cache(ttl: Optional[int] = None) -> Optional[dict]:
    """Load cached tool discovery results."""
    cache_ttl = ttl if ttl is not None else CACHE_TTL
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if CACHE_FILE.exists():
            with open(CACHE_FILE) as f:
                data = json.load(f)
            if time.time() - data.get("timestamp", 0) < cache_ttl:
                return data.get("tools", {})
    except Exception:
        pass
    return None


def _load_expired_cache() -> Optional[dict]:
    """Load cached data even if expired."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if CACHE_FILE.exists():
            with open(CACHE_FILE) as f:
                data = json.load(f)
            return data.get("tools", {})
    except Exception:
        pass
    return None


def has_cache_file() -> bool:
    """Check if cache file exists."""
    try:
        return CACHE_FILE.exists()
    except Exception:
        return False


def is_cache_valid(ttl: Optional[int] = None) -> bool:
    """Check if cache file is valid (not expired)."""
    cache_ttl = ttl if ttl is not None else CACHE_TTL
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE) as f:
                data = json.load(f)
            return time.time() - data.get("timestamp", 0) < cache_ttl
    except Exception:
        pass
    return False


def _save_cache(tools: dict) -> None:
    """Save tool discovery results to cache."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data = {"timestamp": time.time(), "tools": tools}
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


class ToolDiscovery:
    """Discovers and manages opencode-compatible CLI tools."""

    def __init__(self):
        self.tools: dict[str, DiscoveredTool] = {}

    def which(self, command: str) -> Optional[str]:
        """Find the full path of a command using shutil.which."""
        return shutil.which(command)

    def load_cached(self) -> dict[str, "DiscoveredTool"]:
        """Load tools from cache only without refreshing."""
        cached = _load_expired_cache()
        self.tools = {}
        if cached:
            for name, data in cached.items():
                tool = DiscoveredTool(
                    name=name,
                    command=data.get("command", name),
                    path=data.get("path", ""),
                    version=data.get("version", ""),
                    available_models=data.get("available_models", []),
                    authenticated_providers=data.get("authenticated_providers", []),
                    enabled=data.get("enabled", True),
                )
                self.tools[name] = tool
        return self.tools

    def discover_all(
        self, cache_ttl: Optional[int] = None
    ) -> dict[str, DiscoveredTool]:
        """Discover all known opencode-compatible tools."""
        cached = _load_cache(cache_ttl)
        if cached:
            for name, data in cached.items():
                tool = DiscoveredTool(
                    name=name,
                    command=data.get("command", name),
                    path=data.get("path", ""),
                    version=data.get("version", ""),
                    available_models=data.get("available_models", []),
                    authenticated_providers=data.get("authenticated_providers", []),
                    enabled=data.get("enabled", True),
                )
                self.tools[name] = tool
            return self.tools

        self.tools = {}
        for tool_name in KNOWN_TOOLS:
            tool = self.discover_tool(tool_name)
            if tool:
                self.tools[tool_name] = tool

        cache_data = {name: tool.to_dict() for name, tool in self.tools.items()}
        _save_cache(cache_data)
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
