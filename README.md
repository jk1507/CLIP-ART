# ClipEngine: Local, Unrestricted OpusClip Alternative

ClipEngine is an open-source, local, and unrestricted AI-powered multimedia system that converts long-form YouTube videos (from 5 minutes up to 3+ hours) into viral, vertical 9:16 highlight clips under 30 seconds with active face tracking, word-level karaoke animated subtitles, and -14 LUFS YouTube broadcast-standard audio.

---

## 🌟 Key Features

1. **Long-Video Safe Ingestion**:
   - Downloads audio stream first (`m4a`), minimizing memory and bandwidth.
   - Slices only the target 15s-30s highlight video clips without ever downloading multi-gigabyte video files.

2. **Accurate Word-Level Transcription**:
   - Powered by `faster-whisper` (`CTranslate2`) with automatic CUDA/CPU detection and `int8` quantization fallback.
   - Generates exact word-level start and end timestamps.

3. **Intelligent Highlight Detection & Speech Boundary Snapping**:
   - Semantic chunking evaluated via Gemini API or local Ollama.
   - Strict 15s to 30s duration clamping.
   - **Boundary Snapping**: Clips snap to nearest complete sentence/word ends so speakers are never cut off mid-sentence.

4. **Active Speaker Framing (16:9 to 9:16)**:
   - Tracks speaker face coordinates across frames.
   - Applies an **Exponential Moving Average (EMA)** filter to produce butter-smooth 9:16 vertical crop pans without jitter.

5. **Dynamic Word-Level Karaoke Subtitles**:
   - Generates Advanced SubStation Alpha (`.ass`) with karaoke `\k` tags.
   - Spoken words dynamically highlight in real-time with vibrant colors and bold outlines.

6. **High-Fidelity Rendering**:
   - Normalized audio to **-14 LUFS** via FFmpeg `loudnorm`.
   - Renders crisp **1080x1920** MP4s with GPU acceleration (`h264_nvenc`) and CPU (`libx264 -preset fast -crf 18`) fallback.
   - **Zero Watermarks**.

---

## 🚀 Quickstart

### 1. Configure Environment
Copy `.env.example` to `.env` and set your preferred settings:
```env
LLM_PROVIDER=gemini # or 'ollama'
GEMINI_API_KEY=your_key_here # if using gemini
WHISPER_MODEL=base # tiny, base, small, medium, large-v3
```

### 2. Start the Server & Web Dashboard
```bash
uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

### 3. Run CLI Integration Verification
```bash
python test_pipeline.py
```
This runs the end-to-end integration test validating:
- Crop framing calculations
- ASS dynamic karaoke generation
- FFmpeg 1080x1920 MP4 rendering
- -14 LUFS loudnorm audio normalization
