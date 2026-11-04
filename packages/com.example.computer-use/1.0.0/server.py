"""Computer Use: macOS screen, pointer and keyboard tools for BSH.

A single Python process that speaks the BSH stdio protocol. Every tool is a
function here; the manifest in extension.toml must declare each one and name
this file. Targeting is per process and per window, not per screen: capture
and input name the app they act on, so an app that is not frontmost can still
be screenshotted, raised and driven.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes  # noqa: F401  (kept for POINT on other platforms)
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if sys.platform == "darwin":
    try:
        import Quartz  # optional; the ctypes bindings below do not need it
    except ModuleNotFoundError:
        Quartz = None

# The BSH host speaks one request per line on stdin, one response per line on
# stdout. Anything else written to stdout corrupts the stream, so diagnostics
# go to stderr only.

POINT = None
CG = None
CF = None
AS = None
LIBC = None

# CoreGraphics window-list option bits: on-screen only, desktop excluded.
WINDOW_ON_SCREEN = 1
WINDOW_EXCLUDE_DESKTOP = 2
CF_NUMBER_SINT64 = 4
CF_UTF8 = 0x08000100


def load():
    """Bind the frameworks the tools need. Called once at startup."""
    global POINT, CG, CF, AS, LIBC
    if sys.platform != "darwin":
        return False
    CG = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    CF = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    AS = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    LIBC = ctypes.CDLL("/usr/lib/libSystem.B.dylib")

    class CGPoint(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

    POINT = CGPoint

    CG.CGEventSourceStateID.restype = ctypes.c_uint32
    CG.CGEventSourceCombinedSessionState.argtypes = [ctypes.c_uint32]
    CG.CGEventSourceCombinedSessionState.restype = ctypes.c_uint32
    CG.CGWarpMouseCursorPosition.argtypes = [POINT]
    CG.CGWarpMouseCursorPosition.restype = ctypes.c_int32
    CG.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, POINT, ctypes.c_uint32]
    CG.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    CG.CGEventCreateScrollWheelEvent2.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32,
    ]
    CG.CGEventCreateScrollWheelEvent2.restype = ctypes.c_void_p
    CG.CGEventSetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_longlong]
    CG.CGEventSetIntegerValueField.restype = None
    CG.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    CG.CGEventPost.restype = None
    CG.CGEventGetIntegerValueField.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    CG.CGEventGetIntegerValueField.restype = ctypes.c_longlong
    CG.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
    CG.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
    CG.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    CG.CGEventSetFlags.restype = None
    CG.CGEventKeyboardSetUnicodeString.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_char_p,
    ]
    CG.CGEventKeyboardSetUnicodeString.restype = None
    CG.CGDisplayPixelsWide.argtypes = [ctypes.c_uint32]
    CG.CGDisplayPixelsWide.restype = ctypes.c_uint32
    CG.CGDisplayPixelsHigh.argtypes = [ctypes.c_uint32]
    CG.CGDisplayPixelsHigh.restype = ctypes.c_uint32
    CG.CGMainDisplayID.restype = ctypes.c_uint32
    CG.CGDisplayScreenSize.argtypes = [ctypes.c_uint32]
    CG.CGDisplayScreenSize.restype = CGSize
    CG.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    CG.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p

    CF.CFRelease.argtypes = [ctypes.c_void_p]
    CF.CFRelease.restype = None
    CF.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    CF.CFStringCreateWithCString.restype = ctypes.c_void_p
    CF.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
    CF.CFStringGetCString.restype = ctypes.c_bool
    CF.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    CF.CFArrayGetCount.restype = ctypes.c_long
    CF.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
    CF.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
    CF.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    CF.CFDictionaryGetValue.restype = ctypes.c_void_p
    CF.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
    CF.CFNumberGetValue.restype = ctypes.c_bool
    AS.AXUIElementCreateApplication.argtypes = [ctypes.c_int32]
    AS.AXUIElementCreateApplication.restype = ctypes.c_void_p
    AS.AXUIElementCopyAttributeValue.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ]
    AS.AXUIElementCopyAttributeValue.restype = ctypes.c_int32
    AS.AXUIElementSetAttributeValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    AS.AXUIElementSetAttributeValue.restype = ctypes.c_int32
    AS.AXUIElementPerformAction.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    AS.AXUIElementPerformAction.restype = ctypes.c_int32
    LIBC.kill.argtypes = [ctypes.c_int32, ctypes.c_int32]
    LIBC.kill.restype = ctypes.c_int32
    return True


EVENTS: list[dict] = []
_CF_STRINGS: dict[bytes, int] = {}


def cfstring(raw: bytes):
    """A cached CFString for a constant key such as b'kCGWindowNumber'."""
    ref = _CF_STRINGS.get(raw)
    if ref is None:
        ref = CF.CFStringCreateWithCString(None, raw, CF_UTF8)
        _CF_STRINGS[raw] = ref
    return ref


def cf_true():
    return ctypes.c_void_p.in_dll(CF, "kCFBooleanTrue")


def _cf_number(ref):
    if not ref:
        return None
    value = ctypes.c_longlong(0)
    if CF.CFNumberGetValue(ref, CF_NUMBER_SINT64, ctypes.byref(value)):
        return int(value.value)
    return None


def _cf_text(ref):
    if not ref:
        return ""
    buffer = ctypes.create_string_buffer(512)
    if CF.CFStringGetCString(ref, buffer, 512, CF_UTF8):
        return buffer.value.decode("utf-8", "replace")
    return ""


def _cf_rect(ref):
    if not ref:
        return None
    x = _cf_number(CF.CFDictionaryGetValue(ref, cfstring(b"X")))
    y = _cf_number(CF.CFDictionaryGetValue(ref, cfstring(b"Y")))
    width = _cf_number(CF.CFDictionaryGetValue(ref, cfstring(b"Width")))
    height = _cf_number(CF.CFDictionaryGetValue(ref, cfstring(b"Height")))
    if None in (x, y, width, height):
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def on_screen_windows():
    """Every on-screen window, front to back, as plain dicts."""
    array = CG.CGWindowListCopyWindowInfo(WINDOW_ON_SCREEN | WINDOW_EXCLUDE_DESKTOP, 0)
    if not array:
        return []
    rows = []
    for index in range(CF.CFArrayGetCount(array)):
        window = CF.CFArrayGetValueAtIndex(array, index)
        rows.append({
            "window_id": _cf_number(CF.CFDictionaryGetValue(window, cfstring(b"kCGWindowNumber"))),
            "pid": _cf_number(CF.CFDictionaryGetValue(window, cfstring(b"kCGWindowOwnerPID"))),
            "owner": _cf_text(CF.CFDictionaryGetValue(window, cfstring(b"kCGWindowOwnerName"))),
            "title": _cf_text(CF.CFDictionaryGetValue(window, cfstring(b"kCGWindowName"))),
            "layer": _cf_number(CF.CFDictionaryGetValue(window, cfstring(b"kCGWindowLayer"))) or 0,
            "bounds": _cf_rect(CF.CFDictionaryGetValue(window, cfstring(b"kCGWindowBounds"))),
        })
    CF.CFRelease(array)
    return rows


def front_window_of(pid: int):
    """The topmost normal-layer window owned by one process, or None."""
    for row in on_screen_windows():
        if row["pid"] == int(pid) and row["layer"] == 0 and row["window_id"]:
            return row["window_id"]
    return None


def process_alive(pid: int):
    return LIBC.kill(int(pid), 0) == 0


def list_windows(pid=None, limit=40, include_overlays=False):
    """Group on-screen windows per process so a hidden app stays targetable."""
    need_macos()
    limit = max(1, min(100, int(limit)))
    rows = on_screen_windows()
    if pid is not None:
        rows = [row for row in rows if row["pid"] == int(pid)]
    if not include_overlays:
        rows = [row for row in rows if row["layer"] == 0]
    rows = [row for row in rows if row["window_id"] and row["bounds"]]
    truncated = len(rows) > limit
    rows = rows[:limit]
    apps: dict[int, dict] = {}
    for row in rows:  # CGWindowList order is front to back, so first hit is frontmost
        entry = apps.setdefault(row["pid"], {
            "pid": row["pid"],
            "name": row["owner"],
            "windows": 0,
            "front_window_id": row["window_id"],
            "bounds": dict(row["bounds"]),
        })
        entry["windows"] += 1
        bounds = entry["bounds"]
        other = row["bounds"]
        bounds["x"] = min(bounds["x"], other["x"])
        bounds["y"] = min(bounds["y"], other["y"])
        bounds["width"] = max(bounds["x"] + bounds["width"], other["x"] + other["width"]) - bounds["x"]
        bounds["height"] = max(bounds["y"] + bounds["height"], other["y"] + other["height"]) - bounds["y"]
    return {
        "ok": True,
        "count": len(rows),
        "truncated": truncated,
        "windows": rows,
        "apps": list(apps.values()),
        "note": "Bounds are display points usable with the mouse tools; front_window_id is the app's topmost window.",
    }


def raise_process(pid):
    """Bring one process and its frontmost window to the front via Accessibility."""
    need_macos()
    pid = int(pid)
    if not process_alive(pid):
        raise RuntimeError(f"no process with pid {pid} is running; call list_windows for live targets")
    app = AS.AXUIElementCreateApplication(pid)
    if not app:
        raise RuntimeError(f"pid {pid} has no accessibility element; grant Accessibility to BSH in System Settings")
    activated = AS.AXUIElementSetAttributeValue(app, cfstring(b"AXFrontmost"), cf_true()) == 0
    if not activated:
        activated = AS.AXUIElementPerformAction(app, cfstring(b"AXRaise")) == 0
    windows = ctypes.c_void_p(0)
    if AS.AXUIElementCopyAttributeValue(app, cfstring(b"AXWindows"), ctypes.byref(windows)) == 0 and windows:
        if CF.CFArrayGetCount(windows) > 0:
            AS.AXUIElementPerformAction(CF.CFArrayGetValueAtIndex(windows, 0), cfstring(b"AXRaise"))
        CF.CFRelease(windows)
    CF.CFRelease(app)
    if not activated:
        raise RuntimeError(f"could not bring pid {pid} to the front; grant Accessibility to BSH in System Settings")
    time.sleep(0.1)
    return {"ok": True, "pid": pid, "raised": True}


def need_macos():
    if sys.platform != "darwin":
        raise RuntimeError("computer use tools require macOS")


MOUSE_DOWN = {"left": 1, "right": 3, "middle": 2}
MOUSE_UP = {"left": 2, "right": 4, "middle": 3}
MOUSE_DRAG = {"left": 6, "right": 7, "middle": 8}
MOUSE_MOVE = 5
HID = 0
MOVE = 0
LEFT = 0
RIGHT = 1
DOWN = 10
UP = 11
DRAG = 6
SCROLL = 22
KEY_DOWN = 10
KEY_UP = 11
FLAGS = 2
SHIFT = 0x00020000
CONTROL = 0x00040000
ALTERNATE = 0x00080000
COMMAND = 0x00100000
FUNCTION = 0x00800000

SPECIAL_KEYS = {
    "return": 0x24, "enter": 0x24, "tab": 0x30, "space": 0x31,
    "delete": 0x33, "backspace": 0x33, "escape": 0x35, "esc": 0x35,
    "forwarddelete": 0x75, "home": 0x73, "end": 0x77,
    "pageup": 0x74, "pagedown": 0x79, "up": 0x7E, "down": 0x7D,
    "left": 0x7B, "right": 0x7C, "f1": 0x7A, "f2": 0x78, "f3": 0x63,
    "f4": 0x76, "f5": 0x60, "f6": 0x61, "f7": 0x62, "f8": 0x64,
    "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F,
}
MODIFIER_CODES = {"shift": 56, "ctrl": 59, "alt": 58, "cmd": 55, "fn": 63}
MODIFIER_FLAGS = {
    "shift": SHIFT, "ctrl": CONTROL, "alt": ALTERNATE,
    "cmd": COMMAND, "fn": FUNCTION,
}


def screen_size():
    need_macos()
    display = CG.CGMainDisplayID()
    width = CG.CGDisplayPixelsWide(display)
    height = CG.CGDisplayPixelsHigh(display)
    mm = CG.CGDisplayScreenSize(display)
    return {
        "width": int(width),
        "height": int(height),
        "pixel_width": int(width),
        "pixel_height": int(height),
        "mm_width": round(mm.width, 1),
        "mm_height": round(mm.height, 1),
        "scale": 1,
        "note": "Points, the same coordinate space the mouse tools take.",
    }


def main_display():
    need_macos()
    display = CG.CGMainDisplayID()
    return {
        "id": int(display),
        "width": int(CG.CGDisplayPixelsWide(display)),
        "height": int(CG.CGDisplayPixelsHigh(display)),
        "pixel_width": int(CG.CGDisplayPixelsWide(display)),
        "pixel_height": int(CG.CGDisplayPixelsHigh(display)),
    }


def cursor_position():
    need_macos()
    event = CG.CGEventCreate(None)
    x = CG.CGEventGetIntegerValueField(event, 4)  # kCGMouseEventDeltaX is not this; field 4 is location
    y = CG.CGEventGetIntegerValueField(event, 5)
    CG.CFRelease(event)
    return {"x": float(x), "y": float(y)}


def mouse_event(kind, x, y, button=LEFT):
    event = CG.CGEventCreateMouseEvent(None, kind, POINT(float(x), float(y)), ctypes.c_uint32(button))
    CG.CGEventPost(HID, event)
    CF.CFRelease(event)


def mouse_move(x, y, target_pid=None):
    need_macos()
    if target_pid is not None:
        raise_process(target_pid)
    CG.CGWarpMouseCursorPosition(POINT(float(x), float(y)))
    mouse_event(MOVE, x, y)
    return {"ok": True, "x": x, "y": y, "target_pid": target_pid}


def mouse_click(x, y, button="left", clicks=1, target_pid=None):
    need_macos()
    number = {"left": LEFT, "right": RIGHT, "middle": 2}.get(str(button), LEFT)
    count = max(1, min(3, int(clicks)))
    if target_pid is not None:
        raise_process(target_pid)
    for index in range(count):
        kind = MOUSE_DOWN.get(str(button), 1)
        event = CG.CGEventCreateMouseEvent(None, kind, POINT(float(x), float(y)), ctypes.c_uint32(number))
        CG.CGEventSetIntegerValueField(event, 1, index + 1)
        CG.CGEventPost(HID, event)
        CF.CFRelease(event)
        up = MOUSE_UP.get(str(button), 2)
        event = CG.CGEventCreateMouseEvent(None, up, POINT(float(x), float(y)), ctypes.c_uint32(number))
        CG.CGEventSetIntegerValueField(event, 1, index + 1)
        CG.CGEventPost(HID, event)
        CF.CFRelease(event)
        if index < count - 1:
            time.sleep(0.08)
    return {"ok": True, "x": x, "y": y, "button": button, "clicks": count, "target_pid": target_pid}


def mouse_drag(from_x, from_y, to_x, to_y, button="left", duration_ms=300, target_pid=None):
    need_macos()
    number = RIGHT if str(button) == "right" else LEFT
    duration = max(0.05, min(2.0, float(duration_ms) / 1000.0))
    if target_pid is not None:
        raise_process(target_pid)
    steps = max(4, int(duration / 0.01))
    down = MOUSE_DOWN.get(str(button), 1)
    drag = MOUSE_DRAG.get(str(button), 6)
    up = MOUSE_UP.get(str(button), 2)
    event = CG.CGEventCreateMouseEvent(None, down, POINT(float(from_x), float(from_y)), ctypes.c_uint32(number))
    CG.CGEventPost(HID, event)
    CF.CFRelease(event)
    for step in range(1, steps + 1):
        fraction = step / steps
        x = from_x + (to_x - from_x) * fraction
        y = from_y + (to_y - from_y) * fraction
        event = CG.CGEventCreateMouseEvent(None, drag, POINT(float(x), float(y)), ctypes.c_uint32(number))
        CG.CGEventPost(HID, event)
        CF.CFRelease(event)
        time.sleep(duration / steps)
    event = CG.CGEventCreateMouseEvent(None, up, POINT(float(to_x), float(to_y)), ctypes.c_uint32(number))
    CG.CGEventPost(HID, event)
    CF.CFRelease(event)
    return {"ok": True, "from": [from_x, from_y], "to": [to_x, to_y], "target_pid": target_pid}


def scroll(delta_y, delta_x=0, x=None, y=None, target_pid=None):
    need_macos()
    if target_pid is not None:
        raise_process(target_pid)
    if x is not None and y is not None:
        CG.CGWarpMouseCursorPosition(POINT(float(x), float(y)))
        mouse_event(MOVE, x, y)
    event = CG.CGEventCreateScrollWheelEvent2(None, HID, 2, int(delta_y), int(delta_x))
    CG.CGEventPost(HID, event)
    CF.CFRelease(event)
    return {"ok": True, "delta_x": int(delta_x), "delta_y": int(delta_y), "target_pid": target_pid}


def type_text(text, target_pid=None):
    need_macos()
    if target_pid is not None:
        raise_process(target_pid)
        time.sleep(0.15)  # let the newly focused app settle before keystrokes
    payload = str(text).encode("utf-8")
    for char in str(text):
        encoded = char.encode("utf-8")
        down = CG.CGEventCreateKeyboardEvent(None, 0, True)
        CG.CGEventKeyboardSetUnicodeString(down, len(encoded), encoded)
        CG.CGEventPost(HID, down)
        CF.CFRelease(down)
        up = CG.CGEventCreateKeyboardEvent(None, 0, False)
        CG.CGEventKeyboardSetUnicodeString(up, len(encoded), encoded)
        CG.CGEventPost(HID, up)
        CF.CFRelease(up)
    return {"ok": True, "characters": len(str(text)), "target_pid": target_pid}


def key_press(key, modifiers=None, target_pid=None):
    need_macos()
    if target_pid is not None:
        raise_process(target_pid)
        time.sleep(0.15)  # let the newly focused app settle before keystrokes
    mods = [str(item).lower() for item in (modifiers or [])]
    unknown = [item for item in mods if item not in MODIFIER_CODES]
    if unknown:
        raise RuntimeError(f"unknown modifiers: {', '.join(unknown)}")
    parts = [piece.strip().lower() for piece in str(key).split("+") if piece.strip()]
    chord = []
    for piece in parts:
        if piece in MODIFIER_CODES:
            mods.append(piece)
        else:
            chord.append(piece)
    if len(chord) != 1:
        raise RuntimeError(f"key must name exactly one non-modifier key, got: {key}")
    key_name = chord[0]
    flags = 0
    for item in mods:
        flags |= MODIFIER_FLAGS[item]
    code = SPECIAL_KEYS.get(key_name)
    if code is None:
        if len(key_name) != 1:
            raise RuntimeError(f"unknown key: {key_name}")
        code = ord(key_name.upper())
    event = CG.CGEventCreateKeyboardEvent(None, code, True)
    if flags:
        CG.CGEventSetFlags(event, flags)
    CG.CGEventPost(HID, event)
    CF.CFRelease(event)
    up = CG.CGEventCreateKeyboardEvent(None, code, False)
    if flags:
        CG.CGEventSetFlags(up, flags)
    CG.CGEventPost(HID, up)
    CF.CFRelease(up)
    return {"ok": True, "key": key_name, "modifiers": sorted(set(mods)), "target_pid": target_pid}


def screenshot(path: str = "", pid=None, window=None):
    need_macos()
    if not path:
        path = str(Path(tempfile.gettempdir()) / f"bsh-computer-{int(time.time() * 1000)}.png")
    path = os.path.abspath(os.path.expanduser(path))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    command = ["/usr/sbin/screencapture", "-x", "-t", "png"]
    if window is not None:
        command += ["-o", "-l", str(int(window))]
    elif pid is not None:
        pid = int(pid)
        if not process_alive(pid):
            raise RuntimeError(f"no process with pid {pid} is running; call list_windows for live targets")
        target = front_window_of(pid)
        if target is None:
            raise RuntimeError(
                f"process {pid} has no on-screen window to capture; call list_windows "
                "(a minimized window cannot be captured)"
            )
        command += ["-o", "-l", str(target)]
    command.append(path)
    proc = subprocess.run(command, capture_output=True, text=True, timeout=15)
    if proc.returncode != 0 or not os.path.exists(path):
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"screencapture failed: {detail or proc.returncode}")
    return {
        "ok": True,
        "path": path,
        "bytes": os.path.getsize(path),
        "target": {"pid": pid, "window": window} if (pid is not None or window is not None) else "main display",
        "note": "Screenshot pixels are not mouse points; use screen_size or divide by the Retina scale.",
    }


def dispatch(name, args):
    if name == "screen_size":
        return screen_size()
    if name == "list_windows":
        return list_windows(args.get("pid"), args.get("limit", 40), args.get("include_overlays", False))
    if name == "screenshot":
        return screenshot(str(args.get("path", "")), args.get("pid"), args.get("window"))
    if name == "cursor_position":
        return cursor_position()
    if name == "mouse_move":
        return mouse_move(args["x"], args["y"], args.get("target_pid"))
    if name == "mouse_click":
        return mouse_click(args["x"], args["y"], args.get("button", "left"), args.get("clicks", 1), args.get("target_pid"))
    if name == "mouse_drag":
        return mouse_drag(
            args["from_x"], args["from_y"], args["to_x"], args["to_y"],
            args.get("button", "left"), args.get("duration_ms", 300), args.get("target_pid"),
        )
    if name == "scroll":
        return scroll(args["delta_y"], args.get("delta_x", 0), args.get("x"), args.get("y"), args.get("target_pid"))
    if name == "type_text":
        return type_text(args["text"], args.get("target_pid"))
    if name == "key_press":
        return key_press(args["key"], args.get("modifiers"), args.get("target_pid"))
    raise RuntimeError(f"unknown tool: {name}")


def panel_document():
    screen = main_display()
    cursor = cursor_position()
    last = EVENTS[-1]["topic"] if EVENTS else "none"
    return {
        "schema_version": "1.0",
        "revision": 3,
        "root": {
            "type": "column",
            "children": [
                {"type": "heading", "text": "Computer Use", "level": 2},
                {"type": "text", "text": f"Display: {screen['width']} x {screen['height']} points ({screen['pixel_width']} x {screen['pixel_height']} px)"},
                {"type": "text", "text": f"Pointer: {cursor['x']:.0f}, {cursor['y']:.0f}"},
                {"type": "text", "text": f"Events: {len(EVENTS)} (last: {last})"},
                {"type": "text", "text": "Per-app targeting: list_windows, then screenshot(pid=...) or target_pid=... on input tools."},
                {"type": "button", "label": "List Windows", "action": "list_windows"},
                {"type": "button", "label": "Screenshot", "action": "screenshot", "style": "primary"},
                {"type": "button", "label": "Refresh", "action": "refresh"},
            ],
        },
    }


def main():
    load()
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            request = json.loads(raw)
        except json.JSONDecodeError as error:
            print(json.dumps({"id": None, "error": f"bad request: {error}"}), flush=True)
            continue
        request_id = request.get("id")
        method = request.get("method", "")
        try:
            if method == "initialize":
                result = {
                    "server": "com.example.computer-use",
                    "tools": TOOLS,
                }
            elif method == "tool":
                name = request.get("name", "")
                args = request.get("args") or {}
                EVENTS.append({"topic": name, "at": time.time()})
                del EVENTS[:-200]
                result = dispatch(name, args)
            elif method == "panel":
                result = panel_document()
            elif method == "panel_action":
                action = request.get("action", "")
                if action == "screenshot":
                    result = screenshot()
                elif action == "list_windows":
                    result = list_windows()
                else:
                    result = {
                        "ok": True,
                        "revision": int(time.time()),
                        "root": panel_document()["root"],
                    }
            else:
                raise RuntimeError(f"unknown method: {method}")
            print(json.dumps({"id": request_id, "result": result}, default=str), flush=True)
        except Exception as error:  # noqa: BLE001 - one bad request must not kill the server
            print(json.dumps({"id": request_id, "error": str(error)}), flush=True)


if __name__ == "__main__":
    main()
