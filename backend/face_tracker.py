import cv2
import numpy as np
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional

logger = logging.getLogger("clipengine.face_tracker")

class ActiveSpeakerTracker:
    """
    Detects faces in video frames, tracks active horizontal speaker positions,
    and applies an Exponential Moving Average (EMA) to produce smooth 9:16 crop box coordinates.
    """

    def __init__(self, smoothing_alpha: float = 0.12, min_confidence: float = 0.5):
        self.alpha = smoothing_alpha
        self.min_confidence = min_confidence
        self.face_detector = None
        self._init_detector()

    def _init_detector(self):
        """Initializes Face detector with local cascade or MediaPipe Tasks."""
        base_dir = Path(__file__).resolve().parent
        model_xml = base_dir / "models" / "haarcascade_frontalface_default.xml"

        self.cascade = None
        if model_xml.exists():
            self.cascade = cv2.CascadeClassifier(str(model_xml))
            if not self.cascade.empty():
                self.detector_type = "opencv"
                logger.info("Loaded Face Detection model from %s", model_xml)
                return

        cascade_sys = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        self.cascade = cv2.CascadeClassifier(cascade_sys)
        if not self.cascade.empty():
            self.detector_type = "opencv"
        else:
            self.detector_type = "center_fallback"
            logger.warning("No face detector model loaded, defaulting to center framing fallback.")

    def compute_crop_trajectory(self, video_path: Path, sample_fps: int = 4) -> Dict[str, Any]:
        """
        Samples video at sample_fps (default 4 fps is plenty for smooth 20s clip camera movements)
        and downscales frames during detection for 10x faster processing.
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ValueError(f"Cannot open video for tracking: {video_path}")

        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

        # Target 9:16 crop width for standard 16:9 source
        crop_w = int(src_h * (9.0 / 16.0))
        if crop_w % 2 != 0:
            crop_w -= 1
        crop_h = src_h

        # Default center crop
        default_x = max(0, (src_w - crop_w) // 2)
        smoothed_x = float(default_x)

        step_frames = max(1, int(total_fps / sample_fps))
        trajectory = []
        detected_xs = []

        frame_idx = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % step_frames == 0:
                t = frame_idx / total_fps
                detected_center = self._detect_face_center_x(frame, src_w, src_h)

                if detected_center is not None:
                    # Ideal crop top-left X puts face in center of crop_w
                    target_x = detected_center - (crop_w / 2.0)
                    target_x = max(0.0, min(float(src_w - crop_w), target_x))
                    detected_xs.append(target_x)
                else:
                    target_x = smoothed_x

                # Exponential Moving Average (EMA) smoothing
                smoothed_x = (self.alpha * target_x) + ((1.0 - self.alpha) * smoothed_x)
                smoothed_x = max(0.0, min(float(src_w - crop_w), smoothed_x))
                trajectory.append((round(t, 3), int(smoothed_x)))

            frame_idx += 1

        cap.release()

        avg_crop_x = int(np.median(detected_xs)) if detected_xs else default_x
        avg_crop_x = max(0, min(src_w - crop_w, avg_crop_x))

        logger.info("Face tracking finished: %d sampled points. Optimal average crop X: %d (src: %dx%d -> 9:16 crop: %dx%d)",
                    len(trajectory), avg_crop_x, src_w, src_h, crop_w, crop_h)

        return {
            "src_w": src_w,
            "src_h": src_h,
            "crop_w": crop_w,
            "crop_h": crop_h,
            "avg_crop_x": avg_crop_x,
            "trajectory": trajectory
        }

    def _detect_face_center_x(self, frame: np.ndarray, src_w: int, src_h: int) -> Optional[float]:
        """Finds primary active speaker face center X coordinate with 4x downscaling for speed."""
        if self.cascade is not None and not self.cascade.empty():
            # Downscale frame for speed (360p is plenty for frontal face cascade)
            scale_factor = 360.0 / float(src_h)
            small_w = int(src_w * scale_factor)
            small_h = 360
            small_gray = cv2.cvtColor(cv2.resize(frame, (small_w, small_h)), cv2.COLOR_BGR2GRAY)

            faces = self.cascade.detectMultiScale(small_gray, scaleFactor=1.15, minNeighbors=3, minSize=(30, 30))
            if len(faces) > 0:
                largest_face = max(faces, key=lambda f: f[2] * f[3])
                fx, fy, fw, fh = largest_face
                center_small_x = fx + (fw / 2.0)
                # Map back to original coordinate space
                return center_small_x / scale_factor

        return None
