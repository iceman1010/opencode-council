"""Main TUI for OpenCode-Council."""

import asyncio
import re
import time
from pathlib import Path
from typing import Optional

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Button,
    Checkbox,
    Collapsible,
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

    def __init__(self, model_name: str, tool_name: str, **kwargs):
        super().__init__(**kwargs)
        self.model_name = model_name
        self.tool_name = tool_name


class ProviderGroup(Collapsible):
    """A collapsible group for a provider."""

    def __init__(self, provider_name: str, tool_name: str, **kwargs):
        super().__init__(**kwargs)
        self.provider_name = provider_name
        self.tool_name = tool_name
        self.checkboxes: list[ModelCheckBox] = []


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
    """Lower panel for model selection."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.provider_groups: list[ProviderGroup] = []
        self.all_checkboxes: list[ModelCheckBox] = []
        self.current_index: int = 0

    def compose(self) -> ComposeResult:
        yield Label("Select Models", classes="panel-label")
        with Vertical(id="model-list"):
            pass

    def update_models(self, tools: dict) -> None:
        """Update the model list with tree view."""
        model_list = self.query_one("#model-list", Vertical)
        model_list.remove_children()
        self.provider_groups = []
        self.all_checkboxes = []
        self.current_index = 0

        providers: dict[str, dict[str, list[str]]] = {}

        for tool_name, tool in tools.items():
            if not tool.enabled:
                continue
            for model in tool.available_models:
                if "/" in model:
                    provider = model.split("/")[0]
                    model_only = model.split("/", 1)[1] if "/" in model else model
                else:
                    provider = "Other"
                    model_only = model

                if provider not in providers:
                    providers[provider] = {}
                if tool_name not in providers[provider]:
                    providers[provider][tool_name] = []
                providers[provider][tool_name].append(model_only)

        widgets_to_mount = []

        for provider, tool_models in sorted(providers.items()):
            icon = "📁"
            group = ProviderGroup(
                provider,
                "group",
                title=f"{icon} {provider}",
                id=f"provider-{provider}",
            )
            self.provider_groups.append(group)

            group_checkboxes = []
            for tool_name, models in sorted(tool_models.items()):
                tool_icon = "🔵" if tool_name == "opencode" else "🟢"
                for model in models:
                    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{provider}_{model}")
                    checkbox = ModelCheckBox(
                        model,
                        tool_name,
                        id=f"checkbox-{safe_id}",
                        label=f"{tool_icon} {model}",
                    )
                    self.all_checkboxes.append(checkbox)
                    group_checkboxes.append(checkbox)

            widgets_to_mount.append((group, group_checkboxes))

        for group, checkboxes in widgets_to_mount:
            model_list.mount(group)
            group.collapsed = True
            for checkbox in checkboxes:
                group.mount(checkbox)

        if self.all_checkboxes:
            self.current_index = 0

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


class ProgressPanel(Vertical):
    """Panel showing execution progress."""

    def compose(self) -> ComposeResult:
        yield Label("Progress", classes="panel-label")
        with Vertical(id="progress-list"):
            pass
        with Horizontal(id="progress-info"):
            yield Label("Elapsed: ", id="elapsed-label")
            yield Label("0:00", id="elapsed-time")


class ExecutionStatus(Static):
    """Status display for a model."""

    def __init__(self, model_name: str, **kwargs):
        super().__init__(**kwargs)
        self.model_name = model_name

    def update_status(self, status: ModelStatus) -> None:
        """Update the status display."""
        status_text = {
            ModelStatus.PENDING: "⏳ Pending",
            ModelStatus.RUNNING: "🔄 Running...",
            ModelStatus.ANALYSIS_COMPLETE: "📝 Analysis Done",
            ModelStatus.PLAN_COMPLETE: "📋 Plan Done",
            ModelStatus.COMPLETE: "✅ Complete",
            ModelStatus.FAILED: "❌ Failed",
        }
        self.update(f"{self.model_name}: {status_text.get(status, str(status))}")


class PreviewPanel(Vertical):
    """Panel for previewing outputs."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_file: Optional[Path] = None
        self.current_model_index: int = 0

    def compose(self) -> ComposeResult:
        yield Label("Preview", classes="panel-label")
        yield TextArea(id="preview-content", read_only=True)


class CouncilApp(App):
    """Main application for OpenCode-Council."""

    CSS = """
    Screen {
        layout: vertical;
    }
    
    #main-container {
        height: 100%;
        layout: grid;
        grid-size: 2 1;
        grid-columns: 1fr 1fr;
    }
    
    .panel {
        border: solid $primary;
        padding: 1;
        margin: 1;
    }
    
    .panel-label {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    
    #task-input {
        height: 100%;
        border: solid $accent;
    }
    
    #model-list {
        height: 100%;
        layout: vertical;
        overflow-y: auto;
    }
    
    #progress-list {
        height: 100%;
        layout: vertical;
        overflow-y: auto;
    }
    
    #preview-content {
        height: 100%;
    }
    
    #elapsed-label {
        color: $text;
    }
    
    #elapsed-time {
        color: $accent;
    }
    
    .toolbar {
        dock: bottom;
        height: 3;
        background: $surface;
        layout: horizontal;
    }
    
    Button {
        margin: 1;
    }
    
    .active-panel {
        border: solid $accent;
    }
    
    Collapsible {
        margin: 0 0 1 0;
    }
    
    Collapsible > .collapsible--title {
        text-style: bold;
        color: $primary;
    }
    
    Checkbox {
        margin: 0 0 0 2;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "run", "Run"),
        ("ctrl+comma", "settings", "Settings"),
    ]

    def __init__(self):
        super().__init__()
        self.config: Optional[CouncilConfig] = None
        self.run_dir: Optional[Path] = None
        self.engine: Optional[ExecutionEngine] = None
        self.start_time: Optional[float] = None
        self.selected_models: list[str] = []
        self.focus_mode: str = "task"

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-container"):
            with Vertical(classes="panel left-panel"):
                yield TaskInputPanel()
            with Vertical(classes="panel right-panel"):
                yield ModelSelectionPanel()
        with Container(classes="toolbar"):
            yield Button("Run", id="run-button", variant="primary")
            yield Button("Refresh Models", id="refresh-button")
            yield Button("Settings", id="settings-button")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize on mount."""
        self.refresh_models()
        self.query_one("#task-input").focus()

    def load_config(self) -> None:
        """Load configuration."""
        discovery = ToolDiscovery()
        tools = discovery.discover_all()
        self.config = CouncilConfig(tools=tools)

        model_panel = self.query_one(ModelSelectionPanel)
        model_panel.update_models(tools)

    def refresh_models(self) -> None:
        """Refresh the model list."""
        discovery = ToolDiscovery()
        tools = discovery.discover_all()
        self.config = CouncilConfig(tools=tools)

        model_panel = self.query_one(ModelSelectionPanel)
        model_panel.update_models(tools)

    def on_key(self, event) -> None:
        """Handle key events."""
        if self.focus_mode == "models":
            model_panel = self.query_one(ModelSelectionPanel)
            if event.key == "up":
                model_panel.move_selection(-1)
                event.prevent_default()
            elif event.key == "down":
                model_panel.move_selection(1)
                event.prevent_default()
            elif event.key == "tab":
                self.focus_mode = "task"
                self.query_one("#task-input").focus()
                event.prevent_default()
        else:
            if event.key == "tab":
                self.focus_mode = "models"
                model_panel = self.query_one(ModelSelectionPanel)
                if model_panel.all_checkboxes:
                    model_panel.all_checkboxes[model_panel.current_index].focus()
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

        if not selected:
            self.notify("Please select at least one model", severity="warning")
            return

        model_names = [f"{tool}/{model}" for tool, model in selected]
        self.run_models(task, model_names)

    def action_settings(self) -> None:
        """Open settings."""
        self.notify("Settings (Ctrl+,) not yet implemented", severity="information")

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

        self.start_time = time.time()
        self.query_one("#run-button", Button).disabled = True

        try:
            await self.engine.run_analysis_phase()
            await self.engine.run_plan_phase()
            await self.engine.run_commentary_phase()
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")
        finally:
            self.query_one("#run-button", Button).disabled = False

        self.notify("Execution complete!")

    def on_progress(self, model_name: str, status: ModelStatus) -> None:
        """Handle progress updates."""
        pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "run-button":
            self.action_run()
        elif event.button.id == "refresh-button":
            self.refresh_models()
        elif event.button.id == "settings-button":
            self.action_settings()


def run_app() -> None:
    """Run the TUI application."""
    app = CouncilApp()
    app.run()


if __name__ == "__main__":
    run_app()
