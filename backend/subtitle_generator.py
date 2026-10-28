import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from backend.config import (
    SUBTITLE_FONT,
    SUBTITLE_FONT_SIZE,
    SUBTITLE_PRIMARY_COLOR,
    SUBTITLE_HIGHLIGHT_COLOR,
    SUBTITLE_OUTLINE_COLOR,
    SUBTITLE_OUTLINE_WIDTH
)

logger = logging.getLogger("clipengine.subtitles")

def format_ass_timestamp(seconds: float) -> str:
    """Formats seconds into ASS timestamp format: H:MM:SS.cs"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

class SubtitleGenerator:
    """
    Generates dynamic, word-level animated Advanced SubStation Alpha (.ass) subtitles.
    Supports viral karaoke styling (\\k tags), glow, outlines, and bold typography.
    """

    def __init__(self,
                 font_name: str = SUBTITLE_FONT,
                 font_size: int = SUBTITLE_FONT_SIZE,
                 primary_color: str = SUBTITLE_PRIMARY_COLOR,
                 highlight_color: str = SUBTITLE_HIGHLIGHT_COLOR,
                 outline_color: str = SUBTITLE_OUTLINE_COLOR,
                 outline_width: float = SUBTITLE_OUTLINE_WIDTH):
        self.font_name = font_name
        self.font_size = font_size
        self.primary_color = primary_color       # Default word color (e.g. Pure White)
        self.highlight_color = highlight_color   # Spoken word highlight (e.g. Vibrant Yellow &H0000FFFF)
        self.outline_color = outline_color       # Shadow / outline (Pure Black &H00000000)
        self.outline_width = outline_width

    def generate_ass(self,
                     words: List[Dict[str, Any]],
                     clip_start: float,
                     clip_end: float,
                     output_ass_path: Path,
                     words_per_batch: int = 4) -> Path:
        """
        Creates an .ass script specifically timed for [clip_start, clip_end].
        Timestamps are shifted so that clip_start becomes 00:00:00.00.
        """
        # Filter words within this clip window
        clip_words = []
        for w in words:
            if w["end"] > clip_start and w["start"] < clip_end:
                shifted_start = max(0.0, w["start"] - clip_start)
                shifted_end = min(clip_end - clip_start, w["end"] - clip_start)
                if shifted_end > shifted_start:
                    clip_words.append({
                        "word": w["word"],
                        "start": shifted_start,
                        "end": shifted_end,
                        "duration_cs": max(1, int(round((shifted_end - shifted_start) * 100)))
                    })

        ass_header = f"""[Script Info]
Title: ClipEngine Dynamic Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ViralDefault,{self.font_name},72,{self.primary_color},{self.highlight_color},{self.outline_color},&H80000000,-1,0,0,0,100,100,2,0,1,6,3,2,60,60,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        dialogue_lines = []

        # Group words into short dynamic bursts (3-5 words) for viral mobile retention
        batches = []
        for i in range(0, len(clip_words), words_per_batch):
            batches.append(clip_words[i:i + words_per_batch])

        for batch in batches:
            if not batch:
                continue
            line_start = batch[0]["start"]
            line_end = batch[-1]["end"]

            start_str = format_ass_timestamp(line_start)
            end_str = format_ass_timestamp(line_end)

            # Build karaoke payload: {\k<cs>}Word {\k<cs>}Word
            karaoke_chunks = []
            for w in batch:
                dur = w["duration_cs"]
                text = w["word"].upper()
                karaoke_chunks.append(f"{{\\k{dur}}}{text}")

            karaoke_text = " ".join(karaoke_chunks)
            dialogue = f"Dialogue: 0,{start_str},{end_str},ViralDefault,,0,0,0,,{karaoke_text}"
            dialogue_lines.append(dialogue)

        output_ass_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_ass_path, "w", encoding="utf-8") as f:
            f.write(ass_header + "\n".join(dialogue_lines) + "\n")

        logger.info("Generated ASS karaoke subtitle file: %s (%d dialogue lines)", output_ass_path, len(dialogue_lines))
        return output_ass_path
