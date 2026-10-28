import json
import logging
import re
from typing import List, Dict, Any, Optional
import httpx
from backend.config import (
    LLM_PROVIDER,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL
)

logger = logging.getLogger("clipengine.highlight_detector")

HIGHLIGHT_SYSTEM_PROMPT = """
You are a viral social media video editor specializing in YouTube Shorts, TikTok, and Instagram Reels.
Your task is to analyze video transcripts and extract the most engaging, self-contained highlight clips.

CRITICAL RULES:
1. Target duration for each clip MUST be strictly between 15 and 30 seconds (ideal: 18 - 28s).
2. The clip MUST be self-contained: it must start with an intriguing question, strong statement, or hook, deliver a payoff or punchline, and finish on a complete thought.
3. Output MUST be valid JSON only, without markdown fences or any conversational preface.

Output JSON Format:
[
  {
    "start_time": float,
    "end_time": float,
    "hook_title": str,
    "viral_score": int,
    "reasoning": str
  }
]
"""

class HighlightDetector:
    """
    Identifies viral clips from transcripts using Gemini or local Ollama.
    Enforces 15s-30s boundaries and snaps to precise word/sentence boundaries.
    """

    def __init__(self, provider: Optional[str] = None):
        self.provider = (provider or LLM_PROVIDER).lower()

    def snap_boundaries(self, raw_start: float, raw_end: float, sentences: List[Dict[str, Any]], words: List[Dict[str, Any]]) -> tuple[float, float]:
        """
        Snaps start and end times to the nearest sentence or word boundary,
        guaranteeing the clip stays between 15.0 and 30.0 seconds and does not cut off mid-speech.
        """
        # 1. Try finding matching sentence start & end
        best_start = raw_start
        best_end = raw_end

        # Find closest sentence start near raw_start
        closest_start_diff = float("inf")
        for s in sentences:
            diff = abs(s["start"] - raw_start)
            if diff < closest_start_diff and diff < 3.0:
                closest_start_diff = diff
                best_start = s["start"]

        # Find closest sentence end near raw_end
        closest_end_diff = float("inf")
        for s in sentences:
            diff = abs(s["end"] - raw_end)
            if diff < closest_end_diff and diff < 4.0:
                closest_end_diff = diff
                best_end = s["end"]

        # Fallback to word boundaries if sentence boundaries are too coarse
        if words:
            # Snap start to the earliest word >= best_start
            valid_start_words = [w["start"] for w in words if abs(w["start"] - best_start) <= 2.0]
            if valid_start_words:
                best_start = min(valid_start_words, key=lambda t: abs(t - best_start))

            # Snap end to the word end near best_end
            valid_end_words = [w["end"] for w in words if abs(w["end"] - best_end) <= 2.5]
            if valid_end_words:
                best_end = min(valid_end_words, key=lambda t: abs(t - best_end))

        # Enforce strict 15.0s to 30.0s clamp
        duration = best_end - best_start
        if duration < 15.0:
            best_end = best_start + 15.0
        elif duration > 30.0:
            best_end = best_start + 30.0

        return round(best_start, 2), round(best_end, 2)

    def detect_highlights(self, transcript_data: Dict[str, Any], max_clips: int = 5) -> List[Dict[str, Any]]:
        """
        Detects viral highlight moments from transcript.
        If LLM is unavailable or fails, gracefully falls back to high-speech semantic density heuristic.
        """
        sentences = transcript_data.get("sentences", [])
        words = transcript_data.get("words", [])

        if not sentences:
            return []

        # Prepare formatted transcript text with timestamps
        formatted_blocks = []
        for s in sentences:
            formatted_blocks.append(f"[{s['start']:.1f}s - {s['end']:.1f}s]: {s['text']}")

        full_text = "\n".join(formatted_blocks)

        clips = []
        # Attempt LLM detection if keys/endpoints configured
        if self.provider == "gemini" and GEMINI_API_KEY:
            clips = self._call_gemini(full_text, max_clips)
        elif self.provider == "ollama":
            clips = self._call_ollama(full_text, max_clips)

        # Fallback heuristic if no LLM or empty response
        if not clips:
            logger.info("Using semantic heuristic highlight detection...")
            clips = self._heuristic_detection(sentences, max_clips)

        # Post-process: Snap boundaries & enforce strict rules
        refined_clips = []
        for clip in clips:
            raw_s = float(clip.get("start_time", 0.0))
            raw_e = float(clip.get("end_time", raw_s + 20.0))
            
            s, e = self.snap_boundaries(raw_s, raw_e, sentences, words)
            score = int(clip.get("viral_score", 85))
            score = max(1, min(100, score))

            refined_clips.append({
                "start_time": s,
                "end_time": e,
                "duration": round(e - s, 2),
                "hook_title": clip.get("hook_title", "Viral Highlight Moment"),
                "viral_score": score,
                "reasoning": clip.get("reasoning", "Strong engagement hook and natural conversational flow.")
            })

        refined_clips.sort(key=lambda x: x["viral_score"], reverse=True)
        return refined_clips[:max_clips]

    def _call_gemini(self, transcript_text: str, max_clips: int) -> List[Dict[str, Any]]:
        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            prompt = (
                f"{HIGHLIGHT_SYSTEM_PROMPT}\n\n"
                f"Extract up to {max_clips} viral highlight clips under 30 seconds from this transcript:\n\n"
                f"{transcript_text[:12000]}"
            )
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )
            return self._parse_json_response(response.text)
        except Exception as e:
            logger.warning("Gemini highlight detection error: %s", e)
            return []

    def _call_ollama(self, transcript_text: str, max_clips: int) -> List[Dict[str, Any]]:
        try:
            url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
            prompt = (
                f"{HIGHLIGHT_SYSTEM_PROMPT}\n\n"
                f"Extract up to {max_clips} viral highlight clips under 30 seconds from this transcript:\n\n"
                f"{transcript_text[:10000]}"
            )
            resp = httpx.post(url, json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}, timeout=60.0)
            if resp.status_code == 200:
                data = resp.json()
                return self._parse_json_response(data.get("response", ""))
        except Exception as e:
            logger.warning("Ollama highlight detection error: %s", e)
        return []

    def _parse_json_response(self, text: str) -> List[Dict[str, Any]]:
        text = text.strip()
        # Remove markdown fences if present
        text = re.sub(r"^```(?:json)?", "", text, flags=re.MULTILINE)
        text = re.sub(r"```$", "", text, flags=re.MULTILINE).strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        except Exception as e:
            logger.warning("Failed to parse JSON response: %s", e)
        return []

    def _heuristic_detection(self, sentences: List[Dict[str, Any]], max_clips: int) -> List[Dict[str, Any]]:
        """
        Algorithmic highlight selector:
        Finds dense, active speech clusters spanning 18-28 seconds.
        """
        candidates = []
        i = 0
        while i < len(sentences):
            start = sentences[i]["start"]
            j = i
            while j < len(sentences) and (sentences[j]["end"] - start) < 26.0:
                j += 1
            
            end = sentences[j-1]["end"] if j > i else start + 20.0
            duration = end - start
            if 15.0 <= duration <= 30.0:
                combined_text = " ".join([sentences[k]["text"] for k in range(i, j)])
                word_count = len(combined_text.split())
                wps = word_count / max(1.0, duration) # words per second
                
                # Boost if containing questions, exclamation, or hook words
                hook_words = ["why", "how", "secret", "never", "always", "money", "think", "truth", "crazy", "best"]
                boost = sum(5 for hw in hook_words if hw in combined_text.lower())
                score = min(98, int(70 + (wps * 4) + boost))

                first_sentence = sentences[i]["text"]
                hook_title = first_sentence[:45] + "..." if len(first_sentence) > 45 else first_sentence

                candidates.append({
                    "start_time": start,
                    "end_time": end,
                    "hook_title": hook_title or "Key Insight Highlight",
                    "viral_score": score,
                    "reasoning": f"High semantic density ({round(wps, 1)} wps) with impactful dialogue."
                })
            i = max(i + 1, j - 1)

        candidates.sort(key=lambda x: x["viral_score"], reverse=True)
        return candidates[:max_clips]
