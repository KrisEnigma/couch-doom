"""Release notes header keeps Windows-first download links the workflow can stamp."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = (ROOT / "packaging" / "release-header.md").read_text(encoding="utf-8")


def test_release_header_lists_windows_before_other_platforms():
    windows = HEADER.index("**Windows:**")
    macos = HEADER.index("**macOS:**")
    linux = HEADER.index("**Linux:**")
    steam = HEADER.index("**Steam Deck:**")
    assert windows < macos < linux < steam


def test_release_header_uses_tag_placeholders_for_download_links():
    assert "CouchDoom-__TAG__-windows-x64.zip" in HEADER
    assert "releases/download/__TAG__/CouchDoom-__TAG__-windows-x64.zip" in HEADER
    assert "CouchDoom-__TAG__-macos-arm64.dmg" in HEADER
    assert "CouchDoom-__TAG__-linux-x64.tar.gz" in HEADER


def test_release_workflow_stamps_the_tag_into_the_header():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert 'sed "s/__TAG__/${GITHUB_REF_NAME}/g" packaging/release-header.md' in workflow
