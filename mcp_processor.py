import io
from contextlib import redirect_stderr, redirect_stdout
from typing import Callable, Optional

from mcpk import pack_mcpk, unpack_mcpk

ProgressCallback = Callable[[int, str], None]


def _run_with_logging(
    action: Callable[[], None],
    progress_callback: Optional[ProgressCallback],
    start_progress: int,
    start_message: str,
    end_progress: int,
    end_message: str,
) -> str:
    log_stream = io.StringIO()
    if progress_callback:
        progress_callback(start_progress, start_message)
    try:
        with redirect_stdout(log_stream), redirect_stderr(log_stream):
            action()
    except Exception:
        if progress_callback:
            progress_callback(start_progress, "Processing failed")
        raise
    if progress_callback:
        progress_callback(end_progress, end_message)
    return log_stream.getvalue()


def run_unpack(
    input_file: str, output_dir: str, progress_callback: Optional[ProgressCallback] = None
) -> str:
    return _run_with_logging(
        lambda: unpack_mcpk(input_file, output_dir),
        progress_callback,
        5,
        "Unpacking MCPK",
        80,
        "Unpack complete",
    )


def run_pack(
    input_dir: str, output_file: str, progress_callback: Optional[ProgressCallback] = None
) -> str:
    return _run_with_logging(
        lambda: pack_mcpk(input_dir, output_file),
        progress_callback,
        20,
        "Packing MCPK",
        85,
        "Pack complete",
    )
