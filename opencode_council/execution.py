"""Execution engine for running models in parallel."""

import asyncio
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from opencode_council.config import CouncilConfig


class ModelStatus(Enum):
    """Status of a model execution."""

    PENDING = "pending"
    RUNNING = "running"
    ANALYSIS_COMPLETE = "analysis_complete"
    PLAN_COMPLETE = "plan_complete"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ModelExecution:
    """Represents a single model execution."""

    tool_name: str
    model_name: str
    status: ModelStatus = ModelStatus.PENDING
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    error: Optional[str] = None


ANALYSIS_PROMPT_TEMPLATE = """Analyze the following task and provide a detailed analysis of what needs to be done, including:
- Problem understanding
- Requirements extraction
- Technical considerations
- Potential challenges

Task: {task}

Write your analysis to: {output_dir}/analysis.md"""

PLAN_PROMPT_TEMPLATE = """Based on your analysis, provide a solution or implementation plan.

Task: {task}

Write your plan to: {output_dir}/plan.md"""

COMMENTARY_PROMPT_TEMPLATE = """Review the following work from another model and provide commentary:

Model: {other_model}
Analysis:
{other_analysis}

Solution/Plan:
{other_plan}

Provide:
1. Commentary on their analysis
2. Commentary on their solution
3. Comparison with your own approach

Write to: {output_dir}"""


class ExecutionEngine:
    """Manages parallel execution of multiple models."""

    def __init__(
        self,
        config: CouncilConfig,
        run_dir: Path,
        progress_callback: Optional[Callable[[str, ModelStatus], None]] = None,
    ):
        self.config = config
        self.run_dir = run_dir
        self.progress_callback = progress_callback
        self.executions: dict[str, ModelExecution] = {}
        self.task: str = ""
        self._cancelled_models: set[str] = set()
        self._cancelled_global = False
        self.debug_log = self.run_dir / "debug.log"
        # Initialize debug log
        if self.config.debug_logging:
            self.debug_log.write_text(
                f"DEBUG LOG STARTED: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            )
            self.debug_log.write_text(f"Run directory: {self.run_dir}\n")
            self.debug_log.write_text("=" * 80 + "\n\n")

    def _debug(
        self, message: str, model: Optional[str] = None, phase: Optional[str] = None
    ) -> None:
        """Write debug log entry with timestamp."""
        if not self.config.debug_logging:
            return
        timestamp = time.strftime("%H:%M:%S.%f")[:-3]
        parts = [timestamp]
        if phase is not None:
            parts.append(f"[{phase:8}]")
        if model is not None:
            parts.append(f"| {model:30} |")
        parts.append(message)
        line = " ".join(parts) + "\n"
        with self.debug_log.open("a") as f:
            f.write(line)

    def set_task(self, task: str) -> None:
        """Set the task to execute."""
        self.task = task
        # Write task file to run directory
        task_file = self.run_dir / "TASK.md"
        task_file.write_text(self.task)
        # Write run config
        import json

        config_file = self.run_dir / "config.json"
        with config_file.open("w") as f:
            json.dump(
                {
                    "task": self.task,
                    "models": list(self.executions.keys()),
                    "started_at": time.time(),
                },
                f,
                indent=2,
            )

    def prepare_models(self, selected_models: list[str]) -> None:
        """Prepare model executions."""
        self.executions = {}
        available_models = [full_name for full_name, _ in self.config.get_all_models()]

        # Validate all requested models exist first
        invalid_models = []
        for full_name in selected_models:
            if full_name not in available_models:
                invalid_models.append(full_name)

        if invalid_models:
            raise ValueError(
                f"Requested models do not exist: {', '.join(invalid_models)}\nAvailable models: {', '.join(available_models[:20])}"
            )

        for full_name in selected_models:
            # Split on FIRST slash only (models may contain slashes)
            tool_name, model_name = full_name.split("/", 1)
            # Create unique directory for each full model name (replace slashes)
            safe_model_name = model_name.replace("/", "_")
            model_dir = self.run_dir / tool_name / safe_model_name
            model_dir.mkdir(parents=True, exist_ok=True)
            self.executions[full_name] = ModelExecution(
                tool_name=tool_name, model_name=model_name
            )

    async def run_analysis_phase(self) -> None:
        """Run analysis phase for all models."""
        semaphore = asyncio.Semaphore(self.config.max_concurrent_models)

        async def run_single(full_name: str, execution: ModelExecution) -> None:
            async with semaphore:
                if (
                    execution.status != ModelStatus.PENDING
                    or full_name in self._cancelled_models
                    or self._cancelled_global
                ):
                    return

                execution.status = ModelStatus.RUNNING
                execution.start_time = time.time()
                self._notify_progress(full_name, execution.status)

                try:
                    await self._run_model(execution, ANALYSIS_PROMPT_TEMPLATE)
                    execution.status = ModelStatus.ANALYSIS_COMPLETE
                except Exception as e:
                    execution.status = ModelStatus.FAILED
                    execution.error = str(e)

                execution.end_time = time.time()
                self._notify_progress(full_name, execution.status)

        tasks = [run_single(name, exec) for name, exec in self.executions.items()]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def run_plan_phase(self) -> None:
        """Run plan phase for all models."""
        semaphore = asyncio.Semaphore(self.config.max_concurrent_models)

        async def run_single(full_name: str, execution: ModelExecution) -> None:
            async with semaphore:
                if execution.status != ModelStatus.ANALYSIS_COMPLETE:
                    return

                execution.status = ModelStatus.RUNNING
                execution.start_time = time.time()
                self._notify_progress(full_name, execution.status)

                try:
                    await self._run_model(execution, PLAN_PROMPT_TEMPLATE)
                    execution.status = ModelStatus.PLAN_COMPLETE
                except Exception as e:
                    execution.status = ModelStatus.FAILED
                    execution.error = str(e)

                execution.end_time = time.time()
                self._notify_progress(full_name, execution.status)

        tasks = [run_single(name, exec) for name, exec in self.executions.items()]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_model(self, execution: ModelExecution, prompt_template: str) -> None:
        """Run a single model with the given prompt."""
        safe_model_name = execution.model_name.replace("/", "_")
        output_dir = self.run_dir / execution.tool_name / safe_model_name
        output_dir.mkdir(parents=True, exist_ok=True)

        # Always pass relative paths to LLMs so they write files correctly inside their directory
        prompt = prompt_template.format(
            task=self.task,
            output_dir=".",
        )

        # Add auto-approve flags for each tool
        cmd = [execution.tool_name, "run"]

        if execution.tool_name == "kilo":
            cmd.append("--auto")
        elif execution.tool_name == "opencode":
            cmd.append("--dangerously-skip-permissions")

        cmd.extend(
            [
                "--model",
                execution.model_name,
                "--format",
                "json",
                prompt,
            ]
        )

        model_full = f"{execution.tool_name}/{execution.model_name}"
        self._debug(
            f"Executing command: {' '.join(cmd)}", model=model_full, phase="EXECUTE"
        )
        self._debug(f"Working directory: {output_dir}", model=model_full)

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=output_dir,
        )

        stdout, stderr = await process.communicate()

        self._debug(f"Process exited with code: {process.returncode}", model=model_full)
        self._debug(f"STDOUT length: {len(stdout)} bytes", model=model_full)
        self._debug(f"STDERR length: {len(stderr)} bytes", model=model_full)

        # Also treat zero stdout as failure even if exit code is 0
        if process.returncode == 0 and len(stdout.strip()) == 0:
            error_msg = "Tool exited with success code but returned empty output"
            self._debug(f"FAILED: {error_msg}", model=model_full, phase="ERROR")
            raise RuntimeError(error_msg)

        if stderr:
            self._debug(f"--- STDERR BEGIN ---", model=model_full)
            for err_line in stderr.decode().splitlines():
                self._debug(f"STDERR: {err_line}", model=model_full)
            self._debug(f"--- STDERR END ---", model=model_full)

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            self._debug(f"FAILED: {error_msg}", model=model_full, phase="ERROR")
            raise RuntimeError(error_msg)

        # Collect final text output from json stream
        output_text = []
        for line in stdout.decode().splitlines():
            try:
                import json

                event = json.loads(line)
                if event.get("type") == "text" and "text" in event.get("part", {}):
                    output_text.append(event["part"]["text"])
            except:
                pass

        # Write full output to the model directory
        if output_text:
            if "analysis" in prompt_template.lower():
                out_file = output_dir / "analysis.md"
            elif "plan" in prompt_template.lower():
                out_file = output_dir / "plan.md"
            else:
                out_file = output_dir / "output.md"

            out_file.write_text("\n".join(output_text))

    async def run_commentary_phase(self) -> None:
        """Run commentary phase - each model reviews other models."""
        self._debug("Starting commentary phase", phase="PHASE")
        model_names = list(self.executions.keys())
        semaphore = asyncio.Semaphore(self.config.max_concurrent_models)
        COMMENTARY_TASK_TIMEOUT = 300  # 5 minutes per model
        COMMENTARY_PHASE_TIMEOUT = 900  # 15 minutes total phase

        # First wait for ALL models to finish plan phase before starting ANY commentary
        self._debug("Waiting for all models to complete plan phase", phase="COMMENT")
        for name, exec in self.executions.items():
            while exec.status not in (
                ModelStatus.PLAN_COMPLETE,
                ModelStatus.FAILED,
                ModelStatus.CANCELLED,
            ):
                await asyncio.sleep(0.1)

        self._debug(
            "All models completed plan phase, starting commentary tasks",
            phase="COMMENT",
        )

        # Now pre-calculate completed models once BEFORE starting any tasks
        completed_models_global = [
            name
            for name, exec in self.executions.items()
            if exec.status == ModelStatus.PLAN_COMPLETE
        ]
        self._debug(
            f"Total completed models ready for commentary: {len(completed_models_global)}",
            phase="COMMENT",
        )

        async def run_single(full_name: str, execution: ModelExecution) -> None:
            self._debug(
                f"Preparing commentary task for {full_name}",
                model=full_name,
                phase="COMMENT",
            )

            async with semaphore:
                self._debug(
                    f"Acquired semaphore for {full_name}",
                    model=full_name,
                    phase="COMMENT",
                )

                if execution.status != ModelStatus.PLAN_COMPLETE:
                    self._debug(
                        f"Skipping {full_name} - not in PLAN_COMPLETE status",
                        model=full_name,
                        phase="COMMENT",
                    )
                    return

                safe_model_name = execution.model_name.replace("/", "_")
                commentary_dir = (
                    self.run_dir / execution.tool_name / safe_model_name / "comments"
                )
                commentary_dir.mkdir(parents=True, exist_ok=True)

                execution.status = ModelStatus.RUNNING
                execution.start_time = time.time()
                self._notify_progress(full_name, execution.status)
                self._debug(
                    f"Started commentary run for {full_name}",
                    model=full_name,
                    phase="COMMENT",
                )

                # Use pre-calculated completed list - NO RACE CONDITION
                completed_models = [
                    name for name in completed_models_global if name != full_name
                ]

                self._debug(
                    f"Found {len(completed_models)} models to comment on",
                    model=full_name,
                    phase="COMMENT",
                )

                for other_name in completed_models:
                    self._debug(
                        f"Commenting on {other_name}", model=full_name, phase="COMMENT"
                    )
                    try:
                        other_tool, other_model = other_name.split("/", 1)
                        other_safe_name = other_model.replace("/", "_")
                        analysis_path = (
                            self.run_dir / other_tool / other_safe_name / "analysis.md"
                        )
                        plan_path = (
                            self.run_dir / other_tool / other_safe_name / "plan.md"
                        )

                        other_analysis = (
                            analysis_path.read_text() if analysis_path.exists() else ""
                        )
                        other_plan = plan_path.read_text() if plan_path.exists() else ""

                        # Replace slashes with hyphens to avoid subdirectories
                        safe_other_name = other_name.replace("/", "-")
                        prompt = COMMENTARY_PROMPT_TEMPLATE.format(
                            other_model=other_model,
                            other_analysis=other_analysis,
                            other_plan=other_plan,
                            output_dir=f"{safe_other_name}.md",
                        )

                        cmd = [execution.tool_name, "run"]

                        if execution.tool_name == "kilo":
                            cmd.append("--auto")
                        elif execution.tool_name == "opencode":
                            cmd.append("--dangerously-skip-permissions")

                        cmd.extend(
                            [
                                "--model",
                                execution.model_name,
                                "--format",
                                "json",
                                prompt,
                            ]
                        )

                        self._debug(
                            f"Running commentary command for {other_name}",
                            model=full_name,
                            phase="EXECUTE",
                        )

                        process = await asyncio.create_subprocess_exec(
                            *cmd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            cwd=commentary_dir,
                        )

                        stdout, stderr = await process.communicate()

                        self._debug(
                            f"Commentary command completed for {other_name} with code {process.returncode}",
                            model=full_name,
                            phase="EXECUTE",
                        )

                        if process.returncode == 0:
                            output_text = []
                            for line in stdout.decode().splitlines():
                                try:
                                    import json

                                    event = json.loads(line)
                                    if event.get(
                                        "type"
                                    ) == "text" and "text" in event.get("part", {}):
                                        output_text.append(event["part"]["text"])
                                except:
                                    pass

                            if output_text:
                                comment_file = commentary_dir / f"{safe_other_name}.md"
                                comment_file.write_text("\n".join(output_text))
                                self._debug(
                                    f"Wrote commentary file for {other_name}",
                                    model=full_name,
                                    phase="COMMENT",
                                )
                            else:
                                self._debug(
                                    f"WARNING: Model returned empty commentary output for {other_name}",
                                    model=full_name,
                                    phase="WARNING",
                                )
                                raise RuntimeError(
                                    f"Model returned empty output when commenting on {other_name}"
                                )

                    except Exception as e:
                        execution.error = str(e)
                        self._debug(
                            f"Error commenting on {other_name}: {str(e)}",
                            model=full_name,
                            phase="ERROR",
                        )

                if execution.error:
                    execution.status = ModelStatus.FAILED
                    self._debug(
                        f"Commentary failed for {full_name}: {execution.error}",
                        model=full_name,
                        phase="ERROR",
                    )
                else:
                    execution.status = ModelStatus.COMPLETE
                    self._debug(
                        f"Completed commentary for {full_name}",
                        model=full_name,
                        phase="COMMENT",
                    )

                execution.end_time = time.time()
                self._notify_progress(full_name, execution.status)

        # Fix: wrap each task with timeout and run sequentially with as_completed to avoid Python 3.10 gather deadlock
        self._debug(
            f"Creating {len(self.executions)} commentary tasks", phase="COMMENT"
        )

        try:
            # Create tasks with individual timeouts
            tasks = []
            for name, exec in self.executions.items():
                task = asyncio.create_task(
                    asyncio.wait_for(
                        run_single(name, exec), timeout=COMMENTARY_TASK_TIMEOUT
                    )
                )
                tasks.append(task)

            self._debug(
                f"Waiting for all commentary tasks to complete", phase="COMMENT"
            )

            # Use as_completed instead of gather to avoid deadlock
            for coro in asyncio.as_completed(tasks, timeout=COMMENTARY_PHASE_TIMEOUT):
                try:
                    await coro
                except asyncio.TimeoutError:
                    self._debug("Commentary task timed out", phase="ERROR")
                except Exception as e:
                    self._debug(f"Commentary task failed: {str(e)}", phase="ERROR")

        except asyncio.TimeoutError:
            self._debug("Commentary phase global timeout reached", phase="ERROR")
        except Exception as e:
            self._debug(f"Commentary phase crashed: {str(e)}", phase="ERROR")

        self._debug("Commentary phase completed", phase="PHASE")

    def _notify_progress(self, model_name: str, status: ModelStatus) -> None:
        """Notify progress callback."""
        if self.progress_callback:
            self.progress_callback(model_name, status)

    def get_elapsed_time(self, model_name: str) -> float:
        """Get elapsed time for a model."""
        execution = self.executions.get(model_name)
        if not execution or not execution.start_time:
            return 0.0
        end = execution.end_time or time.time()
        return end - execution.start_time

    def get_completed_count(self) -> int:
        """Get count of completed executions."""
        return sum(
            1
            for e in self.executions.values()
            if e.status in (ModelStatus.COMPLETE, ModelStatus.FAILED)
        )

    def get_total_count(self) -> int:
        """Get total number of executions."""
        return len(self.executions)

    def get_status(self, model_name: str) -> ModelStatus:
        """Get status of a model."""
        execution = self.executions.get(model_name)
        return execution.status if execution else ModelStatus.PENDING

    def cancel_model(self, model_name: str) -> None:
        """Cancel a single running model."""
        self._cancelled_models.add(model_name)
        if model_name in self.executions:
            self.executions[model_name].status = ModelStatus.CANCELLED
            self._notify_progress(model_name, ModelStatus.CANCELLED)

    def cancel_all(self) -> None:
        """Cancel all running models."""
        self._cancelled_global = True
        for model_name in self.executions:
            self.cancel_model(model_name)

    def get_failed_models(self) -> list[tuple[str, str]]:
        """Get list of failed models and their errors."""
        return [
            (name, exec.error)
            for name, exec in self.executions.items()
            if exec.status == ModelStatus.FAILED and exec.error
        ]

    def get_completed_models(self) -> list[str]:
        """Get list of successfully completed models."""
        return [
            name
            for name, exec in self.executions.items()
            if exec.status == ModelStatus.COMPLETE
        ]
