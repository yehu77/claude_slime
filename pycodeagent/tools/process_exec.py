"""Shared process execution primitives for family-specific tool runtimes.

This module is intentionally internal-only:

- it is not a canonical tool
- it is not model-visible
- it does not validate tool schemas or command policy

It provides one reusable process execution substrate that later runtime
families can build on top of without duplicating subprocess, timeout, session,
and background-task bookkeeping logic.
"""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path
from typing import Literal

_DEFAULT_SHELL = "bash"
_DEFAULT_TIMEOUT_MS = 60_000
_DEFAULT_OUTPUT_LIMIT_CHARS = 50_000
_DEFAULT_SESSION_YIELD_MS = 10_000
_DEFAULT_WRITE_SESSION_YIELD_MS = 250
_DEFAULT_POLL_SESSION_YIELD_MS = 5_000
_MIN_SESSION_YIELD_MS = 250
_MAX_SESSION_YIELD_MS = 30_000
_MAX_EMPTY_POLL_YIELD_MS = 300_000
_FALLBACK_BACKGROUND_ROOT = Path(tempfile.gettempdir()) / "pycodeagent-process-tasks"
_TERM_GRACE_TIMEOUT_SEC = 1.0
_SESSION_DRAIN_TIMEOUT_SEC = 0.1
_READ_CHUNK_SIZE = 4096

BackgroundTaskState = Literal["running", "completed", "failed", "timed_out"]


class ProcessExecError(RuntimeError):
    """Raised when background or live-session process execution fails."""


@dataclass(frozen=True)
class ProcessExecRequest:
    """Normalized internal request for shell-string process execution."""

    command: str
    cwd: Path
    shell: str = _DEFAULT_SHELL
    login: bool = False
    tty: bool = False
    timeout_ms: int | None = _DEFAULT_TIMEOUT_MS
    output_limit_chars: int = _DEFAULT_OUTPUT_LIMIT_CHARS
    env_overrides: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProcessExecResult:
    """Structured result for one foreground or live-session execution step."""

    stdout: str
    stderr: str
    exit_code: int | None
    duration_ms: int
    timed_out: bool = False
    spawn_error: str | None = None
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    session_id: int | None = None


@dataclass(frozen=True)
class BackgroundTaskHandle:
    """Stable handle returned immediately for one background process."""

    task_id: str
    pid: int
    output_path: Path
    started_at_ms: int


@dataclass(frozen=True)
class BackgroundTaskStatus:
    """Current or terminal state for one background process."""

    task_id: str
    state: BackgroundTaskState
    pid: int | None
    output_path: Path
    exit_code: int | None
    started_at_ms: int
    finished_at_ms: int | None = None
    duration_ms: int | None = None
    error_message: str | None = None


@dataclass
class _BackgroundTaskRecord:
    """Mutable in-memory record for one background process."""

    handle: BackgroundTaskHandle
    process: subprocess.Popen[bytes] | None
    started_perf: float
    timeout_ms: int | None
    state: BackgroundTaskState = "running"
    exit_code: int | None = None
    finished_at_ms: int | None = None
    duration_ms: int | None = None
    error_message: str | None = None

    def to_status(self) -> BackgroundTaskStatus:
        return BackgroundTaskStatus(
            task_id=self.handle.task_id,
            state=self.state,
            pid=self.handle.pid,
            output_path=self.handle.output_path,
            exit_code=self.exit_code,
            started_at_ms=self.handle.started_at_ms,
            finished_at_ms=self.finished_at_ms,
            duration_ms=self.duration_ms,
            error_message=self.error_message,
        )


@dataclass
class _LiveSessionRecord:
    """Mutable in-memory record for one interactive exec session."""

    session_id: int
    process: subprocess.Popen[bytes]
    started_perf: float
    timeout_ms: int | None
    output_limit_chars: int
    tty: bool


class SharedProcessExecutor:
    """Reusable internal executor for foreground, background, and live sessions."""

    def __init__(self) -> None:
        self._task_counter = count(1)
        self._session_counter = count(1)
        self._lock = threading.Lock()
        self._background_tasks: dict[str, _BackgroundTaskRecord] = {}
        self._live_sessions: dict[int, _LiveSessionRecord] = {}

    def run_foreground(self, request: ProcessExecRequest) -> ProcessExecResult:
        """Execute one shell-string command in the foreground."""
        started_perf = time.perf_counter()
        try:
            process = subprocess.Popen(
                self._build_shell_argv(request),
                cwd=request.cwd,
                env=self._build_env(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                start_new_session=True,
            )
        except OSError as exc:
            duration_ms = _duration_ms_since(started_perf)
            return ProcessExecResult(
                stdout="",
                stderr="",
                exit_code=None,
                duration_ms=duration_ms,
                spawn_error=str(exc),
            )

        try:
            stdout_bytes, stderr_bytes = self._communicate(process, request.timeout_ms)
        except subprocess.TimeoutExpired:
            self._terminate_process_group(process)
            remaining_stdout, remaining_stderr = self._drain_process(process)
            stdout_text, stdout_truncated = _truncate_output(
                remaining_stdout,
                limit=request.output_limit_chars,
            )
            stderr_text, stderr_truncated = _truncate_output(
                remaining_stderr,
                limit=request.output_limit_chars,
            )
            return ProcessExecResult(
                stdout=stdout_text,
                stderr=stderr_text,
                exit_code=None,
                duration_ms=_duration_ms_since(started_perf),
                timed_out=True,
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
            )

        stdout_text, stdout_truncated = _truncate_output(
            _decode_output(stdout_bytes),
            limit=request.output_limit_chars,
        )
        stderr_text, stderr_truncated = _truncate_output(
            _decode_output(stderr_bytes),
            limit=request.output_limit_chars,
        )
        return ProcessExecResult(
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=process.returncode,
            duration_ms=_duration_ms_since(started_perf),
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )

    def run_background(
        self,
        request: ProcessExecRequest,
        *,
        artifact_root: Path | None = None,
    ) -> BackgroundTaskHandle:
        """Launch one shell-string command in the background."""
        task_id = f"bg_{next(self._task_counter):06d}"
        background_root = self._resolve_background_root(artifact_root)
        background_root.mkdir(parents=True, exist_ok=True)
        output_path = background_root / f"{task_id}.log"
        if output_path.exists():
            output_path.unlink()

        started_at_ms = _unix_time_ms()
        started_perf = time.perf_counter()

        try:
            with output_path.open("ab") as output_file:
                process = subprocess.Popen(
                    self._build_shell_argv(request),
                    cwd=request.cwd,
                    env=self._build_env(request),
                    stdout=output_file,
                    stderr=output_file,
                    text=False,
                    start_new_session=True,
                )
        except OSError as exc:
            try:
                output_path.unlink()
            except FileNotFoundError:
                pass
            raise ProcessExecError(f"Failed to start background process: {exc}") from exc

        handle = BackgroundTaskHandle(
            task_id=task_id,
            pid=process.pid,
            output_path=output_path,
            started_at_ms=started_at_ms,
        )
        record = _BackgroundTaskRecord(
            handle=handle,
            process=process,
            started_perf=started_perf,
            timeout_ms=request.timeout_ms,
        )
        with self._lock:
            self._background_tasks[task_id] = record

        watcher = threading.Thread(
            target=self._watch_background_task,
            args=(task_id,),
            name=f"SharedProcessExecutor[{task_id}]",
            daemon=True,
        )
        watcher.start()
        return handle

    def start_session(
        self,
        request: ProcessExecRequest,
        *,
        yield_time_ms: int | None = None,
    ) -> ProcessExecResult:
        """Start one live exec session and return immediate output or a session id."""
        started_perf = time.perf_counter()
        try:
            process = subprocess.Popen(
                self._build_shell_argv(request),
                cwd=request.cwd,
                env=self._build_env(request),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                bufsize=0,
                start_new_session=True,
            )
        except OSError as exc:
            return ProcessExecResult(
                stdout="",
                stderr="",
                exit_code=None,
                duration_ms=_duration_ms_since(started_perf),
                spawn_error=str(exc),
            )

        if process.stdout is None or process.stderr is None:
            self._terminate_process_group(process)
            return ProcessExecResult(
                stdout="",
                stderr="",
                exit_code=None,
                duration_ms=_duration_ms_since(started_perf),
                spawn_error="Failed to capture process output pipes",
            )

        _set_nonblocking(process.stdout.fileno())
        _set_nonblocking(process.stderr.fileno())
        session_id = next(self._session_counter)
        record = _LiveSessionRecord(
            session_id=session_id,
            process=process,
            started_perf=time.perf_counter(),
            timeout_ms=request.timeout_ms,
            output_limit_chars=request.output_limit_chars,
            tty=request.tty,
        )
        with self._lock:
            self._live_sessions[session_id] = record

        effective_yield_ms = (
            _DEFAULT_SESSION_YIELD_MS if yield_time_ms is None else yield_time_ms
        )
        return self._poll_live_session(
            record,
            yield_time_ms=effective_yield_ms,
            output_limit_chars=request.output_limit_chars,
            call_started_perf=started_perf,
        )

    def write_session_stdin(
        self,
        session_id: int,
        chars: str = "",
        *,
        yield_time_ms: int | None = None,
        output_limit_chars: int | None = None,
    ) -> ProcessExecResult:
        """Write to or poll one live exec session."""
        started_perf = time.perf_counter()
        with self._lock:
            record = self._live_sessions.get(session_id)
        if record is None:
            raise ProcessExecError(f"Unknown live session: {session_id!r}")

        if chars and not record.tty:
            raise ProcessExecError("Live session stdin is closed for non-tty sessions")

        if chars:
            stdin = record.process.stdin
            if stdin is None:
                raise ProcessExecError("Live session stdin is unavailable")
            try:
                stdin.write(chars.encode("utf-8"))
                stdin.flush()
            except BrokenPipeError as exc:
                raise ProcessExecError("Live session stdin is closed") from exc
            except OSError as exc:
                raise ProcessExecError(
                    f"Failed to write to live session stdin: {exc}"
                ) from exc

        effective_yield_ms = _coerce_session_yield_ms(
            yield_time_ms,
            is_empty_poll=not bool(chars),
        )
        return self._poll_live_session(
            record,
            yield_time_ms=effective_yield_ms,
            output_limit_chars=output_limit_chars or record.output_limit_chars,
            call_started_perf=started_perf,
        )

    def get_background_status(self, task_id: str) -> BackgroundTaskStatus:
        """Return the current or terminal state for one background task."""
        with self._lock:
            record = self._background_tasks.get(task_id)
            if record is None:
                raise ProcessExecError(f"Unknown background task: {task_id!r}")

        with self._lock:
            refreshed = self._background_tasks.get(task_id)
            if refreshed is None:
                raise ProcessExecError(f"Unknown background task: {task_id!r}")
            return refreshed.to_status()

    def _watch_background_task(self, task_id: str) -> None:
        """Wait for one background task and finalize its terminal state."""
        with self._lock:
            record = self._background_tasks.get(task_id)
            if record is None or record.process is None:
                return
            process = record.process
            timeout_ms = record.timeout_ms

        try:
            if timeout_ms is None:
                exit_code = process.wait()
                self._finalize_background_task(
                    task_id,
                    state="completed",
                    exit_code=exit_code,
                )
                return

            try:
                exit_code = process.wait(timeout=timeout_ms / 1000.0)
            except subprocess.TimeoutExpired:
                self._terminate_process_group(process)
                self._finalize_background_task(
                    task_id,
                    state="timed_out",
                    exit_code=process.poll(),
                    error_message=f"Command timed out after {timeout_ms}ms",
                )
                return

            self._finalize_background_task(
                task_id,
                state="completed",
                exit_code=exit_code,
            )
        except Exception as exc:
            self._finalize_background_task(
                task_id,
                state="failed",
                exit_code=process.poll(),
                error_message=str(exc),
            )

    def _finalize_background_task(
        self,
        task_id: str,
        *,
        state: BackgroundTaskState,
        exit_code: int | None,
        error_message: str | None = None,
    ) -> None:
        """Store the terminal state for one background task exactly once."""
        with self._lock:
            record = self._background_tasks.get(task_id)
            if record is None or record.state != "running":
                return

            record.state = state
            record.exit_code = exit_code
            record.finished_at_ms = _unix_time_ms()
            record.duration_ms = _duration_ms_since(record.started_perf)
            record.error_message = error_message
            record.process = None

    def _poll_live_session(
        self,
        record: _LiveSessionRecord,
        *,
        yield_time_ms: int,
        output_limit_chars: int,
        call_started_perf: float,
    ) -> ProcessExecResult:
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []
        deadline = time.monotonic() + max(0, yield_time_ms) / 1000.0

        while True:
            if self._session_timed_out(record):
                self._terminate_process_group(record.process)
                drained_stdout, drained_stderr = self._drain_process_bytes(record.process)
                stdout_chunks.append(drained_stdout)
                stderr_chunks.append(drained_stderr)
                self._remove_live_session(record.session_id)
                return self._build_session_result(
                    stdout_chunks,
                    stderr_chunks,
                    exit_code=None,
                    duration_ms=_duration_ms_since(call_started_perf),
                    output_limit_chars=output_limit_chars,
                    timed_out=True,
                    session_id=None,
                )

            wait_seconds = max(0.0, deadline - time.monotonic())
            if wait_seconds > 0:
                stdout_bytes, stderr_bytes = self._read_live_output_once(
                    record.process,
                    timeout_seconds=wait_seconds,
                )
                if stdout_bytes:
                    stdout_chunks.append(stdout_bytes)
                if stderr_bytes:
                    stderr_chunks.append(stderr_bytes)

            exit_code = record.process.poll()
            if exit_code is not None:
                drained_stdout, drained_stderr = self._drain_process_bytes(record.process)
                if drained_stdout:
                    stdout_chunks.append(drained_stdout)
                if drained_stderr:
                    stderr_chunks.append(drained_stderr)
                self._remove_live_session(record.session_id)
                return self._build_session_result(
                    stdout_chunks,
                    stderr_chunks,
                    exit_code=exit_code,
                    duration_ms=_duration_ms_since(call_started_perf),
                    output_limit_chars=output_limit_chars,
                    timed_out=False,
                    session_id=None,
                )

            if time.monotonic() >= deadline:
                return self._build_session_result(
                    stdout_chunks,
                    stderr_chunks,
                    exit_code=None,
                    duration_ms=_duration_ms_since(call_started_perf),
                    output_limit_chars=output_limit_chars,
                    timed_out=False,
                    session_id=record.session_id,
                )

    def _read_live_output_once(
        self,
        process: subprocess.Popen[bytes],
        *,
        timeout_seconds: float,
    ) -> tuple[bytes, bytes]:
        stdout = process.stdout
        stderr = process.stderr
        if stdout is None or stderr is None:
            return b"", b""

        stdout_fd = stdout.fileno()
        stderr_fd = stderr.fileno()
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []

        with selectors.DefaultSelector() as selector:
            selector.register(stdout_fd, selectors.EVENT_READ, "stdout")
            selector.register(stderr_fd, selectors.EVENT_READ, "stderr")
            events = selector.select(timeout_seconds)
            for key, _ in events:
                while True:
                    try:
                        chunk = os.read(key.fd, _READ_CHUNK_SIZE)
                    except BlockingIOError:
                        break
                    if not chunk:
                        break
                    if key.data == "stdout":
                        stdout_chunks.append(chunk)
                    else:
                        stderr_chunks.append(chunk)
                    if len(chunk) < _READ_CHUNK_SIZE:
                        break

        return b"".join(stdout_chunks), b"".join(stderr_chunks)

    def _build_session_result(
        self,
        stdout_chunks: list[bytes],
        stderr_chunks: list[bytes],
        *,
        exit_code: int | None,
        duration_ms: int,
        output_limit_chars: int,
        timed_out: bool,
        session_id: int | None,
    ) -> ProcessExecResult:
        stdout_text, stdout_truncated = _truncate_output(
            _decode_output(b"".join(stdout_chunks)),
            limit=output_limit_chars,
        )
        stderr_text, stderr_truncated = _truncate_output(
            _decode_output(b"".join(stderr_chunks)),
            limit=output_limit_chars,
        )
        return ProcessExecResult(
            stdout=stdout_text,
            stderr=stderr_text,
            exit_code=exit_code,
            duration_ms=duration_ms,
            timed_out=timed_out,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            session_id=session_id,
        )

    def _session_timed_out(self, record: _LiveSessionRecord) -> bool:
        if record.timeout_ms is None:
            return False
        return _duration_ms_since(record.started_perf) >= record.timeout_ms

    def _remove_live_session(self, session_id: int) -> None:
        with self._lock:
            self._live_sessions.pop(session_id, None)

    def _build_shell_argv(self, request: ProcessExecRequest) -> list[str]:
        flag = "-lc" if request.login else "-c"
        return [request.shell, flag, request.command]

    def _build_env(self, request: ProcessExecRequest) -> dict[str, str]:
        env = os.environ.copy()
        env.update(request.env_overrides)
        return env

    def _communicate(
        self,
        process: subprocess.Popen[bytes],
        timeout_ms: int | None,
    ) -> tuple[bytes | None, bytes | None]:
        if timeout_ms is None:
            return process.communicate()
        return process.communicate(timeout=timeout_ms / 1000.0)

    def _drain_process(
        self,
        process: subprocess.Popen[bytes],
    ) -> tuple[str, str]:
        stdout_bytes, stderr_bytes = self._drain_process_bytes(process)
        return _decode_output(stdout_bytes), _decode_output(stderr_bytes)

    def _drain_process_bytes(
        self,
        process: subprocess.Popen[bytes],
    ) -> tuple[bytes, bytes]:
        try:
            stdout_bytes, stderr_bytes = process.communicate(timeout=_SESSION_DRAIN_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            return b"", b""
        return stdout_bytes or b"", stderr_bytes or b""

    def _terminate_process_group(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return

        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            except OSError:
                process.terminate()
        else:
            process.terminate()

        try:
            process.wait(timeout=_TERM_GRACE_TIMEOUT_SEC)
            return
        except subprocess.TimeoutExpired:
            pass

        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            except OSError:
                process.kill()
        else:
            process.kill()

        try:
            process.wait(timeout=_TERM_GRACE_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            pass

    def _resolve_background_root(self, artifact_root: Path | None) -> Path:
        if artifact_root is None:
            return _FALLBACK_BACKGROUND_ROOT
        return artifact_root / "background_tasks"


def _coerce_session_yield_ms(
    yield_time_ms: int | None,
    *,
    is_empty_poll: bool,
) -> int:
    if yield_time_ms is None:
        return (
            _DEFAULT_POLL_SESSION_YIELD_MS
            if is_empty_poll
            else _DEFAULT_WRITE_SESSION_YIELD_MS
        )
    value = max(_MIN_SESSION_YIELD_MS, int(yield_time_ms))
    if is_empty_poll:
        return min(value, _MAX_EMPTY_POLL_YIELD_MS)
    return min(value, _MAX_SESSION_YIELD_MS)


def _set_nonblocking(fd: int) -> None:
    try:
        os.set_blocking(fd, False)
    except AttributeError:
        pass


def _decode_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _truncate_output(text: str, *, limit: int) -> tuple[str, bool]:
    if limit < 0:
        raise ValueError("output limit must be non-negative")
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n... [truncated at {limit} chars]", True


def _duration_ms_since(started_perf: float) -> int:
    return int((time.perf_counter() - started_perf) * 1000)


def _unix_time_ms() -> int:
    return int(time.time() * 1000)
