import threading
import queue
import time
import json
import os
from pathlib import Path

from config import log, WAKE_WORD, DATA_DIR

VOSK_MODEL_DIR = DATA_DIR / "vosk_model"


class WakeWordDetector:
    def __init__(self, wake_word: str = "开始输入", callback=None):
        self._wake_word = wake_word
        self._callback = callback
        self._running = False
        self._thread = None
        self._audio_queue = queue.Queue()
        self._model = None
        self._recognizer = None
        self._p = None
        self._stream = None
        self._model_loaded = False
        self._load_error = None

    def _load_model(self):
        model_paths = [
            VOSK_MODEL_DIR,
            Path(os.environ.get("VOSK_MODEL_PATH", str(VOSK_MODEL_DIR))),
            Path.home() / ".cache" / "vosk",
        ]
        for mp in model_paths:
            if mp.exists() and any(mp.glob("*")):
                try:
                    from vosk import Model, KaldiRecognizer
                    self._model = Model(str(mp))
                    self._recognizer = KaldiRecognizer(self._model, 16000)
                    self._recognizer.SetWords(False)
                    self._model_loaded = True
                    log.info("VOSK模型已加载: %s", mp)
                    return
                except Exception as exc:
                    log.warning("加载VOSK模型失败 %s: %s", mp, exc)
        self._load_error = (
            f"未找到VOSK模型。请下载模型到 {VOSK_MODEL_DIR}\n"
            f"下载地址: https://alphacephei.com/vosk/models\n"
            f"推荐: vosk-model-small-cn-0.22 (约42MB)"
        )
        log.warning("VOSK模型未找到，唤醒词功能不可用")

    def start(self):
        if self._running:
            return
        self._load_model()
        if not self._model_loaded:
            log.error("唤醒词模块初始化失败: %s", self._load_error)
            return False
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="WakeWord")
        self._thread.start()
        log.info("唤醒词监听已启动: wake_word='%s'", self._wake_word)
        return True

    def stop(self):
        self._running = False
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._p is not None:
            try:
                self._p.terminate()
            except Exception:
                pass
            self._p = None
        log.info("唤醒词监听已停止")

    def set_callback(self, callback):
        self._callback = callback

    def set_wake_word(self, word: str):
        self._wake_word = word

    def is_available(self) -> bool:
        return self._model_loaded

    def get_load_error(self) -> str:
        return self._load_error or ""

    def _run(self):
        import pyaudio
        self._p = pyaudio.PyAudio()
        try:
            self._stream = self._p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=4000,
                stream_callback=self._audio_callback,
            )
            self._stream.start_stream()
            while self._running:
                try:
                    data = self._audio_queue.get(timeout=0.1)
                    if self._recognizer.AcceptWaveform(data):
                        result = json.loads(self._recognizer.Result())
                        self._check_result(result)
                    else:
                        partial = json.loads(self._recognizer.PartialResult())
                        self._check_partial(partial)
                except queue.Empty:
                    if not self._stream.is_active():
                        log.warning("音频流中断，尝试恢复")
                        self._stream.start_stream()
            self._recognizer = None
        except Exception as exc:
            log.error("唤醒词音频线程异常: %s", exc)
        finally:
            if self._stream is not None:
                try:
                    self._stream.stop_stream()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

    def _audio_callback(self, in_data, frame_count, time_info, status):
        self._audio_queue.put(in_data)
        return (None, pyaudio.paContinue)

    def _check_result(self, result):
        text = result.get("text", "")
        if text and self._wake_word in text:
            log.info("唤醒词检测到: '%s' in '%s'", self._wake_word, text)
            if self._callback:
                self._callback()

    def _check_partial(self, partial):
        text = partial.get("partial", "")
        if text and self._wake_word in text:
            log.info("唤醒词(部分)检测到: '%s' in '%s'", self._wake_word, text)
            if self._callback:
                self._callback()


class DummyWakeWordDetector:
    def start(self):
        log.info("唤醒词功能已禁用（哑实现）")
        return True

    def stop(self):
        pass

    def set_callback(self, callback):
        pass

    def set_wake_word(self, word: str):
        pass

    def is_available(self) -> bool:
        return False

    def get_load_error(self) -> str:
        return ""


def create_detector(wake_word: str, enabled: bool, callback=None):
    if enabled:
        return WakeWordDetector(wake_word, callback)
    return DummyWakeWordDetector()
