import json
import urllib.request
import urllib.error

from config import logger


def generate_viral_hooks(transcript: str, api_key: str) -> list:
    if not transcript or not api_key:
        logger.info(f"Viral Hooks skipped: transcript={'empty' if not transcript else 'ok'}, key={'missing' if not api_key else 'ok'}")
        return []

    url = "https://api.groq.com/openai/v1/chat/completions"
    prompt = (
        "Analyze the following short video transcript and write 3 highly engaging, viral TikTok/Shorts "
        "hooks or on-screen text titles that would capture a viewer's attention instantly. "
        "Return ONLY a raw JSON array of exactly 3 strings. Do NOT include any markdown, code fences, "
        "explanation, or any text outside the JSON array itself.\n\n"
        f"Transcript: {transcript}"
    )
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.8, "max_tokens": 300,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "groq-python/1.0.0",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            resp_body = response.read().decode("utf-8")
            resp_json = json.loads(resp_body)
            text = resp_json["choices"][0]["message"]["content"].strip()
            logger.info(f"Groq raw response: {text[:200]}")
            if text.startswith("```json"):
                text = text[7:]
                text = text[:text.rfind("```")].strip()
            elif text.startswith("```"):
                text = text[3:]
                text = text[:text.rfind("```")].strip()
            hooks = json.loads(text)
            if isinstance(hooks, list):
                logger.info(f"Generated {len(hooks)} viral hooks successfully")
                return hooks[:3]
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        logger.error(f"Groq API HTTP {e.code} error: {error_body[:500]}")
    except urllib.error.URLError as e:
        logger.error(f"Groq API connection error: {e.reason}")
    except json.JSONDecodeError as e:
        logger.error(f"Groq response JSON parse error: {e}")
    except Exception as e:
        logger.error("Groq unexpected error occurred", exc_info=True)
    return []


def calculate_viral_score(transcript: str, clip_duration: float,
                           caption_style: str, broll_count: int) -> float:
    score = 4.0
    if 28 <= clip_duration <= 62:
        score += 1.0
    elif 15 <= clip_duration < 28 or 62 < clip_duration <= 90:
        score += 0.4
    if transcript and clip_duration > 0:
        wpm = len(transcript.split()) / (clip_duration / 60)
        if 120 <= wpm <= 200:
            score += 0.7
        elif 80 <= wpm < 120 or 200 < wpm <= 250:
            score += 0.3
    HOOK = {
        'shocking','secret','truth','revealed','exposed','incredible','insane',
        'crazy','unbelievable','never','always','mistake','wrong','stop',
        'biggest','warning','must','need','hack','trick','strategy','proven',
        'rich','money','free','fast','easy','nobody','everyone','why','how',
        'best','worst','only','actually','honestly','literally','finally',
    }
    if transcript:
        hits = len(set(transcript.lower().split()[:30]) & HOOK)
        score += min(1.0, hits * 0.5)
    score += min(1.5, broll_count * 0.5)
    if caption_style in {'mrbeast','hormozi','tiktok','garyvee','imangadzi','devinjatho'}:
        score += 0.4
    if transcript and len(transcript.split()) >= 60:
        score += 0.3
    return round(min(10.0, max(1.0, score)), 1)
