import json

from couch_doom.asset_cache import _endoom_from_dict, _endoom_to_dict
from couch_doom.endoom import Endoom, SIZE


def test_endoom_cache_round_trip_preserves_raw_bytes():
    screen = Endoom("hell-revealed-2.wad", bytes(range(256)) * (SIZE // 256) + bytes(range(SIZE % 256)))

    encoded = json.loads(json.dumps(_endoom_to_dict(screen)))
    restored = _endoom_from_dict(encoded)

    assert restored == screen
