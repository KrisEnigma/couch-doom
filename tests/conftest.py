import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pytest

from couch_doom import i18n


@pytest.fixture(autouse=True)
def _english_ui():
    """The catalog is process-wide; a test that switches language must not leak it into the next."""
    i18n.set_language("en")
    yield
    i18n.set_language("en")
