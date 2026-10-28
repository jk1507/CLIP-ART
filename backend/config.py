import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

# Load .env
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
TEMP_DIR = BASE_DIR / "temp"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Server
PORT = int(os.getenv("PORT", 8000))
HOST = os.getenv("HOST", "127.0.0.1")

# LLM Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

# Whisper Configuration
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")

# Face Tracking
FACE_DETECTION_CONFIDENCE = float(os.getenv("FACE_DETECTION_CONFIDENCE", 0.5))
TRACKING_SMOOTHING_ALPHA = float(os.getenv("TRACKING_SMOOTHING_ALPHA", 0.15))

# Subtitle styling
SUBTITLE_FONT = os.getenv("SUBTITLE_FONT", "Arial")
SUBTITLE_FONT_SIZE = int(os.getenv("SUBTITLE_FONT_SIZE", 28))
SUBTITLE_PRIMARY_COLOR = os.getenv("SUBTITLE_PRIMARY_COLOR", "&H00FFFFFF")
SUBTITLE_HIGHLIGHT_COLOR = os.getenv("SUBTITLE_HIGHLIGHT_COLOR", "&H0000FFFF")
SUBTITLE_OUTLINE_COLOR = os.getenv("SUBTITLE_OUTLINE_COLOR", "&H00000000")
SUBTITLE_OUTLINE_WIDTH = float(os.getenv("SUBTITLE_OUTLINE_WIDTH", 3.0))

# Hardware
HARDWARE_ACCELERATION = os.getenv("HARDWARE_ACCELERATION", "auto").lower()

def resolve_ffmpeg_binaries():
    """Finds ffmpeg and ffprobe in PATH or common Windows installation directories."""
    # First check if system PATH has it
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")

    if not ffmpeg_path:
        winget_gyan = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe" / "ffmpeg-9.0.2-full_build" / "bin"
        if (winget_gyan / "ffmpeg.exe").exists():
            ffmpeg_path = str(winget_gyan / "ffmpeg.exe")
            ffprobe_path = str(winget_gyan / "ffprobe.exe")

    if not ffmpeg_path:
        # Search common WinGet / Chocolatey / custom paths
        candidate_dirs = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages",
            Path(r"C:\Program Files\ffmpeg\bin"),
            Path(r"C:\ffmpeg\bin"),
            Path(r"C:\ProgramData\chocolatey\bin")
        ]
        for cdir in candidate_dirs:
            if cdir.exists():
                found = list(cdir.glob("**/ffmpeg.exe"))
                if found:
                    ffmpeg_path = str(found[0])
                    probe_match = found[0].parent / "ffprobe.exe"
                    if probe_match.exists():
                        ffprobe_path = str(probe_match)
                    break
    
    ffmpeg_dir = str(Path(ffmpeg_path).parent) if ffmpeg_path else ""
    if ffmpeg_dir and ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

    return ffmpeg_path or "ffmpeg", ffprobe_path or "ffprobe"

FFMPEG_BIN, FFPROBE_BIN = resolve_ffmpeg_binaries()
FFMPEG_DIR = str(Path(FFMPEG_BIN).parent) if Path(FFMPEG_BIN).is_file() else None
