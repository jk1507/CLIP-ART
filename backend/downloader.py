import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import yt_dlp
from backend.config import TEMP_DIR, FFMPEG_BIN, FFMPEG_DIR

logger = logging.getLogger("clipengine.downloader")

class VideoDownloader:
    """
    Long-video safe downloader:
    1. Downloads audio first (low memory, low bandwidth) for transcription & scoring.
    2. Downloads target video clip section (e.g. 15-30s) directly without downloading the multi-hour video.
    """

    def __init__(self, temp_dir: Optional[Path] = None):
        self.temp_dir = temp_dir or TEMP_DIR

    def get_video_info(self, url: str) -> Dict[str, Any]:
        """Fetches video metadata without downloading video payload."""
        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "id": info.get("id"),
                "title": info.get("title"),
                "duration": info.get("duration", 0),
                "channel": info.get("uploader"),
                "thumbnail": info.get("thumbnail"),
                "subtitles": info.get("subtitles", {}),
                "automatic_captions": info.get("automatic_captions", {}),
            }

    def fetch_instant_captions(self, video_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Instant speed accelerator:
        If YouTube already has English captions (manual or auto-generated with word timings),
        fetches and parses them in 1-2 seconds without running heavy local Whisper models!
        """
        import urllib.request
        import json

        subs = video_info.get("subtitles", {}).get("en", [])
        if not subs:
            subs = video_info.get("automatic_captions", {}).get("en", [])

        if not subs:
            return None

        # Look for json3 format first (contains word-level segs and ms timestamps)
        json3_urls = [s["url"] for s in subs if s.get("ext") == "json3"]
        if not json3_urls:
            return None

        try:
            req = urllib.request.urlopen(json3_urls[0], timeout=10)
            data = json.loads(req.read().decode("utf-8"))
            events = data.get("events", [])
            
            sentences = []
            words = []
            
            for ev in events:
                if "segs" not in ev:
                    continue
                start_ms = ev.get("tStartMs", 0)
                dur_ms = ev.get("dDurationMs", 0)
                end_ms = start_ms + dur_ms

                seg_text_parts = []
                current_time = start_ms / 1000.0

                for seg in ev["segs"]:
                    text = seg.get("utf8", "").strip()
                    if not text or text == "\u200b":
                        continue
                    seg_text_parts.append(text)
                    t_offset = seg.get("tOffsetMs", 0)
                    w_start = round((start_ms + t_offset) / 1000.0, 3)
                    w_end = round(w_start + 0.35, 3) # estimation if end not discrete
                    words.append({
                        "word": text,
                        "start": w_start,
                        "end": w_end,
                        "probability": 0.99
                    })

                full_sentence = " ".join(seg_text_parts).strip()
                if full_sentence:
                    sentences.append({
                        "start": round(start_ms / 1000.0, 3),
                        "end": round(end_ms / 1000.0, 3),
                        "text": full_sentence,
                        "words": []
                    })

            if len(words) > 10:
                logger.info("Found %d words from instant YouTube captions in seconds!", len(words))
                return {
                    "language": "en",
                    "language_probability": 0.99,
                    "duration": video_info.get("duration", 0),
                    "sentences": sentences,
                    "words": words
                }
        except Exception as e:
            logger.warning("Could not parse instant YouTube captions (%s), falling back to Whisper.", e)

        return None

    def download_audio_stream(self, url: str, video_id: str) -> Path:
        """
        Downloads ONLY the audio stream formatted as M4A or WAV for fast Whisper transcription.
        Safe for 3+ hour videos.
        """
        out_template = str(self.temp_dir / f"{video_id}_audio.%(ext)s")
        expected_m4a = self.temp_dir / f"{video_id}_audio.m4a"
        if expected_m4a.exists():
            logger.info("Using cached audio: %s", expected_m4a)
            return expected_m4a

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": out_template,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "192",
            }],
            "ffmpeg_location": FFMPEG_BIN if FFMPEG_BIN != "ffmpeg" else None,
            "quiet": False,
            "no_warnings": True,
        }
        
        # Remove None values
        ydl_opts = {k: v for k, v in ydl_opts.items() if v is not None}

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if not expected_m4a.exists():
            # Check if downloaded as another extension
            matches = list(self.temp_dir.glob(f"{video_id}_audio.*"))
            if matches:
                return matches[0]
            raise FileNotFoundError(f"Failed to locate downloaded audio for {video_id}")

        return expected_m4a

    def download_video_segment(self, url: str, clip_id: str, start_time: float, end_time: float) -> Path:
        """
        Downloads or slices ONLY the selected duration bounds directly.
        Prevents full video download for long streams.
        """
        out_file = self.temp_dir / f"{clip_id}_raw.mp4"
        if out_file.exists():
            return out_file

        duration = end_time - start_time
        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": str(out_file),
            "download_ranges": yt_dlp.utils.download_range_func(None, [(start_time, end_time)]),
            "force_keyframes_at_cuts": True,
            "ffmpeg_location": FFMPEG_DIR or FFMPEG_BIN,
            "quiet": True,
            "no_warnings": True,
        }
        ydl_opts = {k: v for k, v in ydl_opts.items() if v is not None}

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if not out_file.exists():
            matches = list(self.temp_dir.glob(f"{clip_id}_raw.*"))
            if matches:
                return matches[0]
            raise FileNotFoundError(f"Failed to slice video segment for {clip_id}")

        return out_file
