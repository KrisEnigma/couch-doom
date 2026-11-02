from pathlib import Path

from couch_doom import whats_new
from couch_doom.state import State

LOG = """# Changelog

Intro line that is not a release.

**New in 1.3.0**

- Third, with `code` and [a link](https://example.com).

**New in 1.2.1**

- Second.
- Second again.

**New in 1.2.0**

- First.
"""


def _log(tmp_path: Path) -> Path:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(LOG, encoding="utf-8")
    return path


def test_sections_read_every_release_as_plain_text():
    assert whats_new.sections(LOG) == [
        ("1.3.0", ["Third, with code and a link."]),
        ("1.2.1", ["Second.", "Second again."]),
        ("1.2.0", ["First."]),
    ]


def test_since_lists_every_skipped_release_newest_first():
    assert [v for v, _ in whats_new.since(LOG, "1.2.0", "1.3.0")] == ["1.3.0", "1.2.1"]


def test_since_without_a_previous_version_is_only_the_current_release():
    assert [v for v, _ in whats_new.since(LOG, None, "1.3.0")] == ["1.3.0"]


def test_pending_after_an_update(tmp_path):
    found = whats_new.pending("1.2.0", True, "1.3.0", _log(tmp_path))
    assert found and found["previous"] == "1.2.0" and len(found["sections"]) == 2


def test_pending_is_quiet_on_a_fresh_install_and_on_the_same_or_older_version(tmp_path):
    path = _log(tmp_path)
    assert whats_new.pending(None, False, "1.3.0", path) is None
    assert whats_new.pending("1.3.0", True, "1.3.0", path) is None
    assert whats_new.pending("1.4.0", True, "1.3.0", path) is None


def test_pending_without_a_changelog_is_quiet(tmp_path):
    assert whats_new.pending("1.2.0", True, "1.3.0", tmp_path / "missing.md") is None


def test_state_remembers_the_seen_version(tmp_path):
    path = tmp_path / "last_played.json"
    first = State(path)
    assert first.seen_version is None and not first.returning
    first.set_seen_version("1.2.4")
    again = State(path)
    assert again.seen_version == "1.2.4" and again.returning
