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

# --- Kamera Ayarları ---
# Denenecek kamera indeksleri, sırayla. İlk açılan kullanılır.
CAMERA_INDICES = [1, 2, 3, 4]

# İstenen çözünürlük. Bu bir istektir; sürücü desteklemezse en yakın modu verir.
# Gerçekte ne alındığı kamera başlatılırken konsola yazdırılır ve sistemin geri
# kalanı (PID merkezi, kutu ölçeği) o gerçek değere göre çalışır.
CAMERA_WIDTH = 1080
CAMERA_HEIGHT = 720

# MJPG sıkıştırmasını zorla. Çoğu UVC kamera ham formatta yüksek çözünürlükte
# 5-10 fps'e düşer; MJPG ile 30 fps'e çıkabilir. Kamera desteklemiyorsa etkisizdir.
CAMERA_USE_MJPG = True
