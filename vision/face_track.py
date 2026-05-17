from config import logger

_face_cascade = None

def _get_face_cascade():
    global _face_cascade
    if _face_cascade is None:
        import cv2 as _cv2
        xml = _cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade = _cv2.CascadeClassifier(xml)
    return _face_cascade

def _detect_face_at_ms(cap, t_ms: float, scale_w: int = 320):
    import cv2 as _cv2
    cap.set(_cv2.CAP_PROP_POS_MSEC, t_ms)
    ret, frame = cap.read()
    if not ret or frame is None: return None
    h, w = frame.shape[:2]
    if w == 0 or h == 0: return None
    scale = scale_w / w
    small = _cv2.resize(frame, (scale_w, max(1, int(h * scale))))
    gray = _cv2.cvtColor(small, _cv2.COLOR_BGR2GRAY)
    cascade = _get_face_cascade()
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(20, 20))
    if not len(faces): return None
    fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
    sh = max(1, int(h * scale))
    return ((fx + fw / 2) / scale_w, (fy + fh / 2) / sh)

def _smooth_track(positions: list, window: int = 2):
    if len(positions) < 2: return positions
    ts = [p[0] for p in positions]
    xs = [p[1] for p in positions]
    ys = [p[2] for p in positions]
    def avg(vals, i, w):
        lo, hi = max(0, i - w), min(len(vals), i + w + 1)
        return sum(vals[lo:hi]) / (hi - lo)
    return [(ts[i], avg(xs, i, window), avg(ys, i, window)) for i in range(len(ts))]

def _build_track_expr(keyframes: list, crop_dim: int, total_dim: int, coord: int):
    max_pos = total_dim - crop_dim
    def to_px(frac):
        return max(0, min(max_pos, int(frac * total_dim - crop_dim / 2))) & ~1
    if not keyframes: return str(max_pos // 2)
    pts = [(t, to_px(cx if coord == 0 else cy)) for t, cx, cy in keyframes]
    if len(pts) == 1: return str(pts[0][1])
    expr = str(pts[-1][1])
    for i in range(len(pts) - 2, -1, -1):
        t0, p0 = pts[i]
        t1, p1 = pts[i + 1]
        dt = round(t1 - t0, 3)
        if dt <= 0: continue
        lerp = f"({p0}+({p1 - p0})*(t-{t0:.3f})/{dt:.3f})"
        expr = f"if(lt(t,{t1:.3f}),{lerp},{expr})"
    return f"if(lt(t,{pts[0][0]:.3f}),{pts[0][1]},{expr})"

def build_face_tracking_vf(video_path, start: float, dur: float,
                            in_w: int, in_h: int,
                            sample_interval: float = 1.5,
                            out_w: int = 1080, out_h: int = 1920):
    import cv2 as _cv2
    ratio = 9 / 16
    is_landscape = (in_w / in_h) > ratio

    if is_landscape:
        crop_w = int(in_h * ratio) & ~1
        crop_h = in_h & ~1
    else:
        crop_w = in_w & ~1
        crop_h = int(in_w / ratio) & ~1

    crop_w = min(crop_w, in_w)
    crop_h = min(crop_h, in_h)

    n_samples = max(4, min(14, int(dur / sample_interval)))
    step = dur / n_samples
    timestamps_abs = [start + i * step for i in range(n_samples + 1) if (start + i * step) < (start + dur - 0.2)]

    detections = []
    try:
        cap = _cv2.VideoCapture(str(video_path))
        if not cap.isOpened(): raise RuntimeError("Cannot open video")
        for t_abs in timestamps_abs:
            result = _detect_face_at_ms(cap, t_abs * 1000)
            if result:
                cx, cy = result
                detections.append((t_abs - start, cx, cy))
        cap.release()
        logger.info(f"Face tracking: {len(detections)}/{len(timestamps_abs)} frames with face")
    except Exception as exc:
        logger.error("Face tracking failed", exc_info=True)

    def center_crop():
        if is_landscape:
            cx_px = ((in_w - crop_w) // 2) & ~1
            return f"crop={crop_w}:{crop_h}:{cx_px}:0,scale={out_w}:{out_h}:flags=lanczos"
        else:
            cy_px = ((in_h - crop_h) // 2) & ~1
            return f"crop={crop_w}:{crop_h}:0:{cy_px},scale={out_w}:{out_h}:flags=lanczos"

    if not detections:
        logger.warning("Face tracking: no faces detected \u2014 using center crop fallback")
        return center_crop()

    smoothed = _smooth_track(detections, window=2)

    if is_landscape:
        x_expr = _build_track_expr(smoothed, crop_w, in_w, 0)
        return f"crop={crop_w}:{crop_h}:{x_expr}:0,scale={out_w}:{out_h}:flags=lanczos"
    else:
        y_expr = _build_track_expr(smoothed, crop_h, in_h, 1)
        return f"crop={crop_w}:{crop_h}:0:{y_expr},scale={out_w}:{out_h}:flags=lanczos"
