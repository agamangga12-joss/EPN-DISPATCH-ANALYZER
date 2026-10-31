"""Isolated, supervised Phase 7 solver processes owned by the API instance.

The database remains the durable progress/result store. API restart recovery
marks interrupted jobs failed; this is not a second durable job queue.
"""
from __future__ import annotations

import logging
import multiprocessing
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select
from .database import SessionLocal, engine
from .models import OptimizationJob, OptimizationRun, OptimizationParameterSnapshot

logger = logging.getLogger(__name__)
_slots = threading.BoundedSemaphore(1)
_stopping = threading.Event()
_processes = set()
_process_lock = threading.Lock()


def stage_budget(stage: str, parameters: dict) -> float:
    # Include model construction/initial propagation, which OR-Tools' own search
    # time limit does not reliably interrupt. Coordination has a second route
    # repair budget plus its shared bay budget.
    if stage == "SOLVING_ROUTES":
        return max(30, 2 * int(parameters.get("route_optimization_time_limit", 30))
                   + int(parameters.get("bay_optimization_time_limit", 30))) + 30
    if stage == "BUILDING_MATRIX":
        restricted = bool((parameters.get("restricted_roads") or {}).get("roads"))
        return int(parameters.get("restricted_matrix_time_limit_seconds" if restricted else "route_matrix_time_limit_seconds", 900 if restricted else 90)) + 60
    if stage == "PERSISTING_RESULT":
        return int(parameters.get("route_geometry_time_limit_seconds", 30)) + 120
    return 120


def _execute(job_id, payload, reroute, actor):
    engine.dispose()
    from .phase7_service import _run_optimization_session
    _run_optimization_session(job_id, payload, reroute=reroute, actor=actor)


def _make_process(job_id, payload, reroute, actor):
    return multiprocessing.get_context("spawn").Process(
        target=_execute, args=(job_id, payload, reroute, actor),
        name=f"phase7-{job_id}", daemon=True)


def _inspect_job(job_id):
    with SessionLocal() as db:
        job = db.get(OptimizationJob, job_id) or db.scalar(select(OptimizationJob).where(OptimizationJob.job_no == job_id))
        if not job or job.status != "CALCULATING":
            return None
        run = db.scalar(select(OptimizationRun).where(OptimizationRun.job_id == job.job_id, OptimizationRun.status == "RUNNING").order_by(OptimizationRun.start_time.desc()).limit(1))
        snapshot = db.get(OptimizationParameterSnapshot, run.parameter_snapshot_id) if run else None
        return ((run.solver_metadata or {}).get("stage", "PREPARING") if run else "PREPARING",
                snapshot.effective_parameters if snapshot else {})


def _fail_job(job_id, code, message):
    with SessionLocal() as db:
        job = db.get(OptimizationJob, job_id) or db.scalar(select(OptimizationJob).where(OptimizationJob.job_no == job_id))
        # Do not overwrite a result that committed just before process exit.
        if not job or job.status != "CALCULATING":
            return
        now = datetime.now(timezone.utc)
        runs = db.scalars(select(OptimizationRun).where(OptimizationRun.job_id == job.job_id, OptimizationRun.status == "RUNNING")).all()
        for run in runs:
            run.status = run.solver_status = "FAILED"
            run.end_time, run.error_code, run.error_message = now, code, message
            if run.start_time:
                started = run.start_time.replace(tzinfo=timezone.utc) if run.start_time.tzinfo is None else run.start_time
                run.solve_duration_ms = round((now - started).total_seconds() * 1000)
            run.solver_metadata = {**(run.solver_metadata or {}), "stage": "TIMEOUT" if code == "PHASE7_PROCESS_TIMEOUT" else "INTERRUPTED", "progress_pct": 100, "execution_mode": "ISOLATED_PROCESS"}
        job.status, job.error_message = "FAILED", message
        db.commit()


def _terminate(process):
    if process.is_alive():
        process.terminate()
        process.join(timeout=3)
    if process.is_alive():
        process.kill()
        process.join(timeout=3)


def supervise_optimization(job_id, payload, *, reroute, actor="local-user"):
    # One CPU-heavy optimization at a time per API instance. Waiting supervisors
    # consume no solver CPU and do not occupy the API interpreter with native work.
    while not _slots.acquire(timeout=0.5):
        if _stopping.is_set():
            _fail_job(job_id, "PHASE7_PROCESS_INTERRUPTED", "Optimization stopped before execution. Retry the Job.")
            return
    process = None
    failure = None
    try:
        if _stopping.is_set():
            raise RuntimeError("API is stopping")
        if _inspect_job(job_id) is None:
            return
        process = _make_process(job_id, payload, reroute, actor)
        with _process_lock:
            _processes.add(process)
        process.start()
        stage, stage_started = "PREPARING", time.monotonic()
        while process.is_alive():
            process.join(timeout=0.5)
            if _stopping.is_set():
                failure = ("PHASE7_PROCESS_INTERRUPTED", "API stopped during optimization. Retry the Job.")
                break
            state = _inspect_job(job_id)
            if state is None:
                # Terminal result is committed; stop any leftover serialization
                # without touching that result.
                break
            current_stage, parameters = state
            if current_stage != stage:
                stage, stage_started = current_stage, time.monotonic()
            limit = stage_budget(stage, parameters)
            if time.monotonic() - stage_started > limit:
                failure = ("PHASE7_PROCESS_TIMEOUT", f"Phase 7 exceeded the {limit:g}-second execution limit in {stage}. The solver process was stopped; API remains available. Adjust the profile or retry the Job.")
                break
        _terminate(process)
        if failure:
            _fail_job(job_id, *failure)
        else:
            _fail_job(job_id, "PHASE7_PROCESS_EXITED", f"Optimization process exited without a terminal result (exit code {process.exitcode}). Retry the Job.")
    except Exception:
        logger.exception("Phase 7 process supervisor failed job=%s", job_id)
        if process and process.pid:
            _terminate(process)
        _fail_job(job_id, "PHASE7_PROCESS_FAILED", "Could not execute the isolated optimization process. Retry the Job.")
    finally:
        if process:
            with _process_lock:
                _processes.discard(process)
        _slots.release()


def initialize_optimization_processes():
    _stopping.clear()


def shutdown_optimization_processes():
    _stopping.set()
    with _process_lock:
        processes = list(_processes)
    for process in processes:
        if process.pid:
            _terminate(process)
