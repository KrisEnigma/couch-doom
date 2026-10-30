import couch_doom.config as config


def test_self_location_is_none_when_not_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FROZEN", False)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    assert config.self_location() is None


def test_self_location_is_the_install_folder_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FROZEN", True)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    assert config.self_location() == tmp_path


def test_self_location_skips_translocated_and_missing_folders(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FROZEN", True)
    translocated = tmp_path / "AppTranslocation" / "ABC" / "CouchDoom.app"
    translocated.mkdir(parents=True)
    monkeypatch.setattr(config, "PROJECT_ROOT", translocated)
    assert config.self_location() is None

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path / "gone")
    assert config.self_location() is None
