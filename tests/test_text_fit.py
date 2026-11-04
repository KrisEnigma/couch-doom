from couch_doom.ui import App, _wrap_mono


class CountingFont:
    def __init__(self):
        self.size_calls = 0

    def size(self, text: str) -> tuple[int, int]:
        self.size_calls += 1
        return len(text) * 10, 20


def test_fit_handles_long_byline_without_measuring_every_character():
    font = CountingFont()

    fitted = App._fit("a" * 400, font, 100)

    assert fitted == "a" * 9 + "…"
    assert font.size_calls <= 3


def test_wrapping_a_readme_is_cached_between_frames():
    text = "A long readme description with enough words to wrap into several lines. " * 12
    font = CountingFont()

    first = App._wrap(text, font, 120, 6)
    calls_after_first = font.size_calls
    second = App._wrap(text, font, 120, 6)

    assert second == first
    assert calls_after_first > 0
    assert font.size_calls == calls_after_first


def test_wrapping_without_a_line_cap_keeps_the_whole_bullet():
    text = " ".join(["word"] * 40)
    font = CountingFont()

    lines = App._wrap(text, font, 50, None)

    assert " ".join(lines) == text
    assert len(lines) > 2
    assert not any(line.endswith("…") for line in lines)


def test_wrapping_a_long_readme_stops_after_the_visible_lines():
    text = "description word " * 400
    font = CountingFont()

    lines = App._wrap(text, font, 120, 6)

    assert len(lines) == 6
    assert lines[-1].endswith("…")
    assert font.size_calls < 50


def test_readme_rules_are_cut_to_the_column_instead_of_wrapping():
    text = "=" * 120 + "\n" + "  " + "-=" * 60 + "\n" + "word " * 30
    lines = _wrap_mono(text, 40)
    assert lines[0] == "=" * 40
    assert lines[1] == "  " + "-=" * 19
    assert len(lines) > 3  # prose still wraps
