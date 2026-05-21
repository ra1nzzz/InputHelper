import json
import threading
import queue
import time
import tempfile
import os

from config import log

API_KEY = "64GLA6Ad6JIn8QgL7Qw3UQ9vmSxsFwXkWtt3KgK0VIaCyK903UlAACPkLLAOPJfaw"
WS_URL = "wss://api.stepfun.com/step_plan/v1/realtime?model=stepaudio-2.5-realtime"

_DEFAULT_VOICE = "qingnianansheng"
_DEFAULT_INSTRUCTIONS = "你是一个语音播报助手，用自然、清晰的语气朗读用户提供的文本。不要添加额外的问候语或解释，直接朗读文本内容。"


class StepAudioClient:
    def __init__(self, voice: str = _DEFAULT_VOICE, instructions: str = _DEFAULT_INSTRUCTIONS):
        self._voice = voice
        self._instructions = instructions
        self._ws = None
        self._thread = None
        self._running = False
        self._audio_queue: queue.Queue = queue.Queue()
        self._connected = threading.Event()
        self._pending_text: queue.Queue = queue.Queue()
        self._lock = threading.Lock()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_ws, daemon=True, name="StepAudio")
        self._thread.start()
        log.info("StepAudio WebSocket 连接已启动")

    def stop(self):
        self._running = False
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=3)
        log.info("StepAudio WebSocket 已关闭")

    def speak(self, text: str):
        if not text or not self._running:
            return
        self._pending_text.put(text)

    def set_voice(self, voice: str):
        self._voice = voice

    def set_instructions(self, instructions: str):
        self._instructions = instructions

    def _run_ws(self):
        try:
            import websocket
        except ImportError:
            log.error("StepAudio 需要 websocket-client 库: pip install websocket-client")
            return

        headers = {"Authorization": f"Bearer {API_KEY}"}

        def on_open(ws):
            self._ws = ws
            ws.send(json.dumps({
                "event_id": "event_init",
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": self._instructions,
                    "voice": self._voice,
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                }
            }))
            self._connected.set()
            log.info("StepAudio WebSocket 已连接")

        def on_message(ws, message):
            try:
                data = json.loads(message)
                event_type = data.get("type", "")
                if event_type == "response.audio.delta":
                    audio_b64 = data.get("delta", "")
                    if audio_b64:
                        import base64
                        self._audio_queue.put(base64.b64decode(audio_b64))
                elif event_type == "response.done":
                    self._audio_queue.put(None)
            except Exception as exc:
                log.debug("StepAudio 消息解析异常: %s", exc)

        def on_error(ws, error):
            log.warning("StepAudio WebSocket 错误: %s", error)

        def on_close(ws, close_status_code, close_msg):
            self._connected.clear()
            log.info("StepAudio WebSocket 已断开")

        while self._running:
            try:
                ws = websocket.WebSocketApp(
                    WS_URL,
                    header=headers,
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close,
                )
                ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as exc:
                log.error("StepAudio 连接异常: %s", exc)
            if self._running:
                time.sleep(3)
                self._connected.clear()

    def _play_audio_loop(self):
        while self._running:
            try:
                text = self._pending_text.get(timeout=1)
            except queue.Empty:
                continue

            if not self._connected.wait(timeout=5):
                log.warning("StepAudio 连接超时，跳过播报")
                continue

            if self._ws is None:
                continue

            try:
                self._ws.send(json.dumps({
                    "event_id": f"event_{int(time.time()*1000)}",
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": text}
                        ]
                    }
                }))
                self._ws.send(json.dumps({
                    "event_id": f"event_resp_{int(time.time()*1000)}",
                    "type": "response.create",
                    "response": {"modalities": ["audio"]}
                }))

                import winsound
                import base64
                import io
                import wave

                chunks = []
                while self._running:
                    chunk = self._audio_queue.get(timeout=10)
                    if chunk is None:
                        break
                    chunks.append(chunk)

                if chunks:
                    pcm_data = b"".join(chunks)
                    wav_buffer = io.BytesIO()
                    with wave.open(wav_buffer, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(24000)
                        wf.writeframes(pcm_data)
                    wav_buffer.seek(0)

                    tmp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                    tmp_file.write(wav_buffer.read())
                    tmp_file.close()
                    try:
                        winsound.PlaySound(tmp_file.name, winsound.SND_FILENAME | winsound.SND_ASYNC)
                        time.sleep(len(pcm_data) / (24000 * 2) + 0.5)
                    except Exception as exc:
                        log.warning("音频播放失败: %s", exc)
                    finally:
                        try:
                            os.unlink(tmp_file.name)
                        except Exception:
                            pass

            except Exception as exc:
                log.error("StepAudio 播报异常: %s", exc)


_step_audio_client: StepAudioClient | None = None


def get_client() -> StepAudioClient | None:
    global _step_audio_client
    return _step_audio_client


def init_client(voice: str = _DEFAULT_VOICE, enabled: bool = True):
    global _step_audio_client
    if not enabled:
        if _step_audio_client is not None:
            _step_audio_client.stop()
            _step_audio_client = None
        return
    if _step_audio_client is None:
        _step_audio_client = StepAudioClient(voice=voice)
        _step_audio_client.start()
        t = threading.Thread(target=_step_audio_client._play_audio_loop, daemon=True, name="StepAudioPlayer")
        t.start()
    else:
        _step_audio_client.set_voice(voice)


def speak(text: str):
    if _step_audio_client is not None:
        _step_audio_client.speak(text)


def cleanup():
    global _step_audio_client
    if _step_audio_client is not None:
        _step_audio_client.stop()
        _step_audio_client = None
