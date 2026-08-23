import json

from lesysbot.artifacts.lockfile import JsonState


def test_load_missing_file(tmp_path):
    state = JsonState(tmp_path / "lesysbot.lock.json", "tools")
    assert state.load() == {}


def test_round_trip(tmp_path):
    path = tmp_path / "lesysbot.lock.json"
    state = JsonState(path, "tools")
    state.save({"gpu-temp": {"repo": "acme/mono", "commit": "abc"}})
    assert JsonState(path, "tools").load() == {
        "gpu-temp": {"repo": "acme/mono", "commit": "abc"}
    }
    payload = json.loads(path.read_text())
    assert payload["version"] == 1
    assert not path.with_name("lesysbot.lock.json.tmp").exists()  # atomic write cleaned up


def test_corrupt_file_backed_up(tmp_path):
    path = tmp_path / "lesysbot.lock.json"
    path.write_text("{not json")
    state = JsonState(path, "tools")
    assert state.load() == {}
    assert path.with_name("lesysbot.lock.json.bad").exists()
    assert not path.exists()


def test_wrong_shape_treated_as_corrupt(tmp_path):
    path = tmp_path / "lesysbot.lock.json"
    path.write_text(json.dumps({"tools": ["a", "list"]}))
    assert JsonState(path, "tools").load() == {}
    assert path.with_name("lesysbot.lock.json.bad").exists()


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "deep" / "nested" / "lesysbot.lock.json"
    JsonState(path, "tools").save({"a": {}})
    assert json.loads(path.read_text())["tools"] == {"a": {}}
