import os
import re
import socket
import subprocess
from datetime import datetime


POWER_SUPPLY_SYS = "/sys/class/power_supply"
PISUGAR_SOCKET = "/tmp/pisugar-server.sock"
_TRAILING_PUNCT = re.compile(r"[.?!\s]+$")
_TIME_LOCATION_QUALIFIER = re.compile(r"\b(?:in|for|at)\s+[a-z0-9]", re.IGNORECASE)
_VISUAL_REQUEST_RE = re.compile(
    r"\b(?:picture|photo|image|map|diagram|chart|visual|poster|banner|flyer|sign|graphic|card)\b",
    re.IGNORECASE,
)


def maybe_answer_local_status(user_text: str) -> str | None:
    text = (user_text or "").strip()
    if not text:
        return None
    lower = text.lower()

    if _looks_like_visual_request(lower):
        return None

    if _is_time_question(lower):
        now = datetime.now()
        return f"It's {now.strftime('%-I:%M %p')}."

    if _is_device_identity_question(lower):
        model = _read_device_model()
        if "are you on the pi" in lower or "are you on a raspberry pi" in lower:
            if model:
                return f"Yes, I'm running on {model}."
            return "Yes, I'm running on a Raspberry Pi."
        if model:
            return f"I'm running on {model}."
        return "I'm running on a Raspberry Pi."

    if _is_online_question(lower):
        online = _internet_available()
        connected, ssid = _read_wifi_status()
        if online:
            if connected and ssid:
                return f"Yes, I'm online and connected to Wi-Fi on {ssid}."
            return "Yes, I'm online right now."
        if connected and ssid:
            return f"I'm connected to Wi-Fi on {ssid}, but I don't appear to be online."
        return "I'm not online right now."

    if _is_wifi_question(lower):
        connected, ssid = _read_wifi_status()
        if connected:
            if ssid:
                return f"I'm connected to Wi-Fi on {ssid}."
            return "I'm connected to Wi-Fi right now."
        return "I'm not connected to Wi-Fi right now."

    if _is_battery_question(lower):
        pct, status = _read_battery()
        if pct is None and status is None:
            return "I can't read my battery right now."

        if _is_should_plug_in_question(lower):
            if status == "Charging":
                if pct is not None:
                    return f"I'm already plugged in and charging. My battery is {pct} percent."
                return "I'm already plugged in and charging."
            if pct is None:
                return "I can't tell right now whether I need charging."
            if pct <= 20:
                return f"Yes, please plug me in soon. My battery is {pct} percent."
            if pct <= 50:
                return f"Not urgently, but charging me soon would help. My battery is {pct} percent."
            return f"Not right now. My battery is {pct} percent."

        if _is_charging_question(lower):
            if status == "Charging":
                if pct is not None:
                    return f"I'm charging, and my battery is {pct} percent."
                return "I'm charging right now."
            if status == "Discharging":
                if pct is not None:
                    return f"I'm not charging, and my battery is {pct} percent."
                return "I'm not charging right now."
            return "I can't tell whether I'm charging right now."

        if pct is not None and status == "Charging":
            return f"My battery is {pct} percent, and I'm charging."
        if pct is not None and status == "Discharging":
            return f"My battery is {pct} percent, and I'm not charging."
        if pct is not None:
            return f"My battery is {pct} percent."
        if status == "Charging":
            return "I'm charging right now."
        if status == "Discharging":
            return "I'm not charging right now."
        return "I can't read my battery right now."

    return None


def _is_time_question(lower: str) -> bool:
    asks_for_time = any(
        phrase in lower
        for phrase in (
            "what time is it",
            "what's the time",
            "what is the time",
            "current time",
            "tell me the time",
        )
    )
    if not asks_for_time:
        return False
    if _TIME_LOCATION_QUALIFIER.search(lower):
        return False
    if any(
        phrase in lower
        for phrase in (
            "time zone",
            "timezone",
            "there",
            "over there",
        )
    ):
        return False
    return True


def _looks_like_visual_request(lower: str) -> bool:
    if "help me visualize" in lower:
        return True
    if not _VISUAL_REQUEST_RE.search(lower):
        return False
    return any(
        phrase in lower
        for phrase in (
            "show me",
            "give me",
            "display",
            "pull up",
            "generate",
            "create",
            "make",
            "draw",
            "paint",
        )
    )


def _is_device_identity_question(lower: str) -> bool:
    return any(
        phrase in lower
        for phrase in (
            "what device are you running on",
            "what are you running on",
            "are you on the pi",
            "are you on a raspberry pi",
            "are you running on the pi",
            "what hardware are you on",
        )
    )


def _is_online_question(lower: str) -> bool:
    return any(
        phrase in lower
        for phrase in (
            "are you online",
            "are you on the internet",
            "are you connected to the internet",
            "do you have internet",
        )
    )


def _is_wifi_question(lower: str) -> bool:
    return any(
        phrase in lower
        for phrase in (
            "are you connected to wi-fi",
            "are you connected to wifi",
            "are you connected to the hotspot",
            "what wi-fi are you on",
            "what wifi are you on",
            "what network are you on",
            "what network are you connected to",
            "what hotspot are you on",
            "what hotspot are you connected to",
            "what ssid are you on",
            "what are you connected to",
        )
    )


def _is_battery_question(lower: str) -> bool:
    if any(
        phrase in lower
        for phrase in (
            "battery percentage",
            "battery level",
            "current battery",
            "how much battery do you have",
            "how much charge do you have",
            "how much battery",
            "are you low on battery",
            "are you low",
            "low battery",
            "are you charging",
            "charger",
            "plugged in",
            "plug you in",
            "charge you",
            "power cable",
        )
    ):
        return True
    return (
        "battery" in lower and any(token in lower for token in ("your", "you", "current", "percentage", "level"))
    )


def _is_charging_question(lower: str) -> bool:
    return any(
        phrase in lower
        for phrase in (
            "are you charging",
            "are you plugged in",
            "plugged in",
            "on the charger",
            "charging right now",
            "currently charging",
        )
    )


def _is_should_plug_in_question(lower: str) -> bool:
    return any(
        phrase in lower
        for phrase in (
            "do i plug you in",
            "should i plug you in",
            "do i need to plug you in",
            "should i charge you",
            "do you need charging",
            "do you need to be plugged in",
            "do you need to be charged",
        )
    )


def _read_device_model() -> str | None:
    try:
        with open("/proc/device-tree/model", "rb") as f:
            raw = f.read().replace(b"\x00", b"").decode("utf-8", errors="ignore").strip()
    except OSError:
        return None
    return raw or None


def _internet_available() -> bool:
    for host in (("1.1.1.1", 53), ("8.8.8.8", 53)):
        try:
            with socket.create_connection(host, timeout=1):
                return True
        except OSError:
            continue
    return False


def _read_wifi_status() -> tuple[bool, str | None]:
    connected = _wifi_connected()
    if not connected:
        return (False, None)
    return (True, _read_wifi_ssid())


def _wifi_connected() -> bool:
    try:
        with open("/sys/class/net/wlan0/operstate") as f:
            return f.read().strip() == "up"
    except OSError:
        return False


def _read_wifi_ssid() -> str | None:
    try:
        result = subprocess.run(
            ["iwgetid", "-r"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    ssid = _TRAILING_PUNCT.sub("", result.stdout.strip())
    return ssid or None


def _read_pisugar_battery() -> tuple[int | None, str | None]:
    if not os.path.exists(PISUGAR_SOCKET):
        return (None, None)
    try:
        data = _send_pisugar_command("get battery")
        m = re.search(r"(\d+)", data or "")
        if not m:
            return (None, None)
        pct = max(0, min(100, int(m.group(1))))
        status = None
        charging = (_send_pisugar_command("get battery_charging") or "").lower()
        if "true" in charging:
            status = "Charging"
        elif "false" in charging:
            status = "Discharging"
        return (pct, status)
    except (OSError, ValueError, socket.error):
        return (None, None)


def _send_pisugar_command(command: str) -> str | None:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(1.0)
        sock.connect(PISUGAR_SOCKET)
        sock.sendall(f"{command}\n".encode("utf-8"))
        return sock.recv(64).decode("utf-8", errors="ignore").strip()
    finally:
        sock.close()


def _read_battery() -> tuple[int | None, str | None]:
    result = _read_pisugar_battery()
    if result[0] is not None:
        return result
    if not os.path.isdir(POWER_SUPPLY_SYS):
        return (None, None)

    for name in sorted(os.listdir(POWER_SUPPLY_SYS)):
        base = os.path.join(POWER_SUPPLY_SYS, name)
        if not os.path.isdir(base):
            continue
        if not _is_battery_dir(base, name):
            continue

        pct = _read_battery_percent(base)
        if pct is None:
            continue

        status = None
        status_path = os.path.join(base, "status")
        if os.path.isfile(status_path):
            try:
                with open(status_path) as f:
                    raw = f.read().strip()
                    if raw:
                        status = raw
            except OSError:
                pass
        return (pct, status)

    return (None, None)


def _is_battery_dir(base: str, name: str) -> bool:
    if name.upper().startswith("BAT") or name.lower() == "battery":
        return True
    type_path = os.path.join(base, "type")
    if not os.path.isfile(type_path):
        return False
    try:
        with open(type_path) as f:
            return f.read().strip().upper() == "BATTERY"
    except OSError:
        return False


def _read_battery_percent(base: str) -> int | None:
    cap_path = os.path.join(base, "capacity")
    energy_now_path = os.path.join(base, "energy_now")
    energy_full_path = os.path.join(base, "energy_full")

    if os.path.isfile(cap_path):
        try:
            with open(cap_path) as f:
                return max(0, min(100, int(f.read().strip())))
        except (ValueError, OSError):
            pass

    if os.path.isfile(energy_now_path) and os.path.isfile(energy_full_path):
        try:
            with open(energy_now_path) as f:
                now = int(f.read().strip())
            with open(energy_full_path) as f:
                full = int(f.read().strip())
            if full > 0:
                return max(0, min(100, int(100 * now / full)))
        except (ValueError, OSError):
            pass

    return None
