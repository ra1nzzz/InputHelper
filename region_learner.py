import json
import time
from pathlib import Path
from config import DATA_DIR, log

REGION_FILE = DATA_DIR / "learned_regions.json"

_LEARN_MARGIN = 60
_LEARN_MIN_SAMPLES = 1
_FULL_SCREEN_CONFIDENCE_INTERVAL = 30


class _RegionTracker:
    def __init__(self):
        self._cx_sum = 0.0
        self._cy_sum = 0.0
        self._count = 0
        self._last_cx = 0
        self._last_cy = 0
        self._learned: dict | None = None

    def update(self, cx: int, cy: int, tw: int, th: int):
        self._last_cx = cx
        self._last_cy = cy
        self._count += 1
        alpha = 1.0 / (self._count + 1)
        if self._count == 1:
            self._avg_cx = float(cx)
            self._avg_cy = float(cy)
        else:
            self._avg_cx = self._avg_cx * (1 - alpha) + cx * alpha
            self._avg_cy = self._avg_cy * (1 - alpha) + cy * alpha
        if self._count >= _LEARN_MIN_SAMPLES:
            self._learned = {
                "cx": int(self._avg_cx),
                "cy": int(self._avg_cy),
                "tw": tw,
                "th": th,
            }

    @property
    def has_learned(self) -> bool:
        return self._learned is not None

    def get_search_region(self, screen_w: int, screen_h: int) -> tuple | None:
        if not self.has_learned:
            return None
        r = self._learned
        margin = _LEARN_MARGIN
        left = max(0, r["cx"] - r["tw"] // 2 - margin)
        top = max(0, r["cy"] - r["th"] // 2 - margin)
        right = min(screen_w, r["cx"] + r["tw"] // 2 + margin)
        bottom = min(screen_h, r["cy"] + r["th"] // 2 + margin)
        w = right - left
        h = bottom - top
        if w <= 0 or h <= 0:
            log.warning("学习区域无效: cx=%d cy=%d tw=%d th=%d 屏幕=%dx%d, 重置",
                        r["cx"], r["cy"], r["tw"], r["th"], screen_w, screen_h)
            self.reset()
            return None
        return (left, top, w, h)

    def get_full_coords(self, region_left: int, region_top: int, local_cx: int, local_cy: int):
        return local_cx + region_left, local_cy + region_top

    def reset(self):
        self._count = 0
        self._learned = None


class RegionLearner:
    def __init__(self):
        self._trackers: dict[str, _RegionTracker] = {}
        self._last_full_screen = time.time() - _FULL_SCREEN_CONFIDENCE_INTERVAL
        self._full_screen_counter = 0

    def tracker(self, name: str) -> _RegionTracker:
        if name not in self._trackers:
            self._trackers[name] = _RegionTracker()
        return self._trackers[name]

    def should_full_screen(self) -> bool:
        now = time.time()
        if now - self._last_full_screen >= _FULL_SCREEN_CONFIDENCE_INTERVAL:
            self._last_full_screen = now
            return True
        return False

    def mark_full_screen(self):
        self._last_full_screen = time.time()

    def save(self):
        data = {}
        for name, t in self._trackers.items():
            if t.has_learned:
                data[name] = t._learned
        try:
            with open(REGION_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            log.debug("学习区域已保存: %d 个模板", len(data))
        except Exception as exc:
            log.warning("保存学习区域失败: %s", exc)

    def load(self):
        if not REGION_FILE.exists():
            return
        try:
            with open(REGION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for name, info in data.items():
                t = self.tracker(name)
                t._learned = info
                t._count = _LEARN_MIN_SAMPLES + 5
                t._avg_cx = float(info["cx"])
                t._avg_cy = float(info["cy"])
            log.info("已加载学习区域: %d 个模板", len(data))
        except Exception as exc:
            log.warning("加载学习区域失败: %s", exc)

    def reset_all(self):
        for t in self._trackers.values():
            t.reset()
        log.info("所有学习区域已重置")


region_learner = RegionLearner()
