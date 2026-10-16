import os
import time
import uuid

import pytest

from studybot.core.ingest_staging import StagingArea, StagingError, StagingNotFoundError


@pytest.fixture
def staging(tmp_path):
    area = StagingArea(tmp_path / "ingest_staging")
    area.ensure()
    return area


def stage(area, content=b"%PDF"):
    staging_id = str(uuid.uuid4())
    (area.root / f"{staging_id}.pdf").write_bytes(content)
    return staging_id


def test_resolves_a_staged_file_inside_the_root(staging):
    staging_id = stage(staging)

    path = staging.resolve(staging_id)

    assert path == staging.root / f"{staging_id}.pdf" and path.read_bytes() == b"%PDF"


@pytest.mark.parametrize(
    "bad",
    ["../x", "../../etc/passwd", "/etc/passwd", "", "not-a-uuid", "a/b", "a\\b", f"{uuid.uuid4()}/..", f"{uuid.uuid4()}.pdf",
     f"{uuid.uuid4()}\x00", str(uuid.uuid4()).upper(), str(uuid.uuid1())],
)
def test_malformed_ids_are_rejected_without_touching_the_filesystem(staging, bad):
    with pytest.raises(StagingError):
        staging.resolve(bad)


def test_missing_file_is_not_found(staging):
    with pytest.raises(StagingNotFoundError):
        staging.resolve(str(uuid.uuid4()))


def test_a_symlink_is_never_followed(staging, tmp_path):
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"secret")
    staging_id = str(uuid.uuid4())
    os.symlink(outside, staging.root / f"{staging_id}.pdf")

    with pytest.raises(StagingError):
        staging.resolve(staging_id)
    staging.discard(staging_id)

    assert outside.read_bytes() == b"secret"  # discard did not touch the link target


def test_a_directory_in_place_of_a_file_is_rejected(staging):
    staging_id = str(uuid.uuid4())
    (staging.root / f"{staging_id}.pdf").mkdir()

    with pytest.raises(StagingError):
        staging.resolve(staging_id)


def test_discard_removes_only_the_staged_file(staging):
    staging_id, other = stage(staging), stage(staging)

    staging.discard(staging_id)
    staging.discard(staging_id)  # already gone: no error

    assert not (staging.root / f"{staging_id}.pdf").exists()
    assert (staging.root / f"{other}.pdf").exists()


def test_orphan_cleanup_removes_only_old_files_with_the_staging_name(staging):
    old, fresh = stage(staging), stage(staging)
    ancient = time.time() - 48 * 3600
    os.utime(staging.root / f"{old}.pdf", (ancient, ancient))
    foreign = staging.root / "notes.txt"
    foreign.write_text("keep")
    os.utime(foreign, (ancient, ancient))
    near_miss = staging.root / f"{uuid.uuid4()}.pdf.bak"
    near_miss.write_text("keep")
    os.utime(near_miss, (ancient, ancient))

    removed = staging.cleanup_orphans()

    assert removed == 1
    assert not (staging.root / f"{old}.pdf").exists()
    assert (staging.root / f"{fresh}.pdf").exists() and foreign.exists() and near_miss.exists()


def test_cleanup_without_a_staging_directory_does_nothing(tmp_path):
    assert StagingArea(tmp_path / "missing").cleanup_orphans() == 0


def test_cleanup_does_not_leave_the_staging_root(tmp_path, staging):
    elsewhere = tmp_path / "library-folder"
    elsewhere.mkdir()
    victim = elsewhere / f"{uuid.uuid4()}.pdf"
    victim.write_bytes(b"user file")
    ancient = time.time() - 72 * 3600
    os.utime(victim, (ancient, ancient))

    staging.cleanup_orphans()

    assert victim.exists()
