from config import MAX_CLIPS, DEFAULT_DURATION, MIN_GAP_SECONDS, logger, LANGUAGE_CODES
from utils.ffmpeg import extract_audio_energy


def _extract_video_id(url: str):
    try:
        from urllib.parse import urlparse, parse_qs
        p = urlparse(url)
        if p.hostname in ("www.youtube.com", "youtube.com"):
            if p.path.startswith("/shorts/"):
                return p.path.split("/")[2]
            vid = parse_qs(p.query).get("v", [None])[0]
            return vid
        if p.hostname == "youtu.be":
            return p.path.lstrip("/")
    except Exception:
        pass
    return None


def _youtube_transcript_words(video_id: str, language: str = None):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        ytt = YouTubeTranscriptApi()
        lang_code = language or "en"
        entries = None
        for lang_try in [lang_code, None]:
            try:
                logger.info(f"Fetching transcript for {video_id} (lang: {lang_try or 'auto'})...")
                if lang_try:
                    entries = ytt.fetch(video_id, languages=[lang_try])
                else:
                    entries = ytt.fetch(video_id)
                logger.info(f"Got {len(entries)} transcript entries.")
                break
            except Exception as e:
                logger.warning(f"Transcript fetch failed ({lang_try or 'auto'}): {e}")
                continue
        if entries is None:
            return None
        words = []
        for e in entries:
            raw = getattr(e, "text", None) or (e.get("text", "") if isinstance(e, dict) else "")
            raw = raw.strip()
            if not raw: continue
            start = getattr(e, "start", None) or (e.get("start", 0) if isinstance(e, dict) else 0)
            duration = getattr(e, "duration", None) or (e.get("duration", 2) if isinstance(e, dict) else 2)
            parts = raw.split()
            dur_per_word = duration / max(len(parts), 1)
            for i, w in enumerate(parts):
                words.append({"word": w, "start": start + i * dur_per_word, "end": start + (i + 1) * dur_per_word})
        return words if words else None
    except Exception as exc:
        logger.warning(f"YouTube transcript not available: {exc}")
        return None


def find_speech_dense_segments(video_path, duration, n_clips=MAX_CLIPS, clip_duration=DEFAULT_DURATION, video_id=None, language=None):
    all_words = None
    if video_id:
        all_words = _youtube_transcript_words(video_id, language=language)

    if all_words is None:
        logger.info("YouTube transcript unavailable \u2014 using Audio RMS for segment detection (fast)")
        energies = extract_audio_energy(video_path, duration)
        return find_segments(energies, duration, n_clips, clip_duration)

    if not all_words:
        logger.warning("No speech detected, falling back to Audio Energy RMS hook detection.")
        energies = extract_audio_energy(video_path, duration)
        return find_segments(energies, duration, n_clips, clip_duration)

    max_start_time = int(duration - clip_duration)
    if max_start_time < 0:
        max_start_time = 0

    window_scores = []
    for t in range(0, max_start_time + 1):
        window_end = t + clip_duration
        word_count = sum(1 for w in all_words if w["start"] >= t and w["start"] <= window_end)
        window_scores.append((t, word_count))

    if not window_scores:
        energies = extract_audio_energy(video_path, duration)
        return find_segments(energies, duration, n_clips, clip_duration)

    window_scores.sort(key=lambda x: x[1], reverse=True)

    selected_clips = []
    for t, count in window_scores:
        if len(selected_clips) >= n_clips:
            break
        conflict = False
        for selected_start in selected_clips:
            if abs(t - selected_start) < MIN_GAP_SECONDS:
                conflict = True
                break
        if not conflict:
            selected_clips.append(t)

    selected_clips.sort()

    if len(selected_clips) < n_clips:
        step = max(60.0, (duration - clip_duration) / max(n_clips, 1))
        t = 10.0
        while len(selected_clips) < n_clips and t + clip_duration <= duration:
            if all(abs(t - p) >= MIN_GAP_SECONDS for p in selected_clips):
                selected_clips.append(t)
            t += step
        selected_clips.sort()

    final_segments = []
    for pt in selected_clips:
        start = float(pt)
        end = start + clip_duration
        if end > duration:
            end = duration
            start = max(0.0, end - clip_duration)
        final_segments.append((round(start, 2), round(end, 2)))

    return final_segments


def find_segments(energies, duration, n_clips=MAX_CLIPS, clip_duration=DEFAULT_DURATION):
    if not energies:
        step = max(60.0, (duration - clip_duration) / max(n_clips, 1))
        return [(round(i * step + 10, 2), round(i * step + 10 + clip_duration, 2))
                for i in range(n_clips) if i * step + 10 + clip_duration <= duration]

    times = [e[0] for e in energies]
    vals  = [e[1] for e in energies]

    w = min(10, max(3, len(vals) // 20))
    smoothed = []
    for i in range(len(vals)):
        lo, hi = max(0, i - w), min(len(vals), i + w + 1)
        smoothed.append(sum(vals[lo:hi]) / (hi - lo))

    used   = [False] * len(smoothed)
    peaks  = []
    gap_idx = MIN_GAP_SECONDS

    while len(peaks) < n_clips * 2:
        best_i = max(
            (i for i in range(len(smoothed)) if not used[i]),
            key=lambda i: smoothed[i], default=-1,
        )
        if best_i < 0: break
        peaks.append(times[best_i])
        lo = max(0, best_i - gap_idx)
        hi = min(len(used), best_i + gap_idx + 1)
        for j in range(lo, hi):
            used[j] = True

    peaks.sort()
    peaks = peaks[:n_clips]

    if len(peaks) < n_clips:
        step = max(60.0, (duration - clip_duration) / max(n_clips, 1))
        t = 10.0
        while len(peaks) < n_clips and t + clip_duration <= duration:
            if all(abs(t - p) >= MIN_GAP_SECONDS for p in peaks):
                peaks.append(t)
            t += step
        peaks.sort()

    segments = []
    for pt in peaks:
        start = max(0.0, pt - clip_duration * 0.25)
        end = start + clip_duration
        if end > duration:
            end = duration
            start = max(0.0, end - clip_duration)
        segments.append((round(start, 2), round(end, 2)))

    return segments
