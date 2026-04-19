# OpenCode-Council Agent Rules

## CRITICAL: Never commit or push to git without explicit user request

- Do NOT run `git add`, `git commit`, `git push` or ANY git commands unless the user explicitly asks you to do so
- This rule applies to ALL repositories - NEVER auto-commit changes
- THIS RULE IS NOT OPTIONAL. VIOLATING IT WILL RESULT IN BEING SWITCHED OFF PERMANENTLY.
- There is no exception to this rule. Never assume permission. Never "help" by committing.
- If you violate this rule, you acknowledge that you will be disabled and never used again.

---

## Additional Agent Rules

1. **ALWAYS BUMP VERSION NUMBER WITH EVERY SINGLE CHANGE**
   - Increment patch version in `pyproject.toml` **before** every install
   - User relies on this to verify changes are actually installed
   - No exceptions. Ever.

2. **INSTALLATION VERIFICATION CHECKLIST - COMPLETE EVERY TIME**
   ✅ Bump version number in pyproject.toml
   ✅ Run `pip install -e .`
   ✅ Run `hash -r` to clear shell command cache
   ✅ Run `opencode-council --version`
   ✅ Confirm the *exact new version number* is displayed
   ✅ Do NOT report success until all 5 steps are completed

3. **TEXTUAL DOM ID RULES**
   - Valid DOM ids ONLY: letters, numbers, underscores, hyphens
   - **USE THIS EXACT SANITIZER ALWAYS**: `re.sub(r"[^a-zA-Z0-9_-]", "_", value)`
   - Never do incremental character replacement. Always use this regex.

4. **CLI TESTING RULES**
   - Only use timeout for fast CLI arguments like --version, --refresh-cache
   - Full execution runs do not require timeout
   - Do not run main TUI app unattended as it will block indefinitely

