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
# Sahada olculdu: kalan gecikme ~0.22 sn (asagiya bakin). Etkin ileri gorus
# GAIN x LEAD_TIME carpimidir; eskiden 0.3 x 0.10 = 0.03 sn idi, yani olcumun
# ancak yedide biri. Aci gecmisi duzeltilmeden bu carpimi buyutmek isleri
# KOTULESTIRIYORDU (sahte hiz tahmini yuzunden); duzeltme sonrasi guvenli.
FEEDFORWARD_GAIN = 0.8

# Duyarga gecikmesi (saniye): kamera + cikarim + aci raporu + motor tepkisi.
# EKRAN KAYDINDAN OLCULDU: hedef sabit hizla giderken kalan piksel hatasi
# hedefin acisal hizina bolununce her kesitte ayni sayi cikti:
#   hedef hizi  5-15 derece/sn araliginda 14 olcum -> ortanca 0.22 sn
#   (dagilim 0.17-0.24 sn; yon ve hizdan bagimsiz, yani saf olu zaman)
# Etkin telafi = FEEDFORWARD_GAIN x bu deger.
FEEDFORWARD_LEAD_TIME = 0.22

# --- Kamera boru hattı gecikmesi (ölü zaman telafisinin eksik kalan kısmı) ---
# Kamera karesinin zaman damgası, sensörün POZLADIĞI an değil karenin
# OKUNDUĞU andır; USB + MJPG boru hattı arada bir gecikme ekler ve bu telafi
# edilmiyordu. Sonuç: taret hızlıyken hedefin dünya açısı olduğundan ileride
# hesaplanıyor ve taret hedefi AŞIYOR. Aşımın taret hızıyla büyümesi bu
# mekanizmanın imzasıdır (ölçümde 25°/s'de 27 px, 70°/s'de 75 px).
#
# DEĞER SAHADA AYARLANMALIDIR: az da fazla da zararlı, en iyisi gerçek
# gecikmeye eşit olandır. Otomatik ölçmeyi denedim ama güvenilir çıkmadı
# (PID geri beslemesi tahmini saptırıyor, gerçeğin ancak %42'sini buluyor),
# o yüzden kademeli denemek gerekiyor. Ölçülen aşım tablosu (46.7°/s'de):
#
#   gerçek gecikme →   0.00s  0.02s  0.04s  0.06s  0.10s
#   ofset 0.00         7 px   15 px  31 px  51 px  84 px
#   ofset 0.04        33 px   23 px   7 px  15 px  52 px
#   ofset 0.06        43 px   29 px  13 px   7 px  32 px
#
# Yöntem: 0.04 ile başla, aşım azaldıysa 0.06 ve 0.08'i dene. Aşım tekrar
# büyümeye başladığında bir önceki değerde kal.
CAPTURE_LATENCY_OFFSET = 0.08

# Hedef hızı kare-kare kutu merkezi farkından geliyor ve gürültülü. Bu üstel
# yumuşatma katsayısı 0-1 arası: küçük değer daha çok yumuşatır (daha kararlı
# ama daha tepkisiz), büyük değer ham hıza yakınlaşır.
# Bu değer hız ARTARKEN kullanılır (gürültü sıçramalarını reddetmek için yavaş).
VELOCITY_SMOOTHING = 0.3

# Hedef GERÇEKTEN hızlı hareket ederken kullanılan katsayı. Tek bir yumuşatma
# değeri iki çelişen ihtiyaca hizmet edemiyordu: sabit hedefte gürültüyü
# bastırmak için yavaş (0.3), hareketli hedefte ivmelenmeye yetişmek için
# hızlı (0.5-0.6) olmalı. Sahada 0.5-0.6 hareketli takibi iyileştirirken
# sabit hedefe oturmayı bozuyordu. Artık hıza göre seçiliyor.
VELOCITY_FAST_SMOOTHING = 0.6

# Bu hızın (derece/sn) üstünde hedef "gerçekten hareketli" sayılır ve hızlı
# yumuşatmaya geçilir. Altında tespit gürültüsü baskındır, yavaş yumuşatma
# kullanılır. Ölü bant (FEEDFORWARD_VELOCITY_DEADBAND) bunun altında kalmalı.
# Ekran kaydindan olculdu: elde gezdirilen balonun gercek acisal hizi 5-15
# derece/sn araligindaydi. Esik 10 iken hareketin cogu yavas moda dusuyor ve
# hizli yumusatma hic devreye girmiyordu.
VELOCITY_FAST_THRESHOLD = 4.0

# Hız AZALIRKEN kullanılan katsayı — kasıtlı olarak daha büyük, yani daha hızlı
# söner. Sebep: hedef durduğunda simetrik yumuşatma hız tahminini birkaç kare
# boyunca yüksek tutuyor, feedforward itmeye devam ediyor ve taret hedefi geçip
# geri dönüyordu. Asimetrik sönüm bu aşımı ölçümde 5 px'den 2 px'e indirdi.
# 0.6 -> 0.75: etkin ileri gorus alti kat buyuyunce sonme kuyrugu da alti kat
# agirlik kazandi ve "hedefi elden birakip masaya koyma" aninda hata 4.1 px'den
# 7.2 px'e cikti. Tarama (gercek yorunge tekrar oynatilarak, ort. hata px):
#   sonum   hareketli  durdurma  oturmus  edinme-salinimi
#    0.60      22.4       7.2      1.4        6.8
#    0.75      25.4       2.9      1.4        6.8   <-- secilen: dordu de iyi
#    0.85      27.2       1.5      2.2        6.8
# 0.85 durdurmayi daha da iyilestiriyor ama hareketli takibi ve oturmayi
# bozuyor; 0.75 dort fazin dordunde de eski degerlerden iyi.
VELOCITY_DECAY_SMOOTHING = 0.75

# Bu eşiğin altındaki hız tahmini feedforward'a verilmez (derece/sn).
# Sabit hedefte tespit gürültüsünün ürettiği sahte hızın tareti titretmesini
# engeller; hedef gerçekten dururken feedforward tam olarak sıfırlanır.
# 2.0 -> 4.0: etkin ileri gorus 0.03 sn'den 0.18 sn'ye cikinca ayni gurultu
# alti kat buyuk bir itme uretmeye basladi ve oturmus sabit hedefte hata
# 2.4 px'den 5.3 px'e cikti. Tarama (gercek yorunge tekrar oynatilarak):
#   olu bant  2.0 -> hareketli 21.7 px, sabit 5.3 px
#   olu bant  3.0 -> hareketli 22.1 px, sabit 2.7 px
#   olu bant  4.0 -> hareketli 22.4 px, sabit 1.4 px   <-- secilen
# Hareketli hedefte bedeli yok cunku gercek hedef hizi 5-15 derece/sn.
FEEDFORWARD_VELOCITY_DEADBAND = 4.0

# Feedforward katkısının üst sınırı (derece). Ani/hatalı bir hız tahmininin
# tareti savurmasını engeller. Etkin ileri gorus 0.18 sn'ye cikinca 15 derece/sn
# hedefte katki 2.7 dereceye ulasiyor; 3.0 siniri normal calismayi kirpmaya
# baslıyordu. 5.0 = 28 derece/sn'lik hedefe kadar kirpmaz.
FEEDFORWARD_MAX_DEGREE = 5.0

# --- Feedforward kapilari (sahada olculdu, hedefTakipDeneme.mp4) ---
# Feedforward yalnizca KILITLI takipte anlamli. Hata buyukken taret tepe
# hizinda doner ve tam o anda aci telemetrisi en guvenilmez halindedir: Pi
# adim atarken aci gonderen is parcacigi gecikir, 15 ms'lik gecikme 89 derece/sn
# hizda 1.3 derece = 25 piksellik aci hatasi demektir. Bu hata hiz tahminine
# sizar, sizinti feedforward'i besler, feedforward tareti daha hizli dondurur
# ve sizinti buyur -- pozitif geri besleme. Sahada edinme manevrasi 10 saniye
# boyunca +-4 derece salindi.
#
# (tam_piksel, sifir_piksel): bu hatanin altinda feedforward tam, ustunde sifir,
# arasinda dogrusal soner. Hata buyukken oransal terim zaten feedforward'in yuz
# kati oldugu icin kapatmanin maliyeti yok.
# Olcum (edinme manevrasi, Pi 20 Hz + 15 ms jitter):
#   kapi yok        -> ort 19.0 px, tepe 137 px, oturma 6.34 sn
#   kapi 30/120     -> ort  2.2 px, tepe  49 px, oturma 0.88 sn
FEEDFORWARD_ERROR_GATE_PIXELS = (30.0, 120.0)

# Feedforward'in bir denetim cevriminde degisebilecegi en buyuk miktar (derece).
# Iki kapidan sonra bile hiz tahmini kare kare ziplayabiliyor ve feedforward
# onu aynen aktariyor; takibin "akici" degil "kasintili" gorunmesinin dogrudan
# sebebi bu. Olcumde yon degistirme sayisi 157'den 69'a indi ve ortalama hata
# da 32.2'den 31.4 piksele dustu -- yani yumusatmanin bedeli yok.
FEEDFORWARD_MAX_STEP_DEGREE = 0.25

# Hedefin dünya açısal hızı için üst sınır (derece/sn). Elde gezdirilen bir
# balon bunu aşmaz. Bu sınır iki yerde koruma sağlar: feedforward ve hedef
# kaybındaki tahmin. Sahada 90 iken, 0.6 sn kayıpta tahmin 54° savrulup
# tareti ters yöne fırlatıyordu (-791 piksellik hayali hata).
# Elde gezdirilen balon 1.5 m'de 1 m/s ile 38, 2 m/s ile 76 derece/sn ediyor.
# 20'de kirpmak feedforward'i calisamaz hale getiriyordu: 50 derece/sn hedefte
# kalan hata 33 px, sinir 80 olunca 12 px.
MAX_TARGET_RATE_DEG_S = 80.0

# Hedef KAYBOLDUGUNDA tahmin icin kullanilan ayri (ve dar) sinir. Genis tutmak
# hayali hedefin uzaga kacmasina yol acar: 80 derece/sn x 5 kare = 16 derece.
# Feedforward'dan ayri tutuluyor cunku ikisi farkli riskler tasiyor —
# feedforward olculen hizi kullanir, tahmin ise korlemesine ekstrapolasyondur.
PREDICTION_MAX_RATE_DEG_S = 20.0

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

# Kutu, karenin bu oranından büyükse tespit reddedilir. Sahada YOLO karenin
# %85'ini kaplayan bir 'blue_balloon' üretti ve taret ona kilitlendi; balon
# hangi mesafede olursa olsun kareyi bu kadar dolduramaz.
# Üç kayıttan çıkarılan 642 GERÇEK balon kutusu ölçüldü: en büyüğü karenin
# %2.2'si, %99 dilim %1.9. Bu sınır 11 kat emniyet payı bırakıyor ve renkten
# bağımsız çalıştığı için renk kontrolünün kaçırdığı saçma kutuları da yakalar.
DETECTION_MAX_AREA_RATIO = 0.25

# --- Hedef seçiminde güven skoru ---
# Aday seçimi "kareye en yakın tespit" kuralıyla yapılıyor ve güveni hiç
# dikkate almıyordu; sahada tavandaki hayalet (0.66) tam merkezde olduğu için
# gerçek balonu (0.81) yenmişti. Artık önce belirgin şekilde daha güvenli
# tespitler ayıklanıyor, sonra kalanlar arasında merkeze yakınlık karar veriyor.
# Bu marj kadar düşük güvenli adaylar, daha iyisi varken değerlendirmeye alınmaz.
ACQUIRE_CONFIDENCE_MARGIN = 0.15
