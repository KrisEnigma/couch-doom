from collections import OrderedDict
from types import SimpleNamespace

import pygame

from couch_doom import gamepad, i18n, ui
from couch_doom.gamepad import Action
from couch_doom.theme import theme_for_palette


def make_app(sections=("Section A", "Section B"), collapsed=(), filter_text=""):
    presets = [
        SimpleNamespace(name="Alpha", section="Section A"),
        SimpleNamespace(name="Beta", section="Section A"),
        SimpleNamespace(name="Gamma", section="Section B"),
    ]
    app = ui.App.__new__(ui.App)
    app.opts = SimpleNamespace(presets=presets, sections=list(sections), path="/settings.ini")
    app.state = SimpleNamespace(
        favorites=[],
        history=[],
        music=False,
        menu_sounds=True,
        recent_group=False,
        launcher=("doomrunner", "/settings.ini"),
        color_palette="auto",
        language="en",
    )
    app.state.set_music = lambda on: setattr(app.state, "music", on)
    app.state.set_menu_sounds = lambda on: setattr(app.state, "menu_sounds", on)
    app.state.set_recent_group = lambda on: setattr(app.state, "recent_group", on)
    app.state.set_color_palette = lambda key: setattr(app.state, "color_palette", "auto" if key in (None, "auto") else key)
    app.state.set_language = lambda code: setattr(app.state, "language", code)
    app.quit_at = None
    app.launchers = None
    app.filter = filter_text
    app.mode = "list"
    app.menu_sel = 0
    app.menu_opened = 0.0
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
    app.info_scrolls = [0] * ui.INFO_TAB_COUNT
    app.info_scroll = 0.0
    app.info_view = 0.0
    app.info_opened = 0.0
    app.info_lines = ((), [])
    app.themes = {}
    app.theme = ui.HOUSE
    app.theme_from = None
    app.theme_born = 0.0
    app.theme_t = 1.0
    app.bar_surface = None
    app._bar_for = lambda theme: theme
    app.art_layers = [(0, object(), 0.0)]
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


def test_backspace_repeats_on_repeated_keydown_and_stops_on_keyup():
    inp = gamepad.Input.__new__(gamepad.Input)
    inp._pad_last = False
    inp._held = {}
    down = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE)
    up = pygame.event.Event(pygame.KEYUP, key=pygame.K_BACKSPACE)

    assert inp.handle(down, 0.0) == [Action.DELETE]
    assert inp.handle(down, 0.04) == [Action.DELETE]
    assert inp.update(1.0) == []  # repeated keydowns own the timing; the hold timer must not add more

    assert inp.handle(up, 1.1) == []
    assert inp.update(1.2) == []
    assert inp.handle(down, 1.3) == [Action.DELETE]


def test_keyboard_repeat_does_not_double_fire_a_held_direction():
    inp = gamepad.Input.__new__(gamepad.Input)
    inp._pad_last = False
    inp._held = {}
    down = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN)

    assert inp.handle(down, 0.0) == [Action.DOWN]
    assert inp.handle(down, 0.05) == []
    assert inp.update(0.4) == [Action.DOWN]

    assert inp.handle(pygame.event.Event(pygame.KEYUP, key=pygame.K_DOWN), 0.5) == []
    assert inp.update(0.6) == []


def test_keyboard_repeat_timing_is_positive():
    delay, interval = gamepad.keyboard_repeat_timing()

    assert delay > 0
    assert interval > 0


def test_typing_only_edits_the_filter_in_list_and_search():
    app = make_app(filter_text="abc")
    for mode in ("menu", "launcher", "browse", "info", "help", "update"):
        app.mode = mode
        app._on_text("x", 0.0)
        assert app.filter == "abc"

    app.mode = "search"
    app._on_text("x", 0.0)
    assert app.filter == "abcx"


def test_keyboard_slash_types_into_the_filter_instead_of_opening_search():
    app = make_app()
    app.mode = "list"
    opened = []
    app._open_search = lambda now: opened.append(now)

    app._on_text("/", 0.0)

    assert app.filter == "/"
    assert opened == []


def test_keyboard_list_footer_has_no_search_hint_but_pad_does():
    from couch_doom.i18n import t as tr

    app = make_app()
    app._rebuild_rows()
    app.input = SimpleNamespace(pad_mode=False, left_y=0.0, family="xbox")
    assert not any(label == tr("hint.search") for _, label, _ in app._footer_hints())

    app.input.pad_mode = True
    assert any("Y" in glyphs and label == tr("hint.search") for glyphs, label, _ in app._footer_hints())


def test_backspace_is_consumed_by_overlays_but_reaches_the_filter_in_list_mode():
    app = make_app(filter_text="abc")
    down = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE)
    for mode in ("menu", "launcher", "browse", "update"):
        app.mode = mode
        assert app._on_key(down) is True
    for mode in ("list", "search", "info", "help"):
        app.mode = mode
        assert app._on_key(down) is False

    app.mode = "list"
    app._on_action(Action.DELETE, 0.0)
    assert app.filter == "ab"


def test_ctrl_jumps_to_the_last_played_game_and_a_chord_does_not():
    from couch_doom.glyphs import ASSET_DIR, _KEY_FILES
    from couch_doom.i18n import t as tr

    assert (ASSET_DIR / f"{_KEY_FILES['CTRL']}.svg").is_file()

    app = make_app(filter_text="hello world ")
    app.state.last_played = "Gamma"
    app.collapsed_sections = {"Section B"}
    app._rebuild_rows()
    app.current = 0

    app._on_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LCTRL))
    chord = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE, mod=pygame.KMOD_CTRL)
    assert app._on_key(chord) is True
    assert app.filter == "hello "
    app._release_ctrl(pygame.K_LCTRL)
    assert app.current == 0

    app._set_filter("")
    assert any(glyphs == ("KEY:CTRL",) and label == tr("hint.last") for glyphs, label, _ in app._footer_hints())
    app._on_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RCTRL))
    app._release_ctrl(pygame.K_RCTRL)
    assert app.opts.presets[app.current].name == "Gamma"
    assert "Section B" not in app.collapsed_sections


def test_ctrl_backspace_deletes_the_last_filter_word():
    app = make_app(filter_text="hello world ")
    app.mode = "list"
    down = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE, mod=pygame.KMOD_CTRL)

    assert app._on_key(down) is True
    assert app.filter == "hello "

    assert app._on_key(down) is True
    assert app.filter == ""

    app.filter = "alpha beta"
    app.mode = "search"
    assert app._on_key(down) is True
    assert app.filter == "alpha "

    app.mode = "menu"
    app.filter = "keep me"
    assert app._on_key(down) is True  # overlays still swallow Backspace
    assert app.filter == "keep me"

    plain = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE, mod=0)
    app.mode = "list"
    app.filter = "ab"
    assert app._on_key(plain) is False  # bare Backspace still reaches Action.DELETE


def test_escape_clears_the_filter_before_opening_the_menu():
    from couch_doom.i18n import t as tr

    app = make_app(filter_text="beta")
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)

    assert app._footer_hints()[0][1] == tr("hint.clear")
    assert app._on_key(esc) is True
    assert app.filter == ""
    assert app.mode == "list"
    assert app._footer_hints()[0][1] == tr("hint.menu")

    assert app._on_key(esc) is False  # empty filter: Escape reaches the menu action

    app.filter = "beta"
    app._rebuild_rows()
    app._on_action(Action.BACK, 0.0)  # clicking the Clear hint (or B) does the same
    assert app.filter == ""


def test_art_fades_out_when_the_filter_has_no_matching_presets():
    app = make_app()
    app.filter = "nothing matches this"
    app._rebuild_rows()
    app.art_layers = [(app.current, None, 0.0)]
    app.art_cache = {}

    app._update_art(0.7)

    assert app.rows == []
    assert app.art_layers[-1][0] == -1


def test_recently_played_group_uses_history_and_skips_stale_names():
    app = make_app()
    app.state.history = ["Gamma", "Missing", "Alpha"]
    app.state.recent_group = True

    app._rebuild_rows()

    from couch_doom.i18n import t as tr

    headers = [row for row in app.rows if row.kind == "header"]
    assert [row.group_id or row.text for row in headers] == [ui.RECENT_ID, "Section A", "Section B"]
    assert headers[0].text == tr("group.recent")
    assert headers[0].count == 2
    assert [row.text for row in app.rows if row.kind == "preset"][:2] == ["Gamma", "Alpha"]


def test_menu_cycles_global_colors_with_left_right_and_enter():
    app = make_app()
    art_theme = theme_for_palette("green")
    app.themes[0] = art_theme
    app.themes[1] = art_theme
    app.theme = art_theme
    app.mode = "menu"
    app.menu_sel = [key for key, _ in app._menu_items()].index("colors")
    assert app.state.color_palette == "auto"

    app._on_action(Action.RIGHT, 1.0)
    assert app.state.color_palette == "red"
    assert app.theme == theme_for_palette("red")
    assert app.mode == "menu"

    app._on_action(Action.LEFT, 2.0)
    assert app.state.color_palette == "auto"
    assert app.theme == art_theme

    app._menu_pick(app.menu_sel)
    assert app.state.color_palette == "red"

    app.current = 1
    app.art_layers = [(1, object(), 0.0)]
    app._update_theme(3.0)
    assert app.theme == theme_for_palette("red")


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
    assert ui.info_tabs()[app.info_tab] == "Readme"


def test_back_opens_help_and_start_opens_menu_with_music_option():
    inp = gamepad.Input.__new__(gamepad.Input)
    inp._pad_last = False
    inp._held = {}

    back = inp.handle(pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, instance_id=0, button=pygame.CONTROLLER_BUTTON_BACK), 1.0)
    start = inp.handle(pygame.event.Event(pygame.CONTROLLERBUTTONDOWN, instance_id=0, button=pygame.CONTROLLER_BUTTON_START), 2.0)

    assert back == [Action.HELP]
    assert start == [Action.MENU]

    app = make_app()
    app.input.pad_mode = True
    app._on_action(back[0], 1.0)
    assert app.mode == "help"
    app.mode = "list"
    app._on_action(start[0], 2.0)
    assert app.mode == "menu"
    app._menu_pick(2)
    assert app.state.music


def test_pad_footer_puts_help_on_back_and_menu_on_start():
    from couch_doom.i18n import t as tr

    app = make_app()
    app.input.pad_mode = True

    hints = app._footer_hints()

    assert any(glyphs == ("BACK",) and label == tr("hint.help") for glyphs, label, _ in hints)
    assert any(glyphs == ("START",) and label == tr("hint.menu") for glyphs, label, _ in hints)


def test_b_jumps_to_the_last_played_game_and_opens_its_group():
    from couch_doom.i18n import t as tr

    app = make_app()
    app.state.last_played = "Gamma"
    app.collapsed_sections = {"Section B"}
    app.input.pad_mode = True
    app._rebuild_rows()
    app.current = 0

    assert not any(row.kind == "preset" and row.text == "Gamma" for row in app.rows)
    assert any(glyphs == ("B",) and label == tr("hint.last") and actions == (Action.BACK,) for glyphs, label, actions in app._footer_hints())

    app._on_action(Action.BACK, 0.0)

    assert app.opts.presets[app.current].name == "Gamma"
    assert any(row.kind == "preset" and row.text == "Gamma" for row in app.rows)
    assert "Section B" not in app.collapsed_sections


def _group_of(app, row: int) -> str | None:
    for i in range(row, -1, -1):
        if app.rows[i].kind == "header":
            return app.rows[i].group_id or app.rows[i].text
    return None


def test_selecting_recently_played_does_not_slide_the_same_game_below():
    app = make_app()
    app.row_offset = {}
    app.dt = 1.0
    app.s = 1.0
    alpha = 0

    recent = app._row_slide(ui.RECENT_ID, alpha, True)
    section = app._row_slide("Section A", alpha, False)

    assert recent == 16
    assert section == 0
    assert app.row_offset[(ui.RECENT_ID, alpha)] == 16
    assert app.row_offset[("Section A", alpha)] == 0


def test_last_toggles_between_recently_played_and_the_games_own_group():
    app = make_app()
    app.state.last_played = "Gamma"
    app.state.history = ["Gamma", "Alpha"]
    app.state.recent_group = True
    app.collapsed_sections = {"Section B", ui.RECENT_ID}
    app._rebuild_rows()
    app.current = 0  # Alpha, not the last game

    app._on_action(Action.BACK, 0.0)

    assert _group_of(app, app._sel_row()) == ui.RECENT_ID
    assert ui.RECENT_ID not in app.collapsed_sections
    assert "Section B" in app.collapsed_sections

    app._on_action(Action.BACK, 1.0)

    assert app.opts.presets[app.current].name == "Gamma"
    assert _group_of(app, app._sel_row()) == "Section B"
    assert "Section B" not in app.collapsed_sections

    app._on_action(Action.BACK, 2.0)

    assert _group_of(app, app._sel_row()) == ui.RECENT_ID


def test_b_on_the_last_played_game_stays_put_and_a_missing_one_does_nothing():
    app = make_app()
    app.state.last_played = "Alpha"
    app._rebuild_rows()
    app.current = 0
    sounds = []
    app._sound = sounds.append

    app._on_action(Action.BACK, 0.0)

    assert app.current == 0
    assert sounds == []

    app.state.last_played = "Gone"
    app.current = 1
    app._on_action(Action.BACK, 1.0)

    assert app.current == 1
    assert sounds == []


def test_pad_footer_hides_last_until_a_game_has_been_played_and_b_still_clears_search():
    from couch_doom.i18n import t as tr

    app = make_app()
    app.input.pad_mode = True
    app._rebuild_rows()

    assert not any(glyphs == ("B",) for glyphs, _, _ in app._footer_hints())

    app.filter = "beta"
    app._rebuild_rows()
    assert any(glyphs == ("B",) and label == tr("hint.clear") for glyphs, label, _ in app._footer_hints())
    app._on_action(Action.BACK, 0.0)
    assert app.filter == ""


def test_help_covers_the_usage_guide_without_hard_coded_buttons():
    sections = ui.help_sections()
    headings = [heading for heading, _ in sections]
    text = " ".join(body for _, body in sections)

    assert {"START PLAYING", "CAN'T FIND YOUR PRESETS?", "MENU AND MUSIC", "IF SOMETHING DOESN'T WORK"} <= set(headings)
    assert {"REPORT A BUG", "ABOUT"} <= set(headings)
    assert "controller" in text.lower()
    assert "last preset you played" in text.lower()
    assert "KrisEnigma" in text
    assert "STEAM DECK" not in headings
    assert "F1" not in text and "Enter" not in text and "Tab" not in text


def test_every_language_fills_in_the_version_and_log_location():
    for code, _ in i18n.LANGUAGES:
        i18n.set_language(code)
        text = " ".join(body for _, body in ui.help_sections())
        assert "{" not in text and "}" not in text, code
        assert f"v{ui.__version__}" in text, code
        assert "couch-doom.log" in text, code


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

    from couch_doom.i18n import t as tr

    hints = app._footer_hints()
    app._on_action(Action.SEARCH, 0.0)

    assert any("Y" in glyphs and label == tr("hint.help_feedback") for glyphs, label, _ in hints)
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
    from couch_doom.i18n import t as tr

    app = make_app()
    hints = app._footer_hints()
    labels = [label for _, label, _ in hints]

    assert tr("hint.help") in labels and tr("hint.info") in labels
    assert "Help / Info" not in labels
    assert not any(label == "Fold group" for label in labels)
    assert any("KEY:F3" in glyphs and label == tr("hint.favorite") for glyphs, label, _ in hints)
    assert any("KEY:ESC" in glyphs and label == tr("hint.menu") for glyphs, label, _ in hints)

    app.mode = "help"
    hints = app._footer_hints()
    assert any("KEY:F5" in glyphs and label == tr("hint.help_feedback") for glyphs, label, _ in hints)


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


def test_category_selection_shows_no_games_art():
    app = make_app()
    app._rebuild_rows()
    app._select_row(0)
    lead = app._category_presets(app.rows[0])[0]
    app.art_layers = [(lead, object(), 0.0)]
    app.art_cache = OrderedDict({lead: object()})
    app._update_art(1.0)

    assert app.art_layers[-1] == (-1, None, 1.0)


def test_category_count_says_presets_not_games():
    from couch_doom.i18n import t as tr

    app = make_app()
    app._rebuild_rows()
    row = next(r for r in app.rows if r.kind == "header")
    row.count = 2
    label = app._category_count_label(row)

    assert label == tr("group.n_presets_plural", count=2)
    assert "preset" in label.lower()
    assert "game" not in label.lower()


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


def test_alt_on_header_collapses_all_groups():
    app = make_app()
    app._rebuild_rows()
    app._select_row(0)
    opened = []
    app._open_info = lambda now: opened.append(now)

    app._on_action(Action.ALT, 0.0)

    assert app.collapsed_sections == {"Section A", "Section B"}
    assert not opened
    assert all(row.kind == "header" for row in app.rows)


def test_alt_on_header_expands_when_everything_is_collapsed():
    app = make_app(collapsed={"Section A", "Section B"})
    app._rebuild_rows()
    app._select_row(0)

    app._on_action(Action.ALT, 0.0)

    assert app.collapsed_sections == set()


def test_alt_on_preset_still_opens_info():
    app = make_app()
    app._rebuild_rows()
    app._select_row(1)
    opened = []
    app._open_info = lambda now: opened.append(now)

    app._on_action(Action.ALT, 1.0)

    assert opened == [1.0]
    assert app.collapsed_sections == set()


def test_bulk_fold_blocked_while_filter_active():
    app = make_app(filter_text="Alpha")
    app._rebuild_rows()
    notes = []
    app._notify = lambda msg, color: notes.append(msg)
    app.collapsed_sections = set()

    app._collapse_all_groups()

    assert notes
    assert app.collapsed_sections == set()


def test_menu_has_no_expand_or_collapse_all_rows():
    app = make_app()
    keys = [key for key, _ in app._menu_items()]
    assert "expand_all" not in keys
    assert "collapse_all" not in keys


def test_menu_full_screen_row_uses_the_same_toggle_as_alt_enter():
    app = make_app()
    app.mode = "menu"
    calls = []
    app._toggle_window = lambda: calls.append("toggle")
    index = [key for key, _ in app._menu_items()].index("fullscreen")
    assert index == [key for key, _ in app._menu_items()].index("recent") + 1

    app._menu_pick(index)
    app.menu_sel = index
    app._set_menu_option(-1)
    app._on_menu_action(Action.RIGHT, repeat=True)

    assert calls == ["toggle", "toggle"]


def test_menu_includes_language_row():
    app = make_app()
    keys = [key for key, _ in app._menu_items()]
    assert "language" in keys
    assert keys.index("language") == keys.index("colors") + 1


def test_cycle_language_applies_catalog():
    from couch_doom.i18n import current_language, set_language

    app = make_app()
    set_language("en")
    app.state.language = "en"
    applied = []
    app.state.set_language = lambda code: (applied.append(code), setattr(app.state, "language", code))
    app._rebuild_rows = lambda: None
    app._cycle_language(1)
    assert applied[0] == "es"
    assert current_language() == "es"
    assert app.state.language == "es"


def test_favorites_collapse_survives_language_change():
    from couch_doom.i18n import set_language, t as tr

    app = make_app()
    app.state.favorites = ["Alpha"]
    app.state.language = "en"
    set_language("en")
    app._rebuild_rows()
    app.collapsed_sections.add(ui.FAVORITES_ID)
    app.state.language = "es"
    set_language("es")
    app._rebuild_rows()
    assert ui.FAVORITES_ID in app.collapsed_sections
    fav = next(r for r in app.rows if getattr(r, "group_id", None) == ui.FAVORITES_ID)
    assert fav.text == tr("group.favorites")
    assert fav.collapsed is True


def test_footer_shows_bulk_fold_hint_on_category():
    app = make_app()
    app._rebuild_rows()
    app._select_row(0)
    app.input = SimpleNamespace(pad_mode=False, left_y=0.0, family="xbox")

    hints = app._footer_hints()

    from couch_doom.i18n import t as tr

    assert any(label == tr("hint.collapse_all") and Action.ALT in actions for _, label, actions in hints)


def test_up_down_navigation_can_select_category_without_changing_the_game():
    app = make_app()
    app._rebuild_rows()

    app._move(-1)

    assert app.cur_row == 0
    assert app.rows[app.cur_row].kind == "header"
    assert app.current == 0
    app._move(1)
    assert app.rows[app.cur_row].text == "Alpha"


def test_main_list_wraps_on_press_but_not_while_held():
    app = make_app()
    app._rebuild_rows()
    app._select_row(0)

    app._on_action(Action.UP, 1.0, repeat=True)
    assert app.cur_row == 0

    app._on_action(Action.UP, 2.0)
    assert app.cur_row == len(app.rows) - 1


def test_main_list_held_repeat_at_limit_does_not_reselect_row():
    app = make_app()
    app._rebuild_rows()
    app._select_row(0)
    selected = []
    app._select_row = selected.append

    app._on_action(Action.UP, 1.0, repeat=True)

    assert selected == []


def test_launcher_selector_wraps_on_press_but_not_while_held():
    first, second = SimpleNamespace(id="first"), SimpleNamespace(id="second")
    app = ui.App.__new__(ui.App)
    app.launchers = SimpleNamespace(choices=[first, second], current=first)
    app.picker = [first, second, None]
    app.picker_sel = 0
    sounds = []
    app._sound = sounds.append

    app._on_picker_action(Action.UP, repeat=True)
    assert app.picker_sel == 0
    assert sounds == []

    app._on_picker_action(Action.UP)
    assert app.picker_sel == 2
    assert sounds == ["move"]


def test_folder_browser_wraps_on_press_but_not_while_held(tmp_path):
    from couch_doom.filebrowser import Browser

    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()
    app = ui.App.__new__(ui.App)
    app.file_browser = Browser(tmp_path, candidates=[tmp_path])
    app.browser_scroll = 0
    app.mode = "browse"
    app.quit_at = None
    app.h, app.s = 810, 1
    app.footer_h = 48
    app._sound = lambda _name: None

    app._on_action(Action.UP, 1.0, repeat=True)
    assert app.file_browser.selected == 0

    app._on_action(Action.UP, 2.0)
    assert app.file_browser.selected == len(app.file_browser.entries) - 1


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


def test_launcher_picker_opens_from_cached_choices_without_refreshing_or_loading():
    choice = SimpleNamespace(id="doomrunner")
    app = ui.App.__new__(ui.App)
    app.launchers = SimpleNamespace(
        choices=[choice], current=choice,
        refresh=lambda: (_ for _ in ()).throw(AssertionError("picker refresh must not block")),
        preview=lambda _choice: (_ for _ in ()).throw(AssertionError("picker preview must not block")),
    )
    app._sound = lambda _name: None

    app._open_picker()

    assert app.mode == "launcher"
    assert app.picker == [choice, None]
