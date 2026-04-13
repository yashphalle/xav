"""
All constants and configuration for the DriveVLM nuScenes pipeline.
Switch NUSCENES_VERSION to "v1.0-trainval" for final runs.
"""

# Dataset
NUSCENES_DATAROOT = "/home/meet/projects/bev-perception-autonomous-driving/data/nuscenes"
NUSCENES_VERSION = "v1.0-mini"

# Scene to process — mini split recommendations:
#   scene-0061: pedestrian crossing (recommended)
#   scene-0103: lane change
#   scene-0655: emergency brake
SCENE_NAME = "scene-0061"

# Windowing
FRAMES_PER_WINDOW = 10         # 10 frames × 0.5 s = 5 s per window — enough for TTS to finish

# Video output
FPS_OUTPUT = 2                  # nuScenes CAM_FRONT keyframes are 2 Hz
OUTPUT_DIR = "outputs/"

# OpenAI model — gpt-4o supports vision input
OPENAI_MODEL = "gpt-4o"

# Text rendering
FONT_SCALE = 0.55
FONT_THICKNESS = 1
TEXT_COLOR_DESCRIPTIVE = (255, 255, 255)    # white
TEXT_COLOR_TELEOLOGICAL = (100, 220, 255)   # light blue
TEXT_BOX_ALPHA = 0.55           # transparency of dark background behind text
MAX_LINE_WIDTH_CHARS = 60
MAX_TEXT_LINES = 4
