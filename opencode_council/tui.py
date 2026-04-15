"""Main TUI for OpenCode-Council."""

import asyncio
import re
import time
from pathlib import Path
from typing import Optional

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Label,
    Static,
    TextArea,
)

from opencode_council.config import ConfigManager, CouncilConfig
from opencode_council.execution import ExecutionEngine, ModelStatus
from opencode_council.tools import ToolDiscovery


class ModelCheckBox(Checkbox):
    """A checkbox with model info."""

    def __init__(self, model_name: str, tool_name: str, on_change=None, **kwargs):
        super().__init__(**kwargs)
        self.model_name = model_name
        self.tool_name = tool_name
        self.on_change = on_change

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox state change."""
        if self.on_change:
            self.on_change()


class TreeNode(Static):
    """A tree node that shows provider name."""

    def __init__(self, provider_name: str, **kwargs):
        super().__init__(**kwargs)
        self.provider_name = provider_name

    def on_mount(self) -> None:
        """Show provider name on mount."""
        self.update(f"📂 {self.provider_name}")


class TaskInputPanel(Vertical):
    """Upper panel for task input."""

    def compose(self) -> ComposeResult:
        yield Label("Task Description", classes="panel-label")
        yield TextArea(
            id="task-input",
            placeholder="Enter your task or idea here...",
            classes="task-input",
        )


class ModelSelectionPanel(Vertical):
    """Middle panel for model selection."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tree_nodes: list[TreeNode] = []
        self.all_checkboxes: list[ModelCheckBox] = []
        self.current_index: int = 0

    def compose(self) -> ComposeResult:
        yield Label("Select Models", classes="panel-label")
        with Vertical(id="model-list"):
            pass

    def update_models(self, tools: dict) -> None:
        """Update the model list."""
        model_list = self.query_one("#model-list", Vertical)
        model_list.remove_children()
        self.tree_nodes = []
        self.all_checkboxes = []
        self.current_index = 0

        providers: dict[str, dict[str, list[str]]] = {}

        for tool_name, tool in tools.items():
            if not tool.enabled:
                continue
            for model in tool.available_models:
                if "/" in model:
                    provider = model.split("/")[0]
                    model_only = model.split("/", 1)[1]
                else:
                    provider = "Other"
                    model_only = model

                if provider not in providers:
                    providers[provider] = {}
                if tool_name not in providers[provider]:
                    providers[provider][tool_name] = []
                providers[provider][tool_name].append(model_only)

        def on_change():
            app = self.app
            if app:
                app.update_run_button()

        for provider, tool_models in sorted(providers.items()):
            node = TreeNode(provider, id=f"node-{provider}")
            self.tree_nodes.append(node)
            model_list.mount(node)

            for tool_name, models in sorted(tool_models.items()):
                tool_icon = "🔵" if tool_name == "opencode" else "🟢"
                for model in models:
                    model = (model or "").strip()
                    if not model:
                        continue
                    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{provider}_{model}")
                    checkbox = ModelCheckBox(
                        model,
                        tool_name,
                        on_change=on_change,
                        id=f"checkbox-{safe_id}",
                        label=f"  {tool_icon} {model}",
                    )
                    self.all_checkboxes.append(checkbox)
                    model_list.mount(checkbox)

    def move_selection(self, direction: int) -> None:
        """Move selection up or down."""
        if not self.all_checkboxes:
            return

        new_index = self.current_index + direction
        if new_index < 0:
            new_index = 0
        elif new_index >= len(self.all_checkboxes):
            new_index = len(self.all_checkboxes) - 1

        self.current_index = new_index
        self.all_checkboxes[self.current_index].focus()

    def get_selected(self) -> list[tuple[str, str]]:
        """Get selected models."""
        return [(cb.tool_name, cb.model_name) for cb in self.all_checkboxes if cb.value]


class RunControlPanel(Vertical):
    """Bottom panel for run controls."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.selected_count: int = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="run-controls"):
            yield Label("Selected: 0 models", id="selected-count")
            yield Button("Run", id="run-button", variant="primary", disabled=True)


class SettingsScreen(Screen):
    """Settings screen."""

    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses in settings screen."""
        if event.button.id == "settings-save":
            self.save_settings()
        elif event.button.id == "settings-clear-cache":
            self.clear_cache()
        elif event.button.id == "settings-cancel":
            self.app.pop_screen()

    def save_settings(self) -> None:
        """Save settings."""
        output_dir = (
            self.query_one("#setting-output-dir", TextArea).text.strip() or "council"
        )
        cache_ttl = self.query_one("#setting-cache-ttl", TextArea).text.strip() or "60"

        config = self.config_manager.load()
        config.default_output_dir = output_dir
        pref = getattr(config, "preferences", {})
        pref["cache_ttl"] = int(cache_ttl)
        config.preferences = pref

        self.config_manager.save(config)
        self.app.pop_screen()
        self.app.notify("Settings saved!")

    def clear_cache(self) -> None:
        """Clear the tools cache."""
        from opencode_council.tools import CACHE_FILE

        try:
            if CACHE_FILE.exists():
                CACHE_FILE.unlink()
            self.app.notify("Cache cleared!")
        except Exception as e:
            self.app.notify(f"Failed to clear cache: {e}", severity="error")

    def compose(self) -> ComposeResult:
        config = self.config_manager.load()
        preferences = {"cache_ttl": 60}
        if hasattr(config, "preferences"):
            preferences = config.preferences
        elif "preferences" in config.__dict__:
            preferences = config.__dict__.get("preferences", preferences)

        yield Label("Settings", classes="panel-label")
        yield Label("Output folder:")
        yield TextArea(
            config.default_output_dir or "council",
            id="setting-output-dir",
            classes="setting-input",
        )
        yield Label("Cache TTL (minutes):")
        yield TextArea(
            str(preferences.get("cache_ttl", 60)),
            id="setting-cache-ttl",
            classes="setting-input",
        )
        with Horizontal(id="setting-actions"):
            yield Button("Save", id="settings-save", variant="primary")
            yield Button("Clear Cache", id="settings-clear-cache", variant="warning")
            yield Button("Cancel", id="settings-cancel", variant="default")


class CouncilApp(App):
    """Main application for OpenCode-Council."""

    CSS = """
    Screen { layout: vertical; }
    Header { height: 1; }
    Footer { height: 1; }
    #content-area { height: 100%; layout: vertical; align: center middle; }
    #panels { layout: horizontal; height: 1fr; }
    #panels .left-panel { width: 1fr; }
    #panels .right-panel { width: 1fr; }
    .panel { border: solid $primary; padding: 1 1; }
    .left-panel { margin-right: 1; }
    .right-panel { margin-left: 1; }
    .panel-label { text-style: bold; color: $primary; }
    #task-input { height: 100%; border: solid $accent; }
    #model-list { height: 100%; layout: vertical; overflow-y: auto; }
    #run-bar { layout: horizontal; align: center middle; background: $surface; height: 3; }
    #run-bar Label { margin: 0 4; }
    #run-bar Button { width: 20; margin: 0 4; }
    TreeNode { text-style: bold; color: $primary; }
    Checkbox { margin: 0 0 0 2; }

    SettingsScreen {
        align: center middle;
        width: 50;
        height: auto;
        background: $surface;
        border: solid $primary;
        padding: 1;
    }
    SettingsScreen .panel-label { text-style: bold; color: $primary; margin-bottom: 1; }
    SettingsScreen .setting-input { height: 3; margin-bottom: 1; }
    SettingsScreen #setting-actions { layout: horizontal; height: 3; align: center middle; }
SettingsScreen #setting-actions Button { width: 15; margin: 0 1; }
    """

    SCREENS = {
        "settings": SettingsScreen,
    }

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "quit", "Quit"),
        ("ctrl+s", "push_screen('settings')", "Settings"),
        ("f1", "push_screen('settings')", "Settings"),
    ]

    def __init__(self):
        super().__init__()
        self.config: Optional[CouncilConfig] = None
        self.run_dir: Optional[Path] = None
        self.engine: Optional[ExecutionEngine] = None
        self.focus_mode: str = "task"
        self.config_manager = ConfigManager()

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="content-area"):
            with Horizontal(id="panels"):
                with Vertical(classes="panel left-panel"):
                    yield TaskInputPanel()
                with Vertical(classes="panel right-panel"):
                    yield ModelSelectionPanel()
            with Horizontal(id="run-bar"):
                yield Label("Selected: 0 models", id="selected-count")
                yield Button("Run", id="run-button", variant="primary", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        """Initialize on mount."""
        self.refresh_models()
        self.query_one("#task-input").focus()

    def refresh_models(self) -> None:
        """Refresh the model list."""
        config = self.config_manager.load()
        cache_ttl = getattr(config, "cache_ttl", 60)
        discovery = ToolDiscovery()
        tools = discovery.discover_all(cache_ttl=cache_ttl * 60 if cache_ttl else 3600)
        self.config = config

        model_panel = self.query_one(ModelSelectionPanel)
        model_panel.update_models(tools)
        self.update_run_button()

    def update_run_button(self) -> None:
        """Update run button based on selected models."""
        model_panel = self.query_one(ModelSelectionPanel)
        selected = model_panel.get_selected()
        count = len(selected)

        count_label = self.query_one("#selected-count", Label)
        count_label.update(f"Selected: {count} models")

        run_button = self.query_one("#run-button", Button)
        run_button.disabled = count < 2

    def on_key(self, event) -> None:
        """Handle key events."""
        if self.screen_stack and len(self.screen_stack) > 1:
            return

        model_panel = self.query_one(ModelSelectionPanel)

        if event.key == "tab":
            if self.focus_mode == "task":
                self.focus_mode = "models"
                if model_panel.all_checkboxes:
                    model_panel.all_checkboxes[0].focus()
            elif self.focus_mode == "models":
                self.focus_mode = "run"
                self.query_one("#run-button", Button).focus()
            else:
                self.focus_mode = "task"
                self.query_one("#task-input").focus()
            event.prevent_default()
        elif event.key == "up":
            if self.focus_mode == "models":
                model_panel.move_selection(-1)
            elif self.focus_mode == "run":
                self.focus_mode = "models"
                if model_panel.all_checkboxes:
                    model_panel.all_checkboxes[0].focus()
            event.prevent_default()
        elif event.key == "down":
            if self.focus_mode == "models":
                model_panel.move_selection(1)
            elif self.focus_mode == "task":
                self.focus_mode = "models"
                if model_panel.all_checkboxes:
                    model_panel.all_checkboxes[0].focus()
            event.prevent_default()
        elif self.focus_mode == "run" and event.key == "enter":
            run_button = self.query_one("#run-button", Button)
            if not run_button.disabled:
                self.action_run()
            event.prevent_default()

    def action_run(self) -> None:
        """Start execution."""
        task_input = self.query_one("#task-input", TextArea)
        task = task_input.text.strip()

        if not task:
            self.notify("Please enter a task", severity="warning")
            return

        model_panel = self.query_one(ModelSelectionPanel)
        selected = model_panel.get_selected()

        if len(selected) < 2:
            self.notify("Please select at least two models", severity="warning")
            return

        model_names = [f"{tool}/{model}" for tool, model in selected]
        self.run_models(task, model_names)

    def action_settings(self) -> None:
        """Open settings."""
        settings = SettingsScreen()
        self.mount(settings)
        settings.focus()

    @work(exclusive=True)
    async def run_models(self, task: str, selected: list[str]) -> None:
        """Run models in parallel."""
        manager = ConfigManager()
        output_dir = self.config.default_output_dir if self.config else "council"
        self.run_dir = manager.create_run_dir(output_dir)

        config = manager.load()
        self.engine = ExecutionEngine(config, self.run_dir, self.on_progress)
        self.engine.set_task(task)
        self.engine.prepare_models(selected)

        run_button = self.query_one("#run-button", Button)
        run_button.disabled = True

        try:
            await self.engine.run_analysis_phase()
            await self.engine.run_plan_phase()
            await self.engine.run_commentary_phase()
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")
        finally:
            run_button.disabled = False

        self.notify("Execution complete!")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "run-button":
            self.action_run()


def run_app() -> None:
    """Run the TUI application."""
    app = CouncilApp()
    app.run()


if __name__ == "__main__":
    run_app()
