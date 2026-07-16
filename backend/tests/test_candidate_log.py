from __future__ import annotations

from pathlib import Path

from app.services.candidate_log import CandidateLog


def test_candidate_log_persists_across_instances(tmp_path: Path) -> None:
    log = CandidateLog(tmp_path)
    log.append({"freq_hz": 868_650_000, "candidate_reasons": ["wideband"]})
    log.append({"freq_hz": 868_010_000, "candidate_reasons": ["long_wakeup"]})

    # A fresh instance (simulating a process restart) still sees both.
    reopened = CandidateLog(tmp_path)
    assert reopened.count() == 2
    records = reopened.read_all()
    assert records[0]["freq_hz"] == 868_010_000  # newest first
    assert records[1]["freq_hz"] == 868_650_000


def test_candidate_log_limit_and_clear(tmp_path: Path) -> None:
    log = CandidateLog(tmp_path)
    for i in range(10):
        log.append({"i": i})
    assert len(log.read_all(limit=3)) == 3
    assert log.read_all(limit=3)[0]["i"] == 9
    log.clear()
    assert log.count() == 0
    assert log.read_all() == []


def test_candidate_log_skips_corrupt_lines(tmp_path: Path) -> None:
    log = CandidateLog(tmp_path)
    log.append({"ok": 1})
    with log.path.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    log.append({"ok": 2})
    records = log.read_all()
    assert [r.get("ok") for r in records] == [2, 1]
