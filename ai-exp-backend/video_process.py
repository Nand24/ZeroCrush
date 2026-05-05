import time
import datetime
import numpy as np
import cv2
from typing import Any, Optional
import threading
from ultralytics import YOLO

from util import progress
from pipeline.artifact import end_video, initialize_artifact_state, record_crowd_data, update_artifact_state
from pipeline.analysis import (
	detect_restricted_entry,
	evaluate_abnormal,
	resize_frame_by_width,
	update_track_histories,
)
from pipeline.annotators import (
	annotate_abnormal,
	annotate_crowd_count_if_needed,
	annotate_detections,
)
from pipeline.detection import detect_tracks
from pipeline.overlay import (
	apply_warning_overlays,
	draw_restricted_zone,
	draw_motion_trails,
	draw_risk_meter,
)
from services.runtime_settings import get_setting

FIXED_YOLO_MODEL_PATH = "yolov8n.pt"
_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: dict[str, YOLO] = {}


def _get_cached_model(model_path: str) -> YOLO:
	with _MODEL_LOCK:
		model = _MODEL_CACHE.get(model_path)
		if model is None:
			model = YOLO(model_path)
			_MODEL_CACHE[model_path] = model
		return model


def video_process(
	cap,
	frame_size,
	movement_data_writer,
	crowd_data_writer,
	settings: Optional[dict[str, Any]] = None,
	frame_callback=None,
	stop_event=None,
	headless=False,
	status_callback=None,
	artifact_state: Optional[dict[str, Any]] = None,
):
	if settings is None:
		raise ValueError("Missing settings")
	active_settings = settings
	IS_RTSP_STREAM = bool(active_settings["IS_RTSP_STREAM"])
	DATA_RECORD_RATE = int(active_settings["DATA_RECORD_RATE"])
	CHECK_ABNORMAL = bool(active_settings["CHECK_ABNORMAL"])
	ENERGY_THRESHOLD = float(active_settings["ENERGY_THRESHOLD"])
	ABNORMAL_RATIO_THRESHOLD = float(active_settings["ABNORMAL_RATIO_THRESHOLD"])
	MIN_PERSONS_ABNORMAL = int(active_settings["MIN_PERSONS_ABNORMAL"])
	YOLO_MODEL_PATH = FIXED_YOLO_MODEL_PATH
	YOLO_CONFIDENCE = float(active_settings["YOLO_CONFIDENCE"])
	TRACK_MAX_AGE = int(active_settings["TRACK_MAX_AGE"])
	model: Optional[YOLO] = None
	preview_emitted = False
	show_window = not headless
	# Some sources (especially RTSP) need a short warm-up before first frame.
	startup_deadline = time.time() + 15
	def _calculate_FPS():
		nonlocal VID_FPS
		t1 = time.time() - t0
		VID_FPS = frame_count / t1

	if IS_RTSP_STREAM:
		VID_FPS = None
		DATA_RECORD_FRAME = 1
		TIME_STEP = 1
		t0 = time.time()
	else:
		VID_FPS = float(cap.get(cv2.CAP_PROP_FPS))
		if VID_FPS <= 0:
			raise ValueError("Invalid source FPS")
		DATA_RECORD_FRAME = max(1, int(VID_FPS / DATA_RECORD_RATE))
		TIME_STEP = DATA_RECORD_FRAME / VID_FPS

	frame_count = 0
	display_frame_count = 0
	re_warning_timeout = 0
	ab_warning_timeout = 0
	track_histories = {}
	track_visual_state = {}
	initialize_artifact_state(artifact_state)

	def _motion_score_from_tracks() -> int:
		motion_samples = []
		for data in track_histories.values():
			positions = data.get("positions", [])
			if len(positions) < 2:
				continue
			(px, py), (cx, cy) = positions[-2], positions[-1]
			distance = float(((cx - px) ** 2 + (cy - py) ** 2) ** 0.5)
			motion_samples.append(distance)
		if not motion_samples:
			return 0
		return int(min(100, round((sum(motion_samples) / len(motion_samples)) * 10)))

	while True:
		if stop_event is not None and stop_event.is_set():
			end_video(track_histories, frame_count, movement_data_writer)
			if not VID_FPS:
				_calculate_FPS()
			break

		(ret, frame) = cap.read()

		# Allow source warm-up before declaring startup timeout.
		if not ret and frame_count == 0 and time.time() < startup_deadline:
			time.sleep(0.05)
			continue

		if not ret and frame_count == 0:
			raise RuntimeError("Timeout starting video source")

		# Stop the loop when video ends
		if not ret:
			end_video(track_histories, frame_count, movement_data_writer)
			if not VID_FPS:
				_calculate_FPS()
			break

		# Update frame count
		if frame_count > 1000000:
			if not VID_FPS:
				_calculate_FPS()
			frame_count = 0
			display_frame_count = 0
		frame_count += 1
		
		# Skip frames according to given rate
		if frame_count % DATA_RECORD_FRAME != 0:
			continue

		display_frame_count += 1

		# Resize Frame to given size
		frame = resize_frame_by_width(frame, frame_size)

		# Emit a frame immediately so stream/window becomes visible while model warms up.
		if not preview_emitted:
			if frame_callback is not None:
				frame_callback(frame)
			if show_window:
				cv2.imshow("Processed Output", frame)
				cv2.waitKey(1)
			preview_emitted = True

		if model is None:
			model = _get_cached_model(YOLO_MODEL_PATH)

		# Get current time
		current_datetime = datetime.datetime.now()

		# Run detection algorithm
		if IS_RTSP_STREAM:
			record_time = current_datetime
		else:
			record_time = frame_count

		# Run detection with YOLOv8 and update Deep SORT tracks.
		humans_detected = detect_tracks(model, frame, YOLO_CONFIDENCE, TRACK_MAX_AGE)
		update_track_histories(track_histories, humans_detected, record_time)

		# Check for restricted entry (centroid inside polygon)
		# Read `RESTRICTED_ZONE` live from runtime settings so updates apply while streaming.
		try:
			restricted_zone = get_setting("RESTRICTED_ZONE")
		except KeyError:
			restricted_zone = []
		zone_points = list(restricted_zone) if isinstance(restricted_zone, list) else []
		check_restricted_zone = len(zone_points) >= 3
		RE = detect_restricted_entry(humans_detected, zone_points)

		if check_restricted_zone:
			draw_restricted_zone(frame, np.array(zone_points, dtype=np.int32))

		violations = 0
		abnormal_individual, ABNORMAL = evaluate_abnormal(
			humans_detected,
			track_histories,
			CHECK_ABNORMAL,
			ENERGY_THRESHOLD,
			MIN_PERSONS_ABNORMAL,
			ABNORMAL_RATIO_THRESHOLD,
			TIME_STEP,
		)

		annotate_detections(frame, humans_detected, RE, show_green=not headless)
		annotate_abnormal(frame, humans_detected, abnormal_individual, ABNORMAL)
		annotate_crowd_count_if_needed(frame, len(humans_detected), headless)

		re_warning_timeout, ab_warning_timeout = apply_warning_overlays(
			frame,
			display_frame_count,
			RE,
			ABNORMAL,
			check_restricted_zone,
			CHECK_ABNORMAL,
			re_warning_timeout,
			ab_warning_timeout,
			humans_detected,
			abnormal_individual,
			track_histories,
		)

		# Draw motion trails and risk meter
		draw_motion_trails(frame, track_histories)
		crowd_score = int(min(100, len(humans_detected) * 8))
		abnormal_score = 0
		if len(humans_detected) > 0:
			abnormal_score = int(min(100, (len(abnormal_individual) / max(1, len(humans_detected))) * 100))
		motion_score = _motion_score_from_tracks()
		risk_percent = max(abnormal_score, int(round((crowd_score * 0.45) + (motion_score * 0.55))))
		draw_risk_meter(frame, risk_percent)

		if frame_callback is not None:
			frame_callback(frame)
		record_crowd_data(record_time, len(humans_detected), violations, RE, ABNORMAL, crowd_data_writer)
		if status_callback is not None:
			status_callback(record_time, len(humans_detected), violations, RE, ABNORMAL)
		update_artifact_state(artifact_state, frame, len(humans_detected), violations)
		if show_window:
			cv2.imshow("Processed Output", frame)
		else:
			progress(display_frame_count)

		# Press 'Q' to stop the video display
		if show_window and (cv2.waitKey(1) & 0xFF == ord('q')):
			# Record the movement when video ends
			end_video(track_histories, frame_count, movement_data_writer)
			# Compute the processing speed
			if not VID_FPS:
				_calculate_FPS()
			break
	
	cv2.destroyAllWindows()
	return VID_FPS
