# --- Configuration File ---

# Model Paths
YOLO_MODEL_PATH = "C:/Users/barış hacim/PycharmProjects/PythonProject/train87/weights/best.engine"
YOLO_MODEL_PATH_TASK3 = "C:/Users/barış hacim/PycharmProjects/PythonProject/train9/weights/best.engine"

# Inference thresholds
CONF_THRESHOLD = 0.4
NMS_THRESHOLD = 0.4

# Classes
CLASSES = ['blue_balloon', 'red_balloon']
CLASSES_TASK3 = ['kir_Dai', 'kir_Kar', 'kir_Uc', 'mav_Dai', 'mav_Kar', 'mav_Uc', 'yes_Dai', 'yes_Kar', 'yes_Uc']

# Default Model Input Size
IMG_HEIGHT = 1056
IMG_WIDTH = 1056

# RPi Connection
RPI_IP = '192.168.137.229'
RPI_PORT = 12345
