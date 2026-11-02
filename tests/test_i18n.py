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
