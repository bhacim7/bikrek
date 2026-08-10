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
# Sahada ölçüldü (iki bağımsız koşum, dört örnek; koşumlar arası uyum %1-2).
# İma edilen görüş açısı: 82° yatay / 56° dikey — 16:9 geniş açı kamerayla tutarlı.
# Önceki 0.015 değeri gerçeğin 4.3 katı küçüğüydü; bu yüzden efektif döngü
# kazancı 0.16'da kalıyor ve takip yavaş oluyordu.
DEGREES_PER_PIXEL_YAW = 0.05350
DEGREES_PER_PIXEL_PITCH = -0.05547

# PID oransal kazançları. Kilitlenme hızını belirleyen ana değişken budur.
# Ölçümle doğrulanmış kalibrasyonla güvenli tavan ~0.9; üstünde salınım başlar.
# Kalibrasyon yanlışsa tavan düşer, bu yüzden önce ölçüp sonra yükseltin.
# Ölü zaman telafisi eklendikten sonra bu değerler tekrar yükseltilebildi.
# Daha önce 0.5 bile salınım yapıyordu çünkü bayat hata şimdiki açıya
# ekleniyor ve kat edilen yol iki kez sayılıyordu; aşım gecikmeyle büyüyordu.
# Telafiyle aşım gecikmeden bağımsız hale geldi (ölçümde 10-11 piksel).
# Temiz çalışırsa 0.9'a kadar denenebilir.
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

# Hedefin dünya açısal hızı için üst sınır (derece/sn). Elde gezdirilen bir
# balon bunu aşmaz. Bu sınır iki yerde koruma sağlar: feedforward ve hedef
# kaybındaki tahmin. Sahada 90 iken, 0.6 sn kayıpta tahmin 54° savrulup
# tareti ters yöne fırlatıyordu (-791 piksellik hayali hata).
MAX_TARGET_RATE_DEG_S = 20.0

# Bir aday hedefe kilitlenmeden önce ard arda kaç karede aynı yerde görülmeli.
# YOLO tek tük yanlış pozitif üretiyor; sahada tavanda çıkan hayalet tespit
# (güven 0.59) gerçek balondan (0.44) yüksek çıktı ve hedef seçme kuralı
# "kareye en yakın tespit" olduğu için hayalet kazandı. Hayalet 2 kare sürdü;
# 3 kare onay istemek bunu eler, gerçek hedefe ~0.1 sn gecikme ekler.
LOCK_CONFIRM_FRAMES = 3

# Hedef kaybolduğunda kaç kare tahminle devam edilsin. Kısa tutmak, hatalı bir
# tahminin tareti savurma penceresini daraltır. 15 kare (0.6 sn) fazlaydı.
MAX_MISSING_FRAMES = 5

# --- Ölü bant (durusta titremeyi engeller) ---
# PİKSEL cinsinden tanımlı, çünkü gürültü kaynağı YOLO kutu merkezidir ve o
# piksel cinsinden oynar. Derece karşılığı kalibrasyondan türetilir.
# Sahada 0.05 derece kullanılıyordu; bu 0.8 piksel eder, yani tespit
# gürültüsünün altında — her gürültü hareket komutuna dönüşüp taret titriyordu.
PID_DEADBAND_PIXELS = 5.0

# Bu piksel karşılığından küçük çıkışlar hiç gönderilmez.
MIN_OUTPUT_PIXELS = 3.0

# --- Hayalet tespit filtresi (renk tutarlılığı) ---
# Sınıf adı bir renk belirtiyorsa (red_balloon gibi), kutunun içinde gerçekten
# o renk olmalı. Sahada ölçüldü: tek balonlu sahnede karelerin %41.7'sinde
# hayalet tespit vardı (tavanda red_balloon 0.66 güvenle). Kutu içeriği:
#   gerçek balon  : ortalama %77 kırmızı (en zayıf örnek bile %17)
#   hayalet       : ortalama %0.1 kırmızı
# %5 eşikle 813 gerçek tespitin hiçbiri kaybolmadı, 338 hayaletin %99'u elendi.
DETECTION_COLOR_CHECK = True
DETECTION_COLOR_MIN_RATIO = 0.05

# --- Hedef seçiminde güven skoru ---
# Aday seçimi "kareye en yakın tespit" kuralıyla yapılıyor ve güveni hiç
# dikkate almıyordu; sahada tavandaki hayalet (0.66) tam merkezde olduğu için
# gerçek balonu (0.81) yenmişti. Artık önce belirgin şekilde daha güvenli
# tespitler ayıklanıyor, sonra kalanlar arasında merkeze yakınlık karar veriyor.
# Bu marj kadar düşük güvenli adaylar, daha iyisi varken değerlendirmeye alınmaz.
ACQUIRE_CONFIDENCE_MARGIN = 0.15
