import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import torch

logger = logging.getLogger("clipengine.transcriber")

class AudioTranscriber:
    """
    Transcribes audio using faster-whisper with word-level timestamps.
    Falls back smoothly from CUDA to CPU with compute_type='int8'.
    """

    def __init__(self, model_size: Optional[str] = None, compute_type: str = "int8", device: str = "auto"):
        # Default to 'tiny' or 'base' for jet speed, configurable
        self.model_size = model_size or os.getenv("WHISPER_MODEL", "base")
        self.compute_type = compute_type
        
        if device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device
            
        # If running on CPU, int8 is the most efficient compute_type
        if self.device == "cpu" and self.compute_type not in ["int8", "float32"]:
            self.compute_type = "int8"
            
        self._model = None

    def _load_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            import os
            # Use max CPU threads for jet-speed transcription
            threads = min(16, os.cpu_count() or 4)
            logger.info("Loading faster-whisper '%s' on %s (%s, cpu_threads=%d)...", self.model_size, self.device, self.compute_type, threads)
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=threads,
                num_workers=2
            )
        return self._model

    def transcribe(self, audio_path: Path) -> Dict[str, Any]:
        """
        Transcribes the audio file and returns segments with full word-level timestamps.
        """
        model = self._load_model()
        logger.info("Starting transcription for %s", audio_path)

        segments_generator, info = model.transcribe(
            str(audio_path),
            word_timestamps=True,
            vad_filter=True, # Voice activity detection to ignore silence
            vad_parameters=dict(min_silence_duration_ms=500)
        )

        all_words = []
        sentences = []

        for segment in segments_generator:
            seg_words = []
            if segment.words:
                for w in segment.words:
                    word_obj = {
                        "word": w.word.strip(),
                        "start": round(w.start, 3),
                        "end": round(w.end, 3),
                        "probability": round(w.probability, 3)
                    }
                    if word_obj["word"]:
                        all_words.append(word_obj)
                        seg_words.append(word_obj)

            sentences.append({
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "text": segment.text.strip(),
                "words": seg_words
            })

        logger.info("Transcription complete: %d sentences, %d total words detected (language: %s)",
                    len(sentences), len(all_words), info.language)

        return {
            "language": info.language,
            "language_probability": round(info.language_probability, 3),
            "duration": round(info.duration, 2),
            "sentences": sentences,
            "words": all_words
        }
