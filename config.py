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
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720

# MJPG sıkıştırmasını zorla. Çoğu UVC kamera ham formatta yüksek çözünürlükte
# 5-10 fps'e düşer; MJPG ile 30 fps'e çıkabilir. Kamera desteklemiyorsa etkisizdir.
CAMERA_USE_MJPG = True

# --- Otonom Takip Ayarları ---
# Saha ayarı tek dosyadan yapılabilsin diye burada. Değiştirdikten sonra
# yalnızca arayüzü yeniden başlatmak yeterli.

# Bir piksellik hatanın kaç dereceye karşılık geldiği. KAMERA VEYA LENS
# DEĞİŞİRSE YENİDEN ÖLÇÜLMELİ — arayüzdeki "Derece/Piksel Ölç" butonu bu değeri
# hesaplar. Yanlış değer PID'in efektif kazancını ölçekler: çok büyükse taret
# hedefi aşıp salınır, çok küçükse yavaş yaklaşır.
DEGREES_PER_PIXEL_YAW = 0.015
DEGREES_PER_PIXEL_PITCH = -0.015

# PID oransal kazançları. Kilitlenme hızını belirleyen ana değişken budur.
# Ölçümle doğrulanmış kalibrasyonla güvenli tavan ~0.9; üstünde salınım başlar.
# Kalibrasyon yanlışsa tavan düşer, bu yüzden önce ölçüp sonra yükseltin.
KP_YAW = 0.7
KP_PITCH = 0.6

# Hız ileri-beslemesi (feedforward). Saf oransal denetim hareketli hedefte
# kalıcı olarak geride kalır (10°/s hedefte KP=0.5 ile ~100 piksel). Bu terim
# hedefin ölçüm gecikmesi boyunca kat edeceği yolu önceden telafi eder.
# 0.0 = kapalı. Sahada 0'dan kademeli açın; titreme başlarsa geri düşürün.
FEEDFORWARD_GAIN = 0.3

# Duyarga gecikmesi tahmini (saniye): kamera + çıkarım + açı raporu.
# Feedforward'ın ne kadar ileriyi tahmin edeceğini belirler.
FEEDFORWARD_LEAD_TIME = 0.10

# Hedef hızı kare-kare kutu merkezi farkından geliyor ve gürültülü. Bu üstel
# yumuşatma katsayısı 0-1 arası: küçük değer daha çok yumuşatır (daha kararlı
# ama daha tepkisiz), büyük değer ham hıza yakınlaşır.
# Bu değer hız ARTARKEN kullanılır (gürültü sıçramalarını reddetmek için yavaş).
VELOCITY_SMOOTHING = 0.3

# Hız AZALIRKEN kullanılan katsayı — kasıtlı olarak daha büyük, yani daha hızlı
# söner. Sebep: hedef durduğunda simetrik yumuşatma hız tahminini birkaç kare
# boyunca yüksek tutuyor, feedforward itmeye devam ediyor ve taret hedefi geçip
# geri dönüyordu. Asimetrik sönüm bu aşımı ölçümde 5 px'den 2 px'e indirdi.
VELOCITY_DECAY_SMOOTHING = 0.6

# Bu eşiğin altındaki hız tahmini feedforward'a verilmez (derece/sn).
# Sabit hedefte tespit gürültüsünün ürettiği sahte hızın tareti titretmesini
# engeller; hedef gerçekten dururken feedforward tam olarak sıfırlanır.
FEEDFORWARD_VELOCITY_DEADBAND = 2.0

# Feedforward katkısının üst sınırı (derece). Ani/hatalı bir hız tahmininin
# tareti savurmasını engeller.
FEEDFORWARD_MAX_DEGREE = 3.0
