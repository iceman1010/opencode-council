"""Main TUI for OpenCode-Council."""

import asyncio
import re
import threading
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

from opencode_council.config import (
    ConfigManager,
    CouncilConfig,
    ToolPreference,
    ToolPreferences,
)
from opencode_council.execution import ExecutionEngine, ModelStatus
from opencode_council.tools import ToolDiscovery, has_cache_file, is_cache_valid


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

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Update run button when text changes."""
        app = self.app
        if app:
            app.update_run_button()


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
    """Settings screen with tabs."""

    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        self.current_tab = "general"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses in settings screen."""
        bid = event.button.id
        if bid == "settings-save":
            self.save_settings()
        elif bid == "settings-clear-cache":
            self.clear_cache()
        elif bid == "settings-cancel":
            self.app.pop_screen()
        elif bid == "tab-general":
            self.show_tab("general")
        elif bid == "tab-tools":
            self.show_tab("tools")
        elif bid == "tab-filters":
            self.show_tab("filters")
        elif bid == "tab-custom":
            self.show_tab("custom")
        elif bid == "rescan-tools":
            self.rescan_tools()
        elif bid == "reset-filters":
            self.reset_filters()
        elif bid == "verify-custom":
            self.verify_custom_tool()
        elif bid == "add-custom":
            self.add_custom_tool()

    def show_tab(self, tab: str) -> None:
        """Switch to a different tab."""
        self.current_tab = tab
        for container in self.query(".settings-tab"):
            container.add_class("hidden-tab")
        self.query_one(f"#tab-{tab}").remove_class("hidden-tab")
        for btn in self.query("SettingsScreen Button"):
            if btn.id and btn.id.startswith("tab-"):
                btn.variant = "primary" if btn.id == f"tab-{tab}" else "default"

    def save_settings(self) -> None:
        """Save settings."""
        output_dir = (
            self.query_one("#setting-output-dir", TextArea).text.strip().split("\n")[0]
            or "council"
        )
        cache_ttl_text = (
            self.query_one("#setting-cache-ttl", TextArea).text.strip().split("\n")[0]
            or "60"
        )

        config = self.config_manager.load()
        config.default_output_dir = output_dir
        config.cache_ttl = int(cache_ttl_text)
        config.tool_preferences = self.collect_tool_preferences()

        self.config_manager.save(config)
        self.app.pop_screen()
        self.app.notify("Settings saved!")

    def on_key(self, event) -> None:
        """Handle keyboard navigation in settings."""
        if self.current_tab != "filters":
            return

        if not hasattr(self, "_selected_filter_column"):
            self._selected_filter_column = "providers"
            self._selected_filter_index = 0

        checkboxes = self._get_current_column_checkboxes()
        if not checkboxes:
            return

        if event.key == "left":
            self._selected_filter_column = "providers"
            self._focus_current_filter()
            event.prevent_default()
        elif event.key == "right":
            self._selected_filter_column = "models"
            self._focus_current_filter()
            event.prevent_default()
        elif event.key == "up":
            self._selected_filter_index = max(0, self._selected_filter_index - 1)
            if self._selected_filter_index < len(checkboxes):
                checkboxes[self._selected_filter_index].focus()
            event.prevent_default()
        elif event.key == "down":
            self._selected_filter_index = min(
                len(checkboxes) - 1, self._selected_filter_index + 1
            )
            if self._selected_filter_index < len(checkboxes):
                checkboxes[self._selected_filter_index].focus()
            event.prevent_default()
        elif event.key == " ":
            cb = self.focused
            if cb and hasattr(cb, "value"):
                cb.value = not cb.value
                event.prevent_default()

    def _get_current_column_checkboxes(self) -> list:
        """Get checkboxes for current column."""
        if not hasattr(self, "_selected_filter_column"):
            self._selected_filter_column = "providers"
        if self._selected_filter_column == "providers":
            container = self.query_one("#providers-list")
        else:
            container = self.query_one("#models-list")
        return [cb for cb in container.query("Checkbox")]

    def _focus_current_filter(self) -> None:
        """Focus the first checkbox in current column."""
        checkboxes = self._get_current_column_checkboxes()
        if checkboxes:
            checkboxes[0].focus()
            self._selected_filter_index = 0

    def collect_tool_preferences(self) -> "ToolPreferences":
        """Collect tool preferences from the UI."""
        from opencode_council.config import ToolPreference, ToolPreferences

        enabled_tools = []
        hidden_providers = []
        hidden_models = []
        custom_tools = []

        for tool in self.config_manager.load().tools.values():
            checkbox = self.query_one(f"#tool-enabled-{tool.name}", Checkbox)
            if checkbox.value:
                enabled_tools.append(tool.name)

        all_checkboxes = list(self.query("Checkbox"))
        for cb in all_checkboxes:
            if cb.id:
                if cb.id.startswith("hide-provider-"):
                    provider = cb.id.replace("hide-provider-", "")
                    if cb.value:
                        hidden_providers.append(provider)
                elif cb.id.startswith("hide-model-"):
                    model_id = cb.id.replace("hide-model-", "")
                    full_model = model_id.replace("_", "/")
                    if cb.value:
                        hidden_models.append(full_model)

        return ToolPreferences(
            enabled_tools=enabled_tools,
            hidden_providers=hidden_providers,
            hidden_models=hidden_models,
            custom_tools=custom_tools,
        )

    def clear_cache(self) -> None:
        """Clear the tools cache."""
        from opencode_council.tools import CACHE_FILE

        try:
            if CACHE_FILE.exists():
                CACHE_FILE.unlink()
            self.app.notify("Cache cleared!")
        except Exception as e:
            self.app.notify(f"Failed to clear cache: {e}", severity="error")

    def rescan_tools(self) -> None:
        """Rescan for tools."""
        discovery = ToolDiscovery()
        tools = discovery.discover_all()
        self.query_one("#rescan-status", Label).update(f"Found {len(tools)} tools")
        self.app.notify(f"Found {len(tools)} tools")

    def reset_filters(self) -> None:
        """Reset all filters."""
        for cb in self.query("Checkbox"):
            if cb.id and (
                cb.id.startswith("hide-provider-") or cb.id.startswith("hide-model-")
            ):
                cb.value = False
        self.app.notify("Filters reset")

    def verify_custom_tool(self) -> None:
        """Verify a custom tool works."""
        cmd = self.query_one("#custom-command", TextArea).text.strip()
        path = self.query_one("#custom-path", TextArea).text.strip()

        if not cmd:
            self.app.notify("Enter command name", severity="warning")
            return

        import shutil

        tool_path = shutil.which(cmd) or path
        if not tool_path:
            self.app.notify(f"Command '{cmd}' not found", severity="error")
            return

        import subprocess

        try:
            result = subprocess.run(
                [cmd, "--version"], capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                version = result.stdout.strip().split("\n")[0]
                self.query_one("#verify-status", Label).update(f"OK: {version}")
                self.app.notify(f"Tool verified: {version}")
            else:
                self.query_one("#verify-status", Label).update(
                    f"Error: {result.stderr}"
                )
                self.app.notify(f"Tool error: {result.stderr}", severity="error")
        except Exception as e:
            self.query_one("#verify-status", Label).update(f"Error: {e}")
            self.app.notify(f"Failed: {e}", severity="error")

    def add_custom_tool(self) -> None:
        """Add a custom tool to the list."""
        from opencode_council.config import ToolPreference

        cmd = self.query_one("#custom-command", TextArea).text.strip()
        path = self.query_one("#custom-path", TextArea).text.strip()

        if not cmd:
            self.app.notify("Enter command name", severity="warning")
            return

        config = self.config_manager.load()
        config.tool_preferences.custom_tools.append(
            ToolPreference(command=cmd, path=path, enabled=True)
        )
        self.config_manager.save(config)

        self.query_one("#custom-command", TextArea).update("")
        self.query_one("#custom-path", TextArea).update("")
        self.app.notify(f"Added custom tool: {cmd}")

    def compose(self) -> ComposeResult:
        config = self.config_manager.load()

        if not config.tools:
            try:
                app_config = self.app.config
                if app_config and app_config.tools:
                    config.tools = app_config.tools
            except Exception:
                pass

        if not config.tools:
            discovery = ToolDiscovery()
            config.tools = discovery.load_cached()
            if not config.tools:
                config.tools = discovery.discover_all()

        tool_prefs = config.tool_preferences
        cache_ttl_value = config.cache_ttl

        yield Label("Settings", classes="panel-label")

        with Horizontal(id="settings-tabs"):
            yield Button("General", id="tab-general", variant="primary")
            yield Button("Tools", id="tab-tools")
            yield Button("Filters", id="tab-filters")
            yield Button("Custom", id="tab-custom")

        with Vertical(id="tab-general", classes="settings-tab"):
            yield Label("Output folder:")
            yield TextArea(
                config.default_output_dir or "council",
                id="setting-output-dir",
                classes="setting-input",
            )
            yield Label("Cache TTL (minutes):")
            yield TextArea(
                str(cache_ttl_value),
                id="setting-cache-ttl",
                classes="setting-input",
            )

        def _safe_id(s):
            return re.sub(r"[^a-zA-Z0-9_-]", "_", s)[:40]

        with Vertical(id="tab-tools", classes="settings-tab hidden-tab"):
            yield Label("Enable/Disable Tools:")
            with Vertical(id="tools-list"):
                for tool_name, tool in config.tools.items():
                    is_enabled = tool.enabled
                    if tool_prefs.enabled_tools:
                        is_enabled = tool_name in tool_prefs.enabled_tools
                    yield Checkbox(
                        f"{tool_name}  ({tool.path})  v{tool.version}",
                        id=f"tool-enabled-{tool_name}",
                        value=is_enabled,
                    )
            yield Label("", id="rescan-status")
            with Horizontal(classes="action-row"):
                yield Button("Rescan", id="rescan-tools", variant="success")

        all_providers = set()
        all_models = {}
        for tool in config.tools.values():
            for model in tool.available_models:
                if "/" in model:
                    provider = model.split("/")[0]
                    all_providers.add(provider)
                    if provider not in all_models:
                        all_models[provider] = []
                    all_models[provider].append(model)

        with Vertical(id="tab-filters", classes="settings-tab hidden-tab"):
            with Horizontal(id="filter-columns"):
                with Vertical(id="filter-providers"):
                    yield Label("Providers:")
                    with Vertical(id="providers-list", classes="filter-list"):
                        for provider in sorted(all_providers):
                            yield Checkbox(
                                provider,
                                id=f"hide-provider-{_safe_id(provider)}",
                                value=provider in set(tool_prefs.hidden_providers),
                            )

                with Vertical(id="filter-models"):
                    yield Label("Models:")
                    with Vertical(id="models-list", classes="filter-list"):
                        used_ids = set()
                        for provider in sorted(all_models.keys()):
                            yield Label(f"[{provider}]", classes="filter-provider")
                            for model in sorted(all_models[provider]):
                                full = f"{provider}/{model}"
                                safe = _safe_id(full)
                                if safe in used_ids:
                                    safe = f"{safe}_{len(used_ids)}"
                                used_ids.add(safe)
                                yield Checkbox(
                                    model,
                                    id=f"hide-model-{safe}",
                                    value=full in set(tool_prefs.hidden_models),
                                )

            with Horizontal(classes="action-row"):
                yield Button("Reset", id="reset-filters", variant="warning")

        with Vertical(id="tab-custom", classes="settings-tab hidden-tab"):
            yield Label("Add Custom Tool:")
            yield Label("Command:")
            yield TextArea("", id="custom-command", classes="setting-input")
            yield Label("Path:")
            yield TextArea("", id="custom-path", classes="setting-input")
            yield Label("", id="verify-status")
            with Horizontal(classes="action-row"):
                yield Button("Test", id="verify-custom", variant="success")
                yield Button("Add", id="add-custom", variant="primary")
            yield Label("Custom Tools:")
            with Vertical(id="custom-tools-list"):
                for ct in tool_prefs.custom_tools:
                    yield Label(f"{ct.command} ({ct.path})")

        with Horizontal(id="setting-actions"):
            yield Button("Save", id="settings-save", variant="primary")
            yield Button("Clear Cache", id="settings-clear-cache", variant="warning")
            yield Button("Cancel", id="settings-cancel", variant="default")


class ConfirmQuitScreen(Screen):
    """Confirm quit dialog."""

    def compose(self) -> ComposeResult:
        with Container(id="confirm-wrapper"):
            with Vertical(id="confirm-content"):
                yield Label("Quit OpenCode-Council?", classes="panel-label")
                yield Label("Are you sure you want to quit?")
                with Horizontal(id="confirm-actions"):
                    yield Button("Quit", id="confirm-yes", variant="error")
                    yield Button("Cancel", id="confirm-no", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "confirm-yes":
            self.app.exit()
        elif event.button.id == "confirm-no":
            self.app.pop_screen()

    def on_key(self, event) -> None:
        """Handle Escape to cancel quit."""
        if event.key == "escape":
            self.app.pop_screen()


class CacheRebuildScreen(Screen):
    """Modal screen shown during tool cache rebuild."""

    def __init__(self, show_use_old_cache: bool = True):
        super().__init__()
        self._rebuild_complete = False
        self._use_old_cache = False
        self._abort_flag = threading.Event()
        self._show_use_old_cache = show_use_old_cache

    def compose(self) -> ComposeResult:
        with Container(id="cache-rebuild-wrapper"):
            with Vertical(id="cache-rebuild-content"):
                if self._show_use_old_cache:
                    yield Label("Rebuilding tool cache...", classes="panel-label")
                    yield Label("This may take a moment...")
                    yield Button("Use Old Cache", id="use-old-cache", variant="warning")
                else:
                    yield Label("Building tool cache...", classes="panel-label")
                    yield Label("This may take a moment...")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "use-old-cache":
            self._abort_flag.set()
            self._use_old_cache = True
            self.app.pop_screen()

    @property
    def abort_flag(self) -> threading.Event:
        return self._abort_flag


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
        width: 60;
        max-height: 90%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    SettingsScreen .panel-label { text-style: bold; color: $primary; margin-bottom: 1; }
    SettingsScreen .setting-input { height: 3; margin-bottom: 1; }
    SettingsScreen #settings-tabs { layout: horizontal; height: 3; margin-bottom: 1; }
    SettingsScreen #settings-tabs Button { margin: 0 1; }
    SettingsScreen .settings-tab { layout: vertical; height: 20; overflow-y: auto; }
    SettingsScreen .hidden-tab { display: none; }
    SettingsScreen #tools-list { layout: vertical; height: auto; max-height: 12; overflow-y: auto; }
    SettingsScreen #tools-list Checkbox { margin: 0 0 0 1; }
    SettingsScreen .filter-list { layout: vertical; height: auto; max-height: 14; overflow-y: auto; }
    SettingsScreen .filter-list Checkbox { margin: 0 0 0 1; }
    SettingsScreen .filter-provider { text-style: bold; color: $accent; margin-top: 1; margin-left: 2; }
    SettingsScreen #filter-columns { layout: horizontal; height: auto; }
    SettingsScreen #filter-providers { width: 1fr; margin-right: 2; }
    SettingsScreen #filter-models { width: 2fr; }
    SettingsScreen .action-row { layout: horizontal; height: 3; margin-top: 1; }
    SettingsScreen .action-row Button { margin: 0 1; }
    SettingsScreen #setting-actions { layout: horizontal; height: 3; margin-top: 1; }
    SettingsScreen #setting-actions Button { width: 15; margin: 0 1; }

    ConfirmQuitScreen {
        layers: overlay;
    }
    ConfirmQuitScreen #confirm-wrapper {
        width: 100%;
        height: 100%;
        align: center middle;
    }
    ConfirmQuitScreen #confirm-content {
        align: center middle;
        width: 40;
        height: auto;
        background: $surface;
        border: thick $error;
    }
    ConfirmQuitScreen .panel-label { text-style: bold; color: $error; margin-bottom: 1; }
    ConfirmQuitScreen #confirm-actions { layout: horizontal; height: 3; margin-top: 1; }
    ConfirmQuitScreen #confirm-actions Button { width: 15; margin: 0 1; }

    CacheRebuildScreen {
        layers: overlay;
    }
    CacheRebuildScreen #cache-rebuild-wrapper {
        width: 100%;
        height: 100%;
        align: center middle;
    }
    CacheRebuildScreen #cache-rebuild-content {
        align: center middle;
        width: 40;
        height: auto;
        background: $surface;
        border: thick $accent;
        padding: 1 2;
    }
    CacheRebuildScreen .panel-label { text-style: bold; color: $accent; margin-bottom: 1; }
    """

    SCREENS = {
        "settings": SettingsScreen,
        "confirm_quit": ConfirmQuitScreen,
    }

    BINDINGS = [
        ("q", "handle_quit", "Quit"),
        ("escape", "handle_quit", "Quit"),
        ("ctrl+s", "push_screen('settings')", "Settings"),
        ("f1", "push_screen('settings')", "Settings"),
    ]

    def action_handle_quit(self) -> None:
        """Handle quit - pop from settings first, then confirm quit."""
        if len(self.screen_stack) > 1:
            self.pop_screen()
        else:
            self.push_screen(ConfirmQuitScreen())

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
        cache_ttl_seconds = cache_ttl * 60 if cache_ttl else 3600

        if is_cache_valid(cache_ttl_seconds):
            discovery = ToolDiscovery()
            tools = discovery.discover_all(cache_ttl=cache_ttl_seconds)
            self._apply_tools(config, tools)
            return

        if has_cache_file():
            modal = CacheRebuildScreen(show_use_old_cache=True)
            self.push_screen(modal)

            def do_rebuild():
                discovery = ToolDiscovery()
                tools = discovery.discover_all(cache_ttl=cache_ttl_seconds)
                self.call_from_thread(self._on_rebuild_complete, config, tools, modal)

            thread = threading.Thread(target=do_rebuild, daemon=True)
            thread.start()
        else:
            self._do_rebuild(config, cache_ttl_seconds)

    def _on_rebuild_complete(self, config, tools, modal) -> None:
        """Called from background thread when rebuild completes."""
        if modal._use_old_cache:
            discovery = ToolDiscovery()
            tools = discovery.load_cached()
        self._apply_tools(config, tools)
        if modal in self.screen_stack:
            self.pop_screen()

    def _do_rebuild(self, config, cache_ttl_seconds: int) -> None:
        """Run cache rebuild in executor and show modal without old cache option."""
        modal = CacheRebuildScreen(show_use_old_cache=False)
        self.push_screen(modal)

        def do_rebuild():
            discovery = ToolDiscovery()
            tools = discovery.discover_all(cache_ttl=cache_ttl_seconds)
            self.call_from_thread(
                self._on_rebuild_no_cache_complete, config, tools, modal
            )

        thread = threading.Thread(target=do_rebuild, daemon=True)
        thread.start()

    def _on_rebuild_no_cache_complete(self, config, tools, modal) -> None:
        """Called from background thread when rebuild completes (no old cache)."""
        self._apply_tools(config, tools)
        if modal in self.screen_stack:
            self.pop_screen()
        """Run cache rebuild in executor and apply tools when done."""

        def do_rebuild():
            discovery = ToolDiscovery()
            tools = discovery.discover_all(cache_ttl=cache_ttl_seconds)
            self.call_from_thread(self._apply_tools, config, tools)

        thread = threading.Thread(target=do_rebuild, daemon=True)
        thread.start()

    def _apply_tools(self, config, tools) -> None:
        """Apply discovered tools to the UI."""
        self.config = config
        model_panel = self.query_one(ModelSelectionPanel)
        model_panel.update_models(tools)
        self.update_run_button()

    def update_run_button(self) -> None:
        """Update run button based on task and selected models."""
        task_input = self.query_one("#task-input", TextArea)
        task_text = task_input.text.strip()

        model_panel = self.query_one(ModelSelectionPanel)
        selected = model_panel.get_selected()
        count = len(selected)

        count_label = self.query_one("#selected-count", Label)
        count_label.update(f"Selected: {count} models")

        run_button = self.query_one("#run-button", Button)
        run_button.disabled = count < 2 or not task_text

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
