"""Process-wide GPU contention guard.

Merged-TTS and video render both hammer the GPU (AI Voice local weights / NVENC).
Running a quick-build batch at the same time as a wizard video render / AI Voice
local TTS can OOM the GPU, so we serialise them.

The quick-build batch ACQUIRES this guard synchronously at request time (before
the worker thread is spawned — otherwise there is a check-then-act window) and
holds it for the whole batch, releasing when the batch thread finishes. Wizard
GPU entrypoints only READ `is_busy()` and refuse to start while a batch holds
it; the batch, in turn, refuses to start while a wizard GPU task is in flight
(checked separately against the Task table / TTS active-story set).

Single desktop process, so a plain flag guarded by a lock is enough.
"""
import threading

_lock = threading.Lock()
_busy = False


def try_acquire() -> bool:
    """Atomically take the guard. Returns False if it's already held."""
    global _busy
    with _lock:
        if _busy:
            return False
        _busy = True
        return True


def release() -> None:
    global _busy
    with _lock:
        _busy = False


def is_busy() -> bool:
    with _lock:
        return _busy
