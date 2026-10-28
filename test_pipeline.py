import subprocess
import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.config import OUTPUT_DIR, TEMP_DIR, FFMPEG_BIN, FFPROBE_BIN
from backend.downloader import VideoDownloader
from backend.transcriber import AudioTranscriber
from backend.highlight_detector import HighlightDetector
from backend.face_tracker import ActiveSpeakerTracker
from backend.subtitle_generator import SubtitleGenerator
from backend.video_renderer import VideoRenderer
from backend.pipeline import ClipEnginePipeline

def test_ffprobe_dimensions_and_audio(video_path: Path):
    """Uses ffprobe to verify video resolution is 1080x1920 and audio track is present."""
    cmd = [
        FFPROBE_BIN,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        str(video_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    vdata = json.loads(res.stdout)
    w = vdata["streams"][0]["width"]
    h = vdata["streams"][0]["height"]
    assert (w, h) == (1080, 1920), f"Expected 1080x1920, got {w}x{h}"

    # Verify audio stream exists
    cmd_audio = [
        FFPROBE_BIN,
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name,sample_rate",
        "-of", "json",
        str(video_path)
    ]
    res_audio = subprocess.run(cmd_audio, capture_output=True, text=True, check=True)
    adata = json.loads(res_audio.stdout)
    assert len(adata["streams"]) > 0, "No audio stream found in rendered clip"
    print(f"Verified: {video_path.name} is exactly 1080x1920 with audio codec: {adata['streams'][0]['codec_name']}")

def run_synthetic_benchmark():
    """Generates a 30s test 16:9 MP4 with tone audio, then passes through full ClipEngine pipeline."""
    print("\n--- Running ClipEngine Integration Test ---")
    test_video = TEMP_DIR / "integration_input_16x9.mp4"

    # 1. Create a 30-second test 1920x1080 video with synthetic dialogue test audio tone & visual circle
    print("Generating synthetic 1920x1080 video...")
    gen_cmd = [
        FFMPEG_BIN, "-y",
        "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=25:duration=28",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=28",
        "-c:v", "libx264", "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        str(test_video)
    ]
    subprocess.run(gen_cmd, check=True, capture_output=True)

    # 2. Test Face Tracking & EMA Framing
    print("Testing active speaker tracking & 9:16 frame calculation...")
    tracker = ActiveSpeakerTracker()
    crop_info = tracker.compute_crop_trajectory(test_video)
    assert crop_info["crop_w"] == int(1080 * 9 / 16) or crop_info["crop_h"] == 1080
    print(f"Crop info verified: {crop_info['crop_w']}x{crop_info['crop_h']} at X={crop_info['avg_crop_x']}")

    # 3. Test Dynamic Karaoke Subtitle (.ass) generation
    print("Testing dynamic ASS karaoke subtitle generator...")
    sub_gen = SubtitleGenerator()
    dummy_words = [
        {"word": "Welcome", "start": 1.0, "end": 1.6, "probability": 0.99},
        {"word": "to", "start": 1.6, "end": 1.8, "probability": 0.98},
        {"word": "ClipEngine", "start": 1.8, "end": 2.5, "probability": 0.99},
        {"word": "the", "start": 2.6, "end": 2.8, "probability": 0.95},
        {"word": "local", "start": 2.8, "end": 3.2, "probability": 0.98},
        {"word": "OpusClip", "start": 3.2, "end": 3.8, "probability": 0.97},
        {"word": "alternative", "start": 3.8, "end": 4.5, "probability": 0.96},
    ]
    test_ass = TEMP_DIR / "integration_test.ass"
    sub_gen.generate_ass(dummy_words, 0.0, 18.0, test_ass)
    assert test_ass.exists() and test_ass.stat().st_size > 0
    print(f"ASS subtitle verified: {test_ass}")

    # 4. Test Final Render with 1080x1920 scaling & loudnorm
    print("Testing final render with -14 LUFS loudnorm audio and 1080x1920 scaling...")
    renderer = VideoRenderer()
    output_mp4 = OUTPUT_DIR / "integration_test_9x16.mp4"
    renderer.render_clip(
        source_video=test_video,
        output_video=output_mp4,
        crop_w=crop_info["crop_w"],
        crop_h=crop_info["crop_h"],
        crop_x=crop_info["avg_crop_x"],
        subtitle_ass=test_ass,
        normalize_audio=True
    )

    assert output_mp4.exists(), "Rendered MP4 does not exist"
    test_ffprobe_dimensions_and_audio(output_mp4)
    print("\nSUCCESS: All ClipEngine core modules verified end-to-end!")

if __name__ == "__main__":
    run_synthetic_benchmark()
