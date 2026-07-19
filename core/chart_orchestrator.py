"""
core/chart_orchestrator.py — Manages progressive rendering of figures.

This module orchestrates the rendering of multiple charts in a prioritized order,
updating progress as each chart is generated. Charts can be grouped by sections
with headers and descriptive comments, enabling a streaming UX where users see
charts appear as they are built rather than waiting for all to complete.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

import plotly.graph_objects as go
import streamlit as st

logger = logging.getLogger("portafoglio.chart_orchestrator")


@dataclass
class ChartTask:
    """Metadata for a single chart to be rendered."""

    chart_id: str
    """Unique ID like 'summary_history', 'andamento_pl_decomp_stacked'"""

    builder: Callable[[], go.Figure]
    """Callable that returns go.Figure"""

    page: str
    """Page name: 'Summary', 'Andamento', 'Quotazioni'"""

    priority: int = 10
    """Lower = render first (1 is highest priority)"""

    section_title: Optional[str] = None
    """Section header before this chart (optional)"""

    section_comment: Optional[str] = None
    """Explanatory text for the section (optional)"""

    progress_label: str = ""
    """Label shown in progress bar"""

    extra_params: dict = field(default_factory=dict)
    """Extra params for cache signature"""

    def __lt__(self, other: "ChartTask") -> bool:
        """Enable sorting by priority."""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.chart_id < other.chart_id


class ChartOrchestrator:
    """Manages queue and streaming render of charts."""

    def __init__(self) -> None:
        """Initialize empty task list."""
        self.tasks: list[ChartTask] = []
        self.completed: int = 0
        self.total: int = 0

    def queue_task(
        self,
        chart_id: str,
        builder: Callable[[], go.Figure],
        page: str,
        priority: int = 10,
        section_title: Optional[str] = None,
        section_comment: Optional[str] = None,
        progress_label: str = "",
        extra_params: Optional[dict] = None,
    ) -> None:
        """
        Queue a chart task for rendering.

        Args:
            chart_id: Unique identifier for the chart
            builder: Callable that returns a go.Figure
            page: Page name where chart appears
            priority: Lower number renders first (default 10)
            section_title: Optional section header
            section_comment: Optional explanatory text
            progress_label: Label for progress bar
            extra_params: Optional extra params for cache signature
        """
        if extra_params is None:
            extra_params = {}

        task = ChartTask(
            chart_id=chart_id,
            builder=builder,
            page=page,
            priority=priority,
            section_title=section_title,
            section_comment=section_comment,
            progress_label=progress_label,
            extra_params=extra_params,
        )
        self.tasks.append(task)
        logger.debug(f"Queued chart task: {chart_id} (priority={priority}, page={page})")

    def render_all(
        self,
        render_func: Callable[[go.Figure, str], None],
        show_progress: bool = True,
        progress_container: Optional[object] = None,
    ) -> int:
        """
        Render all queued tasks in priority order.

        Args:
            render_func: Callback function that receives (fig, chart_id)
            show_progress: Whether to show progress bar (default True)
            progress_container: Optional Streamlit container for progress

        Returns:
            Number of successfully rendered charts
        """
        self.tasks.sort()
        self.total = len(self.tasks)
        self.completed = 0

        if show_progress and progress_container is None:
            progress_container = st.empty()

        for task in self.tasks:
            try:
                # Update progress bar
                if show_progress and progress_container is not None:
                    progress = int((self.completed / self.total) * 100)
                    progress_text = (
                        f"Rendering {task.progress_label or task.chart_id}..."
                    )
                    progress_container.progress(progress, text=progress_text)

                # Render section title if provided
                if task.section_title:
                    st.subheader(task.section_title)
                    logger.debug(f"Rendered section title: {task.section_title}")

                # Render section comment if provided
                if task.section_comment:
                    st.markdown(task.section_comment)
                    logger.debug(f"Rendered section comment for: {task.chart_id}")

                # Build and render figure
                fig = task.builder()
                render_func(fig, task.chart_id)
                self.completed += 1
                logger.debug(
                    f"Rendered chart: {task.chart_id} ({self.completed}/{self.total})"
                )

            except Exception as e:
                error_msg = f"❌ Errore caricamento {task.chart_id}: {e}"
                logger.error(error_msg, exc_info=True)
                st.error(error_msg)
                # Continue rendering remaining charts

        # Final progress update
        if show_progress and progress_container is not None:
            final_text = f"✓ Completato: {self.total} grafici"
            progress_container.progress(100, text=final_text)

        return self.completed
