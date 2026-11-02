from couch_doom import i18n
from couch_doom.state import State


def test_t_returns_english_by_default():
    i18n.set_language("en")
    assert i18n.t("menu.quit") == "Quit"


def test_missing_key_falls_back_to_english_then_key():
    i18n.set_language("en")
    assert i18n.t("does.not.exist") == "does.not.exist"


def test_format_kwargs():
    i18n.set_language("en")
    assert "3" in i18n.t("toast.loaded", count=3, source="")


def test_detect_maps_es_family():
    assert i18n.normalize_language_tag("es_CL.UTF-8") == "es"
    assert i18n.normalize_language_tag("pt_BR") == "pt_BR"
    assert i18n.normalize_language_tag("pt_PT") == "pt_BR"  # only BR catalog; map pt* → pt_BR
    assert i18n.normalize_language_tag("de_DE") == "de"
    assert i18n.normalize_language_tag("ja_JP") == "en"


def test_detect_maps_windows_locale_names():
    assert i18n.normalize_language_tag("Spanish_Chile") == "es"
    assert i18n.normalize_language_tag("German_Germany") == "de"
    assert i18n.normalize_language_tag("French_France") == "fr"
    assert i18n.normalize_language_tag("Portuguese_Brazil") == "pt_BR"
    assert i18n.normalize_language_tag("Japanese_Japan") == "en"


def test_detect_prefers_the_windows_display_language(monkeypatch):
    monkeypatch.setattr(i18n.sys, "platform", "win32")
    monkeypatch.setattr(i18n, "_windows_ui_language", lambda: "es_CL")
    monkeypatch.setattr(i18n, "_environment_language", lambda: None)
    monkeypatch.setattr(i18n, "_locale_language", lambda: "English_United States")
    assert i18n.detect_system_language() == "es"


def test_detect_prefers_macos_preferred_languages(monkeypatch):
    monkeypatch.setattr(i18n.sys, "platform", "darwin")
    monkeypatch.setattr(i18n, "_macos_ui_language", lambda: "fr-CA")
    monkeypatch.setattr(i18n, "_environment_language", lambda: "en_US.UTF-8")
    assert i18n.detect_system_language() == "fr"


def test_detect_falls_back_through_environment_then_locale(monkeypatch):
    monkeypatch.setattr(i18n.sys, "platform", "linux")
    monkeypatch.setattr(i18n, "_environment_language", lambda: None)
    monkeypatch.setattr(i18n, "_locale_language", lambda: "de_DE")
    assert i18n.detect_system_language() == "de"
    monkeypatch.setattr(i18n, "_locale_language", lambda: None)
    assert i18n.detect_system_language() == "en"


def test_environment_language_skips_c_locale(monkeypatch):
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    monkeypatch.setenv("LANG", "es_CL.UTF-8")
    assert i18n._environment_language() == "es_CL.UTF-8"
    monkeypatch.setenv("LANGUAGE", "pt_BR:en")
    assert i18n._environment_language() == "pt_BR"


def test_macos_preferred_languages_output_is_parsed(monkeypatch):
    import subprocess

    class Done:
        stdout = '(\n    "es-CL",\n    en\n)\n'

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    assert i18n._macos_ui_language() == "es-CL"


def test_state_redetects_the_english_that_1_2_0_saved(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text('{"language": "en", "favorites": ["Sigil"]}', encoding="utf-8")
    monkeypatch.setattr("couch_doom.state.detect_system_language", lambda: "es")
    s = State(path)
    assert (s.language, s.language_source, s.favorites) == ("es", "auto", ["Sigil"])
    monkeypatch.setattr("couch_doom.state.detect_system_language", lambda: "de")
    assert State(path).language == "es"  # detected once, then remembered


def test_state_keeps_a_non_english_1_2_0_language(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text('{"language": "fr"}', encoding="utf-8")
    monkeypatch.setattr("couch_doom.state.detect_system_language", lambda: "es")
    assert State(path).language == "fr"


def test_state_keeps_english_picked_in_the_menu(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    monkeypatch.setattr("couch_doom.state.detect_system_language", lambda: "es")
    State(path).set_language("en")
    s = State(path)
    assert (s.language, s.language_source) == ("en", "menu")


def test_state_leaves_a_damaged_file_alone(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("couch_doom.state.detect_system_language", lambda: "de")
    assert State(path).language == "de"
    assert path.read_text(encoding="utf-8") == "{not json"


def test_state_survives_a_non_object_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("[1, 2]", encoding="utf-8")
    assert State(path).favorites == []


def test_set_language_unknown_falls_back_to_en():
    assert i18n.set_language("ja") == "en"
    assert i18n.current_language() == "en"


def test_state_language_round_trip(tmp_path):
    path = tmp_path / "state.json"
    s = State(path)
    s.set_language("es")
    s2 = State(path)
    assert s2.language == "es"


def test_state_rejects_unknown_language(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"language": "ja"}', encoding="utf-8")
    assert State(path).language == "en"


def test_state_first_run_persists_detected_language(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    monkeypatch.setattr("couch_doom.state.detect_system_language", lambda: "fr")
    s = State(path)
    assert s.language == "fr"
    assert State(path).language == "fr"


def test_locale_key_parity():
    en = i18n.load_catalog("en")
    for code, _ in i18n.LANGUAGES:
        if code == "en":
            continue
        cat = i18n.load_catalog(code)
        missing = sorted(set(en) - set(cat))
        assert missing == [], f"{code} missing {missing[:10]}..."
        extra = sorted(set(cat) - set(en))
        assert extra == [], f"{code} has extra {extra[:10]}..."


def test_german_launcher_fallback_cases():
    i18n.set_language("de")
    assert i18n.t("empty.the_launcher_cap") == "Der Launcher"
    assert i18n.t("empty.the_launcher_in") == "dem Launcher"
    assert "dem Launcher" in i18n.t("empty.no_presets_hint", who=i18n.t("empty.the_launcher_in"))
    assert "Der Launcher" in i18n.t("empty.no_presets_detail", who=i18n.t("empty.the_launcher_cap"))
