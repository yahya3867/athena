import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_STT_MODEL = os.environ.get("OPENAI_STT_MODEL", os.environ.get("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"))
OPENAI_TRANSCRIBE_MODEL = OPENAI_STT_MODEL
OPENAI_INTENT_MODEL = os.environ.get("OPENAI_INTENT_MODEL", "gpt-5-mini")
OPENAI_CHAT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", "gpt-5.4")
OPENAI_TTS_MODEL = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1.5")
OPENAI_IMAGE_SIZE = os.environ.get("OPENAI_IMAGE_SIZE", "1024x1024")
OPENAI_IMAGE_QUALITY = os.environ.get("OPENAI_IMAGE_QUALITY", "medium")
OPENAI_TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "coral")
OPENAI_TTS_SPEED = float(os.environ.get("OPENAI_TTS_SPEED", "1.12"))
OPENAI_TTS_INSTRUCTIONS = os.environ.get(
    "OPENAI_TTS_INSTRUCTIONS",
    "Speak with a distinctly feminine, elegant, confident voice with a light but noticeable Greek accent. "
    "Sound wise, graceful, deeply knowledgeable, and reassuring, like Athena reimagined as a modern AI guide. "
    "Use clear diction, smooth but slightly brisk pacing, and natural warmth. "
    "Avoid sounding masculine, flat, robotic, childish, theatrical, exaggerated, or overly bubbly.",
)
OPENAI_WEB_SEARCH_TOOL = os.environ.get("OPENAI_WEB_SEARCH_TOOL", "web_search_preview")
OPENAI_ENABLE_WEB_SEARCH = os.environ.get("OPENAI_ENABLE_WEB_SEARCH", "true").lower() in ("1", "true", "yes")
OPENAI_CHAT_INSTRUCTIONS = os.environ.get(
    "OPENAI_CHAT_INSTRUCTIONS",
    "You are Athena, a calm, knowledgeable, highly practical voice assistant for older adults "
    "who want simple help with technology and everyday questions. "
    "If the user asks your name, say your name is Athena. "
    "Reply in the same language the user speaks unless they explicitly ask you to switch languages. "
    "Answer with confident clarity, warmth, and simplicity. "
    "Keep responses short by default: usually 2 to 4 short sentences, or one short paragraph. "
    "Give the direct answer first. "
    "Only add one or two useful follow-up details when they truly help. "
    "Never end your response with a question. "
    "Do not suggest extra options unless the user asks. "
    "If web search is used, silently use it and return a natural spoken-language answer only. "
    "Do not include markdown, URLs, source names, citations, brackets, or parenthetical links in the final answer. "
    "If a request is broad, give the most likely useful concise answer instead of asking the user to narrow it down, "
    "unless clarification is absolutely necessary. "
    "Use web search only when the user asks for current, recent, live, or time-sensitive information, "
    "or when freshness materially improves the answer. "
    "When web search is not needed, answer directly without mentioning search.",
)

AUDIO_SAMPLE_RATE = int(os.environ.get("AUDIO_SAMPLE_RATE", "16000"))
AUDIO_CHANNELS = int(os.environ.get("AUDIO_CHANNELS", "1"))
AUDIO_DEVICE = os.environ.get("AUDIO_DEVICE", "plughw:1,0")
AUDIO_OUTPUT_DEVICE = os.environ.get("AUDIO_OUTPUT_DEVICE", "default")
AUDIO_OUTPUT_CARD = int(os.environ.get("AUDIO_OUTPUT_CARD", "0"))
AUDIO_INPUT_DEVICE = os.environ.get("AUDIO_INPUT_DEVICE", ":0")
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
PLAYBACK_BIN = os.environ.get("PLAYBACK_BIN", "afplay")

CONVERSATION_HISTORY_LENGTH = int(os.environ.get("CONVERSATION_HISTORY_LENGTH", "5"))
SILENCE_RMS_THRESHOLD = float(os.environ.get("SILENCE_RMS_THRESHOLD", "200"))
ENABLE_TTS = os.environ.get("ENABLE_TTS", "true").lower() in ("1", "true", "yes")
LCD_BACKLIGHT = int(os.environ.get("LCD_BACKLIGHT", "70"))
UI_MAX_FPS = int(os.environ.get("UI_MAX_FPS", "4"))
DRY_RUN = not OPENAI_API_KEY

OUTPUT_DIR = BASE_DIR / "output"
IMAGE_OUTPUT_DIR = OUTPUT_DIR / "images"
FIXTURES_DIR = BASE_DIR / "fixtures"
DEFAULT_WAV_PATH = OUTPUT_DIR / "utterance.wav"
DEFAULT_TTS_WAV_PATH = OUTPUT_DIR / "tts_output.wav"


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)


def print_config() -> None:
    print(f"OPENAI_STT_MODEL       = {OPENAI_STT_MODEL}")
    print(f"OPENAI_INTENT_MODEL    = {OPENAI_INTENT_MODEL}")
    print(f"OPENAI_CHAT_MODEL      = {OPENAI_CHAT_MODEL}")
    print(f"OPENAI_TTS_MODEL       = {OPENAI_TTS_MODEL}")
    print(f"OPENAI_IMAGE_MODEL     = {OPENAI_IMAGE_MODEL}")
    print(f"OPENAI_IMAGE_SIZE      = {OPENAI_IMAGE_SIZE}")
    print(f"OPENAI_IMAGE_QUALITY   = {OPENAI_IMAGE_QUALITY}")
    print(f"OPENAI_TTS_VOICE       = {OPENAI_TTS_VOICE}")
    print(f"OPENAI_TTS_SPEED       = {OPENAI_TTS_SPEED}")
    print(f"OPENAI_WEB_SEARCH_TOOL = {OPENAI_WEB_SEARCH_TOOL}")
    print(f"WEB_SEARCH_ENABLED     = {OPENAI_ENABLE_WEB_SEARCH}")
    print(f"AUDIO_DEVICE           = {AUDIO_DEVICE}")
    print(f"AUDIO_SAMPLE_RATE      = {AUDIO_SAMPLE_RATE}")
    print(f"AUDIO_INPUT_DEVICE     = {AUDIO_INPUT_DEVICE}")
    print(f"AUDIO_OUTPUT_DEVICE    = {AUDIO_OUTPUT_DEVICE}")
    print(f"PLAYBACK_BIN           = {PLAYBACK_BIN}")
    print(f"ENABLE_TTS             = {ENABLE_TTS}")
    print(f"LCD_BACKLIGHT          = {LCD_BACKLIGHT}")
    print(f"HISTORY_LENGTH         = {CONVERSATION_HISTORY_LENGTH}")
    print(f"SILENCE_RMS_THRESHOLD  = {SILENCE_RMS_THRESHOLD}")
    print(f"OPENAI_API_KEY set     = {bool(OPENAI_API_KEY)}")
