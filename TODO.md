# OpenCode-Council TODO

## Critical: Agent Rules

See `AGENTS.md` for rules that MUST be followed. The previous agent violated git rules multiple times.

## Failed: Cache Rebuild Modal on Startup

### The Problem
When the app starts and the tool cache is expired, `discover_all()` takes ~14 seconds to complete. During this time the user sees an empty black screen with no feedback, making the app appear frozen.

### What Was Attempted
A `CacheRebuildScreen` modal was created to show during cache rebuild. It should:
- Appear centered on screen when cache is expired and needs rebuilding
- Show "Rebuilding tool cache..." message
- Offer a "Use Old Cache" button (only if an expired cache file exists on disk)
- Automatically close and continue when rebuild completes
- If user clicks "Use Old Cache", abort the rebuild and load the expired cache instead

### Why It Failed
The modal screen was pushed via `push_screen()` but the rebuild (a blocking ~14s call) either:
1. Blocked the event loop so the modal never rendered (with `call_later`)
2. Ran in a `@work` thread but the screen was popped before it was visible (async worker completed too fast in test, but in reality the screen was never shown because the blocking call prevented rendering)

### What Needs to Happen
The rebuild (`ToolDiscovery().discover_all()`) is a **synchronous blocking call** (~14 seconds). To show a modal during this:
1. Push the modal screen first
2. Run `discover_all()` in a **separate thread** (not `@work` which may not work correctly with blocking calls)
3. Use `asyncio.get_event_loop().run_in_executor()` or a threading approach
4. When complete, use `call_from_thread()` to update the UI and pop the screen
5. The "Use Old Cache" button must set an abort flag that the thread checks

### Relevant Files
- `opencode_council/tui.py` - `CouncilApp.refresh_models()` (line ~679), needs CacheRebuildScreen class
- `opencode_council/tools.py` - `ToolDiscovery.discover_all()` (line ~131, takes ~14s), `has_cache_file()`, `is_cache_valid()`, `load_cached()`

### Existing Helper Functions in tools.py
- `has_cache_file()` - returns bool if cache file exists
- `is_cache_valid(ttl)` - returns bool if cache is not expired
- `_load_expired_cache()` - returns dict of cached data even if expired
- `ToolDiscovery.load_cached()` - returns tools from expired cache as DiscoveredTool objects

### CSS Reference (working centered modal pattern from ConfirmQuitScreen)
```css
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
```

### Timing Data
```
discover_all() took 13.85s with 2 tools (opencode: 63 models, kilo: 10 models)
```

---

## Incomplete: Keyboard Navigation in Settings

### The Problem
Keyboard navigation in the settings screen is inconsistent across tabs.

### Current State
- **General tab**: Tab cycles through widgets (works via Textual defaults)
- **Tools tab**: Checkboxes are reachable via Tab (works)
- **Filters tab**: Has custom `on_key` handler for left/right (switch columns) and up/down (navigate within column), and space (toggle). This partially works.
- **Custom tab**: Tab cycles through widgets (works via Textual defaults)

### Issues
- Tab cycling between tabs (General → Tools → Filters → Custom) was attempted multiple times with different approaches and kept breaking other navigation
- The filter navigation (up/down within provider/model columns) works but switching columns with left/right only works when the filters tab is already active via button click, not reliably via keyboard

### What Should Work
1. Tab should cycle through all settings widgets normally (Textual default behavior)
2. In the Filters tab specifically:
   - Left/Right arrows: switch between providers column and models column
   - Up/Down arrows: navigate within current column
   - Space: toggle checkbox
3. This should not interfere with Tab cycling through widgets on other tabs

### Relevant Code
- `SettingsScreen.on_key()` in `tui.py`
- `SettingsScreen._get_current_column_checkboxes()`
- `SettingsScreen._focus_current_filter()`

---

## Incomplete: Escape/Quit Behavior

### Current State
- Escape/Q while in settings screen → pops back to main screen (works)
- Escape/Q on main screen → shows ConfirmQuitScreen (works)
- ConfirmQuitScreen is centered (works)

### Issue
When ConfirmQuitScreen is showing, pressing Escape should return to main screen (Cancel behavior), not do nothing or stack another screen.

### Relevant Code
- `CouncilApp.action_handle_quit()` in `tui.py`
- `ConfirmQuitScreen` class

---

## Potential Issues from Git Reset

The previous agent ran `git reset` without permission, which may have left the codebase in an inconsistent state. Key areas to verify:

1. **Config save/load**: Verify `cache_ttl` and `default_output_dir` persist correctly after save/restart
2. **Tool preferences**: Verify `tool_preferences` (enabled_tools, hidden_providers, hidden_models) save and load correctly
3. **Filter checkboxes**: Verify that checking/unchecking provider and model filters in settings actually saves and applies on next startup
4. **Model filtering**: Verify that `ModelSelectionPanel.update_models()` correctly filters out hidden providers and models based on `tool_preferences`

### Test Commands
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

---

## Architecture Notes

### Tech Stack
- Python Textual TUI framework (v8.2.3)
- Python 3.10

### Key Files
- `opencode_council/tui.py` - Main TUI (CouncilApp, SettingsScreen, ConfirmQuitScreen, panels)
- `opencode_council/config.py` - CouncilConfig, ToolPreferences, ToolPreference, ConfigManager
- `opencode_council/tools.py` - ToolDiscovery, cache functions, DiscoveredTool
- `opencode_council/execution.py` - ExecutionEngine, ModelStatus
- `council/config.json` - Saved config (output dir, cache TTL, tool preferences)
- `~/.cache/opencode-council/tools_cache.json` - Tool cache file

### Config Structure
```json
{
  "tools": {},
  "selected_models": [],
  "preferences": {
    "default_output_dir": "council",
    "parallel_execution": true,
    "max_concurrent_models": 4,
    "auto_refresh_models": true,
    "theme": "dark",
    "cache_ttl": 60
  },
  "tool_preferences": {
    "enabled_tools": [],
    "hidden_providers": [],
    "hidden_models": [],
    "custom_tools": []
  }
}
```

### Important Gotchas
- Textual CSS does NOT support `top`, `left`, `right`, `bottom` positioning properties
- Textual CSS `position: absolute` exists but positioning properties don't
- Use `layers: overlay` + `align: center middle` + width/height 100% for centered modals
- `@work` decorator may not work correctly with synchronous blocking calls
- TextArea `.text` can contain newlines - always `.strip().split('\n')[0]` for settings inputs
- Widget IDs must be unique across the entire screen (not just siblings) - use sanitized IDs for dynamic checkboxes
- `ConfigManager.save()` serializes via `CouncilConfig.to_dict()` which writes to `council/config.json`
- Cache TTL in config is in **minutes**, but `discover_all()` expects **seconds** - multiply by 60
