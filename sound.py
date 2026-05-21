import winsound
from config import (
    SUCCESS_SOUND_FREQ, SUCCESS_SOUND_DUR_MS,
    START_SOUND_FREQ, START_SOUND_DUR_MS,
    ERROR_SOUND_FREQ, ERROR_SOUND_DUR_MS,
)


def beep(frequency: int, duration_ms: int):
    try:
        winsound.Beep(frequency, duration_ms)
    except Exception:
        pass


def play_success():
    beep(SUCCESS_SOUND_FREQ, SUCCESS_SOUND_DUR_MS)


def play_start():
    beep(START_SOUND_FREQ, START_SOUND_DUR_MS)


def play_error():
    beep(ERROR_SOUND_FREQ, ERROR_SOUND_DUR_MS)
