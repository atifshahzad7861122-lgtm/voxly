import os
import platform
import logging
import logging.handlers
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s \u2014 %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            "voxly.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        ),
    ],
)
logger = logging.getLogger("voxly")

PORT = int(os.environ.get("PORT", 5000))

MAX_CLIPS = 10
DEFAULT_DURATION = 45
MIN_GAP_SECONDS = 60
SAMPLE_RATE = 8000
ENERGY_WINDOW = 5

BASE_DIR = Path(__file__).parent.resolve()
CLIPS_DIR = BASE_DIR / "clips"
DOWNLOADS_DIR = BASE_DIR / "downloads"
UPLOADS_DIR = BASE_DIR / "uploads"
FONTS_DIR = BASE_DIR / "fonts"
LOGOS_DIR = BASE_DIR / "logos"
BUNDLED_FONT_DIR = BASE_DIR / "assets" / "fonts"

CLIPS_DIR.mkdir(exist_ok=True)
DOWNLOADS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)
FONTS_DIR.mkdir(exist_ok=True)
LOGOS_DIR.mkdir(exist_ok=True)
BUNDLED_FONT_DIR.mkdir(parents=True, exist_ok=True)

YTDLP_LAST_UPDATE_FILE = BASE_DIR / ".ytdlp_last_update"
YTDLP_UPDATE_INTERVAL_DAYS = 3

COOKIES_FILE = BASE_DIR / "cookies.txt"
COOKIE_REFRESH_SEC = 1800

DB_PATH = BASE_DIR / "voxly_history.db"

RESOLUTION_MAP = {
    "480p": {
        "width": 480, "height": 854,
        "bitrate": "2000k", "maxrate": "2500k", "bufsize": "4000k", "crf": 24,
    },
    "720p": {
        "width": 720, "height": 1280,
        "bitrate": "4000k", "maxrate": "5000k", "bufsize": "8000k", "crf": 22,
    },
    "1080p": {
        "width": 1080, "height": 1920,
        "bitrate": "8000k", "maxrate": "10000k", "bufsize": "16000k", "crf": 18,
    },
    "4k": {
        "width": 2160, "height": 3840,
        "bitrate": "35000k", "maxrate": "40000k", "bufsize": "70000k", "crf": 16,
    },
}
DEFAULT_RESOLUTION = "1080p"

PRESET_MAP = {
    "480p": "fast",
    "720p": "medium",
    "1080p": "slow",
    "4k": "medium",
}

FORMAT_MAP = {
    "mp4": {
        "extension": ".mp4", "vcodec": "libx264", "acodec": "aac",
        "pixel_fmt": "yuv420p", "extra_flags": ["-movflags", "+faststart"],
        "mime_type": "video/mp4",
    },
    "mov": {
        "extension": ".mov", "vcodec": "libx264", "acodec": "aac",
        "pixel_fmt": "yuv420p", "extra_flags": ["-movflags", "+faststart"],
        "mime_type": "video/quicktime",
    },
    "webm": {
        "extension": ".webm", "vcodec": "libvpx-vp9", "acodec": "libopus",
        "pixel_fmt": "yuv420p",
        "extra_flags": ["-deadline", "realtime", "-cpu-used", "4"],
        "mime_type": "video/webm",
    },
}
DEFAULT_FORMAT = "mp4"

COLOR_GRADE_FILTERS: dict[str, str] = {
    "none": "",
    "cinematic": (
        "curves=r='0/0 0.5/0.55 1/0.97':g='0/0 0.5/0.48 1/0.95':b='0/0.04 0.5/0.38 1/0.82',"
        "eq=saturation=1.2:contrast=1.05"
    ),
    "warm": "curves=r='0/0.04 1/1':g='0/0 1/0.97':b='0/0 1/0.82',eq=saturation=1.1:brightness=0.02",
    "cold": "curves=r='0/0 1/0.86':g='0/0 1/0.96':b='0/0.04 1/1',eq=saturation=0.95",
    "moody": "eq=contrast=1.2:saturation=0.72:brightness=-0.04,curves=r='0/0.02 1/0.95':b='0/0.02 1/0.92'",
    "bleach": "eq=contrast=1.3:saturation=0.35:brightness=-0.02",
}

EMOJI_MAP: dict[str, tuple[str, str]] = {
    "insane": ("INSANE!", "red@0.82"),
    "crazy": ("CRAZY!", "red@0.82"),
    "unbelievable": ("UNBELIEVABLE!", "red@0.82"),
    "shocking": ("SHOCKING!", "red@0.82"),
    "money": ("MONEY!", "0xE0760A@0.85"),
    "rich": ("RICH!", "0xE0760A@0.85"),
    "million": ("MILLIONS!", "0xE0760A@0.85"),
    "billion": ("BILLIONS!", "0xE0760A@0.85"),
    "win": ("WIN!", "0x16A34A@0.85"),
    "won": ("WE WON!", "0x16A34A@0.85"),
    "secret": ("SECRET!", "0x7C3AED@0.85"),
    "revealed": ("REVEALED!", "0x7C3AED@0.85"),
    "truth": ("THE TRUTH!", "0x7C3AED@0.85"),
    "amazing": ("AMAZING!", "0xB45309@0.85"),
    "incredible": ("INCREDIBLE!", "0xB45309@0.85"),
    "stop": ("STOP!", "red@0.85"),
    "warning": ("WARNING!", "red@0.85"),
    "free": ("FREE!", "0x16A34A@0.85"),
    "hack": ("LIFE HACK!", "0x0369A1@0.85"),
    "trick": ("PRO TRICK!", "0x0369A1@0.85"),
}

WHISPER_LANG_PROMPTS: dict[str, str] = {
    "ur": (
        "یہ اردو تقریر ہے۔ تمام الفاظ درست اردو رسم الخط اور صحیح ہجّے کے ساتھ لکھیں۔ "
        "عبادت، توحید، نماز، تہجد، رزق، دعا، صبر، شکر، اللہ، قرآن، حدیث، "
        "مسجد، امام، خطبہ، جمعہ، روزہ، زکات، حج۔"
    ),
    "hi": (
        "यह हिंदी भाषण है। सभी शब्दों को सही हिंदी वर्तनी और व्याकरण के साथ लिखें। "
        "नमाज़, इबादत, तहज्जुद, रोज़ी, दुआ, सब्र, शुक्र, अल्लाह, क़ुरआन, "
        "मस्जिद, इमाम, जुमा, रोज़ा, ज़कात, हज।"
    ),
    "en": (
        "This is a clear English speech. Write all words with correct spelling, "
        "punctuation, and grammar. Use standard English vocabulary."
    ),
    "ar": (
        "هذا خطاب عربي فصيح. اكتب جميع الكلمات بالإملاء العربي الصحيح والنحو السليم. "
        "العبادة، التوحيد، الصلاة، الزكاة، الحج، الدعاء، الصبر، الشكر، القرآن الكريم."
    ),
    "pa": (
        "ਇਹ ਪੰਜਾਬੀ ਭਾਸ਼ਣ ਹੈ। ਸਾਰੇ ਸ਼ਬਦਾਂ ਨੂੰ ਸਹੀ ਪੰਜਾਬੀ ਵਰਤਨੀ ਅਤੇ ਵਿਆਕਰਨ ਨਾਲ ਲਿਖੋ। "
        "ਪਰਮਾਤਮਾ, ਸਤਿਗੁਰੂ, ਗੁਰਬਾਣੀ, ਗੁਰਦੁਆਰਾ, ਨਾਮ, ਸਿਮਰਨ।"
    ),
    "ne": (
        "यो नेपाली भाषण हो। सबै शब्दहरू सही नेपाली वर्तनी र व्याकरणसहित लेख्नुहोस्। "
        "नमस्कार, धन्यवाद, ईश्वर, प्रार्थना, मन्दिर, पूजा।"
    ),
    "te": (
        "ఇది తెలుగు ప్రసంగం. అన్ని పదాలను సరైన తెలుగు వ్యాకరణంతో రాయండి. "
        "నమస్కారం, దేవుడు, దేవాలయం, ప్రార్థన, ధన్యవాదాలు."
    ),
    "ta": (
        "இது தமிழ் பேச்சு. அனைத்து சொற்களையும் சரியான தமிழ் இலக்கணத்துடன் எழுதுங்கள். "
        "வணக்கம், கடவுள், கோவில், பிரார்த்தனை, நன்றி."
    ),
    "bn": (
        "এটি বাংলা ভাষণ। সমস্ত শব্দ সঠিক বাংলা বানান ও ব্যাকরণ সহ লিখুন। "
        "নমস্কার, ঈশ্বর, মন্দির, প্রার্থনা, ধন্যবাদ, ইবাদত।"
    ),
    "gu": (
        "આ ગુજરાતી ભાષણ છે। તમામ શબ્દો સાચી ગુજરાતી જોડણી અને વ્યાકરણ સાથે લખો। "
        "નમસ્કાર, ઈશ્વર, મંદિર, પ્રાર્થના, ખુદા, ઈબાદત."
    ),
    "mr": (
        "हे मराठी भाषण आहे. सर्व शब्द योग्य मराठी शब्दलेखन आणि व्याकरणासह लिहा. "
        "नमस्कार, देव, मंदिर, प्रार्थना, धन्यवाद, इबादत."
    ),
    "ml": (
        "ഇത് മലയാളം പ്രഭാഷണമാണ്. എല്ലാ വാക്കുകളും ശരിയായ മലയാളം വ്യാകരണത്തോടും "
        "അക്ഷരതെറ്റുകൾ ഇല്ലാതെ എഴുതുക. നമസ്കാരം, ദൈവം, ക്ഷേത്രം, പ്രാർത്ഥന."
    ),
    "kn": (
        "ಇದು ಕನ್ನಡ ಭಾಷಣ. ಎಲ್ಲಾ ಪದಗಳನ್ನು ಸರಿಯಾದ ಕನ್ನಡ ವ್ಯಾಕರಣ ಮತ್ತು ಕಾಗುಣಿತದೊಂದಿಗೆ "
        "ಬರೆಯಿರಿ. ನಮಸ್ಕಾರ, ದೇವರು, ದೇವಾಲಯ, ಪ್ರಾರ್ಥನೆ."
    ),
    "sd": (
        "هيءَ سنڌي تقرير آهي. سمورا لفظ صحيح سنڌي رسم الخط ۽ گراميءَ سان لکو. "
        "اللہ، عبادت، نماز، دعا، صبر، شڪر."
    ),
    "ps": (
        "دا پښتو وینا ده. ټول کلمات د سمو پښتو ژبپوهنې او لیکدود سره ولیکئ. "
        "الله، عبادت، لمونځ، دعا، صبر، شکر."
    ),
    "ms": (
        "Ini adalah ucapan Bahasa Melayu. Tulis semua kata-kata dengan ejaan dan "
        "tatabahasa Melayu yang betul. Allah, solat, ibadah, doa, sabar, syukur."
    ),
    "si": (
        "මෙය සිංහල කථාවකි. සියලු වචන නිවැරදි සිංහල ලිපිය සහ ව්‍යාකරණය සමඟ ලියන්න."
    ),
}

LANGUAGE_CODES: dict[str, str] = {
    "english": "en", "hindi": "hi", "urdu": "ur", "nepali": "ne",
    "tamil": "ta", "telugu": "te", "bengali": "bn", "gujarati": "gu",
    "punjabi": "pa", "marathi": "mr", "kannada": "kn", "malayalam": "ml",
    "sindhi": "sd", "pushto": "ps", "malay": "ms",
}

WHISPER_VRAM_REQUIREMENTS = {
    "tiny": 200, "base": 300, "small": 600, "medium": 1500, "large": 3000,
}
WHISPER_MODEL_SIZE = "base"

CHROMIUM_PROFILES = {
    "chrome": Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/User Data",
    "edge": Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Edge/User Data",
    "brave": Path(os.environ.get("LOCALAPPDATA", "")) / "BraveSoftware/Brave-Browser/User Data",
    "chromium": Path(os.environ.get("LOCALAPPDATA", "")) / "Chromium/User Data",
    "opera": Path(os.environ.get("APPDATA", "")) / "Opera Software/Opera Stable",
    "vivaldi": Path(os.environ.get("LOCALAPPDATA", "")) / "Vivaldi/User Data",
}

HOOK_KEYWORDS = {
    'shocking', 'secret', 'truth', 'revealed', 'exposed', 'incredible', 'insane',
    'crazy', 'unbelievable', 'never', 'always', 'mistake', 'wrong', 'stop',
    'biggest', 'warning', 'must', 'need', 'hack', 'trick', 'strategy', 'proven',
    'rich', 'money', 'free', 'fast', 'easy', 'nobody', 'everyone', 'why', 'how',
    'best', 'worst', 'only', 'actually', 'honestly', 'literally', 'finally',
}
