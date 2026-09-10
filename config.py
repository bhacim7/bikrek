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

# Kamera karesini model girişine küçültürken kullanılacak süzgeç.
#
# "LINEAR" (OpenCV varsayılanı) küçültmede yalnızca birkaç komşu pikseli
# örnekler; 1.4 kattan büyük küçültmelerde aradaki pikselleri ATLAR, yani
# aliasing ve gürültü geçirir. "AREA" küçültülen alanın TAMAMINI ortalar:
# doğru süzgeç budur ve ortalama aldığı için sensör gürültüsünü de düşürür.
#
# 1920x1080 -> 1056x608 küçültmesi 1.82 kat olduğu için AREA seçildi.
# Kaynak 1280x720 olsaydı (1.21 kat) ikisi arasında pratik fark olmazdı.
#
# NOT: eğitim tarafı (Ultralytics) LINEAR kullanır, yani AREA küçük bir
# eğitim/çıkarım farkı yaratır. `yolo_kalite.py` ikisini GERÇEK modelle
# ölçüp karşılaştırır; karar tahminle değil o ölçümle verilmeli.
MODEL_RESIZE_INTERPOLATION = "AREA"   # "AREA" veya "LINEAR"

# Kamera karesini MODELİN EN/BOY ORANINA kırp.
#
# Arducam modülü 1920x1080 istense de 1920x1200 (16:10 = 1.600) veriyor.
# Model girişi 1056x608 = 1.737. Aradaki fark yeniden ölçeklemede YATAY
# GERİLME olarak geçiyor: %7.9. Model bugüne kadar 16:9 kaynaktan beslendi,
# yani bu gerilme eğitimde hiç görülmemiş bir bozulma.
#
# Çözüm kareyi ortadan kırpmak. Kırpma derece/pikseli DEĞİŞTİRMEZ (aynı
# optik, aynı piksel), yalnızca dikey görüş açısını kısaltır:
#     1920x1200 -> 16.3 derece dikey
#     1920x1105 -> 15.0 derece dikey   (devir teslim için gereken 5'ten fazla)
#
# Kırpma KAMERA SÜRECİNDE yapılıyor; böylece boru hattının tamamı (çıkarım,
# PID, nişan merkezi, kalibrasyon) tek ve tutarlı bir kare boyutu görüyor.
# Sonradan kırpmak, tespit kutularının kırpma ofsetiyle geri taşınmasını
# gerektirirdi — sessiz koordinat hatası üretmeye çok müsait bir yol.
HUNTER_CROP_TO_MODEL_ASPECT = True

# --- RPi Bağlantısı ---
# --- Yaw enkoder kaydı (FAZ 4: ölçek / boşluk / kaçırma ayrımı) ---
# True iken arayüz, Pi'den gelen her açı raporunu CSV'ye yazar:
#   zaman, adım sayacı yaw, pitch, enkoder yaw, enkoder ok, ham sayım
# Dosya: ENCODER_LOG_DIR/enkoder_YYYYmmdd_HHMMSS.csv (arayüz her açılışta yeni).
# Çözümleme: `python enkoder_analiz.py <csv>` (duruşları bulur, ölçek ve
# boşluğu ayırır). Ölçüm bitince False yapılabilir; yük ihmal edilebilir
# (50 satır/sn).
ENCODER_LOG = True
ENCODER_LOG_DIR = os.path.join(_BURASI, "enkoder_kayit")

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
#
# DİKKAT: avcı kamera Logitech'ten Arducam B0495C'ye değiştiği için
# indeksler büyük ihtimalle KAYDI. `python kamera_tani.py` çalıştırıp
# aşağıdaki listeleri yeniden ayarlayın; ilk deneme listedeki sırayla yapılır.
HUNTER_CAMERA_INDICES = [1, 3, 4]
SPOTTER_CAMERA_INDICES = [2, 3, 4]

SPOTTER_WIDTH = 1280
SPOTTER_HEIGHT = 720
SPOTTER_USE_MJPG = True

# AVCI: Arducam B0495C (AR0234 global shutter, 2.3 MP, USB3) + 12 mm sabit lens.
#
# 1920x1080. Bu karar SAHADA ÖLÇÜLEREK değişti; önce 1280x720 seçilmişti.
#
# Kâğıt üstündeki gerekçe 1280 lehineydi: model girişi 1056x608 olduğu için
# 1280 -> 1056 yalnızca 1.21 kat küçültme, 1920 -> 1056 ise 1.82 kat.
# AMA sahada görüldü ki bu modülün 1280x720 modu sensörü ÖLÇEKLEMİYOR,
# SATIR ATLIYOR (decimation): karanlık bölgelerde renkli benek ve moire
# çıkıyor. Atlanan satırın bilgisi geri gelmez — yazılımla düzeltilemez.
#
# 1920x1080 tam okuma yapıyor ve görüntü temiz. Temiz kaynaktan 1.82 kat
# küçültmek, kirli kaynaktan 1.21 kat küçültmekten iyi. Ölçüm kaydı:
# `kamera_kalite.py` ve `yolo_kalite.py`.
#
# 1920x1200 DEĞİL çünkü 16:10; model girişi 1056/608 = 1.737 (16:9'a yakın)
# olduğu için en-boy bozulması %2.3'ten %8.5'e çıkardı.
#
# Bedeli: kare başına 2.25 kat fazla piksel = daha fazla USB bandı ve
# yeniden ölçekleme, yani biraz daha ölü zaman. CAPTURE_LATENCY_OFFSET
# taramasında bu hesaba katılmalı.
# YÜKSEKLİK 1200 — 1080 İSTENSE DE MODÜL 1200 VERİYOR.
# Sahada doğrulandı: arayüzde pixmap 1728x1080 çıkıyor (16:10'un 1080
# satıra sığdırılmış hali) ve kalibrasyon aracı dikey görüş açısını 16
# derece ölçüyor — 1080 satırla bu 14.6 derece çıkardı. Config'in gerçeği
# yansıtması şart: görüş açısı, piksel eşikleri ve testlerdeki ölçek
# kontrolleri buradan türetiliyor.
#
# BEDELİ — EN/BOY BOZULMASI: 1920x1200 (1.600) kare model girişine
# 1056x608'e (1.737) ezilirken yatayda %8.6 geriliyor; model bugüne kadar
# 16:9 kaynaktan beslendi. Çözüm çıkarımdan önce ortadan 1920x1080'e
# KIRPMAK olurdu (dikey görüş 16.3 -> 14.7 derece; devir teslim için
# gereken 5 dereceden hâlâ fazla). Henüz yapılmadı — `yolo_kalite.py`
# ile ölçülüp karar verilmeli.
HUNTER_WIDTH = 1920
HUNTER_HEIGHT = 1200

# MJPG KAPALI. True iken kod FOURCC'yi MJPG'ye ZORLUYOR; MJPG kayıplı
# sıkıştırmadır ve avcıda gördüğümüz ince detay (15 metrede 25 pikselllik
# balon) tam olarak sıkıştırmanın attığı bölgede. Logitech USB2 iken MJPG
# zorunluydu (bant genişliği), Arducam USB3'te değil: 1280x720 sıkıştırmasız
# YUY2 = 55 MB/s, USB3'ün onda biri.
#
# False olduğunda kod FOURCC'ye HİÇ DOKUNMUYOR, sürücü kendi varsayılanını
# seçiyor. Yani bu ayar "kamerayı olduğu gibi aç" demek.
#
# Kamera açılışında konsola yazılan satırda gerçekleşen format ve fps var.
# Kare hızı 30'un belirgin altına düşerse buraya True'ya dön.
HUNTER_USE_MJPG = False

# --- UVC DENETİMLERİ (beyaz dengesi, pozlama, odak) ---
#
# Bu blok EKSİKTİ: yukarıdaki yorum "otomatik pozlama ve otomatik beyaz
# dengesi KAPALI olmalı" diyordu ama kod bunların hiçbirine dokunmuyordu.
# Sürücü varsayılanı çoğu UVC kamerada OTOMATİK olduğu için sahada:
#   - beyaz dengesi kayıyor (gözcünün renk filtresi ve hayalet eleyici
#     SABİT renk eşikleri varsayıyor),
#   - otomatik pozlama kare kare süreyi değiştirip ölü zaman telafisini
#     bozuyor (CAPTURE_LATENCY_OFFSET sabit varsayılıyor),
#   - Logitech'in otomatik odağı avlanıyor.
#
# DEĞER YAZIM KURALI:
#   None  -> o denetime HİÇ DOKUNMA (sürücü ne yapıyorsa o kalsın)
#   sayı  -> ayarlamayı dene ve geri okuyup konsola yaz
#
# `exposure` DirectShow'da log2(saniye)'dir ve sürücüye göre değişir:
#   -5 = 1/32 s = 31 ms | -6 = 1/64 s = 16 ms | -7 = 1/128 s = 7.8 ms
# Hedefimiz ~10 ms, yani -6 veya -7. GÖRÜNTÜ KARARIRSA önce -5'e çıkın,
# yetmezse `gain` ile telafi edin; ikisi de olmuyorsa `None` yapıp
# otomatiğe bırakın (bulanıklık artar ama en azından görürsünüz).
#
# `auto_exposure` DirectShow'da 0.25 = MANUEL, 0.75 = OTOMATİK'tir. Bazı
# sürücüler 1/3 kullanır; geri okuma satırından hangisinin tuttuğu görülür.
#
# BAŞLANGIÇ AYARI KASITLI OLARAK MUHAFAZAKÂR: yalnızca görüntüyü
# karartma riski OLMAYAN denetimler açık (beyaz dengesi, odak). Pozlama
# sahada ölçüldükten sonra açılacak.
KAMERA_KONTROLLERI = {
    "spotter": {
        "autofocus": 0,          # Logitech'in otomatik odağı avlanmasın
        "focus": None,           # sahada elle ayarlanıp buraya yazılabilir
        "auto_wb": 0,            # renk eşikleri sabit renk varsayıyor
        "wb_temperature": 4600,  # tipik iç mekân floresan
        "auto_exposure": None,   # ölçümden sonra 0.25 yapılacak
        "exposure": None,        # ölçümden sonra -6 / -7
        "gain": None,
        "brightness": None,
        "contrast": None,
        "saturation": None,
        "sharpness": None,
        "gamma": None,
    },
    "hunter": {
        "autofocus": None,       # 12 mm sabit lens, odak halkadan
        "focus": None,
        # 2026-09-09 ölçümü (kamera_renk.py): bu modül DirectShow'dan
        # beyaz dengesi sıcaklığı KABUL ETMİYOR (okuma -1), yani eski 4600
        # hiç uygulanmamıştı; auto_wb=0 kamerayı yanlış bir iç dengede
        # kilitliyordu (her şey kırmızı). auto_wb=1 ile beyaz kâğıt R/G 1.12,
        # B/G 1.00. Otomatik denge sahneye göre biraz kayar; avcı renk eşiği
        # kullanmadığı (YOLO) için kabul edilebilir.
        "auto_wb": 1,
        "wb_temperature": None,
        "auto_exposure": None,
        "exposure": None,
        "gain": None,
        "brightness": None,
        "contrast": None,
        "saturation": None,
        "sharpness": None,
        "gamma": None,
    },
}

# camera_module tek bir sözlükten okur; yeni bir kamera eklemek için buraya
# bir satır yetiyor.
KAMERA_AYARLARI = {
    "spotter": {"indices": SPOTTER_CAMERA_INDICES, "width": SPOTTER_WIDTH,
                "height": SPOTTER_HEIGHT, "mjpg": SPOTTER_USE_MJPG},
    "hunter":  {"indices": HUNTER_CAMERA_INDICES, "width": HUNTER_WIDTH,
                "height": HUNTER_HEIGHT, "mjpg": HUNTER_USE_MJPG},
}

# --- YAZILIM BEYAZ DENGESİ (avcı) ---
# Sürücü beyaz dengesi sıcaklığını kabul etmiyorsa (DirectShow'da bazı
# Arducam modüllerinde CAP_PROP_WB_TEMPERATURE "TUTMADI" döner) kanal
# kazançları burada uygulanır: kare = kare * (B, G, R). `kamera_renk.py`
# 'k' tuşu ortadaki gri kâğıttan hesaplar. None = kapalı. Kazanç, kare
# kameradan çıkar çıkmaz uygulanır; YOLO ve arayüz aynı düzeltilmiş kareyi
# görür (model nötr renkli kaynaktan eğitildi, düzeltme lehine).
HUNTER_WB_GAINS = None      # örn. (0.95, 1.0, 0.78)

# --- KARANLIKTA DOYGUNLUK KIRMA (avcı, IR sızıntısına karşı geçici) ---
# 12 mm lenste IR-cut filtre yok: siyah kumaş kızılötesini yansıtıyor,
# sensörün R ve B filtreleri kızılötesini geçiriyor -> siyah perde MOR
# (ölçüm: perdede R/G 2.65, B/G 1.95; beyaz kâğıtta 1.12 / 1.00 — tek bir
# beyaz dengesi kazancı ikisini birden düzeltemez). Kalıcı çözüm lense
# 650 nm IR-cut filtre. O gelene kadar: parlaklığı (Y) alt eşiğin altındaki
# pikseller griye çekilir, üst eşiğin üstündekilere dokunulmaz, arası
# doğrusal. Balonlar/maketler parlak (Y > 60) olduğu için etkilenmez.
# (alt, ust) Y eşikleri, 0-255. None = kapalı. `kamera_renk.py` 'd' tuşu
# ile önizlenir. Bedeli: 1920x1200'de ~6-8 ms CPU/kare (kamera sürecinde).
# --- MACENTA KIRMA (avcı, IR sızıntısına karşı; gün ışığında ŞART) ---
# Kızılötesi R ve B kanallarını birlikte yükseltir, G'yi yükseltmez
# (ölçüm: perdede R/G 2.65, B/G 1.95). Gün ışığında siyah perde PARLAK
# PEMBE olur; karanlıkta doygunluk kırma parlak pikseli görmez.
# Burada: m = max(0, min(R, B) - G) ; R -= m·güç ; B -= m·güç.
# m yalnızca R ve B'nin İKİSİ de G'den yüksekken sıfırdan büyük, yani:
#   kırmızı balon (B < G)  -> m = 0, DOKUNULMAZ
#   mavi maket   (R < G)   -> m = 0, DOKUNULMAZ (mor kayması varsa azalır)
#   ten, zemin   (B < G)   -> DOKUNULMAZ
#   pembe perde  (R,B > G) -> griye çekilir
# Güç 0..1; 1.0 = ortak fazlalığın tamamı. None/0 = kapalı. ~4 ms/kare.
# IR-cut filtre takılınca None. `kamera_renk.py` 'm' ile önizlenir.
HUNTER_MAGENTA_KIR = 1.0

# Nötr-macenta KARARTMA: kızılötesi G'ye de giriyor, bu yüzden macenta
# kırma sonrası siyah perde GRİ kalıyor (kalan G düzeyi de IR). R ≈ B olan
# (renksiz nesne üstünde IR) piksellerde üç kanal da  m · KARART · nötrlük
# kadar düşürülür; nötrlük = 1 − |R−B| / NOTR_ESIK (0'a kırpılır). Kırmızı
# balon ve mavi maket |R−B| büyük olduğu için nötrlük 0, DOKUNULMAZ.
#   perde (175,130,190) -> macenta kırma (130,130,145) -> karartma (46,46,61)
# 0 = kapalı. Sınır: pembeleşmiş KIRMIZI nesne (füze) bu formülle kurtulmaz,
# |R−B| büyük olduğu için; onu ancak IR-cut filtre düzeltir.
# 2026-09-10: 2.5 sahada perdeyi BENEK BENEK yaptı (gain 168 gürültüsü
# katsayıyla büyüdü). Yumuşatma eklendi ama varsayılan KAPALI; gri perde
# benekli perdeden iyidir. Denemek için kamera_renk.py 'n' ile 1.0-1.5.
HUNTER_MAGENTA_KARART = 0
HUNTER_MAGENTA_NOTR_ESIK = 60

# --- KIRMIZI KURTARMA (avcı, IR sızıntısına karşı; gün ışığında füze/balon) ---
# Kızılötesi kırmızı nesnede B'yi G'nin ÜSTÜNE çıkarır: kırmızı + sahte mavi
# = PEMBE; YOLO kırmızı öğrendi, pembeyi kaçırıyor (2026-09-10 saha).
# Baskın kırmızı piksellerde (R − G ≥ ESIK ve R > B):
#     B := min(B, G)                 (sahte maviyi at)
#     G, B *= (1 − GUC)              (dataset'teki doygun kırmızıya yaklaş)
# Eşik 80: füze/balon R−G 120–190 -> girer; ten ~50, zemin ~20, pembe perde
# ~60 -> girmez. Kırmızı olmayan hiçbir piksele dokunmaz. None/0 = kapalı.
HUNTER_KIRMIZI_ESIK = 80
HUNTER_KIRMIZI_GUC = 0.3

HUNTER_DARK_DESAT = None       # 2026-09-10: macenta kirma karanlik mor perdeyi de griye
                               # cektigi icin gereksiz kaldi; 6 ms/kare tasarruf. (5, 50) idi.

# Pozlama süresi üst sınırı (saniye). Hareket bulanıklığı =
# taret_hızı x pozlama / derece_piksel.
#
# GLOBAL SHUTTER YANLIŞ ANLAŞILMASIN: AR0234 global shutter olduğu için
# yalnızca ROLLING SHUTTER ÇARPILMASI (hızlı dönüşte dikey çizgilerin
# eğrilmesi) ortadan kalkar. HAREKET BULANIKLIĞI tamamen pozlama süresine
# bağlıdır ve global shutter onu azaltmaz — pozlama yine kısaltılmalıdır.
#
# Yeni avcıda (0.014324 derece/piksel, 1920x1080):
#   pozlama 33 ms (1/30 s), taret 89 derece/sn  -> 205 piksel bulanıklık
#   pozlama 10 ms, taret 89 derece/sn           ->  62 piksel
#   pozlama 10 ms, taret  3 derece/sn (takip)   ->   2.1 piksel
# Balon avcıda 15 metrede 37 piksel; 33 ms'de tamamen sıvanır.
#
# Bu değer bilgi amaçlı burada; kamerada ELLE ayarlanmalı (OpenCV'nin
# CAP_PROP_EXPOSURE davranışı sürücüye göre değişiyor, güvenilir değil).
# Arducam modülleri UVC uyumlu; Windows Kamera uygulamasından veya
# Arducam'in kendi aracından manuel pozlama + manuel beyaz dengesi ayarlanır.
CAMERA_TARGET_EXPOSURE_SEC = 0.010

# Çıkarım sürecinden ARAYÜZE gönderilen karenin genişliği (piksel).
# TESPİTİ ETKİLEMEZ — YOLO her zaman ham kareyi görür; bu yalnızca IPC
# yükünü azaltmak için küçültülen GÖSTERİM kopyasıdır.
#
# 810 idi ve sahada "kamera bulanık" olarak görüldü. Zincir şuydu:
#   1280x720 kare -> 810x456'ya küçült (IPC) -> 1920x1080 etikete BÜYÜT
# yani önce detay atılıyor, sonra 2.37 kat geri şişiriliyor. Windows Kamera
# uygulamasının daha net görünmesinin sebebi buydu; kameranın kendisiyle
# ilgisi yoktu.
#
# HUNTER_WIDTH'e eşit veya büyük olduğunda küçültme HİÇ yapılmaz (kare
# olduğu gibi gider) ve çizim ölçeği 1.0 olur, yani kutular/yazılar ham
# piksellere birebir oturur.
#
# Bedeli IPC: kare başına 1.1 MB yerine 2.8 MB. Kare hızı düşerse veya
# gecikme artarsa 960'a çekilebilir.
# 1280 -> 1600: avci paneli artik ESNEK ve maksimize pencerede ~1810
# piksele kadar aciliyor. 1280'lik kare oraya %41 gerilerek cizilirdi.
# 1600 ile gerilme %13'e iniyor; 1920 yapilirsa hic gerilme kalmaz ama
# IPC kare basina 6.4 MB'a cikar. Kare hizi duserse buradan geri cekilir.
DISPLAY_WIDTH = 1600


# =====================================================================
#  ARAYUZ YERLESIMI
# =====================================================================
# Bu degerler YALNIZCA gorunumu belirler. Tespit, PID, kalibrasyon ve nisan
# matematiginin tamami HAM kare koordinatlarinda yurur (bkz. `frame_orig_w`);
# arayuze giden kare salt okunur bir GOSTERIM kopyasidir. Yani buradaki
# sayilari degistirmek hicbir ayari bozmaz.
#
# Tek bagli nokta fare tiklamasi: `_etiket_to_kare` donusumu pixmap
# geometrisini CALISMA ANINDA okur (sabit sayi kullanmaz), bu yuzden boyut
# degisince kendiliginden uyar. Sarti: camera_label'in Qt.AlignCenter
# hizalamasi korunmali.
UI_AVCI_GENISLIK = 1280      # avci panelinin genisligi (piksel)
UI_GOZCU_GENISLIK = 760      # gozcu panelinin genisligi; gozcu onizlemesi
                             # bu genislikte URETILIR (spotter_module), yani
                             # buyutunce gerilme olmaz, gercekten netlesir.
                             # IPC: 640x360 -> ~690 KB/kare, 5 Hz'de gider.
UI_SAG_PANEL_PAYI = 44       # gozcu panelinin saginda/solunda kalan bosluk
                             # (GOREVLER|KONTROL yan yana sigsin diye genis)


def ui_avci_etiket_boyutu():
    """
    Avci etiketinin (QLabel) piksel boyutu.

    Yukseklik kare EN-BOY ORANINDAN turetiliyor; sabit yazilsaydi (orn.
    1280x720) pixmap KeepAspectRatio ile 1280x737 olmak isteyip 720'ye
    sigdirilir ve yanlarda bosluk kalirdi. Oranla hesaplayinca goruntu
    etikete TAM oturur, bosluk olmaz.
    """
    kare_g, kare_y = hunter_etkin_kare()
    yuk = int(round(UI_AVCI_GENISLIK * kare_y / float(kare_g)))
    return UI_AVCI_GENISLIK, yuk


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

# AVCI: Arducam B0495C (AR0234) + 12 mm sabit lens.
# Zoomlu Logitech'in yerine geçti; artık değer tahmin değil OPTİKTEN türetildi:
#
#   AR0234 piksel boyutu 3.0 um, odak uzaklığı 12 mm, dizi 1920x1200
#   sensör piksel başına = atan(0.0030 / 12) = 0.014324 derece
#   tam genişlik 1920 x 3.0 um = 5.76 mm -> yatay görüş açısı 27.0 derece
#
# 1920 GENİŞLİK sensörün tam genişliği olduğu için görüntü piksel başına açı
# doğrudan sensör değerine eşittir:
#   0.014324 derece/piksel
#   görüş açısı 1920 x 0.014324 = 27.5 derece yatay / 15.5 derece dikey
#
# DİKKAT — ÇÖZÜNÜRLÜK DEĞİŞİRSE BU DEĞER DE DEĞİŞİR. 1280x720'ye dönülürse
# aynı görüş açısı 1280 piksele sığar, yani derece/piksel 1.5 KATINA çıkar
# (0.021486) ve aşağıdaki açısal eşiklerin hepsi 1.5'e BÖLÜNMELİDİR.
# Sahada bir kez bu ikisi ayrı düştü ve ima edilen görüş açısı 41 derece
# olarak hesaplandı; PID kazancı sessizce 1.5 kat yanlış çalışıyordu.
# `tests_yeni_mimari.py` 11. bölüm artık bu tutarlılığı kontrol ediyor.
#
# HER HALÜKÂRDA "Derece/Piksel Ölç" İLE DOĞRULANMALI.
#
# Eski (3x zoom, ölçülmemiş) değerler: 0.01783 / -0.01849, 1280x720'de.
# Yeni lens ESKİSİNDEN BİRAZ GENİŞ (27.5 yerine 22.8 derece); 15 metrede
# balon modele giren karede ~%17 daha küçük görünüyor (25 px yerine 20 px).
# Tespit zayıflarsa çözüm 16 mm lens; yazılımda ayarlanacak bir şey yok.
# İKİ EKSEN AYNI DEĞERDE — FİZİKSEL ZORUNLULUK.
# AR0234 pikselleri kare (3.0 x 3.0 um) ve lens rektilineer; bu durumda
# |derece/piksel| iki eksende AYNI olmak zorundadır. Kalibrasyon aracı
# şunları ölçtü:
#     yaw  : 0.01374 , 0.01592   (aralarında %16 fark)
#     pitch: 0.01335 , 0.01362   (aralarında %2 fark)
# Pitch ölçümü sıkı, yaw ölçümü dağınık. Muhtemel sebep yaw'daki 10:30
# DÜZ DİŞLİ BOŞLUĞU: kalibrasyon ileri ve geri hareket yapıyor, yön
# değişiminde boşluk kadar hareket yutuluyor, o yönün ölçümü yüksek
# çıkıyor. (Pitch'te planet redüktör var, boşluğu 1-2 açı dakikası.)
# Birbirini tutan üç ölçümün ortalaması alındı: 0.01374, 0.01335, 0.01362
# -> 0.01357, yuvarlanarak 0.01360. İma ettiği odak uzaklığı 12.6 mm,
# yani takılan 12 mm lensle uyumlu.
#
# YAW ÖLÇÜMÜNÜ 2-3 KEZ TEKRARLAYIN. Sürekli pitch'ten yüksek çıkıyorsa
# fark dişli boşluğudur ve ayrıca ölçülmesi gerekir (yön değiştirirken
# kaç derece kayboluyor).
#
# 2026-09-09, ENKODER HİZALAMASI AÇIKKEN yeniden ölçüldü:
#     yaw  : 0.01415, 0.01408   tutarlı
#     pitch: 0.01405, 0.01420   tutarlı
#     görüş açısı 27 x 16 derece (12 mm lensle birebir)
# Yaw ile pitch artık binde 1 içinde EŞİT (0.999). Eski %5'lik fark
# (0.01430 / 0.01360) boşluğun iziydi: komut edilen yaw tarette eksik
# gerçekleşiyor, kalibrasyon o eksikliği "derece/piksel" sanıyordu. FAZ 5'
# hizalaması komut = gerçek yapınca iz kayboldu. Eski yaw değeri tek
# atımlık komutlarda (tıklama, gözcüden yönelme) %1.3 fazlalık üretiyordu;
# bu değerle o da gitti. Boşluk artık burada değil, enkoderde ele alınıyor.
HUNTER_DPP_YAW = 0.01411
HUNTER_DPP_PITCH = -0.01413

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
# DEĞERLER KAMERA DEĞİŞTİKÇE YENİDEN ÖLÇEKLENİYOR. Kapının koruduğu şey
# AÇISAL bir olgu; geniş kamerada (30, 120) piksel = (1.6, 6.4) dereceydi.
# Aynı açıyı korumak için piksel değerleri derece/piksel ile ters orantılı
# ölçeklenmeli, yoksa kapı hedefi takip ederken bile kapanır ve
# feedforward'ı tam ihtiyaç anında öldürür.
#   3x zoomlu Logitech (0.01783  d/px) -> (90, 360)
#   AR0234 + 12 mm     (0.014324 d/px) -> (112, 448)   <- 1920x1080
FEEDFORWARD_ERROR_GATE_PIXELS = (112.0, 448.0)

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
# 8.0 IDI VE HICBIR KORUMA SAGLAMIYORDU: FAZ 1'de hedef GERCEKTEN sabitken
# sistemin hesapladigi sahte hedef hizi 8.1 derece/sn olculmustu. Yani sinir
# tam olarak gurultu seviyesindeydi ve hayaletin 0.36 saniyede 2.9 derece
# (212 piksel) gezmesine izin veriyordu.
# Gercek yarisma hedefleri 0.6-2.1 derece/sn. 2.5 en hizlisinin %20 ustunde,
# yani gercek hareketi tam kapsiyor; gurultuye birakilan pay ise ucte bir.
PREDICTION_MAX_RATE_DEG_S = 2.5

# --- Ölü bant (duruşta titremeyi engeller) ---
# PİKSEL cinsinden tanımlı, çünkü gürültü kaynağı YOLO kutu merkezidir.
#
# ZOOM veya LENS bu değeri etkilemez; etkileyen tek şey KAYNAK ÇÖZÜNÜRLÜK
# olur, çünkü kutu gürültüsü model giriş uzayında (1056x608) kabaca sabittir
# ve kaynak piksele geri ölçeklenirken kare genişliğiyle çarpılır.
#   1280 genişlik -> gürültü x 1280/1056 = 1.21
#   1920 genişlik -> gürültü x 1920/1056 = 1.82   (1.5 kat artış)
# 1920x1080'e geçildiği için eşikler 1.5 katına çıkarıldı.
# 7 piksel = 0.100 derece = 15 metrede 2.6 cm (1280'de 5 px = 0.107 idi),
# yani açısal anlamı neredeyse aynı kaldı.
PID_DEADBAND_PIXELS = 7.0
MIN_OUTPUT_PIXELS = 4.0

# --- REZONANS SONUMLEME (PID cikis suzgeci) ---
#
# SAHADA OLCULDU (anavlizaşama2/3): kilit sirasindaki salinimin %91-96'si
# taretin KENDI hareketi (balon ve maket kutulari +0.93 korelasyonla birlikte
# kayiyor, yani YOLO gurultusu degil). FFT ile baskin frekans 2.24-3.15 Hz;
# FAZ 3'te olculen YAPISAL REZONANS 2.7 Hz (0.37 sn) ile ayni bant.
#
# Sebep klasik: denetleyici saf oransal (KD = 0.001, pratikte etkisiz) ve
# donguде ~185 ms olu zaman var (kamera + IPC + YOLO + soket + motor).
# Olu zamanli bir sistemde saf P, kazanc yeterince yuksekse o frekansta
# salinir -- sonumleyecek terim yok.
#
# COZUM: PID cikisina birinci derece alcak geciren suzgec. Kesim frekansi
#     fc = -ln(1 - a) * fs / (2*pi)
# a = 0.30, fs = 30 Hz  ->  fc = 1.70 Hz
#     2.7 Hz'de kazanc 0.53 (%47 bastirma)
#     3.15 Hz'de kazanc 0.47
# DC (yavas yonelme) kazanci 1.0 kalir, yani hedefe oturma HIZI degismez;
# yalnizca rezonans bandindaki bileseni kesilir.
#
# 0.0 yazilirsa suzgec KAPANIR (eski davranis). Sahada salinim hala buyukse
# once bu deger kucultulmeli (0.20), yetmezse KP dusurulmeli.
PID_OUTPUT_SMOOTHING = 0.30

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
# SAHADA OLCULEREK AYARLANDI (gozcu_tani.py, siyah perde ortami).
# Eski deger ((100,140,60),(130,255,255)) idi ve DOST HIC TANINMIYORDU:
# mavi maketin olculen doygunlugu S medyan 32, %90'lik dilim 60 -- yani
# esigin (140) cok altinda. Maket penceresinde 0 mavi piksel cikiyor,
# mavi_oran 0.00 oluyor ve DOST 'dusman' olarak isaretleniyordu.
#
# Esik taramasi (dost penceresi 125 kirmizi, dusman penceresi 64 kirmizi):
#   S>=40           -> dusman penceresi de mavi okunuyor (siyah perde),
#                      dusman DOST sanilir. TEHLIKELI YON BU.
#   S>=60, V>=40    -> dost 0.81 / dusman 0.045   dogru
#   S>=80, V>=45    -> dost 0.79 / dusman 0.00    EN GENIS MARJ (secildi)
#   S>=120          -> dost 'kararsiz'a duser
#   S>=140 (eski)   -> dost 0.37 kararsiz, temizlikten sonra 0 -> dusman
# Hue araligi 90-135, tarama bu aralikla dogrulandi.
#
# DIKKAT: `inference_module._MAVI` ile BIRLIKTE degismeli. Orada gevsek
# kalirsa sorun olmaz ama KATI kalirsa YOLO'nun dost-* tespitleri renk
# tutarlilik kontrolunden elenir ve dost hic taninmaz.
SPOTTER_BLUE_RANGES = [((90, 80, 45), (135, 255, 255))]

# Bir blobun aday sayılması için gereken en küçük alan (piksel).
# 15 metrede 14 cm'lik balon gözcüde 10 piksel çap = ~79 piksel alan verir.
# Eşik bunun altında olmalı ama gürültüyü de elemeli.
# 60 -> 30 GERI ALINDI. 60 sahada GERCEK BALONU eledi: analizaşama3.mp4
# kaydinda gozcu panelinde fuzenin altindaki balon "alan 34<60" etiketiyle
# elenmis gorunuyor. 60 degeri tek bir karedeki maket olcumune bakilarak
# onerilmisti; balonun gozcudeki gercek gorunumu (kucuk, kismen maskelenen)
# hesaba katilmamisti.
#
# DENGE: gozcu esigi KATI olursa gercek hedef kacirilir (gorev basarisiz),
# GEVSEK olursa bosuna gidilir (dogrulamada ~1.5 sn kayip). Gozcunun karari
# zaten baglayici degil -- avci dogruluyor -- ve artik dogrulama balonu sart
# kosuyor (VERIFY_MIN_BALLOON_FRAMES), yani bosuna gidisin bedeli kucuk.
# Bu yuzden gevsek taraf tercih ediliyor.
SPOTTER_MIN_BLOB_AREA = 30

# Bir blobun en/boy oranı bu aralığın dışındaysa balon sayılmaz. Balon
# yuvarlaktır; uzun ince bir kırmızı leke maket parçası veya yansımadır.
SPOTTER_BALLOON_ASPECT = (0.5, 2.0)

# Blobun kendi kutusunu ne kadar DOLDURDUGU. Daire icin pi/4 = 0.785.
# Sahada olculdu: gercek balon 0.70, kirmizi F16 maketi 0.37. En-boy
# orani tek basina yetmiyordu -- maket kutusu da kabaca kare olabildigi
# icin 'balon' sayiliyor ve gozcu olmayan bir balona iz aciyordu.
# 0.50 ikisini ayirir; kismen ortulen bir balon icin de pay birakir.
# 0.60 -> 0.45 GERI ALINDI. Ayni kayitta gercek balon "dolg 0.50" ile
# elenmisti. Olculen degerler: gercek balon 0.50-0.70, kirmizi F16 maketi
# 0.36-0.51 (durusa gore degisiyor). Ikisi TAM AYRILAMIYOR; 0.45 gercek
# balonu gecirir, maketlerin bir kismini hala eler, kalanini da dogrulamadaki
# balon sarti temizler.
SPOTTER_BALLOON_MIN_FILL = 0.45

# --- SADECE ARAYUZ: gozcu onizlemesinde cizilecek bloblar ---
# Yonlendirmeye HICBIR etkisi yok. Operatorun "gozcu neyi goruyor, neden
# aday saymiyor" sorusunu ekranda yanitlayabilmesi icin. Esik aday
# esiginden (SPOTTER_MIN_BLOB_AREA) DUSUK, cunku amac elenenleri de
# gostermek.
SPOTTER_DISPLAY_MIN_AREA = 20
SPOTTER_DISPLAY_MAX_BLOBS = 12    # renk basina; IPC yuku sinirli kalsin

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
# |dx| <= bu x maket_genisligi.
# 1.0 IDI VE TEHLIKELIYDI: bir maket, KENDI genisligi kadar yandaki bir
# balonla eslesebiliyordu. 15 metrede maket 126 piksel, yani 45 santim
# yanal tolerans. Sonuc: DUSMANIN maketi + DOSTUN balonu bir cift kurabilir,
# ciftin sinifi maketten geldigi icin 'dusman-' okunur ve ates kilidinin
# dokuz kosulu birden gecer -> DOSTUN BALONUNA ATES. Diskalifiye.
# Sahada olculen gercek deger: dx/mw = 0.02-0.08. 0.4 hala 5 kat pay birakir
# (15 metrede 18 santim yanal sapma; ipte sallanan balon icin fazlasiyla).
PAIR_MAX_HORIZONTAL_OFFSET = 0.4
PAIR_VERTICAL_RANGE = (0.0, 2.5)   # balon merkezi maketin altında, bu aralıkta
                                   # (x maket_genisligi)

# Balon maketten büyük olamaz (14 cm balon, 40-50 cm maket).
PAIR_MAX_BALLOON_RATIO = 0.8       # balon_genisligi / maket_genisligi

# Bir balon, ancak KENDISINE EN YAKIN maket o maketse eslesebilir.
# Esiklerden bagimsiz yapisal koruma: capraz eslesmeyi imkansiz kilar.
# Kapatmak icin bir sebep yok; secenek olmasi yalnizca birim testinde
# kuralin etkisini yalitabilmek icin.
PAIR_REQUIRE_NEAREST_MAKET = True

# Balon tespiti zayıfsa nişan noktası maketten türetilir. 15 metrede balon
# avcıda 30 piksel — YOLO için küçük-nesne sınırı; maket 96 piksel, rahat.
# Nişan noktası = maket_merkezi + (0, bu_kat x maket_genisligi)
PAIR_FALLBACK_AIM_OFFSET = 0.75

# --- NISAN NOKTASI: balon kutusunun NERESINE nisan alinacak ---
# Kutunun ALTINDAN olculen yukseklik orani. 0.5 = merkez, 1.0 = ust kenar.
#
# NEDEN merkez degil: avci kamera namlunun 5.5 cm USTUNDE ve eksenler
# PARALEL. Paralel oldugu icin mermi HER MESAFEDE kamera ekseninin 5.5 cm
# altindan gecer -- yani nisangahi balonun merkezine oturtursak mermi
# merkezin 5.5 cm altina gider. Balonun yaricapi 7 cm; ici ama payi 1.5 cm.
#
# Duzeltmenin guzel yani MESAFEDEN BAGIMSIZ olmasi: gereken ofset ile
# balonun yaricapi ayni mesafedeki iki fiziksel uzunluk, oranlari sabit:
#     5.5 / 7.0 = 0.786 yaricap  =  kutu yuksekliginin 0.393'u
# Yani tam telafi 0.893 oranina karsilik gelir (usten %10.7).
#
# SU ANDA 0.5 = TAM MERKEZ. Yani paralaks telafisi KAPALI ve nisan
# noktasi tespitin tam ortasi -- saha karari boyle.
#
# Yukaridaki analiz burada BILGI olarak duruyor: telafi istenirse tek yapilacak
# sey bu sayiyi buyutmek. 0.893 tam telafi, 0.75 kismi telafidir (mermi
# merkezin 2.0 cm altina gider). Kutunun ust kenarina yaklastikca YOLO'nun
# kutu gurultusu nisan noktasini daha cok etkiler; bu yuzden tam telafi
# otomatik olarak "en iyi" degildir.
#
# BALISTIK DUSUS de eklenmedi: 15 metrede sapma ihmal ediliyor. Gerekirse
# mesafe balonun piksel capindan bedava cikarilabilir (14 cm bilinen boy) ve
# duzeltme atan(g*d/2v^2) ile eklenebilir.
AIM_POINT_HEIGHT_RATIO = 0.5
PAIR_ALLOW_FALLBACK_AIM = True


# =====================================================================
#  ANGAJMAN DURUM MAKİNESİ
# =====================================================================
# Taretin gözcünün verdiği açıya oturduğu kabul edilen tolerans (derece).
ENGAGE_SLEW_TOLERANCE_DEG = 1.0

# Durum zaman aşımları (saniye). Hızlı imha modunda takılıp kalmak yanlış
# yöne gitmekten pahalıdır.
ENGAGE_SLEW_TIMEOUT = 2.5
# 1.5 -> 1.0: dogrulama karar veremiyorsa bosuna bekleniyor. Balonsuz
# hedef artik VERIFY_NO_BALLOON_GIVEUP_SEC ile 0.4 saniyede eleniyor;
# bu timeout yalnizca 'maket var ama sinif tutarsiz' durumunda devrede
# kaliyor ve orada da 1.0 saniye yeterli (30 karede 4 ardisik ayni sinif).
ENGAGE_VERIFY_TIMEOUT = 1.0
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
# değil — tespit gürültüsünün altında bir hassasiyet istememek için alt sınır.
# Ölü bantla aynı gerekçeyle çözünürlüğe bağlıdır, kameraya değil; 1920x1080'e
# geçildiği için 1.5 katına çıkarıldı (6 -> 9). 15 metrede balon yarıçapı 19 px
# olduğundan oran terimi (0.35 x 19 = 6.5 px) bu sınırın altında kalır; yani
# 15 metrede tolerans 9 px = 0.13 derece = 3.4 cm.
AIM_TOLERANCE_MIN_PIXELS = 9.0

# Ateşten önce nişan kaç kare korunmalı.
AIM_HOLD_FRAMES = 3

# --- IMHA DOGRULAMA ---
# Sahada olculdu (asama2-3-hedefTakip.mp4): Asama 3'te ates 4.07 saniyede
# verildi, hemen ardindan `imha_edildi()` cagrildi ve hedef 12 saniye kara
# listeye girdi. Sonraki 6+ saniye boyunca durum satiri kesintisiz
# "TARAMA - gozcude uygun aday yok (1-3 iz) | 1-2 cift | imha 1" yazdi:
# gozcu izi goruyor, avci cifti goruyor, sistem angaje OLMUYOR.
#
# Sebep: sistemde imha DOGRULAMASI yoktu, "ates ettim" = "imha ettim"
# varsayiliyordu. Sarjor takili degilken veya iska gectiginde sistem bunu
# asla ogrenemiyor ve hedefi 12 saniye boyunca gormezden geliyordu.
#
# Yeni davranis: ates sonrasi bir DOGRULAMA PENCERESI aciliyor. Pencere
# boyunca balon HIC gorulmezse imha onaylanir; hala goruluyorsa ayni hedefe
# tekrar ates edilir (butce dahilinde). Tek karelik kacirma "imha" sanilmasin
# diye pencerede balonun kac karede goruldugu sayiliyor.
FIRE_CONFIRM_SEC = 0.7        # pencere suresi: balon kaybolmasi icin beklenen
FIRE_CONFIRM_MAX_SEEN = 4     # pencerede bu kadar karede gorulurse "hala orada"
FIRE_MAX_ATTEMPTS = 3         # ayni hedefe ardisik en fazla kac ates

# Ateste sonra sayima BASLAMADAN once beklenen sure.
#
# SAHADA OLCULDU (anavlizaşama3.mp4): ates 7.60 saniyede verildi, balon
# 8.10'da kayboldu -- yani patlamis balon 0.5 SANIYE (15 kare) daha
# gorunmeye devam etti. Mermi ucus suresi + patlama + YOLO'nun kutuyu
# birakmasi toplami bu. Gecikme olmadan bu 15 kare "balon hala orada"
# sayiliyor ve sistem patlamis hedefe tekrar ates etmeye calisiyordu.
#
# 0.4 sn gecikme + MAX_SEEN 4 ile o olcum rahat geciyor: sayim 8.00'da
# basliyor, 8.10'a kadar 3 kare goruluyor, 3 <= 4 -> "imha onaylandi".
#
# 0.4 -> 0.6 (servo-tetik dali): tetik artik SERVO ile mekanik cekiliyor ve
# mermi, roleye gore ~0.2 sn (FIRE_SERVO_LEG_SEC) daha gec cikiyor. Pencere
# o gecikmeyi de kapsamali, yoksa patlamamis balon sayimi erken baslar ve
# "balon hala orada" yanlisligi geri gelir. Role moduna donulurse 0.4'e cek.
FIRE_CONFIRM_DELAY_SEC = 0.6

# 'tekrar ates' istendigi halde ates kilidi ARDISIK bu kadar karede izin
# vermezse hedef birakilir.
#
# 18. bolumdeki KILITLENMENIN dogrudan carasi: eskiden 'tekrar' karari
# verildikten sonra ates edilemezse ates_kaydet() cagrilmiyor, sayac
# artmiyor, 'pes' asla tetiklenmiyor ve ates_sayisi > 0 oldugu icin KILIT'e
# de donulmuyordu. Sistem ATES durumunda 20 saniye takili kaldi.
FIRE_RETRY_GIVEUP_FRAMES = 45     # ~1.5 sn @30fps

# --- HEDEF TAKIP: hedef surekliligi ---
# Takip modunda secilen hedef, bir sonraki karede bu piksel yaricapi icinde
# aranir; bulunamazsa (gercekten kayboldu) yeni hedef secilir.
# Sahada olculdu: merkeze yaklasan bir hayalet yuzunden nisan hatasi tek
# karede 400 piksel sicradi. 150 px, hedefin bir karede alabilecegi gercek
# yolun cok uzerinde (30 fps'te 15 m'de 150 px ~ 2 derece) ama hayaletin
# uzagina dusuyor.
TRACK_REACQUIRE_PIXELS = 150.0

# Kara liste: doğrulamada DOST çıkan veya imha edilen hedefler buraya girer.
# Gövde çerçevesinde MUTLAK açı olarak tutulur (piksel uzayında tutmak
# anlamsız, taret döndükçe referans kayar).
BLACKLIST_RADIUS_DEG = 4.0
BLACKLIST_TTL_SEC = 12.0          # imha edilenler için
BLACKLIST_FRIEND_TTL_SEC = 600.0  # dost maketler için pratikte kalıcı

# --- BALONSUZ HEDEF: DAR ve KISA kara liste ---
#
# Balonu olmayan bir hedef ATESLENEMEZ, o yuzden orada beklemenin anlami yok;
# ama bu hedefi KALICI olarak elemek de yanlis olur (balon sonradan
# gorulebilir). Amac yalnizca "siradakine gecebilmek".
#
# YARICAP NEDEN AYRI: kara liste aci bazli bir BOLGE kapatiyor. Varsayilan
# 4.0 derece, hedefler birbirine yakinken KOMSUYU DA kapatir:
#     7.5 metrede 1.0 m ayrim = 7.59 derece  -> guvenli
#    16.0 metrede 1.0 m ayrim = 3.58 derece  -> 4.0 KOMSUYU KAPATIR
#    20.0 metrede 1.0 m ayrim = 2.86 derece  -> 4.0 KOMSUYU KAPATIR
# Sahada olculen sahnede hedefler 6.2-7.0 derece araliydi (16 m'de ~1.8 m),
# yani 4.0 orada guvenliydi -- ama 1 metre araliga dusulurse degil.
#
# 1.5 derece 16 metrede yalnizca ~0.42 m yanal bolge kapatir: hedefin
# kendisini yakalar, 1 metre yanindakini birakir.
BLACKLIST_NO_BALLOON_RADIUS_DEG = 1.5
# 4.0 -> 3.0: elenen hedefin yeniden denenebilmesi icin beklenen sure.
# Kisaltmak, balonu ARA SIRA gorunen bir hedefe daha cabuk donmeyi saglar;
# cok kisaltmak ise ayni hedefte gidip gelmeye yol acar.
BLACKLIST_NO_BALLOON_TTL_SEC = 3.0

# Dogrulama penceresinde balon EN AZ bu kadar karede gorulmeli.
#
# 1 = "bir kez gorulmesi yeter". Amac balonu olmayan hedefi elemek, balonu
# ara sira kacirilan hedefi degil; KILIT koprusu zaten anlik kayiplari
# tasiyor. Sahada olculdu (analizaşama3.mp4): balonsuz dusman-F16'ya
# kilitlenildi ve 42 saniye boyunca cikilamadi, cunku dogrulama yalnizca
# SINIFA bakiyordu -- balonun varligini hic sormuyordu.
VERIFY_MIN_BALLOON_FRAMES = 1

# ERKEN CIKIS: dogrulamada balon bu SURE boyunca HIC gorulmediyse, sinif
# tutarliligini beklemeden hedefi birak.
#
# NEDEN: balon sarti `dusman_mi(sinif)` blogunun ICINDE, yani ancak
# VERIFY_CONFIRM_FRAMES kadar ARDISIK ayni sinif toplandiktan sonra
# calisiyordu. Maket araliklı goruluyorsa o toplanma uzuyor ve karar
# ENGAGE_VERIFY_TIMEOUT'a kadar (en kotu 1.5 sn) sarkiyordu. Oysa balonun
# yoklugu sinifin ne oldugundan BAGIMSIZ bir bilgi: balon yoksa hedef
# ateslenemez, sinifi ogrenmenin degeri yok.
#
# 0.40 sn = 12 kare @30fps. Balonun gercekten var olup birkac kare
# kacirildigi durumu elemeyecek kadar uzun, bosuna beklemeyecek kadar kisa.
VERIFY_NO_BALLOON_GIVEUP_SEC = 0.40

# Doğrulaması zaman aşımına uğrayan aday için KISA ömürlü kara liste.
# Sahada ölçüldü (AnalizVideo.mp4, 17-23 sn): taret gözcünün verdiği açıya
# gitti, avcıda hiçbir çift göremedi, DOĞRULAMA 1.5 sn'de zaman aşımına
# uğradı, TARAMA aynı adayı yine ilk sıraya koydu ve aynı açı tekrar
# gönderildi — taret 4 saniye boş duvara baktı. Kısa bir kara liste sıradaki
# adaya geçmeyi sağlar; süre dolunca aday yeniden denenir, yani gerçek bir
# hedefi kalıcı olarak kaybetme riski yok.
BLACKLIST_VERIFY_TTL_SEC = 5.0

# --- KILIT KOPRUSU: maket bir kare gorunmezse kilidi birakma ---
# Sahada olculdu (Asama2Hedef.mp4): kilit fazinin ~yarisinda YOLO maketi
# kaciriyor. Otonom modda maket olmadan cift kurulmadigi icin durum makinesi
# hedef donduremiyor, eski 'takip' dali devraliyor ve TAHMIN devreye giriyor.
# Nisan noktasi balonun merkezinden hayalete atliyor; olculen pitch
# sicramalari +-80..124 piksel. Kilit fazinin yalnizca %3.2'si nisan
# toleransinin icinde gecti.
#
# Cozum: maket kaybolunca, DOGRULANMIS hedefin balonunu tek basina takip
# etmeye devam et. Guvenlik kaybi yok -- `ates_serbest_mi` ates karesinde
# maketin GERCEKTEN tespit edilmis olmasini zaten sart kosuyor.
#
# Kopru genisligi hesabi: en uzun korluk 5 kare / 14 fps = 0.36 sn, hedef
# hizi en fazla 2.1 derece/sn -> balon 0.75 derece kayar. 0.8 derece kapi
# bunu kapsar ama yandaki hedefe atlamaya izin vermez (hedefler uc ayri
# yoldan geldigi icin aralarinda cok daha fazla aci var).
LOCK_BRIDGE_MAX_DEG = 0.8
LOCK_BRIDGE_MAX_FRAMES = 5

# Kilit acisinda BASKA SINIFTAN maket belirdiginde kilidi birakmadan once
# kac kare ust uste gorulmeli. Zamansal onay OLMADAN tek karelik bir
# hayalet (sahada 0.1-0.2 sn suren, 0.6 guvenli etiketler goruldu) iyi
# bir kilidi dusurup TARAMA'ya gonderebiliyordu.
LOCK_ABORT_CONFIRM_FRAMES = 3

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

# --- SINIF BAZLI ACISAL BOYUT KAPISI ---
# Hedeflerin GERCEK boyutu biliniyor, mesafe araligi da belli. O halde
# bir tespitin piksel boyutu fiziksel olarak mumkun bir aralikta olmali.
# Alan orani kapisi (yukarida) cok gevsek: 1920x1105'te 728x728'e kadar
# her kutu geciyor -- 50 cm'lik bir maket bu boyuta ancak 2.7 metrede
# ulasir, yani pratikte hicbir hayaleti kesmiyor.
#
# Kapi DEGREES_PER_PIXEL uzerinden tanimli, yani cozunurluk veya lens
# degisince kendiliginden olcekleniyor.
DETECTION_SIZE_CHECK = True
# BALON 0.14 -> 0.19: sahada olculdu (asama2-3-hedefTakip.mp4). Maket kutusu
# 208 px, balon kutusu 78 px olculdu; maket 50 cm kabul edilince mesafe
# 9.63 m ve ayni mesafede 78 px'lik balonun gercek capi 18.7 cm cikiyor.
# 0.14 sisirilmemis balonun capiydi. Bu duzeltme TARGET_MIN_RANGE_M ile
# BIRLIKTE zorunlu: 7.5 m'de 0.14 varsayimi balon ust sinirini 105 px'e
# indiriyor, oysa balon 7.5 m'de 100 px olarak gorunuyor -- %5 pay kalirdi
# ve gercek balonlar elenmeye baslardi. 0.19 ile ust sinir 142 px olur.
GERCEK_BOYUTLAR_M = {'balon': 0.19, 'maket': 0.50}
# 4.0 -> 7.5: sahada hicbir hedef 7.5 metreden yakin degil (kullanici
# beyani; atislar 7.5-15 m arasi). 4.0 iken maketin ust siniri 700 px'ti ve
# olculen sahte 'dusman-fuze' kutusu 693 px ile 7 PIKSEL FARKLA geciyordu.
#   50 cm @ 4.0 m -> 500 px, x1.40 = 700 px   (eski)
#   50 cm @ 7.5 m -> 267 px, x1.40 = 373 px   (yeni)
# Kayitta olculen sahte kutular 693 / 487 / 464 / 445 px -- hepsi elenir.
# Olculen GERCEK maket kutusu 162-172 px, yani 373 sinirinin cok altinda.
TARGET_MIN_RANGE_M = 7.5
TARGET_MAX_RANGE_M = 20.0
# Alt sinir KASITLI OLARAK GEVSEK: amac dev hayaletleri kesmek, kucuk
# tespitleri elemek degil. Maket yan donunce gorunen boyu kuculebilir.
DETECTION_SIZE_MIN_MARGIN = 0.40
DETECTION_SIZE_MAX_MARGIN = 1.40

# Bir adayın mevcut hedefin yerine geçebilmesi için gereken güven farkı.
ACQUIRE_CONFIDENCE_MARGIN = 0.15


def hunter_etkin_kare():
    """
    Boru hattına GERÇEKTEN giren avcı kare boyutu (kırpma sonrası).

    Görüş açısı, piksel eşiklerinin açısal karşılığı ve testlerdeki ölçek
    kontrolleri bunu kullanmalı — `HUNTER_HEIGHT` yalnızca kameradan
    İSTENEN yüksekliktir.
    """
    if not HUNTER_CROP_TO_MODEL_ASPECT:
        return HUNTER_WIDTH, HUNTER_HEIGHT
    hedef_oran = IMG_WIDTH / float(IMG_HEIGHT)
    yuk = int(round(HUNTER_WIDTH / hedef_oran))
    return HUNTER_WIDTH, min(yuk, HUNTER_HEIGHT)
