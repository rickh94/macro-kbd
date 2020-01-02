import subprocess
import threading
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Union, List

import click
import toml
from evdev import InputDevice, categorize, ecodes

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
        if next_config["macros"] != self.macros:
            self.macros = next_config["macros"]


def get_devices(config_path: Path):
    config = toml.load(config_path)
    devices: List[InputWithMacros] = []
    for name, data in config.items():
        devices.append(
            InputWithMacros(
                data["input_path"],
                data["macros"],
                name,
                config_path,
                data.get("DEBUG", False),
            )
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
            elif result == EventResults.NO_MACRO:
                print("no macro for that key")
            elif result == EventResults.FAILED:
                print("macro failed")


def handle_event(key, precursor_key: (str, datetime), macros: dict):
    if key.keystate == key.key_down:
        if key.keycode not in macros:
            return EventResults.NO_MACRO
        if isinstance(macros.get(key.keycode, None), dict):
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
        result = subprocess.Popen(macro.split(" "))
        if result.returncode and result.returncode != 0:
            return EventResults.COMPLETE
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
