import subprocess
import threading
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Union, List

import click
import toml
from evdev import InputDevice, categorize, ecodes
import pyautogui

DEFAULT_CONFIG_PATH = Path("~").expanduser() / ".config" / "macro-kbd" / "config.toml"


class EventResults(Enum):
    COMPLETE = auto()
    PRECURSOR = auto()
    FAILED = auto()
    NO_MACRO = auto()


class InputWithMacros:
    def __init__(
        self,
        event_path: Union[str, Path],
        macro_dict: dict,
        device_name: str,
        config_path: Path,
        debug: bool = False,
    ):
        self.name = device_name
        self.dev = InputDevice(str(event_path))
        self.macros = macro_dict
        self.config_path = config_path
        self.debug = debug

    def reload_macros(self):
        config = toml.load(self.config_path)
        next_config = config.get(self.name)
        if (next_macros := next_config.get("macros", {})) != self.macros:
            self.macros = next_macros


def non_blocking_alert(*args, **kwargs):
    thread_alert = threading.Thread(target=pyautogui.alert, args=args, kwargs=kwargs)
    thread_alert.start()


def get_devices(config_path: Path):
    config = toml.load(config_path)
    devices: List[InputWithMacros] = []
    for name, data in config.items():
        if "input_path" not in data:
            non_blocking_alert(
                f"Device {name} does not have an input path", title="Keyboard Macros."
            )
            continue
        try:
            devices.append(
                InputWithMacros(
                    data["input_path"],
                    data.get("macros", {}),
                    name,
                    config_path,
                    data.get("DEBUG", False),
                )
            )
        except FileNotFoundError:
            non_blocking_alert(
                f"Device {name} could not be found at {data['input_path']}. Other"
                f" devices will not be affected.",
                title="Keyboard Macros",
            )
    return devices


def create_loop(input_device: InputWithMacros, macros_reload_seconds: int = 300):
    input_device.dev.grab()
    precursor_key = None
    last_config_reload = datetime.now()
    for event in input_device.dev.read_loop():
        if datetime.now() - last_config_reload >= timedelta(
            seconds=macros_reload_seconds
        ):
            input_device.reload_macros()
        if event.type == ecodes.EV_KEY:
            key = categorize(event)
            result = handle_event(key, precursor_key, input_device.macros)
            if input_device.debug:
                print(key.keycode)
            if result == EventResults.COMPLETE:
                precursor_key = None
            elif result == EventResults.PRECURSOR:
                precursor_key = (key.keycode, datetime.now())
            elif result == EventResults.NO_MACRO and not input_device.debug:
                non_blocking_alert("No Macro for that Key.", title="Keyboard Macros")
                print("no macro for that key")
            elif result == EventResults.FAILED:
                non_blocking_alert("Macro failed.", title="Keyboard Macros")
                print("macro failed")


def handle_event(key, precursor_key: (str, datetime), macros: dict):
    if key.keystate == key.key_down:
        if key.keycode not in macros:
            return EventResults.NO_MACRO
        if macros[key.keycode].get("precursor", False):
            return EventResults.PRECURSOR
        if precursor_key and datetime.now() - precursor_key[1] < timedelta(
            milliseconds=1500
        ):
            macros = macros.get(precursor_key[0], {})
        return execute_macro(macros, key.keycode)


def execute_macro(macros: dict, key_code: str):
    macro = macros.get(key_code)
    if not macro:
        return EventResults.NO_MACRO
    try:
        if command := macro.get("shell", None):
            result = subprocess.Popen(command.split(" "))
            if result.returncode and result.returncode != 0:
                return EventResults.COMPLETE
        elif keys := macro.get("type"):
            pyautogui.typewrite(keys['text'])
            if keys.get('enter', False):
                pyautogui.press("enter")
        elif keys := macro.get("press"):
            pyautogui.press(keys)
        else:
            return EventResults.NO_MACRO
    except Exception as err:
        print(err)
        return EventResults.FAILED


@click.command()
@click.option(
    "-c",
    "--config",
    default=DEFAULT_CONFIG_PATH,
    type=click.Path(exists=True),
    help="Path to config file",
    show_default=True,
)
@click.option(
    "-r",
    "--reload-seconds",
    default=300,
    show_default=True,
    help="Interval (in seconds) to reload macros from configuration file. "
    "(Adding a device requires a restart)",
)
def cli(config, reload_seconds):
    devices = get_devices(Path(config))
    for device in devices:
        new_thread = threading.Thread(target=create_loop, args=(device, reload_seconds))
        new_thread.start()
