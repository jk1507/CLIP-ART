import subprocess
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from backend.config import FFMPEG_BIN, FFPROBE_BIN, HARDWARE_ACCELERATION

logger = logging.getLogger("clipengine.renderer")

class VideoRenderer:
    """
    Renders the final 9:16 vertical MP4:
    - Crops using smooth face-tracked coordinates.
    - Scales to exactly 1080x1920.
    - Hardcodes animated dynamic karaoke .ass subtitles.
    - Normalizes audio to -14 LUFS standard YouTube broadcast level.
    - Supports NVENC GPU acceleration with CPU fallback.
    """

    def __init__(self, ffmpeg_bin: str = FFMPEG_BIN, ffprobe_bin: str = FFPROBE_BIN):
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin
        self._check_nvenc()

    def _check_nvenc(self):
        """Checks if h264_nvenc encoder is functional on this system."""
        self.use_nvenc = False
        if HARDWARE_ACCELERATION in ["auto", "cuda", "nvenc"]:
            try:
                cmd = [self.ffmpeg_bin, "-hide_banner", "-encoders"]
                res = subprocess.run(cmd, capture_output=True, text=True, check=True)
                if "h264_nvenc" in res.stdout:
                    # Test a 1-frame dummy encode
                    test_cmd = [
                        self.ffmpeg_bin, "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.1",
                        "-c:v", "h264_nvenc", "-f", "null", "-"
                    ]
                    test_res = subprocess.run(test_cmd, capture_output=True)
                    if test_res.returncode == 0:
                        self.use_nvenc = True
                        logger.info("NVIDIA NVENC hardware acceleration enabled.")
            except Exception as e:
                logger.debug("NVENC test failed: %s", e)

        if not self.use_nvenc:
            logger.info("Using high-performance CPU libx264 encoder.")

    def render_clip(self,
                    source_video: Path,
                    output_video: Path,
                    crop_w: int,
                    crop_h: int,
                    crop_x: int,
                    crop_y: int = 0,
                    subtitle_ass: Optional[Path] = None,
                    normalize_audio: bool = True) -> Path:
        """
        Executes FFmpeg pipeline:
        1. Crop 9:16 region: crop=crop_w:crop_h:crop_x:crop_y
        2. Scale to 1080:1920
        3. Burn ASS subtitles (if provided)
        4. Apply loudnorm audio filter: loudnorm=I=-14:LRA=11:TP=-1.5
        """
        output_video.parent.mkdir(parents=True, exist_ok=True)

        video_filters = [
            f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
            "scale=1080:1920:flags=lanczos"
        ]

        if subtitle_ass and subtitle_ass.exists():
            # Escape path for FFmpeg filter on Windows
            ass_escaped = str(subtitle_ass).replace("\\", "/").replace(":", "\\:")
            video_filters.append(f"ass='{ass_escaped}'")

        vf_str = ",".join(video_filters)

        audio_filters = []
        if normalize_audio:
            # YouTube standard broadcast level (-14 LUFS)
            audio_filters.append("loudnorm=I=-14:LRA=11:TP=-1.5")

        cmd = [
            self.ffmpeg_bin,
            "-y",
            "-i", str(source_video),
            "-vf", vf_str,
        ]

        if audio_filters:
            cmd.extend(["-af", ",".join(audio_filters)])

        if self.use_nvenc:
            cmd.extend([
                "-c:v", "h264_nvenc",
                "-preset", "p4",
                "-b:v", "6000k",
                "-maxrate", "8000k",
                "-bufsize", "12000k",
                "-c:a", "aac",
                "-b:a", "192k"
            ])
        else:
            import os
            cpu_threads = str(min(16, os.cpu_count() or 4))
            cmd.extend([
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-threads", cpu_threads,
                "-crf", "20",
                "-c:a", "aac",
                "-b:a", "192k"
            ])

        cmd.extend([
            "-movflags", "+faststart",
            "-pix_fmt", "yuv420p",
            str(output_video)
        ])

        logger.info("Executing FFmpeg render command:\n%s", " ".join(cmd))
        process = subprocess.run(cmd, capture_output=True, text=True)
        if process.returncode != 0:
            logger.error("FFmpeg render failed:\n%s", process.stderr)
            raise RuntimeError(f"FFmpeg error: {process.stderr[-500:]}")

        logger.info("Successfully rendered clip to %s", output_video)
        return output_video
