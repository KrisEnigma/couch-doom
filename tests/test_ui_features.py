from types import SimpleNamespace

import pygame

from couch_doom import gamepad, ui
from couch_doom.gamepad import Action


def make_app(sections=("Section A", "Section B"), collapsed=(), filter_text=""):
    presets = [
        SimpleNamespace(name="Alpha", section="Section A"),
        SimpleNamespace(name="Beta", section="Section A"),
        SimpleNamespace(name="Gamma", section="Section B"),
    ]
    app = ui.App.__new__(ui.App)
    app.opts = SimpleNamespace(presets=presets, sections=list(sections))
    app.state = SimpleNamespace(favorites=[], music=False)
    app.launchers = None
    app.filter = filter_text
    app.mode = "list"
    app.help_scroll = 0.0
    app.help_view = 0.0
    app.current = 0
    app.cur_row = -1
    app.rows = []
    app.free_scroll = None
    app.collapsed_sections = set(collapsed)
    app.s = 1
    app.header_h = 36
    app.preset_h = 48
    app.problem = None
    app.endooms = {}
    app.readmes = {}
    app.info_tab = 0
    app.info_scrolls = [0] * len(ui.INFO_TABS)
    app.info_scroll = 0.0
    app.info_view = 0.0
    app.info_opened = 0.0
    app.info_lines = ((), [])
    app.input = SimpleNamespace(pad_mode=False, left_y=0.0)
    app._sound = lambda _name: None
    app._compute_row_y()
    return app


def test_f1_is_a_help_action():
    inp = gamepad.Input.__new__(gamepad.Input)
    inp._pad_last = False
    inp._held = {}

    actions = inp.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F1), 0.0)

    assert [action.name for action in actions] == ["HELP"]


def test_f5_opens_help_and_feedback():
    inp = gamepad.Input.__new__(gamepad.Input)
    inp._pad_last = False
    inp._held = {}
    actions = inp.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F5), 0.0)

    assert actions == [Action.ISSUES]


def test_typing_repeated_dashes_filters_without_triggering_an_action():
    app = make_app()
    inp = gamepad.Input.__new__(gamepad.Input)
    inp._pad_last = False
    inp._held = {}

    for _ in range(3):
        actions = inp.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_MINUS), 0.0)
        assert actions == []
        app._on_text("-", 0.0)

    assert app.filter == "---"
    assert app.rows == []


def test_f1_opens_separate_help_and_info_button_keeps_readme_default():
    app = make_app()
    help_action = gamepad.Input.__new__(gamepad.Input)
    help_action._pad_last = False
    help_action._held = {}
    actions = help_action.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F1), 1.0)
    assert [action.name for action in actions] == ["HELP"]

    app._on_action(actions[0], 1.0)
    assert app.mode == "help"

    app.mode = "list"
    app._rebuild_rows()
    app._on_action(Action.ALT, 2.0)
    assert ui.INFO_TABS[app.info_tab] == "Readme"


def test_start_button_opens_the_same_help_modal_for_controller_users():
    app = make_app()
    app.input.pad_mode = True

    app._on_action(Action.MENU, 1.0)

    assert app.mode == "help"


def test_help_covers_the_usage_guide_without_hard_coded_buttons():
    headings = [heading for heading, _ in ui.HELP_SECTIONS]
    text = " ".join(body for _, body in ui.HELP_SECTIONS)

    assert {"START PLAYING", "CAN'T FIND YOUR GAMES?", "MUSIC", "IF SOMETHING DOESN'T WORK"} <= set(headings)
    assert {"REPORT A BUG", "ABOUT"} <= set(headings)
    assert "controller" in text.lower()
    assert "KrisEnigma" in text
    assert "STEAM DECK" not in headings
    assert "F1" not in text and "Enter" not in text and "Tab" not in text


def test_help_scroll_actions_move_by_lines_and_keep_a_smooth_view_target():
    app = make_app()
    app.mode = "help"
    app._help_line_h = lambda: 28
    app._help_max_scroll = lambda: 1000

    app._on_action(Action.DOWN, 0.0)

    assert app.help_scroll == 84
    assert app.help_view == 0


def test_controller_y_opens_the_bug_report_and_footer_shows_it(monkeypatch):
    app = make_app()
    app.mode = "help"
    app.input.pad_mode = True
    opened = []
    monkeypatch.setattr(ui.webbrowser, "open", opened.append)

    hints = app._footer_hints()
    app._on_action(Action.SEARCH, 0.0)

    assert any("Y" in glyphs and label == "Help & Feedback" for glyphs, label, _ in hints)
    assert opened == [ui.ISSUE_URL]
    assert ui.ISSUE_URL.endswith("/issues")


def test_keyboard_f5_opens_help_and_feedback_from_help_modal(monkeypatch):
    app = make_app()
    app.mode = "help"
    opened = []
    monkeypatch.setattr(ui.webbrowser, "open", opened.append)

    app._on_action(Action.ISSUES, 0.0)

    assert opened == [ui.ISSUE_URL]


def test_keyboard_f5_does_nothing_outside_help_modal(monkeypatch):
    app = make_app()
    opened = []
    monkeypatch.setattr(ui.webbrowser, "open", opened.append)

    app._on_action(Action.ISSUES, 0.0)

    assert opened == []


def test_keyboard_footer_separates_help_and_info_and_has_feedback_shortcut():
    app = make_app()
    hints = app._footer_hints()
    labels = [label for _, label, _ in hints]

    assert "Help" in labels and "Info" in labels
    assert "Help / Info" not in labels
    assert not any(label == "Fold group" for label in labels)
    assert any("KEY:F3" in glyphs and label == "Favorite" for glyphs, label, _ in hints)
    assert any("KEY:F2" in glyphs and label in {"Music", "Mute"} for glyphs, label, _ in hints)

    app.mode = "help"
    hints = app._footer_hints()
    assert any("KEY:F5" in glyphs and label == "Help & Feedback" for glyphs, label, _ in hints)


def test_collapsed_sections_keep_their_header_and_hide_their_presets():
    app = make_app(collapsed={"Section A"})

    app._rebuild_rows()

    assert [(row.kind, row.text) for row in app.rows] == [
        ("header", "Section A"),
        ("header", "Section B"),
        ("preset", "Gamma"),
    ]
    assert app.rows[0].collapsed


def test_category_preview_lists_its_games_even_when_the_group_is_collapsed():
    app = make_app(collapsed={"Section A"})
    app._rebuild_rows()
    category = app.rows[0]

    assert [app.opts.presets[i].name for i in app._category_presets(category)] == ["Alpha", "Beta"]


def test_category_preview_uses_available_height_and_two_columns():
    app = make_app()

    columns, visible, more = app._category_preview_capacity(8, 600, 150, 30)

    assert (columns, visible, more) == (2, 8, 0)


def test_category_selection_suppresses_preset_artwork():
    app = make_app()
    app._rebuild_rows()
    app._select_row(0)
    app.art_layers = [(0, object(), 0.0)]
    app.art_jobs = {}
    app._update_art(1.0)

    assert app.art_layers[-1] == (-1, None, 1.0)


def test_category_selection_stops_preset_music():
    app = make_app()
    app._rebuild_rows()
    app._select_row(0)
    requests = []
    app.music = SimpleNamespace(update=lambda: None, want=0, request=requests.append)
    app.state.music = True
    app._music_sel = app.current

    app._update_music(1.0)

    assert requests == [None]


def test_search_temporarily_expands_a_collapsed_section():
    app = make_app(collapsed={"Section A"}, filter_text="Alpha")

    app._rebuild_rows()

    assert any(row.kind == "preset" and row.text == "Alpha" for row in app.rows)
    assert getattr(app.rows[0], "collapsed", None) is False


def test_confirm_on_a_selected_header_toggles_it_and_keeps_category_focus():
    app = make_app()
    app._rebuild_rows()
    app._select_row(0)
    launched = []
    app._launch_selected = lambda: launched.append(True)

    app._on_action(Action.CONFIRM, 0.0)

    assert app.collapsed_sections == {"Section A"}
    assert app.rows[app._sel_row()].kind == "header"
    assert not launched

    app._on_action(Action.CONFIRM, 1.0)
    assert app.collapsed_sections == set()
    assert app.rows[app._sel_row()].kind == "header"


def test_up_down_navigation_can_select_category_without_changing_the_game():
    app = make_app()
    app._rebuild_rows()

    app._move(-1)

    assert app.cur_row == 0
    assert app.rows[app.cur_row].kind == "header"
    assert app.current == 0
    app._move(1)
    assert app.rows[app.cur_row].text == "Alpha"


def test_section_jump_lands_on_the_category_card():
    app = make_app()
    app._rebuild_rows()

    app._jump_section(1)

    assert app.rows[app.cur_row].kind == "header"
    assert app.rows[app.cur_row].text == "Section B"


def test_left_from_a_game_selects_its_group_header_then_previous_group():
    app = make_app()
    app._rebuild_rows()
    app._select_row(4)  # Gamma in Section B

    app._on_action(Action.LEFT, 0.0)

    assert app.collapsed_sections == set()
    assert app.rows[app._sel_row()].kind == "header"
    assert app.rows[app._sel_row()].text == "Section B"

    app._on_action(Action.LEFT, 1.0)

    assert app.rows[app._sel_row()].text == "Section A"


def test_section_jump_selects_folded_category_then_confirm_reopens_it():
    app = make_app(collapsed={"Section A"})
    app._rebuild_rows()

    app._jump_section(-1)

    assert app.rows[app._sel_row()].kind == "header"
    assert app.rows[app._sel_row()].text == "Section A"
    app._on_action(Action.CONFIRM, 1.0)
    assert app.collapsed_sections == set()
    assert app.rows[app._sel_row()].kind == "header"
