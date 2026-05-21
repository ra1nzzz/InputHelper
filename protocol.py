from abc import ABC, abstractmethod
from typing import Any


class IDetector(ABC):
    @abstractmethod
    def find(self, template_name: str, confidence: float = 0.82) -> dict | None: ...

    @abstractmethod
    def find_on_screen(self, screen, template_name: str, confidence: float = 0.7) -> dict | None: ...

    @abstractmethod
    def check_on_screen(self, screen, template_name: str, confidence: float = 0.82) -> bool: ...

    @abstractmethod
    def batch_check(self, screen, checks: list[tuple]) -> dict[str, bool]: ...


class ISpeechClient(ABC):
    @abstractmethod
    def start(self): ...

    @abstractmethod
    def stop(self): ...

    @abstractmethod
    def speak(self, text: str): ...

    @abstractmethod
    def set_voice(self, voice: str): ...


class IStateMachine(ABC):
    @abstractmethod
    def start(self): ...

    @abstractmethod
    def stop(self): ...

    @abstractmethod
    def transition(self, new_state: Any): ...

    @abstractmethod
    def tick(self): ...
