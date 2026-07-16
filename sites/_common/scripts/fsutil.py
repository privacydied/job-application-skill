#!/usr/bin/env python3
"""fsutil.py — shared atomic + advisory-locked file writes for the CSV/JSONL state
files that the warm-queue daemon and a live loop firing both touch concurrently
(perf-roadmap Tier A). Before this, several shared writers were non-atomic
(`open(path, "w")` streaming rows) and/or did an unguarded read-modify-write, so a
concurrent reader could see a truncated file and a concurrent writer could lose an
update. Every writer in `_common/scripts` should route through these two primitives.

Two primitives:
  file_lock(path)   — context manager holding an EXCLUSIVE advisory flock on
                      <path>.lock for the duration of a read-modify-write. Best-effort:
                      a missing fcntl or a lock error degrades to a no-op (advisory —
                      never block a state write; matches the "yield log is advisory,
                      a write failure must never break sourcing" contract).
  atomic_write(path, write_fn)
                    — stream content via write_fn(fh) into a temp file in the SAME
                      directory, then os.replace() it onto `path` (atomic on POSIX).
                      A reader never observes a truncated/half-written file.

Typical locked read-modify-write (the pattern A.2/A.3/A.4 use):
    with file_lock(path):
        rows = read(path)                       # reflects the latest committed state
        rows = mutate(rows)
        atomic_write(path, lambda f: dump(rows, f))
"""
import contextlib
import os
import tempfile

try:
    import fcntl  # POSIX only (this host is Linux); degrade gracefully elsewhere
except ImportError:  # pragma: no cover
    fcntl = None


@contextlib.contextmanager
def file_lock(path):
    """Hold an exclusive advisory lock on <path>.lock across a read-modify-write.
    Best-effort: if the lock file can't be opened or flock fails/absent, yields anyway
    (an unlocked pass is strictly better than blocking or crashing a state write)."""
    lock_path = str(path) + ".lock"
    fh = None
    try:
        try:
            fh = open(lock_path, "w")
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except OSError:
            if fh is not None:
                try:
                    fh.close()
                except OSError:
                    pass
            fh = None
        yield
    finally:
        if fh is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                fh.close()
            except OSError:
                pass


def atomic_write(path, write_fn, mode="w", encoding="utf-8", newline=""):
    """Write via write_fn(fh) into a temp file in the same dir, then os.replace onto
    `path`. On any error the temp file is removed and `path` is left untouched. For
    binary, pass mode="wb" (encoding/newline are ignored). Returns True on success."""
    path = str(path)
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".swp")
    try:
        if "b" in mode:
            with os.fdopen(fd, mode) as f:
                write_fn(f)
        else:
            with os.fdopen(fd, mode, encoding=encoding, newline=newline) as f:
                write_fn(f)
        os.replace(tmp, path)
        return True
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def locked_append(path, write_fn, encoding="utf-8", newline=""):
    """Append via write_fn(fh) under the file lock — serializes concurrent appenders so
    a header-creation race can't double-write and rows can't interleave. Best-effort on
    the lock; the append itself is a normal open(,"a")."""
    with file_lock(path):
        with open(path, "a", encoding=encoding, newline=newline) as f:
            write_fn(f)
