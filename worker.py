import os
import shutil
import time
import zipfile
from typing import Optional

from models import SessionLocal, Task, init_db
from mcp_processor import run_pack, run_unpack

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
POLL_INTERVAL = 2

PYTHON2_PATH = os.environ.get("PYTHON2_PATH") or os.environ.get("PYTHON2_7_PATH") or "python2.7"
os.environ.setdefault("PYTHON2_PATH", PYTHON2_PATH)


def ensure_dirs() -> None:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)


def update_task(task_id: str, **updates) -> None:
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if not task:
            return
        for key, value in updates.items():
            setattr(task, key, value)
        db.commit()


def append_log(task_id: str, content: str) -> None:
    if not content:
        return
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if not task:
            return
        task.log = (task.log or "") + content
        db.commit()


def claim_pending_task() -> Optional[str]:
    with SessionLocal() as db:
        task = (
            db.query(Task)
            .filter(Task.status == "pending")
            .order_by(Task.created_at)
            .first()
        )
        if not task:
            return None
        updated = (
            db.query(Task)
            .filter(Task.id == task.id, Task.status == "pending")
            .update(
                {
                    Task.status: "processing",
                    Task.progress: 0,
                    Task.message: "Processing",
                },
                synchronize_session=False,
            )
        )
        db.commit()
        return task.id if updated else None


def safe_remove(path: str) -> None:
    if path and os.path.exists(path):
        os.remove(path)


def safe_rmtree(path: str) -> None:
    if path and os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def safe_extract(zip_file: zipfile.ZipFile, dest_dir: str) -> None:
    dest_dir = os.path.abspath(dest_dir)
    for member in zip_file.infolist():
        member_path = os.path.abspath(os.path.join(dest_dir, member.filename))
        if os.path.commonpath([dest_dir, member_path]) != dest_dir:
            raise ValueError("Invalid archive entry path")
    zip_file.extractall(dest_dir)


def process_task(task_id: str) -> None:
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if not task:
            return
        task_type = task.task_type
        input_file = task.input_file

    progress_callback = lambda progress, message: update_task(
        task_id, progress=progress, message=message
    )

    extract_dir = None
    try:
        if task_type == "unpack":
            output_dir = os.path.join(RESULTS_DIR, task_id)
            os.makedirs(output_dir, exist_ok=True)
            log_content = run_unpack(input_file, output_dir, progress_callback)
            append_log(task_id, log_content)

            archive_base = os.path.join(RESULTS_DIR, task_id)
            update_task(task_id, progress=90, message="Creating archive")
            archive_path = shutil.make_archive(archive_base, "zip", output_dir)
            append_log(task_id, "\n[+] Archive created\n")
            safe_rmtree(output_dir)

            update_task(
                task_id,
                status="completed",
                progress=100,
                message="Done",
                output_file=archive_path,
            )
        elif task_type == "pack":
            extract_dir = os.path.join(UPLOAD_DIR, f"{task_id}_src")
            os.makedirs(extract_dir, exist_ok=True)
            update_task(task_id, progress=10, message="Extracting archive")
            with zipfile.ZipFile(input_file, "r") as zip_ref:
                safe_extract(zip_ref, extract_dir)
            append_log(task_id, "[+] Archive extracted\n")

            output_file = os.path.join(RESULTS_DIR, f"{task_id}.mcpk")
            log_content = run_pack(extract_dir, output_file, progress_callback)
            append_log(task_id, log_content)

            update_task(
                task_id,
                status="completed",
                progress=100,
                message="Done",
                output_file=output_file,
            )
        else:
            update_task(
                task_id,
                status="failed",
                progress=100,
                message="Unknown task type",
            )
    except Exception as exc:
        append_log(task_id, f"\n[!] Error: {exc}\n")
        update_task(task_id, status="failed", progress=100, message="Failed")
    finally:
        safe_remove(input_file)
        safe_rmtree(extract_dir)


def run_worker() -> None:
    init_db()
    ensure_dirs()
    while True:
        try:
            task_id = claim_pending_task()
            if task_id:
                process_task(task_id)
        except Exception as exc:
            print(f"[!] Worker loop error: {exc}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run_worker()
