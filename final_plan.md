# OpenCode-Council - Final Implementation Plan

## Project Overview

OpenCode-Council is a multi-model collaborative analysis tool that runs multiple opencode-compatible AI agents simultaneously on the same problem, enabling diverse perspectives and cross-analysis.

## Core Workflow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         USER WORKFLOW                               │
├─────────────────────────────────────────────────────────────────────┤
│  1. Input Task: Enter problem/idea in upper panel (textbox)        │
│  2. Select Models: Choose from model list in lower panel           │
│  3. Execute: Run all selected models in parallel                   │
│  4. Monitor: Progress bar shows completion status + timer          │
│  5. Preview: Review analysis, solutions, and cross-comments        │
└─────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
<current_dir>/
└── council/
    └── <timestamp>/
        ├── config.json                 # Run configuration
        └── <model_name>/
            ├── analysis.md            # Model's analysis of the task
            ├── plan.md                # Model's solution/implementation plan
            └── comments/
                ├── <other_model_1>.md # Commentary on model 1's work
                ├── <other_model_2>.md # Commentary on model 2's work
                └── ...
```

## Technical Stack

- **Language**: Python 3.10+
- **TUI Framework**: Textual
- **CLI Integration**: subprocess (for running opencode/kilo commands)
- **Configuration**: JSON files

## Feature Specifications

### 1. Auto-Discovery System

**Purpose**: Automatically detect installed opencode-compatible tools and their available models.

**Known Compatible Tools**:
- `opencode` - Original opencode CLI
- `kilo` - Kilo CLI (fork of opencode)

**Discovery Process**:
1. Scan for known CLI tools using `which <command>`
2. For each found tool:
   - Run `<tool> --version` to get version
   - Run `<tool> models` to get available models
   - Run `<tool> auth list` to check authenticated providers
3. Store results in configuration

**Configuration File** (`council/config.json`):
```json
{
  "tools": {
    "opencode": {
      "command": "opencode",
      "path": "/usr/local/bin/opencode",
      "version": "v1.2.3",
      "available_models": [
        "anthropic/claude-sonnet-4-20250514",
        "google/gemini-2.5-pro",
        "openai/gpt-5.2"
      ],
      "enabled": true
    },
    "kilo": {
      "command": "kilo",
      "path": "/usr/local/bin/kilo",
      "version": "v7.1.21",
      "available_models": [
        "anthropic/claude-4.5-sonnet",
        "openai/gpt-5.1-codex"
      ],
      "enabled": true
    }
  },
  "selected_models": [],
  "preferences": {
    "default_output_dir": "council",
    "parallel_execution": true,
    "max_concurrent_models": 4
  }
}
```

### 2. TUI Interface

**Layout**: Split panel design (upper/lower)

**Upper Panel - Task Input**:
- Large text input area for task description
- Multi-line input with scrolling
- Placeholder text: "Enter your task or idea here..."

**Lower Panel - Model Selection**:
- List of available models with checkboxes
- Show tool icon (🔵 opencode / 🟢 kilo) next to each model
- Gray out models from unauthenticated providers
- Keyboard navigation with Tab to switch panels

**Navigation**:
- `Tab`: Switch between upper/lower panel
- `Space`: Toggle model selection
- `Enter`: Start execution
- `q`: Quit application

### 3. Execution Phase

**Parallel Execution** (Step 1 & 2):
- All selected models run simultaneously
- Each model gets the same task prompt

**Model Prompts**:

*Analysis Prompt*:
```
Analyze the following task and provide a detailed analysis of what needs to be done, including:
- Problem understanding
- Requirements extraction
- Technical considerations
- Potential challenges

Task: <user_task>

Write your analysis to: council/<model_name>/analysis.md
```

*Plan/Solution Prompt* (after analysis completes):
```
Based on your analysis, provide a solution or implementation plan.

Task: <user_task>

Write your plan to: council/<model_name>/plan.md
```

**Progress Display**:
- Progress bar showing completed/total models
- Timer showing elapsed time
- Individual model status indicators
- Real-time status updates

### 4. Cross-Commentary Phase (Step 4)

After all models complete their analysis and plans:

**Commentary Prompt**:
```
Review the following work from another model and provide commentary:

Model: <other_model_name>
Analysis:
<read from council/<other_model_name>/analysis.md>

Solution/Plan:
<read from council/<other_model_name>/plan.md>

Provide:
1. Commentary on their analysis
2. Commentary on their solution
3. Comparison with your own approach

Write to: council/<model_name>/comments/<other_model_name>.md
```

### 5. Preview System

**Split-Panel Viewer**:
- Left panel: Model/file selector (checkboxes)
- Right panel: Live preview of selected content

**Navigation**:
- `Tab`: Switch between selector and preview
- `Up/Down`: Navigate models/files
- `Enter`: Cycle through files (analysis.md → plan.md → comments/)
- `Space`: Toggle model selection for final review

### 6. Preferences/Settings

**Accessible via**: Menu or keyboard shortcut (`Ctrl+,`)

**Configurable Options**:
- Default output directory
- Max concurrent models
- Auto-refresh models on startup
- Theme (dark/light)
- Edit config.json directly

## Non-Interactive Execution

OpenCode supports non-interactive mode via:
```bash
opencode run "<prompt>" --format json
```

This enables:
- Scripted automation
- No user input required
- Auto-approval of permissions
- JSON output for parsing

## Implementation Phases

### Phase 1: Core Infrastructure
- Project setup (Python + Textual)
- CLI discovery system
- Configuration management
- Basic TUI layout

### Phase 2: Model Discovery
- Auto-detect installed tools
- Fetch available models
- Build model selection menu
- Preferences panel

### Phase 3: Execution Engine
- Parallel subprocess management
- Progress tracking
- Timer implementation
- Output file handling

### Phase 4: Cross-Analysis
- Read other models' outputs
- Generate commentary prompts
- File management

### Phase 5: Preview System
- Split-panel viewer
- File browser
- Content display

### Phase 6: Polish
- Error handling
- Edge cases
- Documentation

## Error Handling

- Tool not found: Show warning, disable tool in config
- Model not available: Gray out, show tooltip
- Execution failure: Log error, continue with other models
- Permission denied: Display helpful message

## Extensibility

Adding new opencode-compatible forks:
1. Add tool name to `KNOWN_TOOLS` list
2. Implement same interface (--version, models, auth list)
3. Tool auto-detected on next discovery run

## File Outputs

All outputs are Markdown files for:
- Human readability
- Easy comparison
- No special tooling required
- Standard format across models