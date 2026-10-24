import os
import stat
import uuid

import pytest

from studybot.core.upload_store import UploadStore, is_stored_name


@pytest.fixture
def store(tmp_path):
    return UploadStore(tmp_path / "library_files")


def name():
    return f"{uuid.uuid4()}.pdf"


def test_store_copies_privately_and_leaves_the_source_alone(store, tmp_path):
    original = tmp_path / "Lecture 1.pdf"
    original.write_bytes(b"%PDF original")
    before = original.stat()
    stored = name()

    path = store.store(original, stored)

    assert path == store.root / stored and path.read_bytes() == b"%PDF original"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert original.read_bytes() == b"%PDF original" and original.stat().st_mtime == before.st_mtime
    assert not list(store.root.glob("*.part"))


def test_the_private_copy_survives_the_original_being_deleted(store, tmp_path):
    original = tmp_path / "a.pdf"
    original.write_bytes(b"%PDF data")
    path = store.store(original, name())

    original.unlink()

    assert path.read_bytes() == b"%PDF data"


def test_a_failed_copy_leaves_nothing_behind(store, tmp_path):
    with pytest.raises(FileNotFoundError):
        store.store(tmp_path / "missing.pdf", name())

    assert list(store.root.iterdir()) == []


@pytest.mark.parametrize("bad", ["../x.pdf", "a.pdf", "/etc/passwd", f"{uuid.uuid4()}.txt", "", f"{uuid.uuid4()}/../x.pdf"])
def test_only_generated_names_are_accepted(store, bad):
    assert not is_stored_name(bad)
    with pytest.raises(ValueError):
        store.path_for(bad)


def test_discard_removes_only_the_named_private_file(store, tmp_path):
    original = tmp_path / "a.pdf"
    original.write_bytes(b"x")
    first, second = name(), name()
    store.store(original, first)
    store.store(original, second)

    store.discard(first)
    store.discard(first)
    store.discard("../a.pdf")

    assert not (store.root / first).exists() and (store.root / second).exists() and original.exists()


def test_discard_never_follows_a_symlink(store, tmp_path):
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"user file")
    store.ensure()
    linked = name()
    os.symlink(outside, store.root / linked)

    store.discard(linked)

    assert outside.read_bytes() == b"user file"


def test_orphan_cleanup_removes_only_unreferenced_stored_files_and_partials(store, tmp_path):
    original = tmp_path / "a.pdf"
    original.write_bytes(b"x")
    kept, orphan = name(), name()
    store.store(original, kept)
    store.store(original, orphan)
    partial = store.root / f"{name()}.part"
    partial.write_bytes(b"half")
    foreign = store.root / "notes.txt"
    foreign.write_text("keep")

    removed = store.cleanup_orphans({kept})

    assert removed == 2
    assert (store.root / kept).exists() and not (store.root / orphan).exists() and not partial.exists()
    assert foreign.exists()


def test_cleanup_without_a_directory_does_nothing(tmp_path):
    assert UploadStore(tmp_path / "missing").cleanup_orphans(set()) == 0
