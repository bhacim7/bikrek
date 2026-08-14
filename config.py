# --- BUKREK Yapılandırma Dosyası ---
#
# MİMARİ: iki kamera var ve görevleri kesin çizgilerle ayrılmış.
#
#   GÖZCÜ (spotter) : gövdeye sabit, zoomsuz, geniş açı. YOLO ÇALIŞTIRMAZ.
#                     Sadece OpenCV renk analizi yapar; adayların gövde
#                     çerçevesindeki MUTLAK açısını ve açısal hızını üretir.
#                     Gövdeye sabit olduğu için taretin hareketi ölçümünü
#                     bozmaz — hız tahmini yapısal olarak sızıntısızdır.
#
#   AVCI (hunter)   : taret üzerinde, SABİT 3x zoom. YOLO burada çalışır.
#                     Dost/düşman doğrulaması ve nişan alma bu kameradan.
#
# Zoom sabit olduğu için derece/piksel yine tek bir sabittir; uçuşta değişen
# kazanç riski yoktur.

import os

_BURASI = os.path.dirname(os.path.abspath(__file__))

# --- Model ---
# Ağırlık dosyası bu dosyayla aynı klasörde. Mutlak yol yazmıyoruz ki proje
# başka bir makineye taşındığında bozulmasın.
YOLO_MODEL_PATH = os.path.join(_BURASI, "best.engine")

# Üç aşamanın ÜÇÜ de bu tek modeli kullanır; aşamalar arasında fark yalnızca
# görev mantığındadır. (Eskiden Aşama 3 ayrı bir model yüklüyordu.)
CONF_THRESHOLD = 0.4
NMS_THRESHOLD = 0.4

# data.yaml ile BİREBİR aynı sıra olmalı — sınıf indeksleri buradan çözülüyor.
CLASSES = ['balon', 'dost-F16', 'dost-Helikopter',
           'dusman-Drone', 'dusman-F16', 'dusman-Fuze']

# Balon sınıfının adı. Nişan noktası budur; dost/düşman bilgisi TAŞIMAZ,
# karar her zaman üstündeki maketten gelir.
BALLOON_CLASS = 'balon'

# Maket sınıflarının ön ekleri. Karar doğrudan ön ekten üretiliyor, ayrı bir
# eşleme tablosuna gerek yok (dusman-Drone ve dusman-Fuze zaten tek taraflı).
FRIEND_PREFIX = 'dost-'
ENEMY_PREFIX = 'dusman-'

IMG_HEIGHT = 608
IMG_WIDTH = 1056

# --- RPi Bağlantısı ---
RPI_IP = '192.168.137.229'
RPI_PORT = 12345


# =====================================================================
#  KAMERALAR
# =====================================================================
# İki kamera aynı USB denetleyicisinde 1280x720 MJPG @30 fps ile
# çalışmayabilir. Sorun çıkarsa önce farklı USB kök hub'larına takın;
# olmazsa GÖZCÜ çözünürlüğünü 640x480'e düşürün (blob tespiti için yeterli,
# açısal doğruluk yarıya iner ama ±0.3 derece hâlâ fazlasıyla yeterli).
#
# HER İKİ KAMERADA DA otomatik pozlama ve otomatik beyaz dengesi KAPALI
# olmalı. Sebep iki katlı:
#   1) Otomatik pozlama kare kare gecikmeyi değiştirir ve ölü zaman
#      telafisini bozar (CAPTURE_LATENCY_OFFSET sabit varsayılıyor).
#   2) Otomatik beyaz dengesi renk eşiklerini kaydırır; hem gözcünün renk
#      filtresi hem de hayalet eleyici sabit renk varsayıyor.

# Denenecek kamera indeksleri; ilk açılan kullanılır.
#
# HANGİ İNDEKS HANGİ KAMERA: Windows'ta indeks numarası USB portuna ve
# takılma sırasına göre değişir, kamera modeline göre DEĞİL. Yani bu iki
# listenin doğru olduğunu tahminle bilemeyiz — bakıp ayarlamak gerekir.
#
# NASIL DOĞRULARSINIZ: arayüzde ana (büyük) görüntü TARET ÜZERİNDEKİ
# kamerayı, sağ üstteki küçük panel ise GÖVDEYE SABİT kamerayı göstermeli.
# Ters görünüyorsa aşağıdaki iki satırı yer değiştirin. Gözcü panelinin
# altındaki bilgi satırı hangi indeksin açıldığını da yazar.
#
# Sahada ölçüldü (kamera_tani.py): indeks 0 = dizüstünün dahili kamerası,
# indeks 1 = taret üzerindeki kamera, indeks 2 = gövdeye sabit kamera.
HUNTER_CAMERA_INDICES = [1, 3, 4]
SPOTTER_CAMERA_INDICES = [2, 3, 4]

SPOTTER_WIDTH = 1280
SPOTTER_HEIGHT = 720
SPOTTER_USE_MJPG = True

HUNTER_WIDTH = 1280
HUNTER_HEIGHT = 720
HUNTER_USE_MJPG = True

# camera_module tek bir sözlükten okur; yeni bir kamera eklemek için buraya
# bir satır yetiyor.
KAMERA_AYARLARI = {
    "spotter": {"indices": SPOTTER_CAMERA_INDICES, "width": SPOTTER_WIDTH,
                "height": SPOTTER_HEIGHT, "mjpg": SPOTTER_USE_MJPG},
    "hunter":  {"indices": HUNTER_CAMERA_INDICES, "width": HUNTER_WIDTH,
                "height": HUNTER_HEIGHT, "mjpg": HUNTER_USE_MJPG},
}

# Pozlama süresi üst sınırı (saniye). Hareket bulanıklığı =
# taret_hızı x pozlama / derece_piksel. Avcıda derece/piksel 3 kat küçük
# olduğu için aynı hareket 3 kat fazla bulanıklık üretir:
#   pozlama 33 ms (1/30 s), taret 89 derece/sn  -> 165 piksel bulanıklık
#   pozlama 10 ms, taret 89 derece/sn           ->  50 piksel
#   pozlama 10 ms, taret  3 derece/sn (takip)   ->   1.7 piksel
# Balon avcıda 15 metrede 30 piksel; 33 ms'de tamamen sıvanır.
# Bu değer bilgi amaçlı burada; kamerada ELLE ayarlanmalı (OpenCV'nin
# CAP_PROP_EXPOSURE davranışı sürücüye göre değişiyor, güvenilir değil).
CAMERA_TARGET_EXPOSURE_SEC = 0.010


# =====================================================================
#  ÖLÇEK KALİBRASYONU (derece / piksel)
# =====================================================================
# KAMERA VEYA LENS DEĞİŞİRSE YENİDEN ÖLÇÜLMELİ — arayüzdeki
# "Derece/Piksel Ölç" butonu bu değerleri hesaplar.
# Yanlış değer PID'in efektif kazancını ölçekler: çok büyükse taret hedefi
# aşıp salınır, çok küçükse yavaş yaklaşır.

# GÖZCÜ: bugüne kadar kullandığımız kamera, zoomsuz. Sahada iki bağımsız
# koşumla ölçüldü (dört örnek, koşumlar arası uyum %1-2).
# İma edilen görüş açısı: 68.5 derece yatay / 39.9 derece dikey.
SPOTTER_DPP_YAW = 0.05350
SPOTTER_DPP_PITCH = -0.05547

# AVCI: sabit 3x zoom. Aşağıdaki değerler gözcününkinin üçte biri olarak
# HESAPLANDI, ölçülmedi. İlk sahada "Derece/Piksel Ölç" ile DOĞRULANMALI.
# Beklenen görüş açısı: 22.8 derece yatay / 13.3 derece dikey.
HUNTER_DPP_YAW = 0.01783
HUNTER_DPP_PITCH = -0.01849

# Geriye uyumluluk: denetim döngüsü avcı kamerayı kullanır.
DEGREES_PER_PIXEL_YAW = HUNTER_DPP_YAW
DEGREES_PER_PIXEL_PITCH = HUNTER_DPP_PITCH

# Gözcü ekseni ile taretin sıfır açısı arasındaki montaj farkı (derece).
# Gözcü "hedef 15 derece solda" dediğinde taret buraya gider:
#     hedef_yaw = gozcu_yaw + SPOTTER_YAW_OFFSET
# ÖLÇÜM: tek bir hedefi önce gözcüyle merkeze al (açısını not et), sonra
# tareti elle o hedefi avcının merkezine getirene kadar döndür; fark budur.
SPOTTER_YAW_OFFSET = 0.0

# Aynısı pitch için. Bu ofset montaj eğimini VE paralaksı birlikte yutar.
# Paralaks: gözcü avcının ~17 cm altında, 15 metrede atan(0.17/15) = 0.65
# derece. Avcının dikey yarı görüş açısı 6.65 derece olduğundan bu %10'u;
# sabit ofsetle rahatça telafi edilir. AMA mesafeye bağlı: 5 metrede 1.9,
# 2 metrede 4.9 derece. Yarışma 15 metrede olduğu için sabit kabul ediyoruz.
SPOTTER_PITCH_OFFSET = 0.0


# =====================================================================
#  DENETİM (PID + ileri besleme)
# =====================================================================
# Bu bölümdeki değerlerin çoğu ekran kayıtlarından kare kare ölçülerek
# ayarlandı. Değiştirmeden önce PROJE_DURUMU.md'deki ölçüm tablolarına bakın.

# PID oransal kazançları. DERECE uzayında çalışırlar (komut = KP x hata_derece),
# yani zoomdan bağımsızdırlar — 3x zoomlu avcıda da aynı değerler geçerli.
KP_YAW = 0.7
KP_PITCH = 0.6

# --- İleri besleme (feedforward) ---
# Saf oransal denetim hareketli hedefte kalıcı olarak geride kalır. Bu terim
# hedefin ölçüm gecikmesi boyunca kat edeceği yolu önceden telafi eder.
# Etkin telafi = FEEDFORWARD_GAIN x FEEDFORWARD_LEAD_TIME.
FEEDFORWARD_GAIN = 0.8

# Duyarga gecikmesi (saniye): kamera + çıkarım + açı raporu + motor tepkisi.
# EKRAN KAYDINDAN ÖLÇÜLDÜ: hedef sabit hızla giderken kalan piksel hatası
# hedefin açısal hızına bölününce her kesitte aynı sayı çıktı — 14 ölçümde
# ortanca 0.22 sn (dağılım 0.17-0.24; yön ve hızdan bağımsız, saf ölü zaman).
FEEDFORWARD_LEAD_TIME = 0.22

# Kamera boru hattı gecikmesi. Karenin zaman damgası sensörün POZLADIĞI an
# değil OKUNDUĞU andır; aradaki fark telafi edilmezse taret hedefi AŞAR ve
# aşım taret hızıyla büyür (25 derece/sn'de 27 px, 70 derece/sn'de 75 px).
# Gözcüde 0.078-0.08 aralığı sahada en iyi sonucu vermişti.
# AVCI KAMERA İÇİN YENİDEN ÖLÇÜLMELİ — farklı kamera, farklı boru hattı.
# Yöntem: 0.04'ten başla, aşım azaldıysa 0.06 ve 0.08'i dene; aşım tekrar
# büyümeye başladığında bir önceki değerde kal.
CAPTURE_LATENCY_OFFSET = 0.08

# Gözcünün kendi gecikmesi. YOLO çalıştırmadığı için avcıdan belirgin
# şekilde kısa; devir teslim öngörüsünde kullanılıyor.
SPOTTER_LATENCY = 0.05

# --- Hız tahmini yumuşatma ---
# Hız kare-kare ölçülen dünya açısı farkından geliyor ve gürültülü.
# Katsayı 0-1: küçük değer daha çok yumuşatır (kararlı ama tepkisiz).
# Hız ARTARKEN kullanılan (gürültü sıçramalarını reddetmek için yavaş).
VELOCITY_SMOOTHING = 0.3

# Hedef GERÇEKTEN hızlı giderken kullanılan katsayı. Tek bir değer iki
# çelişen ihtiyaca hizmet edemiyordu: sabit hedefte gürültüyü bastırmak için
# yavaş, hareketli hedefte ivmelenmeye yetişmek için hızlı olmalı.
VELOCITY_FAST_SMOOTHING = 0.6

# Bu hızın üstünde hedef "gerçekten hareketli" sayılır (derece/sn).
# YARIŞMA HEDEFLERİ İÇİN YENİDEN ÖLÇEKLENDİ. Hedefler 0.4 m/s ile tarete
# doğru geliyor; hareket büyük ölçüde RADYAL olduğu için açısal hız çok
# düşük. 7.5 m yanal ofsetli bir yol için hesap:
#     15 m -> 0.8 derece/sn,  8 m -> 1.4,  5 m -> 2.6
# Eski 4.0 değeri hedefin ulaşamayacağı bir eşikti; hızlı yumuşatma hiç
# devreye girmezdi.
VELOCITY_FAST_THRESHOLD = 1.5

# Hız AZALIRKEN kullanılan katsayı — kasıtlı olarak daha büyük, hızlı söner.
# Hedef durduğunda simetrik yumuşatma tahmini birkaç kare yüksek tutuyor,
# feedforward itmeye devam ediyor ve taret hedefi geçip geri dönüyordu.
VELOCITY_DECAY_SMOOTHING = 0.75

# Bu eşiğin altındaki hız tahmini feedforward'a verilmez (derece/sn).
# YARIŞMA HEDEFLERİ İÇİN YENİDEN ÖLÇEKLENDİ. Eski 4.0 değeri gerçek
# hedeflerin açısal hızının (0.5-2.6 derece/sn) üstündeydi; feedforward
# HİÇ çalışmazdı. Feedforward'sız kalan hata: 2.6 x 0.22 = 0.57 derece =
# avcıda 32 piksel. Balon 15 metrede 30 piksel — nişangah tam kenarda kalır.
#
# Neden 4.0'dan 1.0'a inebiliyoruz: gürültünün iki bileşeni var. Tespit
# piksel gürültüsü 3x zoomda üçte birine iner; açı telemetrisi sızıntısı ise
# taret hızıyla orantılı ve taret burada 0.5-2.6 derece/sn'de dönüyor, yani
# sızıntı da küçük. Sahada oturmuş halde ölçülen sahte hız 1.1 derece/sn idi
# (geniş kamera, taret dururken); avcıda ~0.4 bekleniyor.
# SAHADA DOĞRULANMALI: sabit hedefte titreme başlarsa 1.5-2.0'a çekin.
FEEDFORWARD_VELOCITY_DEADBAND = 1.0

# Feedforward katkısının üst sınırı (derece).
FEEDFORWARD_MAX_DEGREE = 5.0

# --- Feedforward kapıları ---
# Üçü de aynı gerçeğe dayanır: hız tahmininin güvenilirliği duruma göre çok
# değişiyor ve feedforward güvenilmez olduğu anda zarar veriyor.

# (tam_piksel, sifir_piksel): bu hatanın altında feedforward tam, üstünde
# sıfır, arasında doğrusal söner.
#
# Feedforward yalnızca KİLİTLİ takipte anlamlı. Hata büyükken taret tepe
# hızında döner ve tam o anda açı telemetrisi en güvenilmez halindedir: Pi
# adım atarken açı gönderen iş parçacığı gecikir, 15 ms'lik gecikme
# 89 derece/sn'de 1.3 derece açı hatası demektir. Bu hata hız tahminine
# sızar, sızıntı feedforward'ı besler, feedforward tareti daha hızlı
# döndürür — pozitif geri besleme. Sahada edinme manevrası 10 saniye
# boyunca +-4 derece salındı.
#   kapı yok     -> ort 19.0 px, tepe 137 px, oturma 6.34 sn
#   kapı açık    -> ort  2.2 px, tepe  49 px, oturma 0.88 sn
#
# DEĞERLER 3x ZOOM İÇİN YENİDEN ÖLÇEKLENDİ. Kapının koruduğu şey AÇISAL bir
# olgu; geniş kamerada (30, 120) piksel = (1.6, 6.4) dereceydi. Avcıda aynı
# açıyı korumak için piksel değerleri 3 katına çıkmalı, yoksa kapı hedefi
# takip ederken bile kapanır ve feedforward'ı tam ihtiyaç anında öldürür.
FEEDFORWARD_ERROR_GATE_PIXELS = (90.0, 360.0)

# Feedforward'ın bir denetim çevriminde değişebileceği en büyük miktar
# (derece). İki kapıdan sonra bile hız tahmini kare kare zıplayabiliyor;
# takibin akıcı değil kasıntılı görünmesinin doğrudan sebebi buydu.
# Ölçümde yön değiştirme sayısı 157'den 69'a indi, ortalama hata da
# 32.2'den 31.4 piksele düştü — yumuşatmanın bedeli yok.
FEEDFORWARD_MAX_STEP_DEGREE = 0.25

# Hedefin dünya açısal hızı için üst sınır (derece/sn). Gerçek hedefler
# 0.5-2.6 derece/sn; bu sınır hesap hatalarına karşı emniyet. Elle test
# ederken balonu hızlı gezdirmek 15-20 derece/sn üretebildiği için pay
# bırakıldı, ama eski 80 değeri gerçeğin 30 katıydı ve koruma sağlamıyordu.
MAX_TARGET_RATE_DEG_S = 30.0

# Hedef KAYBOLDUĞUNDA tahmin için kullanılan ayrı (ve dar) sınır.
# Feedforward ölçülen hızı kullanır, tahmin ise körlemesine ekstrapolasyondur.
PREDICTION_MAX_RATE_DEG_S = 8.0

# --- Ölü bant (duruşta titremeyi engeller) ---
# PİKSEL cinsinden tanımlı, çünkü gürültü kaynağı YOLO kutu merkezidir ve o
# piksel cinsinden oynar. 3x zoomda da geçerli: tespit gürültüsü ölçekten
# bağımsız olarak birkaç pikseldir. Avcıda 5 piksel = 0.089 derece =
# 15 metrede 2.3 cm.
PID_DEADBAND_PIXELS = 5.0
MIN_OUTPUT_PIXELS = 3.0

# Bir aday hedefe kilitlenmeden önce ard arda kaç karede aynı yerde görülmeli.
# YOLO tek tük yanlış pozitif üretiyor ve hayaletler 1-2 kare sürüyor.
LOCK_CONFIRM_FRAMES = 3

# Hedef kaybolduğunda kaç kare tahminle devam edilsin.
MAX_MISSING_FRAMES = 5


# =====================================================================
#  GÖZCÜ KAMERA — renk analizi
# =====================================================================
# Gözcü YOLO çalıştırmaz. Kırmızı ve mavi maskeler çıkarır, blobları bulur,
# balon adaylarını maketleriyle eşleştirir ve gövde çerçevesinde MUTLAK açı
# üretir.

# HSV aralıkları. OpenCV'de H 0-179; kırmızı iki uçta olduğu için iki aralık.
# Mavi doygunluk eşiği kasıtlı olarak yüksek (140): sahada soluk camgöbeği
# bir duvar S>100 ile eşiği kıl payı aşıp karenin %85'ini kaplayan sahte bir
# mavi tespit üretmişti. S>140 ile duvarın katkısı %0.16'ya düşüyor.
# Ortam siyah perdeyle kaplı ve aydınlatmalı olduğu için V alt sınırı düşük
# tutulabilir; parlama olursa yükseltin.
SPOTTER_RED_RANGES = [((0, 120, 70), (10, 255, 255)),
                      ((170, 120, 70), (179, 255, 255))]
SPOTTER_BLUE_RANGES = [((100, 140, 60), (130, 255, 255))]

# Bir blobun aday sayılması için gereken en küçük alan (piksel).
# 15 metrede 14 cm'lik balon gözcüde 10 piksel çap = ~79 piksel alan verir.
# Eşik bunun altında olmalı ama gürültüyü de elemeli.
SPOTTER_MIN_BLOB_AREA = 30

# Bir blobun en/boy oranı bu aralığın dışındaysa balon sayılmaz. Balon
# yuvarlaktır; uzun ince bir kırmızı leke maket parçası veya yansımadır.
SPOTTER_BALLOON_ASPECT = (0.5, 2.0)

# --- Dost/düşman ayrımı: "maviyi üstte ara" ---
# Aşama 3'te "en büyük kırmızı yoğunluk = düşman" kuralı ÇALIŞMAZ; mesafeye
# duyarlıdır. Örnek görselde ölçüldü (kırmızı piksel alanı):
#     yakın DOST  (mavi heli + kırmızı balon) : ~16.200
#     yakın DÜŞMAN (kırmızı drone + balon)    : ~43.300
#     uzak  DÜŞMAN (kırmızı F16 + balon)      :  ~3.600
# Yani uzak düşman, yakın dostun 4.5 katı daha az kırmızı veriyor ve sistem
# dostu seçiyor. Sebep: dostun altında da kırmızı balon var (kırmızı tabanı
# sıfır değil) ve alan mesafenin karesiyle ters orantılı.
#
# Bunun yerine GEOMETRİ kullanıyoruz: maket balonun hemen üstünde. Balonun
# KENDİ piksel çapıyla ölçeklenen bir pencereye bakıp mavi/kırmızı ORANINA
# karar veriyoruz. Oran mesafeden bağımsızdır.
#
# Pencere: balonun üstünde, balon çapının bu katları kadar.
SPOTTER_MODEL_WINDOW_ABOVE = (0.2, 3.5)   # (alt, üst) x balon çapı
SPOTTER_MODEL_WINDOW_WIDTH = 2.5          # yarı genişlik x balon çapı

# Penceredeki mavi oranı bunun üstündeyse DOST, altındaysa DÜŞMAN sayılır.
# Ara bölge "kararsız" olarak işaretlenir ve avcının doğrulamasına bırakılır.
SPOTTER_FRIEND_BLUE_RATIO = 0.60
SPOTTER_ENEMY_BLUE_RATIO = 0.25

# Gözcü izlerinin eşleştirme toleransı (derece) ve kaç kare kayıpta silinir.
SPOTTER_TRACK_MATCH_DEG = 3.0
SPOTTER_TRACK_MAX_MISS = 8


# =====================================================================
#  HEDEF ÇİFTİ EŞLEŞTİRME (avcı / YOLO tarafı)
# =====================================================================
# data.yaml'da TEK bir 'balon' sınıfı var — balon dost/düşman bilgisi
# taşımıyor. Karar zorunlu olarak üstündeki maketten geliyor. Bu yüzden
# takip birimi artık tek nesne değil, bir ÇİFT.

# Balon, maketin altında ve yatayda hizalı olmalı. Ölçüler maketin kutu
# genişliğine göre normalize edilir, böylece mesafeden bağımsız çalışır.
PAIR_MAX_HORIZONTAL_OFFSET = 1.0   # |dx| <= bu x maket_genisligi
PAIR_VERTICAL_RANGE = (0.0, 2.5)   # balon merkezi maketin altında, bu aralıkta
                                   # (x maket_genisligi)

# Balon maketten büyük olamaz (14 cm balon, 40-50 cm maket).
PAIR_MAX_BALLOON_RATIO = 0.8       # balon_genisligi / maket_genisligi

# Balon tespiti zayıfsa nişan noktası maketten türetilir. 15 metrede balon
# avcıda 30 piksel — YOLO için küçük-nesne sınırı; maket 96 piksel, rahat.
# Nişan noktası = maket_merkezi + (0, bu_kat x maket_genisligi)
PAIR_FALLBACK_AIM_OFFSET = 0.75
PAIR_ALLOW_FALLBACK_AIM = True


# =====================================================================
#  ANGAJMAN DURUM MAKİNESİ
# =====================================================================
# Taretin gözcünün verdiği açıya oturduğu kabul edilen tolerans (derece).
ENGAGE_SLEW_TOLERANCE_DEG = 1.0

# Durum zaman aşımları (saniye). Hızlı imha modunda takılıp kalmak yanlış
# yöne gitmekten pahalıdır.
ENGAGE_SLEW_TIMEOUT = 2.5
ENGAGE_VERIFY_TIMEOUT = 1.5
ENGAGE_LOCK_TIMEOUT = 8.0

# Doğrulama: maket sınıfı kaç kare üst üste aynı çıkmalı, hangi güvenin
# üstünde. Aşama 3'te dost vurmak diskalifiye olduğu için katı tutuldu.
VERIFY_CONFIRM_FRAMES = 4
VERIFY_MIN_CONFIDENCE = 0.55

# Nişan toleransı: hata balonun YARIÇAPININ bu oranından küçük olmalı.
# Piksel yerine orana bağlamak hem mesafeden hem zoomdan bağımsız kılar
# (balon 15 metrede 30 px, 5 metrede 90 px).
AIM_TOLERANCE_RATIO = 0.35

# Nişan toleransı ayrıca bu mutlak piksel değerinin altına inmek zorunda
# değil — çok yakın hedefte gereksiz katılık yapmasın diye alt sınır.
AIM_TOLERANCE_MIN_PIXELS = 6.0

# Ateşten önce nişan kaç kare korunmalı.
AIM_HOLD_FRAMES = 3

# Kara liste: doğrulamada DOST çıkan veya imha edilen hedefler buraya girer.
# Gövde çerçevesinde MUTLAK açı olarak tutulur (piksel uzayında tutmak
# anlamsız, taret döndükçe referans kayar).
BLACKLIST_RADIUS_DEG = 4.0
BLACKLIST_TTL_SEC = 12.0          # imha edilenler için
BLACKLIST_FRIEND_TTL_SEC = 600.0  # dost maketler için pratikte kalıcı

# Balistik: 15 metrede mermi düşüşünü telafi eden sabit pitch ofseti
# (derece, pozitif = yukarı nişan al). SAHADA ÖLÇÜLMELİ; ölçülene kadar 0.
BALLISTIC_PITCH_OFFSET = 0.0


# =====================================================================
#  HAYALET TESPİT FİLTRESİ (renk tutarlılığı)
# =====================================================================
# Sınıf adı bir renk ima ediyorsa (dost- mavi, dusman- kırmızı, balon
# kırmızı), kutunun içinde gerçekten o renk olmalı. Sahada ölçüldü: tek
# balonlu sahnede karelerin %41.7'sinde hayalet tespit vardı. Kutu içeriği
# gerçek balonda ortalama %77, hayalette %0.1 kırmızıydı. %5 eşikle 813
# gerçek tespitin hiçbiri kaybolmadı, 338 hayaletin %99'u elendi.
#
# YENİ MİMARİDE AYRICA KRİTİK: dost-F16 ile dusman-F16 aynı geometriye
# sahip, YOLO'nun onları ayırdığı tek şey RENK. Bu filtre, modelin renk
# kararını bağımsız olarak çapraz doğrular.
DETECTION_COLOR_CHECK = True
DETECTION_COLOR_MIN_RATIO = 0.05

# Kutu karenin bu oranından büyükse tespit saçmadır.
DETECTION_MAX_AREA_RATIO = 0.25

# Bir adayın mevcut hedefin yerine geçebilmesi için gereken güven farkı.
ACQUIRE_CONFIDENCE_MARGIN = 0.15
