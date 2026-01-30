import io
import os
import shutil
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from typing import Callable, Optional

import uncompyle6

from anti_confuser import restore_data
from crypto import encrypt_data
from mcpk import pack_mcpk, unpack_mcpk

ProgressCallback = Callable[[int, str], None]
PYC_HEADER_SIZE = 8

try:
    _decompile_file = uncompyle6.decompile_file
except AttributeError:  # pragma: no cover - fallback for older uncompyle6 layout
    from uncompyle6.main import decompile_file as _decompile_file


def _emit_progress(callback: Optional[ProgressCallback], progress: int, message: str) -> None:
    if callback:
        callback(progress, message)


def _scale_progress(current: int, total: int, start: int, end: int) -> int:
    if total <= 0:
        return end
    ratio = min(max(current / total, 0), 1)
    return int(start + (end - start) * ratio)


def _collect_mcs_files(output_dir: str) -> list[str]:
    mcs_files: list[str] = []
    for root, _, files in os.walk(output_dir):
        for filename in files:
            if filename.endswith(".mcs"):
                mcs_files.append(os.path.join(root, filename))
    return mcs_files


def _decompile_mcs_files(
    output_dir: str, progress_callback: Optional[ProgressCallback] = None
) -> None:
    mcs_files = _collect_mcs_files(output_dir)
    total_files = len(mcs_files)
    if total_files == 0:
        _emit_progress(progress_callback, 90, "No scripts to decompile")
        return
    for index, path in enumerate(mcs_files, start=1):
        rel_path = os.path.relpath(path, output_dir)
        progress = _scale_progress(index, total_files, 60, 90)
        _emit_progress(progress_callback, progress, f"Decompiling {rel_path}")
        temp_pyc = f"{path}.tmp_pyc"
        target_py = os.path.splitext(path)[0] + ".py"
        try:
            with open(path, "rb") as f_in:
                data = f_in.read()
            std_pyc_data = restore_data(data)
            with open(temp_pyc, "wb") as f_tmp:
                f_tmp.write(std_pyc_data)
            with open(target_py, "w", encoding="utf-8") as f_out:
                _decompile_file(temp_pyc, f_out)
            os.remove(path)
            os.remove(temp_pyc)
        except Exception as exc:
            print(f"[!] Failed to decompile {rel_path}: {exc}")
            if os.path.exists(temp_pyc):
                os.remove(temp_pyc)
            if os.path.exists(target_py):
                os.remove(target_py)


def _collect_py_files(input_dir: str) -> list[str]:
    py_files: list[str] = []
    for root, _, files in os.walk(input_dir):
        for filename in files:
            if filename.endswith(".py"):
                py_files.append(os.path.join(root, filename))
    return py_files


def _compile_py_files(
    input_dir: str,
    python2_path: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> None:
    if not python2_path:
        raise ValueError("PYTHON2_PATH is required")
    resolved_python = shutil.which(python2_path) or (
        os.path.abspath(python2_path) if os.path.isfile(python2_path) else None
    )
    if not resolved_python or not os.access(resolved_python, os.X_OK):
        raise ValueError(f"Invalid PYTHON2_PATH: {python2_path}")
    py_files = _collect_py_files(input_dir)
    total_files = len(py_files)
    if total_files == 0:
        _emit_progress(progress_callback, 60, "No .py files to compile")
        return
    for index, py_path in enumerate(py_files, start=1):
        rel_path = os.path.relpath(py_path, input_dir)
        progress = _scale_progress(index, total_files, 20, 60)
        _emit_progress(progress_callback, progress, f"Compiling {rel_path}")
        result = subprocess.run(
            [resolved_python, "-m", "py_compile", py_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            err = result.stderr.strip() or result.stdout.strip()
            print(f"[!] Compilation failed for {rel_path}: {err}")
            continue
        pyc_path = py_path + "c"
        if not os.path.exists(pyc_path):
            print(f"[!] Compilation failed for {rel_path}: pyc not found")
            continue
        with open(pyc_path, "rb") as f_in:
            code_object_data = f_in.read()[PYC_HEADER_SIZE:]
        encrypted_data = encrypt_data(code_object_data, content_type=1)
        mcs_path = os.path.splitext(py_path)[0] + ".mcs"
        with open(mcs_path, "wb") as f_out:
            f_out.write(encrypted_data)
        os.remove(py_path)
        os.remove(pyc_path)


def run_unpack(
    input_file: str, output_dir: str, progress_callback: Optional[ProgressCallback] = None
) -> str:
    log_stream = io.StringIO()
    try:
        with redirect_stdout(log_stream), redirect_stderr(log_stream):
            _emit_progress(progress_callback, 5, "Unpacking MCPK")

            def unpack_progress(current: int, total: int, filename: str) -> None:
                progress = _scale_progress(current, total, 5, 60)
                _emit_progress(progress_callback, progress, f"Unpacking {filename}")

            unpack_mcpk(input_file, output_dir, progress_callback=unpack_progress)
            _emit_progress(progress_callback, 60, "Unpack complete")
            _decompile_mcs_files(output_dir, progress_callback)
            _emit_progress(progress_callback, 90, "Decompile complete")
    except Exception:
        _emit_progress(progress_callback, 90, "Processing failed")
        raise
    return log_stream.getvalue()


def run_pack(
    input_dir: str, output_file: str, progress_callback: Optional[ProgressCallback] = None
) -> str:
    log_stream = io.StringIO()
    try:
        with redirect_stdout(log_stream), redirect_stderr(log_stream):
            python2_path = os.environ.get("PYTHON2_PATH", "python2.7")
            _emit_progress(progress_callback, 20, "Compiling scripts")
            _compile_py_files(input_dir, python2_path, progress_callback)
            _emit_progress(progress_callback, 60, "Packing MCPK")

            def pack_progress(current: int, total: int, filename: str) -> None:
                progress = _scale_progress(current, total, 60, 90)
                _emit_progress(progress_callback, progress, f"Packing {filename}")

            pack_mcpk(input_dir, output_file, progress_callback=pack_progress)
            _emit_progress(progress_callback, 90, "Pack complete")
    except Exception:
        _emit_progress(progress_callback, 90, "Processing failed")
        raise
    return log_stream.getvalue()
