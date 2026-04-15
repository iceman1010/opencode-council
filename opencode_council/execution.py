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

Write to: {output_dir}/{other_model}.md"""


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

    def set_task(self, task: str) -> None:
        """Set the task to execute."""
        self.task = task

    def prepare_models(self, selected_models: list[str]) -> None:
        """Prepare model executions."""
        self.executions = {}
        for full_name in selected_models:
            if "/" not in full_name:
                continue
            tool_name, model_name = full_name.split("/", 1)
            model_dir = self.run_dir / tool_name
            model_dir.mkdir(parents=True, exist_ok=True)
            self.executions[full_name] = ModelExecution(
                tool_name=tool_name, model_name=model_name
            )

    async def run_analysis_phase(self) -> None:
        """Run analysis phase for all models."""
        for full_name, execution in self.executions.items():
            if execution.status != ModelStatus.PENDING:
                continue

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

    async def run_plan_phase(self) -> None:
        """Run plan phase for all models."""
        for full_name, execution in self.executions.items():
            if execution.status != ModelStatus.ANALYSIS_COMPLETE:
                continue

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

    async def _run_model(
        self, execution: ModelExecution, prompt_template: str
    ) -> None:
        """Run a single model with the given prompt."""
        output_dir = self.run_dir / execution.tool_name

        prompt = prompt_template.format(
            task=self.task,
            output_dir=str(output_dir),
        )

        cmd = [
            execution.tool_name,
            "run",
            prompt,
            "--format",
            "json",
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(stderr.decode() if stderr else "Unknown error")

    async def run_commentary_phase(self) -> None:
        """Run commentary phase - each model reviews other models."""
        model_names = list(self.executions.keys())

        for full_name, execution in self.executions.items():
            if execution.status != ModelStatus.PLAN_COMPLETE:
                continue

            commentary_dir = self.run_dir / execution.tool_name / "comments"
            commentary_dir.mkdir(parents=True, exist_ok=True)

            execution.status = ModelStatus.RUNNING
            self._notify_progress(full_name, execution.status)

            for other_name in model_names:
                if other_name == full_name:
                    continue

                try:
                    other_dir = self.run_dir / execution.tool_name.replace("/", "/")[1:]

                    analysis_path = self.run_dir / other_name.replace("/", "/")[1:] / "analysis.md"
                    plan_path = self.run_dir / other_name.replace("/", "/")[1:] / "plan.md"

                    other_analysis = ""
                    other_plan = ""

                    if analysis_path.exists():
                        other_analysis = analysis_path.read_text()
                    if plan_path.exists():
                        other_plan = plan_path.read_text()

                    other_tool, other_model = other_name.split("/", 1)
                    prompt = COMMENTARY_PROMPT_TEMPLATE.format(
                        other_model=other_model,
                        other_analysis=other_analysis,
                        other_plan=other_plan,
                        output_dir=str(commentary_dir),
                    )

                    cmd = [
                        execution.tool_name,
                        "run",
                        prompt,
                        "--format",
                        "json",
                    ]

                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )

                    stdout, stderr = await process.communicate()

                    if process.returncode == 0:
                        comment_file = commentary_dir / f"{other_model}.md"
                        comment_file.write_text(stdout.decode() if stdout else "")

                except Exception as e:
                    execution.error = str(e)

            execution.status = ModelStatus.COMPLETE
            execution.end_time = time.time()
            self._notify_progress(full_name, execution.status)

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
            1 for e in self.executions.values()
            if e.status in (ModelStatus.COMPLETE, ModelStatus.FAILED)
        )

    def get_total_count(self) -> int:
        """Get total number of executions."""
        return len(self.executions)

    def get_status(self, model_name: str) -> ModelStatus:
        """Get status of a model."""
        execution = self.executions.get(model_name)
        return execution.status if execution else ModelStatus.PENDING