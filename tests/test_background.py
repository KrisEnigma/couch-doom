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


def test_linux_background_priority_lowers_this_thread(monkeypatch):
    calls = []

    class Call:
        def __init__(self, result):
            self.result = result
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            calls.append(args)
            return self.result

    class Libc:
        gettid = Call(42)
        setpriority = Call(0)

    monkeypatch.setattr(background.sys, "platform", "linux")
    monkeypatch.setattr(background.ctypes, "CDLL", lambda *_a, **_k: Libc)

    assert background.lower_current_thread_priority() is True
    assert calls == [(), (0, 42, 5)]


def test_linux_without_gettid_stays_at_normal_priority(monkeypatch):
    class Libc:
        setpriority = object()

    monkeypatch.setattr(background.sys, "platform", "linux")
    monkeypatch.setattr(background.ctypes, "CDLL", lambda *_a, **_k: Libc)

    assert background.lower_current_thread_priority() is False


def test_background_priority_is_a_noop_off_windows_and_linux(monkeypatch):
    monkeypatch.setattr(background.sys, "platform", "darwin")

    assert background.lower_current_thread_priority() is False
