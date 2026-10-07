"""Maps keyboard, SDL game controllers and raw joysticks onto abstract actions."""
from __future__ import annotations

from enum import Enum, auto

import pygame
from pygame._sdl2 import controller


class Action(Enum):
    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()
    CONFIRM = auto()
    BACK = auto()
    SEARCH = auto()
    ALT = auto()  # X: info sheet / backspace in search
    PREV_SECTION = auto()
    NEXT_SECTION = auto()
    PAGE_UP = auto()
    PAGE_DOWN = auto()
    MENU = auto()  # Start: alias for Play
    MUSIC = auto()  # Back/View: title music on/off
    FAVORITE = auto()  # R3: add/remove from Favorites


DIRECTIONS = {Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT, Action.PAGE_UP, Action.PAGE_DOWN}

REPEAT_DELAY = 0.32
REPEAT_INTERVAL = 0.07
STICK_THRESHOLD = 0.55
TRIGGER_THRESHOLD = 0.6
ANALOG_DEADZONE = 0.2
JOY_RIGHT_Y_AXIS = 3  # XInput-style raw layout: LX, LY, RX, RY

_CONTROLLER_BUTTONS = {
    pygame.CONTROLLER_BUTTON_A: Action.CONFIRM,
    pygame.CONTROLLER_BUTTON_B: Action.BACK,
    pygame.CONTROLLER_BUTTON_X: Action.ALT,
    pygame.CONTROLLER_BUTTON_Y: Action.SEARCH,
    pygame.CONTROLLER_BUTTON_BACK: Action.MUSIC,
    pygame.CONTROLLER_BUTTON_START: Action.MENU,
    pygame.CONTROLLER_BUTTON_RIGHTSTICK: Action.FAVORITE,
    pygame.CONTROLLER_BUTTON_LEFTSHOULDER: Action.PREV_SECTION,
    pygame.CONTROLLER_BUTTON_RIGHTSHOULDER: Action.NEXT_SECTION,
    pygame.CONTROLLER_BUTTON_DPAD_UP: Action.UP,
    pygame.CONTROLLER_BUTTON_DPAD_DOWN: Action.DOWN,
    pygame.CONTROLLER_BUTTON_DPAD_LEFT: Action.LEFT,
    pygame.CONTROLLER_BUTTON_DPAD_RIGHT: Action.RIGHT,
}

# XInput-style layout for pads SDL has no mapping for.
_JOY_BUTTONS = {
    0: Action.CONFIRM,
    1: Action.BACK,
    2: Action.ALT,
    3: Action.SEARCH,
    4: Action.PREV_SECTION,
    5: Action.NEXT_SECTION,
    6: Action.MUSIC,
    7: Action.MENU,
    9: Action.FAVORITE,
}

_KEYS = {
    pygame.K_UP: Action.UP,
    pygame.K_DOWN: Action.DOWN,
    pygame.K_LEFT: Action.LEFT,
    pygame.K_RIGHT: Action.RIGHT,
    pygame.K_RETURN: Action.CONFIRM,
    pygame.K_KP_ENTER: Action.CONFIRM,
    pygame.K_ESCAPE: Action.BACK,
    pygame.K_TAB: Action.ALT,
    pygame.K_PAGEUP: Action.PAGE_UP,
    pygame.K_PAGEDOWN: Action.PAGE_DOWN,
    pygame.K_F2: Action.MUSIC,
    pygame.K_F3: Action.FAVORITE,
}


def _family(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ("playstation", "dualshock", "dualsense", "ps3", "ps4", "ps5", "wireless controller")):
        return "playstation"
    if any(k in n for k in ("nintendo", "switch", "pro controller", "joy-con")):
        return "switch"
    return "xbox"


class Input:
    def __init__(self) -> None:
        controller.init()
        pygame.joystick.init()
        self._controllers: dict[int, controller.Controller] = {}
        self._joysticks: dict[int, pygame.joystick.JoystickType] = {}
        self._families: dict[int, str] = {}
        self._last_pad: int | None = None
        # source key -> (action, next_fire_time)
        self._held: dict[tuple, tuple[Action, float]] = {}
        self._right_y: dict[int, float] = {}
        self._left_y: dict[int, float] = {}
        for i in range(pygame.joystick.get_count()):
            self._open(i)

    @property
    def pad_count(self) -> int:
        return len(self._controllers) + len(self._joysticks)

    @property
    def family(self) -> str:
        """Button style of the pad used most recently: "xbox", "playstation" or "switch"."""
        if self._last_pad in self._families:
            return self._families[self._last_pad]
        return next(iter(self._families.values()), "xbox")

    @staticmethod
    def _analog(values: dict[int, float]) -> float:
        v = max(values.values(), key=abs, default=0.0)
        if abs(v) < ANALOG_DEADZONE:
            return 0.0
        return (abs(v) - ANALOG_DEADZONE) / (1 - ANALOG_DEADZONE) * (1 if v > 0 else -1)

    @property
    def right_y(self) -> float:
        """Right stick vertical deflection in -1..1 (down is positive), dead zone removed."""
        return self._analog(self._right_y)

    @property
    def left_y(self) -> float:
        """Left stick vertical deflection, same scale; it also drives UP/DOWN actions for menus."""
        return self._analog(self._left_y)

    def _open(self, device_index: int) -> None:
        try:
            if controller.is_controller(device_index):
                pad = controller.Controller(device_index)
                joy = pad.as_joystick()
                iid = joy.get_instance_id()
                self._controllers.setdefault(iid, pad)
            else:
                joy = pygame.joystick.Joystick(device_index)
                iid = joy.get_instance_id()
                self._joysticks.setdefault(iid, joy)
            self._families.setdefault(iid, _family(joy.get_name()))
        except pygame.error:
            pass

    def reset(self) -> None:
        self._held.clear()
        self._right_y.clear()
        self._left_y.clear()

    def _press(self, source: tuple, action: Action, now: float, out: list[Action]) -> None:
        if action in DIRECTIONS:
            if source in self._held and self._held[source][0] == action:
                return
            self._held[source] = (action, now + REPEAT_DELAY)
        out.append(action)

    def _release(self, source: tuple) -> None:
        self._held.pop(source, None)

    def _axis(self, source: tuple, value: float, neg: Action, pos: Action, now: float, out: list[Action]) -> None:
        if value <= -STICK_THRESHOLD:
            self._press(source, neg, now, out)
        elif value >= STICK_THRESHOLD:
            self._press(source, pos, now, out)
        elif abs(value) < STICK_THRESHOLD * 0.6:
            self._release(source)

    def handle(self, event: pygame.event.Event, now: float) -> list[Action]:
        out: list[Action] = []
        t = event.type

        if t in (pygame.CONTROLLERDEVICEADDED, pygame.JOYDEVICEADDED):
            self._open(event.device_index)
        elif t in (pygame.CONTROLLERDEVICEREMOVED, pygame.JOYDEVICEREMOVED):
            self._controllers.pop(event.instance_id, None)
            self._joysticks.pop(event.instance_id, None)
            self._families.pop(event.instance_id, None)
            self._right_y.pop(event.instance_id, None)
            self._left_y.pop(event.instance_id, None)
            self._held = {k: v for k, v in self._held.items() if k[1] != event.instance_id}

        elif t == pygame.KEYDOWN and event.key in _KEYS:
            self._press(("key", event.key), _KEYS[event.key], now, out)
        elif t == pygame.KEYUP and event.key in _KEYS:
            self._release(("key", event.key))

        elif t == pygame.CONTROLLERBUTTONDOWN and event.button in _CONTROLLER_BUTTONS:
            self._last_pad = event.instance_id
            self._press(("cbtn", event.instance_id, event.button), _CONTROLLER_BUTTONS[event.button], now, out)
        elif t == pygame.CONTROLLERBUTTONUP:
            self._release(("cbtn", event.instance_id, event.button))
        elif t == pygame.CONTROLLERAXISMOTION:
            v = event.value / 32767
            src = ("caxis", event.instance_id, event.axis)
            if event.axis == pygame.CONTROLLER_AXIS_LEFTY:
                self._left_y[event.instance_id] = max(-1.0, min(1.0, v))
                self._axis(src, v, Action.UP, Action.DOWN, now, out)
            elif event.axis == pygame.CONTROLLER_AXIS_LEFTX:
                self._axis(src, v, Action.LEFT, Action.RIGHT, now, out)
            elif event.axis == pygame.CONTROLLER_AXIS_RIGHTY:
                self._right_y[event.instance_id] = max(-1.0, min(1.0, v))
            elif event.axis in (pygame.CONTROLLER_AXIS_TRIGGERLEFT, pygame.CONTROLLER_AXIS_TRIGGERRIGHT):
                page = Action.PAGE_UP if event.axis == pygame.CONTROLLER_AXIS_TRIGGERLEFT else Action.PAGE_DOWN
                if v > TRIGGER_THRESHOLD:
                    self._press(src, page, now, out)
                elif v < TRIGGER_THRESHOLD * 0.5:
                    self._release(src)

        elif event.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP, pygame.JOYHATMOTION, pygame.JOYAXISMOTION):
            if event.instance_id not in self._joysticks:
                return out  # handled through the controller API
            if t == pygame.JOYBUTTONDOWN and event.button in _JOY_BUTTONS:
                self._last_pad = event.instance_id
                self._press(("jbtn", event.instance_id, event.button), _JOY_BUTTONS[event.button], now, out)
            elif t == pygame.JOYBUTTONUP:
                self._release(("jbtn", event.instance_id, event.button))
            elif t == pygame.JOYHATMOTION:
                hx, hy = event.value
                for axis, val, neg, pos in (("x", hx, Action.LEFT, Action.RIGHT), ("y", -hy, Action.UP, Action.DOWN)):
                    src = ("jhat", event.instance_id, event.hat, axis)
                    if val:
                        self._press(src, neg if val < 0 else pos, now, out)
                    else:
                        self._release(src)
            elif t == pygame.JOYAXISMOTION and event.axis in (0, 1):
                neg, pos = (Action.LEFT, Action.RIGHT) if event.axis == 0 else (Action.UP, Action.DOWN)
                if event.axis == 1:
                    self._left_y[event.instance_id] = event.value
                self._axis(("jaxis", event.instance_id, event.axis), event.value, neg, pos, now, out)
            elif t == pygame.JOYAXISMOTION and event.axis == JOY_RIGHT_Y_AXIS:
                self._right_y[event.instance_id] = event.value
        return out

    def update(self, now: float) -> list[Action]:
        out: list[Action] = []
        for src, (action, due) in list(self._held.items()):
            if now >= due:
                out.append(action)
                self._held[src] = (action, now + REPEAT_INTERVAL)
        return out
