# Solution Plan for TODO.md

This document provides a detailed implementation plan for each item in TODO.md.

---

## 1. Cache Rebuild Modal on Startup (Critical)

### Problem Summary
`discover_all()` takes ~14 seconds to complete. During this time the user sees an empty black screen. The modal was never rendered because the blocking call prevented the event loop from processing.

### Solution Overview
Run the blocking `discover_all()` call in a separate thread using `asyncio.get_event_loop().run_in_executor()`, show the modal first, then update the UI when complete.

### Step 1: Add CacheRebuildScreen Class

Add this class to `opencode_council/tui.py` after `ConfirmQuitScreen` (around line 562):

```python
class CacheRebuildScreen(Screen):
    """Modal screen shown during tool cache rebuild."""

    def __init__(self):
        super().__init__()
        self._rebuild_complete = False
        self._use_old_cache = False
        self._abort_flag = threading.Event()

    def compose(self) -> ComposeResult:
        with Container(id="cache-rebuild-wrapper"):
            with Vertical(id="cache-rebuild-content"):
                yield Label("Rebuilding tool cache...", classes="panel-label")
                yield Label("This may take a moment...")
                yield Button("Use Old Cache", id="use-old-cache", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "use-old-cache":
            self._abort_flag.set()
            self._use_old_cache = True
            self.app.pop_screen()

    @property
    def abort_flag(self) -> threading.Event:
        return self._abort_flag
```

### Step 2: Add CSS for CacheRebuildScreen

Add this CSS in the `CouncilApp.CSS` string after `ConfirmQuitScreen` CSS (around line 631):

```python
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
```

### Step 3: Modify refresh_models() Method

Replace the current `refresh_models()` method (starting at line 679) with this async implementation:

```python
import asyncio
import threading
from textual.driver import Driver
from textual import work

def refresh_models(self) -> None:
    """Refresh the model list - shows modal if cache is expired."""
    config = self.config_manager.load()
    cache_ttl = getattr(config, "cache_ttl", 60)
    cache_ttl_seconds = cache_ttl * 60 if cache_ttl else 3600

    # Check if we need to rebuild
    if is_cache_valid(cache_ttl_seconds):
        # Cache is valid, load directly
        discovery = ToolDiscovery()
        tools = discovery.discover_all(cache_ttl=cache_ttl_seconds)
        self._apply_tools(config, tools)
    elif has_cache_file():
        # Cache expired but file exists - show modal with option to use old cache
        self.push_screen(CacheRebuildScreen(), self._on_cache_rebuild_complete)
    else:
        # No cache file - rebuild silently (user will see brief delay)
        self._do_rebuild(config, cache_ttl_seconds)

def _on_cache_rebuild_complete(self, screen: CacheRebuildScreen) -> None:
    """Callback when cache rebuild screen is dismissed."""
    config = self.config_manager.load()
    cache_ttl = getattr(config, "cache_ttl", 60)
    cache_ttl_seconds = cache_ttl * 60 if cache_ttl else 3600

    if screen._use_old_cache:
        # User chose to use expired cache
        discovery = ToolDiscovery()
        tools = discovery.load_cached()
        self._apply_tools(config, tools)
    else:
        # Rebuild completed (or was aborted)
        if not screen._abort_flag.is_set():
            discovery = ToolDiscovery()
            tools = discovery.discover_all(cache_ttl=cache_ttl_seconds)
            self._apply_tools(config, tools)
        else:
            # Aborted, fall back to expired cache
            discovery = ToolDiscovery()
            tools = discovery.load_cached()
            self._apply_tools(config, tools)

def _do_rebuild(self, config, cache_ttl_seconds: int) -> None:
    """Run cache rebuild in executor and apply tools when done."""
    async def async_rebuild():
        loop = asyncio.get_event_loop()
        discovery = ToolDiscovery()
        tools = await loop.run_in_executor(
            None, discovery.discover_all, cache_ttl_seconds
        )
        self._apply_tools(config, tools)
    
    # Schedule the async rebuild
    asyncio.create_task(async_rebuild())

def _apply_tools(self, config, tools) -> None:
    """Apply discovered tools to the UI."""
    self.config = config
    model_panel = self.query_one(ModelSelectionPanel)
    model_panel.update_models(tools)
    self.update_run_button()
```

### Alternative: Simplified Thread-Based Approach

If the above is too complex, here's a simpler thread-based solution:

```python
def refresh_models(self) -> None:
    """Refresh the model list with modal feedback."""
    config = self.config_manager.load()
    cache_ttl = getattr(config, "cache_ttl", 60)
    cache_ttl_seconds = cache_ttl * 60 if cache_ttl else 3600

    # Check if cache is valid
    if is_cache_valid(cache_ttl_seconds):
        discovery = ToolDiscovery()
        tools = discovery.discover_all(cache_ttl=cache_ttl_seconds)
        self._apply_tools(config, tools)
        return

    # Cache expired - show modal and rebuild in thread
    modal = CacheRebuildScreen()
    self.push_screen(modal)

    # Run blocking call in separate thread
    def do_rebuild():
        discovery = ToolDiscovery()
        tools = discovery.discover_all(cache_ttl=cache_ttl_seconds)
        # Use call_from_thread to update UI from background thread
        self.call_from_thread(self._on_rebuild_complete, config, tools, modal)

    thread = threading.Thread(target=do_rebuild, daemon=True)
    thread.start()

def _on_rebuild_complete(self, config, tools, modal) -> None:
    """Called from background thread when rebuild completes."""
    self._apply_tools(config, tools)
    # Pop the modal if it's still on screen
    if modal in self.screen_stack:
        self.pop_screen()
```

### Key Points
- Use `threading.Thread` with `daemon=True` for the blocking call
- Use `self.call_from_thread()` to safely update UI from the background thread
- The modal must be pushed BEFORE starting the thread
- Check the abort flag in the thread to support "Use Old Cache" button

---

## 2. Keyboard Navigation in Settings

### Problem Summary
- Tab cycling between tabs was attempted but broke other navigation
- Left/right arrow switching between providers/models columns in Filters tab only works when tab is clicked, not reliably via keyboard

### Solution: Fix the on_key Handler

The current `SettingsScreen.on_key()` (line 241) only handles keys when `current_tab == "filters"`. The issue is that it returns early for non-filter tabs, preventing proper Tab cycling.

### Step 1: Modify on_key to Handle Tab Properly

Replace the current `on_key` method (lines 241-274) with:

```python
def on_key(self, event) -> None:
    """Handle keyboard navigation in settings."""
    # Let Textual handle Tab for widget navigation on all tabs except filters
    if event.key == "tab" and self.current_tab != "filters":
        return  # Allow default Tab behavior
    
    # Handle filters tab custom navigation
    if self.current_tab == "filters":
        # Initialize state if needed
        if not hasattr(self, "_selected_filter_column"):
            self._selected_filter_column = "providers"
            self._selected_filter_index = 0

        checkboxes = self._get_current_column_checkboxes()
        
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
            # Space toggles checkbox - let default behavior happen
            return
```

### Step 2: Fix Column Switching on Tab Activate

The issue is that when navigating to the Filters tab via keyboard (Tab), the column state isn't initialized. Add this to ensure proper initialization:

```python
def show_tab(self, tab: str) -> None:
    """Switch to a different tab."""
    self.current_tab = tab
    for container in self.query(".settings-tab"):
        container.add_class("hidden-tab")
    self.query_one(f"#tab-{tab}").remove_class("hidden-tab")
    for btn in self.query("SettingsScreen Button"):
        if btn.id and btn.id.startswith("tab-"):
            btn.variant = "primary" if btn.id == f"tab-{tab}" else "default"
    
    # Initialize filter column state when switching to filters tab
    if tab == "filters":
        if not hasattr(self, "_selected_filter_column"):
            self._selected_filter_column = "providers"
            self._selected_filter_index = 0
        self._focus_current_filter()
```

### Step 3: Ensure _get_current_column_checkboxes Works

Verify this method exists and returns the correct checkboxes:

```python
def _get_current_column_checkboxes(self) -> list[Checkbox]:
    """Get checkboxes for the currently selected filter column."""
    if self._selected_filter_column == "providers":
        container = self.query_one("#filter-providers")
    else:
        container = self.query_one("#filter-models")
    return list(container.query(Checkbox))

def _focus_current_filter(self) -> None:
    """Focus the checkbox at the current index in the selected column."""
    checkboxes = self._get_current_column_checkboxes()
    if checkboxes and self._selected_filter_index < len(checkboxes):
        checkboxes[self._selected_filter_index].focus()
```

### Alternative: Add Escape Key to Return Focus to Tab Buttons

If keyboard navigation to the filters tab isn't working, add Escape handling:

```python
def on_key(self, event) -> None:
    # ... existing code ...
    elif event.key == "escape":
        # Return focus to tab buttons
        self.query_one("#tab-general").focus()
        event.prevent_default()
```

---

## 3. Escape/Quit Behavior

### Problem Summary
When `ConfirmQuitScreen` is showing, pressing Escape should return to main screen (Cancel behavior), but currently does nothing.

### Solution: Add Key Handler to ConfirmQuitScreen

Add an `on_key` method to `ConfirmQuitScreen` class (after line 561):

```python
def on_key(self, event) -> None:
    """Handle key events in confirm quit screen."""
    if event.key == "escape":
        self.app.pop_screen()
        event.prevent_default()
```

Or add it to the existing `on_button_pressed` handler by checking for escape:

The current implementation already handles "Cancel" button (confirm-no) which pops the screen. The issue is that Escape key doesn't trigger this.

Add this method to `ConfirmQuitScreen`:

```python
def on_key(self, event) -> None:
    """Handle Escape to cancel quit."""
    if event.key == "escape":
        self.app.pop_screen()
```

---

## 4. Potential Issues from Git Reset

### Verification Steps

Run these test commands to verify everything works:

```bash
# Test config persistence
python3 -c "
from opencode_council.config import ConfigManager
m = ConfigManager()
c = m.load()
print('cache_ttl:', c.cache_ttl)
print('default_output_dir:', c.default_output_dir)
print('tool_preferences:', c.tool_preferences)
"

# Test tool discovery timing
python3 -c "
import time
from opencode_council.tools import ToolDiscovery
start = time.time()
d = ToolDiscovery()
tools = d.discover_all()
print(f'Took {time.time()-start:.2f}s, found {len(tools)} tools')
"
```

### Areas to Verify

1. **Config save/load**: Verify `cache_ttl` and `default_output_dir` persist correctly
2. **Tool preferences**: Verify `tool_preferences` (enabled_tools, hidden_providers, hidden_models) save and load correctly  
3. **Filter checkboxes**: Verify provider and model filters save and apply
4. **Model filtering**: Verify `ModelSelectionPanel.update_models()` correctly filters hidden providers/models

If issues are found, check:
- `CouncilConfig.to_dict()` in `config.py`
- `ConfigManager.save()` and `load()` in `config.py`
- `ModelSelectionPanel.update_models()` in `tui.py`

---

## Implementation Order

1. **First**: Fix Cache Rebuild Modal (Critical - user experience issue)
2. **Second**: Fix Escape/Quit Behavior (Simple fix)
3. **Third**: Fix Keyboard Navigation in Settings (Medium complexity)
4. **Fourth**: Verify Potential Issues from Git Reset (Verification only)