"""Tests for backup creation, verification, restore and the file-based index.

The registry must survive a restore: it lives in ``index.json`` next to the
backup files, not in the SQLite database that a restore replaces. These tests
exercise the real service against a real temporary directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from elektrocoach.backup.service import INDEX_NAME, BackupService


@pytest.fixture()
def backup_service(repo, options):
    return BackupService(repo, options)


def _seed_question(repo, prompt: str) -> int:
    return repo.create_question(
        type="numeric", prompt=prompt, subject="Test", topic="Test",
        payload={}, solution={"expected": 1, "max_points": 1},
    )


def test_backup_is_registered_in_a_file_index(backup_service, repo, options):
    _seed_question(repo, "vor dem Backup")
    record = backup_service.create(kind="manual")
    assert record["id"] == 1
    assert Path(record["path"]).is_file()

    index_path = backup_service.target_dir() / INDEX_NAME
    assert index_path.is_file(), "the registry must be a file next to the backups"

    status = backup_service.status()
    assert status["count"] == 1
    assert status["backups"][0]["filename"] == record["filename"]
    assert status["last"]["filename"] == record["filename"]


def test_index_survives_a_database_replacement(backup_service, repo, options):
    """Simulate the core failure: the database is swapped out.

    A registry kept only in the database would come back empty and hide the
    safety backup, so the index must live outside the database.
    """

    _seed_question(repo, "erste Frage")
    first = backup_service.create(kind="manual")

    # Wipe the registry table, as a restore of an older database would.
    repo.db.execute("DELETE FROM backups")
    assert repo.list_backups() == []

    status = backup_service.status()
    assert status["count"] == 1, "the index must restore the lost registry"
    assert status["backups"][0]["filename"] == first["filename"]


def test_restore_keeps_the_safety_backup_visible(backup_service, repo, options):
    _seed_question(repo, "bleibt erhalten")
    first = backup_service.create(kind="manual")
    assert backup_service.status()["count"] == 1

    # Add data that the restore must roll back.
    _seed_question(repo, "wird verworfen")
    assert len(repo.list_questions()) == 2

    result = backup_service.restore(first["id"], create_safety_backup=True)
    assert result["integrity"] == "ok"
    assert result["safety_backup"] is not None

    # The restored database contains only the original question ...
    assert len(repo.list_questions()) == 1

    # ... and both backups are still listed, so the restore can be undone.
    status = backup_service.status()
    filenames = {b["filename"] for b in status["backups"]}
    assert first["filename"] in filenames
    assert result["safety_backup"]["filename"] in filenames
    assert status["count"] == 2


def test_verify_flags_a_corrupt_backup(backup_service, repo, options):
    record = backup_service.create(kind="manual")
    path = Path(record["path"])
    path.write_bytes(b"not a zip file at all")

    report = backup_service.verify(record["id"])
    assert report["ok"] is False
    assert report["problems"]

    # A corrupt backup must be refused for restore.
    with pytest.raises(ValueError):
        backup_service.restore(record["id"])


def test_delete_removes_file_and_index_entry(backup_service, repo, options):
    record = backup_service.create(kind="manual")
    backup_service.delete(record["id"])
    assert not Path(record["path"]).exists()
    assert backup_service.status()["count"] == 0


def test_restore_works_when_the_backup_is_the_oldest(backup_service, repo, options):
    """The safety backup must not prune the file that is being restored."""

    options.backup_keep = 7
    _seed_question(repo, "alt")
    created = [backup_service.create(kind="manual") for _ in range(3)]

    # Tighten the budget so that restoring the oldest backup would normally
    # prune it while the safety backup is being written.
    options.backup_keep = 2

    result = backup_service.restore(created[0]["id"], create_safety_backup=True)
    assert result["integrity"] == "ok"
    assert result["restored"] == created[0]["filename"]
    assert result["safety_backup"] is not None


def test_restore_refreshes_other_threads_connections(backup_service, repo, options):
    """A restore must not leave other threads on the old, replaced file.

    Regression: the job worker kept a SQLite connection to the unlinked file
    after a restore, so it silently stopped processing queued jobs until the
    add-on was restarted. ``invalidate_connections`` bumps a generation counter
    that every thread checks before reusing its connection.
    """

    import threading

    _seed_question(repo, "im Backup")
    record = backup_service.create(kind="manual")

    other = {}
    ready = threading.Event()
    proceed = threading.Event()

    def worker_thread():
        # Open a connection in this thread and read once (as the job worker does).
        other["before"] = repo.db.scalar("SELECT COUNT(*) FROM questions")
        ready.set()
        proceed.wait(timeout=5)
        # After the restore this thread must observe the restored data.
        other["after"] = repo.db.scalar("SELECT COUNT(*) FROM questions")

    thread = threading.Thread(target=worker_thread)
    thread.start()
    ready.wait(timeout=5)

    # Add data that the restore rolls back, then restore in the main thread.
    _seed_question(repo, "wird verworfen")
    backup_service.restore(record["id"], create_safety_backup=False)
    proceed.set()
    thread.join(timeout=5)

    assert other["before"] == 1
    assert other["after"] == 1, (
        "the worker thread must see the restored database, not the replaced file"
    )
    # And the main thread's view matches.
    assert repo.db.scalar("SELECT COUNT(*) FROM questions") == 1


def test_prune_keeps_the_configured_number(backup_service, repo, options):
    options.backup_keep = 2
    created = [backup_service.create(kind="manual") for _ in range(4)]
    status = backup_service.status()
    assert status["count"] == 2
    # The newest two survive.
    names = {b["filename"] for b in status["backups"]}
    assert created[-1]["filename"] in names
    assert created[-2]["filename"] in names
    assert not Path(created[0]["path"]).exists()
