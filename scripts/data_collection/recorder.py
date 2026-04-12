"""
recorder.py — Main recording pipeline for AdaptTrust scenarios.

Wraps a running ScenarioBase instance and, on each call to record(),
  1. Converts the latest CARLA RGB image to a numpy BGR frame.
  2. Writes the frame to video.mp4 (1920×1080, 30 fps, mp4v).
  3. Runs YOLOv8n on the frame (person, car, bicycle, truck, traffic light).
  4. Calls scenario.check_trigger() with YOLO detections.
  5. On any trigger: saves a JPEG snapshot for GPT-4o input and annotates
     the corresponding action_event with its file path.

Outputs written to  data/scenarios/<scenario_id>/:
    video.mp4
    yolo_detections.json
    trigger_frames/
        t_<ts>_<TYPE>.jpg
        ...

telemetry.json and action_events.json are written by ScenarioBase.__exit__.

Typical usage inside a scenario's run():

    from scripts.data_collection.recorder import Recorder

    def run(self):
        ap = AutopilotController(self.ego, self.traffic_manager)
        ap.enable()

        with Recorder(self) as rec:
            while not done:
                frame = self.tick()
                ap.update(frame)
                rec.record(frame)

        ap.disable()
        return {...}
"""

import json
import logging
import time
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

logger = logging.getLogger("recorder")

# COCO class IDs we care about
_YOLO_CLASSES_OF_INTEREST = {
    0: "person",
    1: "bicycle",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
    9: "traffic light",
}

# YOLOv8 model weights — downloaded automatically on first run
_YOLO_MODEL_PATH = "yolov8n.pt"

# Video encoding
_VIDEO_FOURCC  = cv2.VideoWriter_fourcc(*"mp4v")
_VIDEO_FPS     = 30
_VIDEO_WIDTH   = 1920
_VIDEO_HEIGHT  = 1080

# Minimum YOLO confidence to record a detection
_YOLO_CONF_THRESHOLD = 0.40


def _carla_image_to_bgr(image) -> np.ndarray:
    """
    Convert a carla.Image (BGRA raw_data) to a (H, W, 3) uint8 BGR numpy array.
    """
    array = np.frombuffer(image.raw_data, dtype=np.uint8)
    array = array.reshape((image.height, image.width, 4))
    return array[:, :, :3].copy()  # drop alpha, make contiguous


# PiP dimensions: 1/4 of main frame width, top-right corner
_PIP_W, _PIP_H = 480, 270
_PIP_MARGIN    = 12
_PIP_BORDER    = 3


def _composite_rear_pip(main_bgr: np.ndarray, rear_image) -> np.ndarray:
    """Overlay rear-camera feed as a picture-in-picture in the top-right corner."""
    rear_arr = np.frombuffer(rear_image.raw_data, dtype=np.uint8)
    rear_arr = rear_arr.reshape((rear_image.height, rear_image.width, 4))
    rear_bgr = rear_arr[:, :, :3].copy()
    pip = cv2.resize(rear_bgr, (_PIP_W, _PIP_H), interpolation=cv2.INTER_LINEAR)

    # Position: top-right
    x0 = _VIDEO_WIDTH - _PIP_W - _PIP_MARGIN
    y0 = _PIP_MARGIN

    out = main_bgr.copy()
    # White border
    out[y0 - _PIP_BORDER : y0 + _PIP_H + _PIP_BORDER,
        x0 - _PIP_BORDER : x0 + _PIP_W + _PIP_BORDER] = (255, 255, 255)
    out[y0 : y0 + _PIP_H, x0 : x0 + _PIP_W] = pip

    # Label
    cv2.putText(out, "REAR", (x0 + 6, y0 + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2,
                cv2.LINE_AA)
    return out


class Recorder:
    """
    Per-scenario recording context manager.

    Args:
        scenario:   A ScenarioBase instance that has already been set up
                    (i.e. inside its own context manager or after setup()).
        yolo_model: Path to YOLOv8 weights file.  Defaults to yolov8n.pt.
        conf:       YOLO confidence threshold.
    """

    def __init__(
        self,
        scenario,
        yolo_model: str = _YOLO_MODEL_PATH,
        conf: float = _YOLO_CONF_THRESHOLD,
    ):
        self.scenario = scenario
        self.conf = conf

        self.output_dir: Path = scenario.output_dir
        self.trigger_dir: Path = self.output_dir / "trigger_frames"

        self._video_writer: cv2.VideoWriter | None = None
        self._yolo: YOLO | None = None
        self._yolo_model_path = yolo_model

        # Per-frame detection accumulator
        self._all_detections: list[dict] = []

        # Frame counter (video frame index)
        self._frame_idx: int = 0

        # Wall-clock time of last YOLO run — used to skip frames when GPU
        # throughput falls behind the simulation rate (graceful degradation)
        self._last_yolo_wall_time: float = 0.0

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self):
        self.trigger_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Loading YOLO model: %s (CPU — GPU reserved for CARLA)",
                    self._yolo_model_path)
        self._yolo = YOLO(self._yolo_model_path)
        # Warm up the model with a dummy frame so first real frame isn't slow
        dummy = np.zeros((_VIDEO_HEIGHT, _VIDEO_WIDTH, 3), dtype=np.uint8)
        self._yolo(dummy, verbose=False, device="cpu")
        logger.info("YOLO warm-up complete.")

        video_path = str(self.output_dir / "video.mp4")
        self._video_writer = cv2.VideoWriter(
            video_path,
            _VIDEO_FOURCC,
            _VIDEO_FPS,
            (_VIDEO_WIDTH, _VIDEO_HEIGHT),
        )
        if not self._video_writer.isOpened():
            raise RuntimeError(f"cv2.VideoWriter failed to open: {video_path}")
        logger.info("VideoWriter opened → %s", video_path)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._video_writer:
            self._video_writer.release()
            logger.info(
                "VideoWriter closed — %d frames written to %s",
                self._frame_idx,
                self.output_dir / "video.mp4",
            )

        self._save_yolo_detections()
        return False  # propagate exceptions

    # ------------------------------------------------------------------
    # Per-frame recording
    # ------------------------------------------------------------------

    def record(self, telemetry_frame: dict) -> list[dict]:
        """
        Process one simulation tick.

        Call this every time after ScenarioBase.tick() returns.

        Args:
            telemetry_frame: Dict returned by scenario.tick().

        Returns:
            List of YOLO detection dicts for this frame (may be empty).
        """
        raw_image = self.scenario._latest_rgb_frame
        if raw_image is None:
            # Sensor hasn't fired yet — write a black frame to keep video in sync
            bgr = np.zeros((_VIDEO_HEIGHT, _VIDEO_WIDTH, 3), dtype=np.uint8)
            detections = []
        else:
            bgr = _carla_image_to_bgr(raw_image)
            detections = self._run_yolo(bgr, telemetry_frame["timestamp"])

        # Composite rear-camera PiP (top-right corner) if rear cam is active
        rear_image = getattr(self.scenario, "_latest_rear_frame", None)
        if rear_image is not None:
            bgr = _composite_rear_pip(bgr, rear_image)

        self._video_writer.write(bgr)

        # Check action triggers — pass YOLO detections so PEDESTRIAN_CLOSE fires
        trigger = self.scenario.check_trigger(telemetry_frame, detections)
        if trigger:
            frame_path = self._save_trigger_frame(bgr, telemetry_frame["timestamp"], trigger)
            # Annotate the event that was just appended by check_trigger
            if self.scenario._action_events:
                self.scenario._action_events[-1]["frame_path"] = frame_path

        self._frame_idx += 1
        return detections

    # ------------------------------------------------------------------
    # YOLO inference
    # ------------------------------------------------------------------

    def _run_yolo(self, bgr: np.ndarray, timestamp: float) -> list[dict]:
        """
        Run YOLOv8 inference and return filtered detections.

        Returns list of dicts:
            {
                "frame_idx": int,
                "timestamp": float,
                "class_id": int,
                "class_name": str,
                "confidence": float,
                "bbox": [x1, y1, x2, y2],   # pixel coords, ints
            }
        """
        t0 = time.monotonic()
        results = self._yolo(bgr, verbose=False, conf=self.conf, device="cpu")
        inference_ms = (time.monotonic() - t0) * 1000

        detections = []
        for result in results:
            for box in result.boxes:
                cls_id = int(box.cls[0])
                if cls_id not in _YOLO_CLASSES_OF_INTEREST:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                det = {
                    "frame_idx": self._frame_idx,
                    "timestamp": round(timestamp, 4),
                    "class_id": cls_id,
                    "class_name": _YOLO_CLASSES_OF_INTEREST[cls_id],
                    "confidence": round(float(box.conf[0]), 4),
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                }
                detections.append(det)

        self._all_detections.extend(detections)
        self._last_yolo_wall_time = time.monotonic()

        if detections:
            names = [d["class_name"] for d in detections]
            logger.debug(
                "YOLO frame %d (%.1f ms): %s",
                self._frame_idx, inference_ms, names,
            )

        return detections

    # ------------------------------------------------------------------
    # Trigger frame snapshots
    # ------------------------------------------------------------------

    def _save_trigger_frame(self, bgr: np.ndarray, timestamp: float, trigger: str) -> str:
        """
        Save a JPEG snapshot of the frame that fired an action trigger.

        File name:  trigger_frames/t_<timestamp>_<TRIGGER_TYPE>.jpg
        Returns the relative path string stored in action_events.json.
        """
        filename = f"t_{timestamp:.3f}_{trigger}.jpg"
        abs_path = self.trigger_dir / filename
        cv2.imwrite(str(abs_path), bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
        rel_path = str(abs_path.relative_to(self.output_dir.parent.parent))
        logger.info("Trigger frame saved → %s", abs_path)
        return rel_path

    # ------------------------------------------------------------------
    # Save outputs
    # ------------------------------------------------------------------

    def _save_yolo_detections(self) -> None:
        path = self.output_dir / "yolo_detections.json"
        with open(path, "w") as f:
            json.dump(self._all_detections, f, indent=2)
        logger.info(
            "YOLO detections saved → %s (%d detections across %d frames)",
            path, len(self._all_detections), self._frame_idx,
        )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def frame_count(self) -> int:
        return self._frame_idx

    @property
    def detection_count(self) -> int:
        return len(self._all_detections)

    def summary(self) -> dict:
        """Return a summary dict suitable for logging or metadata files."""
        class_counts: dict[str, int] = {}
        for d in self._all_detections:
            class_counts[d["class_name"]] = class_counts.get(d["class_name"], 0) + 1
        return {
            "frames_recorded": self._frame_idx,
            "total_detections": len(self._all_detections),
            "detections_by_class": class_counts,
            "trigger_count": len(self.scenario._action_events),
        }
