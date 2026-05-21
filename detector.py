import pyautogui
import cv2
import numpy as np
import time
import threading

from config import TEMPLATES_DIR, SCREENSHOT_DIR, log, MULTI_SCALE_MATCH, MULTI_SCALE_RANGES
from region_learner import region_learner

_template_cache: dict[str, np.ndarray | None] = {}
_screen_cache_local = threading.local()


def _get_screen_cache():
    if not hasattr(_screen_cache_local, "data"):
        _screen_cache_local.data = None
        _screen_cache_local.time = 0.0
        _screen_cache_local.region = None
    return _screen_cache_local


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


def clear_template_cache():
    _template_cache.clear()


_SCREEN_CACHE_TTL: float = 0.15


def _screenshot(region: tuple = None) -> np.ndarray:
    cache = _get_screen_cache()
    now = time.time()
    if cache.data is not None and (now - cache.time) < _SCREEN_CACHE_TTL and cache.region == region:
        return cache.data
    if region is not None:
        left, top, w, h = region
        if w <= 0 or h <= 0:
            log.warning("截图区域无效: %s, 改用全屏", region)
            region = None
    if region is not None:
        img = pyautogui.screenshot(region=region)
    else:
        img = pyautogui.screenshot()
    cache.data = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    cache.time = now
    cache.region = region
    return cache.data


def invalidate_screen_cache():
    cache = _get_screen_cache()
    cache.data = None
    cache.region = None


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
            resized = cv2.resize(template, (new_w, new_h), interpolation=cv2.INTER_AREA)
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
        return None
    if MULTI_SCALE_MATCH:
        return _multi_scale_match(haystack, template, confidence)
    return _match_one(haystack, template, confidence)


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
