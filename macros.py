import os
import subprocess
import threading
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Union, List, Optional

import toml
from evdev import InputDevice, categorize, ecodes


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
    ):
        self.name = device_name
        self.dev = InputDevice(str(event_path))
        self.macros = macro_dict
        self.config_path = config_path

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
            InputWithMacros(data["input_path"], data["macros"], name, config_path)
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
            if result == EventResults.COMPLETE:
                precursor_key = None
            elif result == EventResults.PRECURSOR:
                precursor_key = key.keycode
            elif result == EventResults.NO_MACRO:
                print("no macro for that key")
            elif result == EventResults.FAILED:
                print("macro failed")


def handle_event(key, precursor_key: str, macros: dict):
    if key.keystate == key.key_down:
        if key.keycode not in macros:
            return EventResults.NO_MACRO
        if isinstance(macros.get(key.keycode, None), dict):
            return EventResults.PRECURSOR
        if precursor_key:
            macros = macros.get(precursor_key, {})
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


def main():
    devices = get_devices(Path("/home/rick/repositories/scratch/macro-kbd/macros.toml"))
    for device in devices:
        new_thread = threading.Thread(target=create_loop, args=(device, 5))
        new_thread.start()


if __name__ == "__main__":
    main()
