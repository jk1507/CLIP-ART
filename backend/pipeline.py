import os
import json
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from backend.config import TEMP_DIR, OUTPUT_DIR
from backend.downloader import VideoDownloader
from backend.transcriber import AudioTranscriber
from backend.highlight_detector import HighlightDetector
from backend.face_tracker import ActiveSpeakerTracker
from backend.subtitle_generator import SubtitleGenerator
from backend.video_renderer import VideoRenderer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("clipengine.pipeline")

class ClipEnginePipeline:
    """
    Master end-to-end pipeline:
    1. Stream Ingestion (Audio first)
    2. Transcription (faster-whisper word-level)
    3. Highlight Detection (LLM + Sentence Snap)
    4. Target Video Segment Download
    5. Active Speaker Tracking (MediaPipe/OpenCV + EMA)
    6. Dynamic Subtitle Generation (.ass karaoke)
    7. 1080x1920 MP4 Render (-14 LUFS audio)
    """

    def __init__(self):
        self.downloader = VideoDownloader()
        self.transcriber = AudioTranscriber()
        self.highlight_detector = HighlightDetector()
        self.face_tracker = ActiveSpeakerTracker()
        self.subtitle_gen = SubtitleGenerator()
        self.renderer = VideoRenderer()

    def run(self, youtube_url: str, max_clips: int = 3, progress_callback: Optional[Callable[[str, int], None]] = None) -> Dict[str, Any]:
        job_id = str(uuid.uuid4())[:8]

        def update_progress(msg: str, percent: int):
            logger.info("[%s%%] %s", percent, msg)
            if progress_callback:
                progress_callback(msg, percent)

        # 1. Inspect metadata
        update_progress("Inspecting YouTube video metadata...", 5)
        video_info = self.downloader.get_video_info(youtube_url)
        video_id = video_info.get("id") or job_id
        update_progress(f"Found: {video_info['title']} ({video_info['duration']}s)", 10)

        # 2. Download audio stream only
        update_progress("Extracting audio stream for fast processing...", 15)
        audio_path = self.downloader.download_audio_stream(youtube_url, video_id)

        # 3. Transcribe audio with word-level timestamps
        update_progress("Transcribing audio with faster-whisper...", 30)
        transcript = self.transcriber.transcribe(audio_path)

        # Save transcript cache
        transcript_cache = TEMP_DIR / f"{video_id}_transcript.json"
        with open(transcript_cache, "w", encoding="utf-8") as f:
            json.dump(transcript, f, indent=2)

        # 4. Highlight detection & sentence boundary snapping
        update_progress("Detecting viral highlights and snapping speech boundaries...", 45)
        highlights = self.highlight_detector.detect_highlights(transcript, max_clips=max_clips)
        if not highlights:
            raise RuntimeError("No highlight clips could be extracted from transcript.")

        update_progress(f"Selected {len(highlights)} viral highlight clip(s). Rendering...", 50)

        generated_clips = []
        clip_progress_weight = 45 / len(highlights)

        for idx, clip in enumerate(highlights, 1):
            clip_id = f"{video_id}_clip_{idx}"
            s = clip["start_time"]
            e = clip["end_time"]
            base_percent = int(50 + ((idx - 1) * clip_progress_weight))

            update_progress(f"Clip {idx}/{len(highlights)}: Downloading target video slice ({s:.1f}s - {e:.1f}s)...", base_percent)
            raw_clip_video = self.downloader.download_video_segment(youtube_url, clip_id, s, e)

            update_progress(f"Clip {idx}/{len(highlights)}: Computing face tracking & 9:16 crop framing...", base_percent + 3)
            tracking_info = self.face_tracker.compute_crop_trajectory(raw_clip_video)

            update_progress(f"Clip {idx}/{len(highlights)}: Generating dynamic karaoke subtitles...", base_percent + 6)
            ass_path = TEMP_DIR / f"{clip_id}.ass"
            self.subtitle_gen.generate_ass(transcript["words"], s, e, ass_path)

            output_mp4 = OUTPUT_DIR / f"{clip_id}_9x16.mp4"
            update_progress(f"Clip {idx}/{len(highlights)}: Rendering final 1080x1920 MP4 with -14 LUFS audio...", base_percent + 9)

            self.renderer.render_clip(
                source_video=raw_clip_video,
                output_video=output_mp4,
                crop_w=tracking_info["crop_w"],
                crop_h=tracking_info["crop_h"],
                crop_x=tracking_info["avg_crop_x"],
                crop_y=0,
                subtitle_ass=ass_path,
                normalize_audio=True
            )

            generated_clips.append({
                "clip_id": clip_id,
                "hook_title": clip["hook_title"],
                "viral_score": clip["viral_score"],
                "reasoning": clip["reasoning"],
                "start_time": s,
                "end_time": e,
                "duration": clip["duration"],
                "output_video_path": str(output_mp4),
                "output_filename": output_mp4.name,
                "subtitle_path": str(ass_path)
            })

        update_progress("All clips successfully generated and verified!", 100)

        return {
            "video_id": video_id,
            "title": video_info["title"],
            "total_clips": len(generated_clips),
            "clips": generated_clips
        }

    def analyze_and_detect(self, youtube_url: str, max_clips: int = 5, progress_callback: Optional[Callable[[str, int], None]] = None) -> Dict[str, Any]:
        """
        Phase 1 (Jet-Speed): Only downloads audio, transcribes with multi-threaded Whisper,
        and scores viral highlights. Returns in seconds!
        """
        def update_progress(msg: str, percent: int):
            logger.info("[%s%%] %s", percent, msg)
            if progress_callback:
                progress_callback(msg, percent)

        update_progress("Inspecting video metadata and instant captions...", 15)
        video_info = self.downloader.get_video_info(youtube_url)
        video_id = video_info.get("id") or str(uuid.uuid4())[:8]

        # FAST PATH: Check if YouTube already has word-level captions
        transcript = self.downloader.fetch_instant_captions(video_info)
        if transcript:
            update_progress("⚡ Instant YouTube word timestamps detected! Skipping audio download...", 70)
        else:
            update_progress("Streaming audio track at high speed...", 35)
            audio_path = self.downloader.download_audio_stream(youtube_url, video_id)

            update_progress("Transcribing with multi-threaded faster-whisper...", 60)
            transcript = self.transcriber.transcribe(audio_path)

        update_progress("Scoring viral highlights and snapping sentences...", 85)
        highlights = self.highlight_detector.detect_highlights(transcript, max_clips=max_clips)

        update_progress("Highlights ready! Choose your clip to render.", 100)
        return {
            "video_id": video_id,
            "title": video_info["title"],
            "youtube_url": youtube_url,
            "highlights": highlights,
            "words": transcript.get("words", [])
        }

    def render_single_highlight(self,
                                youtube_url: str,
                                video_id: str,
                                clip_idx: int,
                                start_time: float,
                                end_time: float,
                                hook_title: str,
                                viral_score: int,
                                reasoning: str,
                                words: List[Dict[str, Any]],
                                progress_callback: Optional[Callable[[str, int], None]] = None) -> Dict[str, Any]:
        """
        Phase 2 (On-Demand User Choice):
        Only downloads and renders the ONE clip the user actually chooses to download.
        """
        def update_progress(msg: str, percent: int):
            logger.info("[%s%%] %s", percent, msg)
            if progress_callback:
                progress_callback(msg, percent)

        clip_id = f"{video_id}_clip_{clip_idx}"
        output_mp4 = OUTPUT_DIR / f"{clip_id}_9x16.mp4"

        # If already rendered, return immediately
        if output_mp4.exists():
            update_progress("Clip already cached and ready!", 100)
            return {
                "clip_id": clip_id,
                "hook_title": hook_title,
                "viral_score": viral_score,
                "reasoning": reasoning,
                "start_time": start_time,
                "end_time": end_time,
                "duration": round(end_time - start_time, 2),
                "output_video_path": str(output_mp4),
                "output_filename": output_mp4.name,
                "download_url": f"/output_files/{output_mp4.name}"
            }

        update_progress(f"Downloading target video slice ({start_time:.1f}s - {end_time:.1f}s)...", 25)
        raw_clip = self.downloader.download_video_segment(youtube_url, clip_id, start_time, end_time)

        update_progress("Computing fast 9:16 face-tracking...", 50)
        tracking_info = self.face_tracker.compute_crop_trajectory(raw_clip, sample_fps=4)

        update_progress("Generating dynamic karaoke subtitles...", 70)
        ass_path = TEMP_DIR / f"{clip_id}.ass"
        self.subtitle_gen.generate_ass(words, start_time, end_time, ass_path)

        update_progress("Rendering 1080x1920 MP4 with -14 LUFS audio...", 85)
        self.renderer.render_clip(
            source_video=raw_clip,
            output_video=output_mp4,
            crop_w=tracking_info["crop_w"],
            crop_h=tracking_info["crop_h"],
            crop_x=tracking_info["avg_crop_x"],
            crop_y=0,
            subtitle_ass=ass_path,
            normalize_audio=True
        )

        update_progress("Clip rendered and ready for instant download!", 100)

        return {
            "clip_id": clip_id,
            "hook_title": hook_title,
            "viral_score": viral_score,
            "reasoning": reasoning,
            "start_time": start_time,
            "end_time": end_time,
            "duration": round(end_time - start_time, 2),
            "output_video_path": str(output_mp4),
            "output_filename": output_mp4.name,
            "download_url": f"/output_files/{output_mp4.name}"
        }
