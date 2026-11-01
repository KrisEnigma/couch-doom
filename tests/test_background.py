from couch_doom import background


def test_windows_background_priority_yields_to_foreground_threads(monkeypatch):
    calls = []

    class WinApiFunction:
        def __init__(self, result):
            self.result = result
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            calls.append(args)
            return self.result

    class Kernel32:
        GetCurrentThread = WinApiFunction(1234)
        SetThreadPriority = WinApiFunction(1)

    monkeypatch.setattr(background.sys, "platform", "win32")
    monkeypatch.setattr(background.ctypes, "WinDLL", lambda *_args, **_kwargs: Kernel32, raising=False)

    assert background.lower_current_thread_priority()
    assert calls == [(), (1234, -1)]


def test_background_priority_is_a_noop_off_windows(monkeypatch):
    monkeypatch.setattr(background.sys, "platform", "linux")

    assert background.lower_current_thread_priority() is False
