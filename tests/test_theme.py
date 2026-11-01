import colorsys
from collections import OrderedDict

import pygame

from couch_doom.theme import HOUSE, from_art
from couch_doom.ui import THEME_CACHE_SIZE, _theme_cache


def _solid_hue(hue: float) -> pygame.Surface:
    rgb = tuple(round(channel * 255) for channel in colorsys.hsv_to_rgb(hue, 1, 1))
    surface = pygame.Surface((48, 36))
    surface.fill(rgb)
    return surface


def test_five_degree_neighboring_art_hues_get_distinct_themes():
    # These hues share a 10-degree bucket, but lie on opposite sides of a 5-degree boundary.
    first = from_art(_solid_hue(180 / 360))
    second = from_art(_solid_hue(186 / 360))

    assert first.key != second.key
    assert first.label != second.label


def test_themes_keep_the_art_hue_within_a_detection_bucket():
    first = from_art(_solid_hue(181 / 360))
    second = from_art(_solid_hue(182 / 360))

    assert first.key != second.key
    assert first.label != second.label


def test_hues_outside_the_curated_warm_range_use_the_art_theme():
    theme = from_art(_solid_hue(20 / 360))

    assert theme != HOUSE


def test_warm_red_art_keeps_the_house_theme():
    assert from_art(_solid_hue(0)) == HOUSE


def test_theme_render_cache_keeps_recent_entries_and_evicts_the_oldest():
    cache = OrderedDict()
    for key in range(THEME_CACHE_SIZE):
        assert _theme_cache(cache, key, lambda key=key: key) == key

    assert _theme_cache(cache, 0, lambda: None) == 0
    assert _theme_cache(cache, THEME_CACHE_SIZE, lambda: THEME_CACHE_SIZE) == THEME_CACHE_SIZE

    assert len(cache) == THEME_CACHE_SIZE
    assert 0 in cache
    assert 1 not in cache
