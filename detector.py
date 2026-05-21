import pyautogui
import cv2
import numpy as np
import time

from config import TEMPLATES_DIR, SCREENSHOT_DIR, log, MULTI_SCALE_MATCH, MULTI_SCALE_RANGES
from config import CONFIDENCE_ADAPTATION_ENABLED, CONFIDENCE_BASE, CONFIDENCE_MIN, CONFIDENCE_MAX, CONFIDENCE_STEP, CONFIDENCE_SUCCESS_THRESHOLD, CONFIDENCE_FAIL_THRESHOLD
from region_learner import region_learner
from protocol import IDetector

_template_cache: dict[str, np.ndarray | None] = {}
_scaled_template_cache: dict[tuple, np.ndarray] = {}
_screen_cache_data: np.ndarray | None = None
_screen_cache_time: float = 0.0
_screen_cache_region: tuple | None = None
_SCREEN_CACHE_TTL: float = 0.15

_conf_adapt: dict[str, float] = {}
_conf_history: dict[str, list[bool]] = {}
_conf_difficulty: dict[str, float] = {}


def _get_adapted_confidence(template_name: str, base_confidence: float) -> float:
    if not CONFIDENCE_ADAPTATION_ENABLED:
        return base_confidence
    adapted = _conf_adapt.get(template_name)
    if adapted is None:
        return base_confidence
    difficulty = _conf_difficulty.get(template_name, 1.0)
    adjusted = adapted * difficulty
    return max(CONFIDENCE_MIN, min(CONFIDENCE_MAX, adjusted))


def _record_match(template_name: str, success: bool):
    if not CONFIDENCE_ADAPTATION_ENABLED:
        return
    if template_name not in _conf_history:
        _conf_history[template_name] = []
    history = _conf_history[template_name]
    history.append(success)
    if len(history) > 20:
        history.pop(0)
    recent_success = sum(history[-10:])
    total = len(history[-10:])
    current = _conf_adapt.get(template_name, CONFIDENCE_BASE)
    if recent_success >= int(total * CONFIDENCE_SUCCESS_THRESHOLD):
        new_conf = min(CONFIDENCE_MAX, current + CONFIDENCE_STEP)
        _conf_difficulty[template_name] = max(0.8, _conf_difficulty.get(template_name, 1.0) - 0.05)
        if new_conf != current:
            _conf_adapt[template_name] = new_conf
            log.debug("置信度上调 %s: %.2f -> %.2f (难度=%.1f)", template_name, current, new_conf, _conf_difficulty[template_name])
    elif recent_success <= int(total * CONFIDENCE_FAIL_THRESHOLD):
        new_conf = max(CONFIDENCE_MIN, current - CONFIDENCE_STEP)
        _conf_difficulty[template_name] = min(1.3, _conf_difficulty.get(template_name, 1.0) + 0.05)
        if new_conf != current:
            _conf_adapt[template_name] = new_conf
            log.debug("置信度下调 %s: %.2f -> %.2f (难度=%.1f)", template_name, current, new_conf, _conf_difficulty[template_name])
    else:
        _conf_adapt[template_name] = current


def _get_screen_cache():
    global _screen_cache_data, _screen_cache_time, _screen_cache_region
    return type("Cache", (), {
        "data": _screen_cache_data,
        "time": _screen_cache_time,
        "region": _screen_cache_region,
    })()


def _update_screen_cache(data, t, region):
    global _screen_cache_data, _screen_cache_time, _screen_cache_region
    _screen_cache_data = data
    _screen_cache_time = t
    _screen_cache_region = region


def _load_template(name: str) -> np.ndarray | None:
    if name in _template_cache:
        return _template_cache[name]
    path = TEMPLATES_DIR / name
    if not path.exists():
        log.warning("模板文件不存在: %s", name)
        _template_cache[name] = None
        return None
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        log.warning("模板文件读取失败: %s", name)
        _template_cache[name] = None
        return None
    _template_cache[name] = img
    return img


def _get_scaled_template(template: np.ndarray, scale: float) -> np.ndarray:
    cache_key = (id(template), scale)
    if cache_key in _scaled_template_cache:
        return _scaled_template_cache[cache_key]
    h, w = template.shape[:2]
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(template, (new_w, new_h), interpolation=cv2.INTER_AREA)
    _scaled_template_cache[cache_key] = resized
    return resized


def clear_template_cache():
    _template_cache.clear()
    _scaled_template_cache.clear()


def _screenshot(region: tuple = None) -> np.ndarray:
    global _screen_cache_data, _screen_cache_time, _screen_cache_region
    now = time.time()
    if _screen_cache_data is not None and (now - _screen_cache_time) < _SCREEN_CACHE_TTL and _screen_cache_region == region:
        return _screen_cache_data
    if region is not None:
        left, top, w, h = region
        if w <= 0 or h <= 0:
            log.warning("截图区域无效: %s, 改用全屏", region)
            region = None
    if region is not None:
        img = pyautogui.screenshot(region=region)
    else:
        img = pyautogui.screenshot()
    _screen_cache_data = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    _screen_cache_time = now
    _screen_cache_region = region
    return _screen_cache_data


def invalidate_screen_cache():
    global _screen_cache_data, _screen_cache_region
    _screen_cache_data = None
    _screen_cache_region = None


def save_debug_screenshot(tag: str, img_bgr=None):
    if img_bgr is None:
        img_bgr = _screenshot()
    ts = time.strftime("%H%M%S")
    path = SCREENSHOT_DIR / f"{tag}_{ts}.png"
    cv2.imwrite(str(path), img_bgr)


def _multi_scale_match(haystack: np.ndarray, template: np.ndarray, base_confidence: float):
    best = None
    for s in MULTI_SCALE_RANGES:
        if abs(s - 1.0) < 0.01:
            r = _match_one(haystack, template, base_confidence - 0.02)
        else:
            h, w = template.shape[:2]
            new_w, new_h = int(w * s), int(h * s)
            if new_h > haystack.shape[0] or new_w > haystack.shape[1]:
                continue
            resized = _get_scaled_template(template, s)
            r = _match_one(haystack, resized, base_confidence - 0.05)
        if r and (best is None or r["confidence"] > best["confidence"]):
            best = r
    return best


def _match_one(haystack: np.ndarray, template: np.ndarray, confidence: float):
    th, tw = template.shape[:2]
    sh, sw = haystack.shape[:2]
    if th > sh or tw > sw:
        return None
    result = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if max_val >= confidence:
        return {
            "center": (max_loc[0] + tw // 2, max_loc[1] + th // 2),
            "top_left": max_loc,
            "size": (tw, th),
            "confidence": max_val,
        }
    return None


def _match_on_array(haystack: np.ndarray, template_name: str, confidence: float = 0.82):
    template = _load_template(template_name)
    if template is None:
        _record_match(template_name, False)
        return None
    adapted = _get_adapted_confidence(template_name, confidence)
    if MULTI_SCALE_MATCH:
        r = _multi_scale_match(haystack, template, adapted)
    else:
        r = _match_one(haystack, template, adapted)
    _record_match(template_name, r is not None)
    return r


def _search_region(template_name: str, screen_size):
    tracker = region_learner.tracker(template_name)
    if tracker.has_learned and not region_learner.should_full_screen():
        return tracker.get_search_region(screen_size.width, screen_size.height)
    return None


def find_template(template_name: str, confidence: float = 0.82):
    tracker = region_learner.tracker(template_name)
    screen_size = pyautogui.size()

    region = _search_region(template_name, screen_size)
    if region:
        screen = _screenshot(region=region)
        r = _match_on_array(screen, template_name, confidence)
        if r:
            abs_cx, abs_cy = tracker.get_full_coords(region[0], region[1], *r["center"])
            r["center"] = (abs_cx, abs_cy)
            r["top_left"] = (r["top_left"][0] + region[0], r["top_left"][1] + region[1])
            tracker.update(abs_cx, abs_cy, r["size"][0], r["size"][1])
            return r

    screen = _screenshot(region=None)
    r = _match_on_array(screen, template_name, confidence)
    if r:
        tracker.update(r["center"][0], r["center"][1], r["size"][0], r["size"][1])
        region_learner.mark_full_screen()
    return r


def find_on_screen(screen: np.ndarray, template_name: str, confidence: float = 0.7,
                   region_offset: tuple = (0, 0)):
    r = _match_on_array(screen, template_name, confidence)
    if r and region_offset != (0, 0):
        r["center"] = (r["center"][0] + region_offset[0], r["center"][1] + region_offset[1])
        r["top_left"] = (r["top_left"][0] + region_offset[0], r["top_left"][1] + region_offset[1])
        tracker = region_learner.tracker(template_name)
        tracker.update(r["center"][0], r["center"][1], r["size"][0], r["size"][1])
    return r


def is_visible(template_name: str, confidence: float = 0.82) -> bool:
    return find_template(template_name, confidence) is not None


def check_on_screen(screen: np.ndarray, template_name: str, confidence: float = 0.82,
                    region_offset: tuple = (0, 0)):
    tracker = region_learner.tracker(template_name)
    screen_size = pyautogui.size()

    region = _search_region(template_name, screen_size)
    if region:
        local_screen = _screenshot(region=region)
        r = _match_on_array(local_screen, template_name, confidence)
        if r:
            abs_cx, abs_cy = tracker.get_full_coords(region[0], region[1], *r["center"])
            tracker.update(abs_cx, abs_cy, r["size"][0], r["size"][1])
            return True

    r = _match_on_array(screen, template_name, confidence)
    if r:
        abs_cx = r["center"][0] + region_offset[0]
        abs_cy = r["center"][1] + region_offset[1]
        tracker.update(abs_cx, abs_cy, r["size"][0], r["size"][1])
        return True
    return False


def batch_check(screen: np.ndarray, checks: list[tuple]) -> dict:
    results = {}
    for template_name, confidence, region_offset in checks:
        r = _match_on_array(screen, template_name, confidence)
        if r and region_offset != (0, 0):
            r["center"] = (r["center"][0] + region_offset[0], r["center"][1] + region_offset[1])
            r["top_left"] = (r["top_left"][0] + region_offset[0], r["top_left"][1] + region_offset[1])
        if r:
            tracker = region_learner.tracker(template_name)
            tracker.update(r["center"][0], r["center"][1], r["size"][0], r["size"][1])
        results[template_name] = r is not None
    return results


def wait_for(template_name: str, timeout: float = 10, confidence: float = 0.82, interval: float = 0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = find_template(template_name, confidence)
        if r:
            return r
        time.sleep(interval)
    return None


def wait_for_vanish(template_name: str, timeout: float = 30, confidence: float = 0.82, interval: float = 0.3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_visible(template_name, confidence):
            return True
        time.sleep(interval)
    return False


def region_has_text(region: tuple, screen_bgr: np.ndarray = None, edge_thresh: float = 5.0,
                    return_ratio: bool = False):
    left, top, w, h = region
    if left < 0:
        w += left
        left = 0
    if top < 0:
        h += top
        top = 0
    if w <= 0 or h <= 0:
        return (False, 0.0) if return_ratio else False
    if screen_bgr is not None:
        sh, sw = screen_bgr.shape[:2]
        if left + w > sw:
            w = sw - left
        if top + h > sh:
            h = sh - top
        if w <= 0 or h <= 0:
            return (False, 0.0) if return_ratio else False
        roi = screen_bgr[top:top + h, left:left + w]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    else:
        img = pyautogui.screenshot(region=(left, top, w, h))
        gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, 50, 150)
    ratio = np.count_nonzero(edges) / (edges.shape[0] * edges.shape[1]) * 100
    has = ratio > edge_thresh
    if return_ratio:
        return has, ratio
    return has


def capture_screen(region: tuple = None) -> np.ndarray:
    return _screenshot(region=region)


def get_voice_bar_region() -> tuple | None:
    screen_size = pyautogui.size()
    for name in ["confirm_btn", "ready_to_speaking"]:
        tracker = region_learner.tracker(name)
        if tracker.has_learned:
            region = tracker.get_search_region(screen_size.width, screen_size.height)
            if region:
                left, top, w, h = region
                return (left, top, w, h + 80)
    return None


class DetectorAdapter(IDetector):
    def find(self, template_name: str, confidence: float = 0.82) -> dict | None:
        return find_template(template_name, confidence)

    def find_on_screen(self, screen, template_name: str, confidence: float = 0.7) -> dict | None:
        return find_on_screen(screen, template_name, confidence)

    def check_on_screen(self, screen, template_name: str, confidence: float = 0.82) -> bool:
        return check_on_screen(screen, template_name, confidence)

    def batch_check(self, screen, checks: list[tuple]) -> dict[str, bool]:
        return batch_check(screen, checks)
