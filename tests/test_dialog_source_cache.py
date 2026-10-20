import os
from pathlib import Path
import struct
import threading
import time
from unittest.mock import Mock

import pytest

from WinUx.dialogs.source_signature_cache import SourceSignatureCache, affects_sources, changed_names


@pytest.mark.parametrize("name,relevant", [
    ("WinUx\\ui\\dialog.py", True), ("WINUX/ui/.private.py", True),
    ("WinUx\\new.folder", True), ("WinUx", True),
    ("WinUx\\__pycache__\\dialog.pyc", False), ("WinUx\\__pycache__", False),
    ("WinUx\\Resources\\icon.png", False), ("WinUx\\Resources", False),
    ("WinUx\\.cache\\module.py", False), ("vendor\\module.py", False),
    ("plot_digitizer.pdg", False),
])
def test_notifications_are_filtered_without_missing_module_tree_renames(name, relevant):
    assert affects_sources(name, "WinUx") is relevant


def test_notification_buffer_decoder_preserves_unicode_and_rejects_damage():
    name = "WinUx\\café.py".encode("utf-16-le")
    data = struct.pack("<III", 0, 3, len(name)) + name
    assert changed_names(data) == ["WinUx\\café.py"]
    assert changed_names(b"") is None
    assert changed_names(data[:-1]) is None
    assert changed_names(struct.pack("<III", 8, 3, len(name)) + name) is None


def fake_cache():
    cache = object.__new__(SourceSignatureCache)
    cache.root = Path("WinUx")
    cache._lock = threading.Lock()
    cache._closed = cache.failed = False
    cache._generation = 7
    cache._signature = (("module.py", 1, 3),)
    cache._backend = Mock()
    cache._backend.poll.return_value = []
    cache.scan = Mock(side_effect=AssertionError("UI snapshot must not scan files"))
    return cache


def test_ui_snapshot_never_walks_files_and_invalidates_on_pending_changes():
    cache = fake_cache()
    assert cache.snapshot().generation == 7
    cache._backend.poll.return_value = ["WinUx\\module.py"]
    assert cache.snapshot() is None
    assert cache.generation == 8
    cache.scan.assert_not_called()
    cache._backend.wake.assert_called_once()


def test_overflow_and_watch_failure_never_return_an_old_signature():
    cache = fake_cache()
    cache._backend.poll.return_value = None
    assert cache.snapshot() is None
    cache._backend.poll.side_effect = OSError("watch failed")
    assert cache.snapshot() is None
    assert cache.failed and cache.generation == 9
    cache.scan.assert_not_called()


@pytest.mark.windows_native
@pytest.mark.skipif(os.name != "nt", reason="Windows source notifications")
def test_native_watch_invalidates_even_with_preserved_timestamp_and_detects_root_replacement(tmp_path):
    from WinUx.dialogs.prewarm_pool import runtime_source_signature
    package = tmp_path / "WinUx"
    package.mkdir()
    source = package / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")
    calls = []

    def scan():
        calls.append(threading.get_ident())
        return runtime_source_signature(package)

    cache = SourceSignatureCache(package, scan, lambda snapshot: None)

    def wait_for(predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            snapshot = cache.snapshot()
            assert not cache.failed
            if snapshot is not None and predicate(snapshot):
                return snapshot
            time.sleep(.01)
        pytest.fail("source notification did not become stable")

    try:
        first = wait_for(lambda snapshot: True)
        for _ in range(50):
            assert cache.snapshot() == first
        assert threading.get_ident() not in calls
        old_stat = source.stat()
        source.write_text("value = 2\n", encoding="utf-8")
        os.utime(source, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        second = wait_for(lambda snapshot: snapshot.generation > first.generation and snapshot.signature == first.signature)
        assert second.signature == first.signature
        source_cache = package / "__pycache__"
        source_cache.mkdir()
        (source_cache / "module.pyc").write_bytes(b"bytecode")
        deadline = time.monotonic() + .15
        while time.monotonic() < deadline:
            assert cache.snapshot() == second
            time.sleep(.01)
        package.rename(tmp_path / "WinUx.old")
        package.mkdir()
        (package / "replacement.py").write_text("replacement = True\n", encoding="utf-8")
        replacement = wait_for(lambda snapshot: snapshot.generation > second.generation and
                               bool(snapshot.signature) and snapshot.signature[0][0] == "replacement.py")
        assert replacement.signature != first.signature
    finally:
        cache.close()
        cache.thread.join(timeout=5)
        assert not cache.thread.is_alive(), "watch I/O must be cancelled before buffers are freed"
