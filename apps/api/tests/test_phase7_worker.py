import ctypes
import multiprocessing
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from app import phase7_worker as worker
from app import phase7_routes
from app.database import get_db
from app.models import OptimizationJob, OptimizationRun
from test_phase7_job_adjustments import workspace


def hold_native_gil(ready):
    ready.set()
    # PyDLL deliberately retains the interpreter lock during native execution,
    # reproducing the failure that a thread-based background solver can cause.
    if os.name == "nt":
        ctypes.PyDLL("kernel32.dll").Sleep(2500)
    else:
        ctypes.PyDLL(None).sleep(3)


@pytest.fixture(autouse=True)
def reset_worker():
    worker.initialize_optimization_processes()
    yield
    worker.shutdown_optimization_processes()
    worker.initialize_optimization_processes()


def test_health_remains_responsive_while_background_native_solver_holds_gil(monkeypatch):
    context=multiprocessing.get_context("spawn")
    ready=context.Event()
    errors=[]
    monkeypatch.setattr(worker,"_make_process",lambda *a:context.Process(target=hold_native_gil,args=(ready,),daemon=True))
    monkeypatch.setattr(worker,"_inspect_job",lambda *a:("SOLVING_ROUTES",{}))
    monkeypatch.setattr(worker,"_fail_job",lambda *a:errors.append(a))
    monkeypatch.setattr(phase7_routes,"enqueue_optimization",lambda *a,**kw:{"job_id":"J","status":"CALCULATING"})
    app=FastAPI();app.include_router(phase7_routes.router)
    app.dependency_overrides[get_db]=lambda:None
    @app.get("/health")
    async def health(): return {"status":"ok"}
    client=TestClient(app)
    with ThreadPoolExecutor(max_workers=1) as pool:
        request=pool.submit(client.post,"/api/v1/phase7/jobs/J/optimize",json={"current_time":"2026-10-30T00:00:00Z"})
        assert ready.wait(15)
        assert not request.done()
        started=time.monotonic()
        for _ in range(3):
            assert client.get("/health").status_code == 200
        assert time.monotonic()-started < 1.5
        assert request.result(timeout=15).status_code == 202
    assert errors[-1][1] == "PHASE7_PROCESS_EXITED"


def test_supervisor_terminates_stuck_child_and_reports_timeout(monkeypatch):
    context=multiprocessing.get_context("spawn")
    ready=context.Event();errors=[];processes=[]
    def make(*args):
        process=context.Process(target=hold_native_gil,args=(ready,),daemon=True)
        processes.append(process);return process
    monkeypatch.setattr(worker,"_make_process",make)
    monkeypatch.setattr(worker,"_inspect_job",lambda *a:("SOLVING_ROUTES",{}))
    monkeypatch.setattr(worker,"stage_budget",lambda *a:0.01 if ready.is_set() else 20)
    monkeypatch.setattr(worker,"_fail_job",lambda *a:errors.append(a))
    worker.supervise_optimization("J",{},reroute=False)
    assert ready.is_set()
    assert errors[-1][1] == "PHASE7_PROCESS_TIMEOUT"
    assert not processes[0].is_alive()
    # The semaphore is released even after timeout.
    assert worker._slots.acquire(timeout=0.1)
    worker._slots.release()


def test_stage_budgets_follow_profile_and_include_model_construction():
    assert worker.stage_budget("SOLVING_ROUTES",{"route_optimization_time_limit":90,"bay_optimization_time_limit":30}) == 240
    assert worker.stage_budget("BUILDING_MATRIX",{"route_matrix_time_limit_seconds":20}) == 80
    assert worker.stage_budget("BUILDING_MATRIX",{"restricted_roads":{"roads":[{}]},"restricted_matrix_time_limit_seconds":200}) == 260


def test_timeout_persists_terminal_failure_and_preserves_existing_plan(workspace,monkeypatch):
    db,_=workspace
    monkeypatch.setattr(worker,"SessionLocal",lambda:db)
    job=db.get(OptimizationJob,"J");job.status="CALCULATING"
    db.add(OptimizationRun(optimization_run_id="R",job_id="J",run_type="INITIAL",status="RUNNING",state_snapshot_id="SS",parameter_snapshot_id="PS",objective="MIN_TOTAL_COST",start_time=datetime.now(timezone.utc),solver_metadata={"stage":"SOLVING_ROUTES"}))
    db.commit()
    worker._fail_job("J","PHASE7_PROCESS_TIMEOUT","Timed out")
    run=db.get(OptimizationRun,"R")
    assert run.status == "FAILED" and run.error_code == "PHASE7_PROCESS_TIMEOUT"
    assert run.solver_metadata["stage"] == "TIMEOUT"
    assert db.get(OptimizationJob,"J").status == "FAILED"


def test_process_exit_does_not_overwrite_committed_success(workspace,monkeypatch):
    db,_=workspace
    monkeypatch.setattr(worker,"SessionLocal",lambda:db)
    job=db.get(OptimizationJob,"J");job.status="ACTIVE";db.commit()
    worker._fail_job("J","PHASE7_PROCESS_EXITED","Unexpected exit")
    assert db.get(OptimizationJob,"J").status == "ACTIVE"
    assert db.get(OptimizationJob,"J").error_message is None
