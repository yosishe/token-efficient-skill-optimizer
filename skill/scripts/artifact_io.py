#!/usr/bin/env python3
"""Collision-safe, atomic publication helpers for generated artifacts."""

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


def _same_existing_file(left, right):
    """Return filesystem identity for two existing paths."""
    try:
        return os.path.samefile(left, right)
    except (FileNotFoundError, NotADirectoryError, OSError):
        return False


def output_overlaps_input(output, source, *, forbid_inside_dirs=True):
    """Return whether OUTPUT aliases, enters, or hard-links to SOURCE.

    Resolved path comparison catches symlink aliases and lexical containment.
    When an output already exists, filesystem identity additionally catches a
    hard link to a protected file, including a file nested under a protected
    directory.
    """
    output = Path(output)
    source = Path(source)
    resolved_output = output.resolve()
    resolved_source = source.resolve()
    if resolved_output == resolved_source:
        return True
    if (forbid_inside_dirs and source.is_dir()
            and resolved_source in resolved_output.parents):
        return True
    if _same_existing_file(output, source):
        return True
    if (not output.exists() or not source.is_dir()
            or source.is_symlink()):
        return False

    for root, dirnames, filenames in os.walk(source, followlinks=False):
        root_path = Path(root)
        dirnames[:] = sorted(
            name for name in dirnames
            if not (root_path / name).is_symlink())
        for name in sorted(filenames):
            candidate = root_path / name
            if candidate.is_symlink():
                continue
            if _same_existing_file(output, candidate):
                return True
    return False


def reject_output_collisions(outputs, inputs, *, forbid_inside_dirs=True):
    """Raise ValueError when an output aliases/enters an input or another output."""
    output_paths = [Path(path) for path in outputs if path is not None]
    input_paths = [Path(path) for path in inputs if path is not None]
    resolved_outputs = [path.resolve() for path in output_paths]
    if len(resolved_outputs) != len(set(resolved_outputs)):
        raise ValueError("generated output paths must be distinct")
    for index, output in enumerate(output_paths):
        for other in output_paths[:index]:
            if _same_existing_file(output, other):
                raise ValueError("generated output paths must be distinct")
    for output, resolved_output in zip(output_paths, resolved_outputs):
        for source in input_paths:
            if output_overlaps_input(
                    output, source,
                    forbid_inside_dirs=forbid_inside_dirs):
                raise ValueError(
                    f"output {output} must not overwrite, alias, or enter "
                    f"input {source}")


def atomic_write_bytes(path, data):
    """Publish DATA with a same-directory fsync + atomic replace."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    )
    staged = Path(handle.name)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, destination)
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def atomic_write_text(path, text):
    atomic_write_bytes(path, text.encode("utf-8"))


@contextmanager
def atomic_text_writer(path):
    """Stream text to a fresh inode, then atomically publish it.

    A caller can safely return from inside the context: the staged file is
    flushed and replaces the destination entry without following a symlink or
    truncating a hard-linked destination inode.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    )
    staged = Path(handle.name)
    try:
        with handle:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, destination)
    except BaseException:
        if not handle.closed:
            handle.close()
        staged.unlink(missing_ok=True)
        raise
