from array import array

from couch_doom.music import _pcm_stats


def test_pcm_stats_reports_peak_and_rms_and_yields_between_chunks(monkeypatch):
    yields = []
    monkeypatch.setattr("couch_doom.music.time.sleep", yields.append)
    samples = array("f", [0.5, -0.5, 1.0, -1.0, 0.0])

    assert _pcm_stats(samples, chunk_size=2) == (1.0, (2.5 / 5) ** 0.5)
    assert yields == [0, 0, 0]
