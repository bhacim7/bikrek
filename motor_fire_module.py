# motor_fire_module.py
# Bu dosya, Raspberry Pi üzerindeki tüm GPIO tabanlı motor ve ateşleme controlünü yönetir.
# control1.py'deki akıcı ve eşzamanlı motor kontrol mantığı ve parametreleri entegre edilmiştir.

import sys
import time  # time.sleep() kullanmak için eklendi
import traceback
import math

# LGpio kütüphanesi ve pin tanımlamaları için global değişkenler
# LGpio, RPi.GPIO'dan farklı olarak bir "handle" (işleyici) gerektirir.
lgh = None  # LGpio handle'ı
LGpio = None  # lgpio modülünün kendisi

# control1.py'den alınan pin tanımlamaları
YAW_ENA_PIN = 17
YAW_DIR_PIN = 27
YAW_STEP_PIN = 22
PITCH_ENA_PIN = 24
PITCH_DIR_PIN = 23
PITCH_STEP_PIN = 25
FIRE_PIN = 16  # control1.py'deki RELAY_PIN'e karşılık gelir

# --- TETİK MODU ---
# 'servo' : GPIO'daki hobi servosu tetiği mekanik olarak çeker (yeni yol)
# 'relay' : GPIO16 rölesi elektronik tetiği sürer (eski yol, geri dönüş için)
FIRE_MODE = 'servo'

# SERVO TETİK — lgpio tx_servo ile yazılım zamanlı 50 Hz darbe.
#
# NEDEN GPIO12: herhangi bir pin çalışır (tx_servo yazılım zamanlı) ama
# 12/13/18/19 Pi 5'te RP1'in DONANIM PWM birimine de bağlı. Yazılım zamanlı
# darbede rahatsız edici titreşim görülürse, kabloya dokunmadan yalnızca
# yazılımı donanım PWM'e çevirme seçeneği açık kalsın diye 12 seçildi.
# (18 dolu: EMERGENCY_STOP_PIN.)  Fiziksel pin: GPIO12 = 32 numaralı pin.
#
# BESLEME UYARISI: servo Pi'nin 5V pininden BESLENMEZ — MG996R kalkışta
# 1-2 A çeker ve Pi 5 çöker. Ayrı 5-6V BEC kullanılmalı, GND'ler ortak.
FIRE_SERVO_PIN = 12

# Konumlar µs cinsinden (50 Hz, 500-2500 µs ~ 0-180°, 11.1 µs/derece).
# 30 derece = 333 µs. İKİ DEĞER DE SAHADA KALİBRE EDİLMELİ: `servo_tani.py`
# ile tetiğin çekildiği ve serbest kaldığı gerçek µs değerleri bulunur.
FIRE_SERVO_REST_US = 1600      # dinlenme (tetik serbest)
FIRE_SERVO_PULL_US = 833       # çekili
# Gerçek strok: 1600 - 833 = 767 us. 500-2500 us = 0-180 derece olduğuna göre
# 11.11 us/derece, yani hareket 30 DEĞİL ~69 derecedir (99.0 -> 75.0 derece).
# MG996R katalog hızı 0.17 sn/60 derece @4.8 V -> 69 derece ~0.20 sn. Yani
# LEG_SEC = 0.20 katalog değeriyle TAM SINIRDA; sahada sorunsuz çalışıyor ama
# gerilim düşerse (Pi 5V hattı servo yükünde sarkar) servo açıya varmadan
# sonraki komut gelir. Tetik yarım çekili kalırsa ilk bakılacak yer burasıdır:
# 0.24'e çıkar.
FIRE_SERVO_LEG_SEC = 0.20      # tek yön hareket süresi
FIRE_SERVO_CYCLES = 1          # fire başına git-gel sayısı (sürekli sarsma için büyüt)
FIRE_SERVO_FREQ = 50           # standart hobi servo frekansı (Hz)

# --- SERVO TIPI ---
# 'konum' : STANDART (180°) servo. Darbe genişliği = AÇI. Yaz, oraya gider,
#           BEKLER. REST/PULL iki sabit sayıdır. Tetik için ideal.
# 'hiz'   : SÜREKLİ DÖNÜŞ (360°) servosu. Darbe genişliği = HIZ ve YÖN;
#           NEUTRAL = dur, uzaklaştıkça hızlanır. KONUM KAVRAMI YOK
#           (potansiyometresi sökülmüş, nerede olduğunu bilmez).
#           Hareket ancak "şu hızda şu SÜRE dön" ile yapılır — AÇIK DÖNGÜ.
#
# Hangisi olduğu etiketten anlaşılmıyor (MG995 iki sürümde de satılıyor).
# `servo_tani.py` içindeki 'x' TEŞHİSİ ile belirlenir.
#
# 'hiz' MODUNUN BEDELİ: servo nereye geldiğini bilmediği için her atışta
# konum bir miktar kayabilir (yük, gerilim, sürtünme farkı). Tetik mekanik
# bir sınıra dayandığı için pratikte tolere edilebilir, ama tekrar
# edilebilirlik standart servodakinin altındadır. Mümkünse 'konum'.
FIRE_SERVO_MODE = 'konum'

# --- 'hiz' modu ayarları (yalnızca FIRE_SERVO_MODE == 'hiz' iken) ---
#
# DUR NOKTASI SAHADA KALİBRE EDİLDİ: `servo_tani.py` 'k' komutuyla 1465 µs
# bulundu. 1500 değil — sürekli dönüş servolarında fabrika trim kayması
# normaldir ve kalibre edilmezse "dur" komutu servoyu yavaşça döndürmeye
# devam eder.
FIRE_SERVO_NEUTRAL_US = 1465
FIRE_SERVO_SPEED_US = 300      # nötrden uzaklık: büyük = hızlı

# TETİĞİ HANGİ YÖN ÇEKİYOR?
# Sahada gözlendi (`servo_tani.py`): 'b' (GERİ, nötrün ALTI) tetiği ÇEKİYOR,
# 'f' (İLERİ, nötrün ÜSTÜ) bırakıyor. Dolayısıyla çekme yönü NEGATİF.
#   -1 : çekme = NEUTRAL - SPEED   (mevcut montaj)
#   +1 : çekme = NEUTRAL + SPEED   (servo ters takılırsa bunu +1 yapın)
FIRE_SERVO_PULL_DIR = -1

# SÜRELER — TAHMİNİ BAŞLANGIÇ DEĞERLERİ, SAHADA AYARLANACAK.
#
# Sürekli dönüş servosunda "şu açıya git" denemediği için süre = mesafe.
# Kol tetiği çekene kadar dönmeli, ama mekanik sınıra dayandıktan sonra
# dönmeye devam etmek servoyu zorlar (ısınma, dişli aşınması).
#
# NASIL AYARLANIR:
#   - tetik ÇEKİLMİYORSA  -> PULL_SEC'i 0.05 artırın
#   - servo zorlanıyor/ısınıyorsa (sınıra dayanıp itiyor) -> azaltın
#   - kol başladığı yere DÖNMÜYORSA -> RELEASE_SEC'i PULL_SEC'e göre
#     ayarlayın (yük farkı yüzünden geri dönüş biraz farklı sürebilir)
FIRE_SERVO_PULL_SEC = 0.40     # tetiği çekme süresi
FIRE_SERVO_HOLD_SEC = 0.10     # çekili bekleme (mekanizmanın tetiklenmesi)

# ATEŞTEN ÖNCE REFERANSA DÖNÜŞ süresi. VARSAYILAN 0 = KAPALI.
#
# Fikir: kol nerede kaldıysa oradan başlamak önceki atışın sapmasını taşır;
# kısa bir bırakma darbesi kolu dayanağa yaslayıp her atışı aynı noktadan
# başlatır. AMA bu, mermi çıkış anını `HOME_SEC` kadar geciktirir ve PC
# tarafındaki imha doğrulama payını yer:
#     mermi çıkışı = HOME_SEC + 0.05 + PULL_SEC
#     bu değer FIRE_CONFIRM_DELAY_SEC'ten KÜÇÜK kalmalı.
#
# Uzatılmış `RELEASE_SEC` (PULL x 1.4) zaten her çevrimin sonunda kolu
# dayanağa yaslıyor, yani aynı işi bedelsiz yapıyor. Bu yüzden varsayılan
# kapalı. Sapma buna rağmen birikirse açın — ama o zaman config.py'deki
# FIRE_CONFIRM_DELAY_SEC'i de en az o kadar büyütün.
FIRE_SERVO_HOME_SEC = 0.0
# BIRAKMA SÜRESİ ÇEKMEDEN UZUN — BU BİLEREK BÖYLE.
#
# SAHADA GÖRÜLDÜ: "bazen az çekilip kalıyor, geri salmıyor; birkaç atıştan
# sonra kol başladığı yerde değil."
#
# Sebep açık döngü: servo nereye geldiğini BİLMİYOR, sadece "şu süre dön"
# komutunu uyguluyor. Gerçekte dönülen açı şunlara göre değişiyor:
#   - ivmelenme payı (servo anında tam hıza çıkmaz; kısa hareketlerde
#     hızlanma+yavaşlama toplam hareketin büyük kısmını oluşturur),
#   - besleme gerilimi (düşerse aynı sürede daha az döner),
#   - yük ve sürtünme.
# Çekme ile bırakma birbirini tam götürmediği için fark ATIŞ BAŞINA BİRİKİR
# ve kol yavaş yavaş kayar.
#
# Açık döngüde tek güvenilir çare MEKANİK REFERANS: bırakma yönünde bilerek
# FAZLA döndürüp kolu bir dayanağa (veya tetiğin serbest konumuna) yaslamak.
# Fazla süre boyunca servo dayanağı iter, kol daha ileri gidemez ve her
# çevrim AYNI noktada biter — birikim sıfırlanır.
#
# 0.56 = PULL_SEC x 1.4, yani %40 fazla.
# DİKKAT: bu ancak bırakma yönünde bir DAYANAK varsa işe yarar. Dayanak
# yoksa kol her atışta bırakma yönüne kayar; o durumda değeri PULL_SEC'e
# eşitleyip mekanik dayanak eklenmeli.
FIRE_SERVO_RELEASE_SEC = 0.56  # tetiği bırakma (geri dönüş) + dayanma payı

# rpi_motor_server.py'den alınan acil durdurma pini
EMERGENCY_STOP_PIN = 18

# GPIO'nun başarıyla başlatılıp başlatılmadığını gösteren bayrak
_gpio_initialized = False

# Simüle edilmiş taret açıları (gerçek enkoderler olmadığında kullanılır)
# Açıları -180 ile 180 arasında tutmak için başlangıçta 0.0 olarak ayarla
_simulated_yaw = 0.0
_simulated_pitch = 0.0

# Manuel hareket için yön değişkenleri (rpi_motor_server tarafından ayarlanır)
_yaw_moving_direction = 0  # -1: sol, 0: dur, 1: sağ
_pitch_moving_direction = 0  # -1: aşağı, 0: dur, 1: yukarı
_manual_degrees_to_move = 0.0 # Manuel hareket için her adımda hareket edilecek derece miktarı

# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# !!! ÖNEMLİ KALİBRASYON AYARLARI - KENDİ SİSTEMİNİZE GÖRE AYARLAMANIZ GEREKİR !!!
# !!! BU DEĞERLER, SİZİN MOTORUNUZUN VE MEKANİK SİSTEMİNİZİN GERÇEKTE BİR DERECE
# !!! DÖNMEK İÇİN KAÇ ADIM ATTIĞINI GÖSTERMELİDİR. YANLIŞ AYARLANIRSA,
# !!! YAZILIMDAKİ AÇI FİZİKSEL HAREKETLERDEN FARKLI OLACAKTIR.
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

# --- Donanım: Leadshine CS-M22323 kapalı çevrim step motor + CS-D508 sürücü ---
# PULSES_PER_REV değerleri sürücünün SW1-SW4 DIP anahtarlarıyla seçilen ayarla
# BİREBİR aynı olmalıdır. Kombinasyon tablosu sürücünün üstünde basılıdır.
# GEAR_RATIO, motor turu : taret turu oranıdır (redüksiyon).
#
# YAW  : motora takili 10 dis -> sistemi ceviren 30 dis = 3.0 redüksiyon.
# PITCH: 2026-08-14'e kadar DOGRUDAN bagliydi (1.0). Silah takilinca eksen
#        agir geldi, duruslarda salindi ve sarkti. Cozum olarak araya
#        PLF060-L1-3-S2-P2-8 planet redüktör (1:3) girdi.
#
#        TAKILAN REDÜKTÖR 1:5 (elde olan buydu; 1:3 icin yazilan degerler
#        buna gore guncellendi).
#
#        Redüktörün asil kazanci torkta degil ATALETTE: yansiyan yük ataleti
#        oran'in KARESI kadar, yani 1:5'te 25 KAT kuculur; salinim/cinlama
#        esas bundan beslenir. Cikis torku da 5 x 0.97 = 4.85 kat artar.
#        Sahada dogrulandi: motor enerjiliyken silahi elle itmek artik cok zor.
#
#        DIP ayari 6400 -> 3200. Sebep hiz tavani: 6400 ile adim/derece
#        88.889 olurdu ve rampa profilinin dogrulandigi donanim tavani
#        (MIN_DELAY = 3333 darbe/sn) pitch'i 37.5 derece/sn'ye dusururdu.
#        3200 ile adim/derece 44.444:
#          - cozunurluk 0.0225 derece/adim (yeni avci kamerada ~1.6 piksel)
#          - tepe hiz 3333/44.444 = 75 derece/sn (manuel ve otonom)
#        75 derece/sn pitch icin fazlasiyla yeterli: hedefler 0.6-2.1
#        derece/sn ile geliyor, devir teslimde pitch yolu en fazla ~20 derece
#        (0.27 sn) ve ENGAGE_SLEW_TIMEOUT 2.5 sn.
#
#        NOT: SERVO_MAX_DEG_PER_SEC hala 100. Saf pitch hareketinde
#        `_servo_gecikme_siniri` bunu donanim tavanina KIRPAR (75 derece/sn);
#        kirpma bilinclidir, yapisal rezonansi daha az uyarmak da ise yarar.
#        Yaw 100 derece/sn'de kalmaya devam eder.
#
#        DIKKAT: planet redüktör cikisi girisle AYNI yonde doner (yaw'daki
#        duz dis ciftinin aksine). Bu yüzden INVERT_PITCH_DIR degismedi.
PULSES_PER_REV_YAW = 3200
PULSES_PER_REV_PITCH = 3200
GEAR_RATIO_YAW = 3.0
GEAR_RATIO_PITCH = 5.0

# Adım/derece bu iki değerden türetilir; DIP ayarını değiştirirsen yalnızca
# yukarıdaki sayıyı güncellemen yeterli.
STEPS_PER_DEGREE_YAW = PULSES_PER_REV_YAW * GEAR_RATIO_YAW / 360.0      # 26.667
STEPS_PER_DEGREE_PITCH = PULSES_PER_REV_PITCH * GEAR_RATIO_PITCH / 360.0  # 44.444

# --- İvme (rampa) profili ---
# Değerler Pi5 üzerinde bu motorlarla çalıştığı doğrulanmış teleop test betiğinden
# alınmıştır. Her adımda sinyal MIN/MAX_DELAY kadar HIGH, sonra o kadar LOW kalır;
# yani bunlar YARIM periyottur (0.00015 -> 3333 pulse/sn).
# CS-M22323 (NEMA23) rotor ataleti yüksek olduğundan sabit hızda kalkış adım
# kaçırmaya yol açar; hareket rampasız yapılmamalıdır.
MIN_DELAY = 0.00040   # Maksimum hız
MAX_DELAY = 0.0015    # Kalkış ve duruş hızı
ACCEL_STEP = 0.00003  # Hızlanma ivmesi
DECEL_STEP = 0.00008  # Frenleme ivmesi

# --- Manuel (sürekli) hareket durumu ---
# Manuel modda hareket, ayrık "N derece git" bloklarıyla değil, yön sıfırlanana
# kadar süren tek bir akış olarak yürür. Rampa bu yüzden çağrılar arasında
# KORUNUR; aksi halde her komutta sıfırlanır ve tam hıza hiç ulaşılamaz.
_manual_current_delay = MAX_DELAY

# Watchdog: arayüz çökerse, ağ koparsa veya "dur" komutu kaybolursa taret
# sonsuza kadar dönmemeli. Bu süre boyunca yeni komut gelmezse hareket durur.
# Arayüz hareket ederken periyodik "canlıyım" komutu gönderir.
MANUAL_COMMAND_TIMEOUT = 0.35
_manual_last_command_time = 0.0

# --- Otonom (pozisyon servosu) durumu ---
# Otonom takipte hareket "şu kadar dön" komutlarıyla değil, "şu açıya git"
# hedefiyle yürür. Kritik fark: yeni hedef eskisinin YERİNE GEÇER, dolayısıyla
# komut kuyruğu ve bayat komut oluşamaz. Önceki bloklayan yapıda PC saniyede 25
# komut gönderirken Pi her birini bloklayarak işliyordu; komutlar birikiyor ve
# taret bayat komutları uygularken hedefi aşıyordu.
_target_yaw = 0.0
_target_pitch = 0.0
_servo_active = False
_servo_current_delay = MAX_DELAY

# Orantılı darbe dağıtımı (Bresenham) birikteçleri. İki eksenin hedefe aynı
# anda varmasını, dolayısıyla çapraz hareketin düz bir çizgi olmasını sağlar.
_servo_bres_yaw = 0.0
_servo_bres_pitch = 0.0

# Otonom modda tepe hız sınırı. Manuel moddan (tam hız) kasıtlı olarak düşük:
# hatalı bir tespit gelirse taret sert savrulmasın.
# Sınır yaw ekseninden türetilir; pitch daha az adım/derece istediği için aynı
# darbe hızında ~90°/s'ye çıkar, pitch hareketleri kısa olduğundan kabul edilebilir.
# Otonom tepe hız. Bu değer GÖRME döngüsünün takip edebileceği hızla sınırlıdır,
# motorun yapabileceğiyle değil (manuel mod hâlâ 125°/s'de çalışır).
#
# Sahada 120°/s ile taret hedefi aşıp kaybediyordu: kamera + çıkarım gecikmesi
# ~0.2 sn olduğu için taret o süre boyunca "kör" ilerliyor. 120°/s'de bu 24°
# demek; dikey görüş açısı 56° olduğundan hedef kareden çıkıyor, döngü açılıyor
# ve tahmin devreye girip tareti savuruyordu.
# Sahada ölçüldü: duyarga gecikmesi ~0.16 sn (taret 7.27s'de hareket etti,
# piksel hatası 7.43s'de tepki verdi). 40°/s ile kilitlenme temiz ve aşmasız
# oldu, yani marj var. 70'e çıkarıldı: kör ilerleme yaw 7.5°, pitch 11.2°
# (dikey görüşün %20'si) — hâlâ hedefi kareden çıkarmayacak seviyede.
# Yavaş gelirse artır, aşma/kayıp başlarsa düşür: ayarlanacak ilk yer burası.
SERVO_MAX_DEG_PER_SEC = 50.0

# Sabit bir alt gecikme YETERSİZ kalıyordu. İki eksen ortak darbe saatini
# paylaşıyor; gecikmeyi adım/derece oranı küçük olan eksenden (pitch)
# türetmek, pitch'i sınıra oturtuyor ama yaw'ı 46.7°/s'de bırakıyordu
# (70 × 17.778/26.667). Oysa saf yaw hareketinde yaw'ın yavaşlaması için
# hiçbir sebep yok.
#
# Artık gecikme HER HAREKET İÇİN, o hareketteki eksen oranlarına göre
# hesaplanıyor (_servo_gecikme_siniri). Böylece her iki eksen de kendi
# başına sınıra kadar çıkabiliyor, çapraz hareket düz kalmaya devam ediyor.
# Sahada hareketli hedef takibinin sınırı buydu: hedef 50°/s'yi geçince
# taret yetişemiyor ve balon kareden çıkıyordu.
SERVO_MIN_DELAY = max(MIN_DELAY,
                      1.0 / (2 * SERVO_MAX_DEG_PER_SEC
                             * min(STEPS_PER_DEGREE_YAW, STEPS_PER_DEGREE_PITCH)))


def _servo_gecikme_siniri(oran_yaw, oran_pitch):
    """
    Bu hareket için izin verilen en kısa yarım periyot.

    Bresenham oranları verildiğinde, bir eksenin gerçek derece/sn hızı
    (tik_hizi × oran / adım_derece) olur. Hiçbir eksen SERVO_MAX_DEG_PER_SEC'i
    aşmamalı, dolayısıyla tik hızı eksenler üzerindeki en kısıtlayıcı değerle
    sınırlanır. Saf yaw hareketinde oran_pitch=0 olduğu için sınırı yalnızca
    yaw belirler ve yaw tam hıza çıkabilir.
    """
    en_yuksek_tik = None
    for oran, adim_derece in ((oran_yaw, STEPS_PER_DEGREE_YAW),
                              (oran_pitch, STEPS_PER_DEGREE_PITCH)):
        if oran <= 0:
            continue
        tik = SERVO_MAX_DEG_PER_SEC * adim_derece / oran
        en_yuksek_tik = tik if en_yuksek_tik is None else min(en_yuksek_tik, tik)
    if not en_yuksek_tik:
        return SERVO_MIN_DELAY
    # DONANIM TAVANI. Bu taban olmadan, disli oranini veya DIP ayarini
    # degistirmek sessizce MIN_DELAY'in (3333 darbe/sn) ustunde bir darbe
    # hizi isteyebiliyordu; rampa profili orada dogrulanmadigi icin sonuc
    # adim kacirma olurdu. Redüktör eklenirken bu tam olarak olabilirdi:
    # 6400 ppr + 1:3 ile otonom pitch 5333 darbe/sn istiyordu.
    return max(MIN_DELAY, 1.0 / (2 * en_yuksek_tik))

PULSE_TIME = 0.1  # Ateşleme rölesinin çekili kalma süresi (saniye)

# Motor yönleri için sabitler
# DİKKAT: Bu değerler motor sürücünüzün DIR pininin nasıl çalıştığına bağlıdır.
DIR_CW = 0  # Saat yönü (veya ileri/yukarı)
DIR_CCW = 1  # Saat yönünün tersi (veya geri/aşağı)

# Eksen başına yön çevirme. Beklenen konvansiyon: +yaw = sağ, +pitch = yukarı.
# Montaj sonrası bir eksen ters dönüyorsa YALNIZCA o eksenin bayrağını True yap.
# (DIR_CW/DIR_CCW ortak olduğu için tek başına eksen bazlı düzeltme yapamaz.)
INVERT_YAW_DIR = True    # Sahada dogrulandi: montaj yonu ters, cevrildi.
# Silah mekanizmasi ters monte edildigi icin yukari/asagi tersine dondu;
# 2026-08-14'te True'dan False'a cevrildi. Bu bayrak YALNIZCA DIR pinine
# yazilan degeri etkiler; aci defteri (_simulated_pitch) komut edilen yonu
# kullandigi icin aci isareti ve tum denetim mantigi ayni kalir.
INVERT_PITCH_DIR = False

# LGpio pin modları ve seviyeleri için sabitler
LGPIO_HIGH = 1
LGPIO_LOW = 0
LGPIO_INPUT = 0
LGPIO_OUTPUT = 1

# Röle aktif/pasif durumları
# DİKKAT: Rölenizin nasıl tetiklendiğine bağlı olarak bu değerleri ayarlayın!
# Eğer röle LOW sinyali ile aktif oluyorsa: RELAY_ACTIVE = LGPIO_LOW, RELAY_INACTIVE = LGPIO_HIGH
# Eğer röle HIGH sinyali ile aktif oluyorsa: RELAY_ACTIVE = LGPIO_HIGH, RELAY_INACTIVE = LGPIO_LOW
RELAY_ACTIVE = LGPIO_HIGH # Varsayılan olarak HIGH ile aktif olduğunu varsayıyoruz
RELAY_INACTIVE = LGPIO_LOW # Varsayılan olarak LOW ile pasif olduğunu varsayıyoruz

# --- GPIO çip (gpiochip) seçimi ---
# 40 pinli başlığın hangi /dev/gpiochipN cihazına düştüğü karta ve çekirdek
# sürümüne göre DEĞİŞİR. Pi 4'te 0, Pi 5'te çekirdeğe göre 4 veya 15 olabiliyor.
# Bu yüzden numara sabit yazılmaz, çipin etiketinden bulunur.
# Otomatik bulma başarısız olursa buraya numarayı elle yaz (örn: 15).
GPIOCHIP_OVERRIDE = None

# 40 pinli başlığı sağlayan denetleyicilerin etiketleri.
# pinctrl-rp1  -> Pi 5 (RP1 yonga seti)
# pinctrl-bcm* -> Pi 4 ve öncesi
_GPIOCHIP_LABELS = ('pinctrl-rp1', 'pinctrl-bcm2712', 'pinctrl-bcm2711', 'pinctrl-bcm2835')
_GPIOCHIP_SCAN_LIMIT = 32  # /dev/gpiochip0 .. gpiochip31 taranır

# Otomatik bulmanın sonucu (teşhis için saklanır)
_resolved_gpiochip = None


def _find_gpiochip(lg):
    """
    40 pinli başlığa karşılık gelen gpiochip numarasını bulur.

    Numara yerine etiketle eşleştirmek, çekirdek güncellemesi chip
    numaralarını kaydırdığında kodun kendiliğinden uyum sağlamasını verir.
    Bulunamazsa, 40+ hatlı ilk çipe düşülür; o da yoksa None döner.
    """
    if GPIOCHIP_OVERRIDE is not None:
        print(f"DEBUG (motor_fire_module): GPIOCHIP_OVERRIDE ayarlı, chip {GPIOCHIP_OVERRIDE} kullanılıyor.")
        sys.stdout.flush()
        return GPIOCHIP_OVERRIDE

    fallback = None
    for n in range(_GPIOCHIP_SCAN_LIMIT):
        try:
            handle = lg.gpiochip_open(n)
        except Exception:
            continue  # Bu numarada cihaz yok, sıradakine bak

        try:
            # gpio_get_chip_info -> [status, lines, name, label]
            info = lg.gpio_get_chip_info(handle)
            lines = int(info[1])
            label = str(info[3])
            print(f"DEBUG (motor_fire_module): gpiochip{n} bulundu: '{label}' ({lines} hat)")
            sys.stdout.flush()

            if label in _GPIOCHIP_LABELS:
                return n
            if lines >= 40 and fallback is None:
                fallback = n
        except Exception as e:
            print(f"UYARI (motor_fire_module): gpiochip{n} bilgisi okunamadı: {e}")
            sys.stdout.flush()
        finally:
            try:
                lg.gpiochip_close(handle)
            except Exception:
                pass

    if fallback is not None:
        print(f"UYARI (motor_fire_module): Bilinen etiket bulunamadı, 40+ hatlı gpiochip{fallback} kullanılacak.")
        sys.stdout.flush()
    return fallback


def initialize_gpio():
    """
    Tüm motor ve ateşleme GPIO pinlerini başlatır ve motorları etkinleştirir.
    Bu fonksiyon sadece rpi_motor_server.py tarafından bir kez çağrılmalıdır.
    """
    global lgh, LGpio, _gpio_initialized, RELAY_ACTIVE, RELAY_INACTIVE, _resolved_gpiochip
    print("DEBUG (motor_fire_module): initialize_gpio() çağrıldı.")
    sys.stdout.flush()
    if sys.platform == 'linux':
        try:
            import lgpio
            LGpio = lgpio

            chip = _find_gpiochip(LGpio)
            if chip is None:
                raise RuntimeError(
                    "40 pinli başlığa ait gpiochip bulunamadı. 'gpiodetect' çıktısında "
                    f"etiketi {_GPIOCHIP_LABELS} olan çipi bulup numarasını "
                    "motor_fire_module.py içindeki GPIOCHIP_OVERRIDE değerine yazın.")
            _resolved_gpiochip = chip

            lgh = LGpio.gpiochip_open(chip)
            if lgh < 0:
                raise RuntimeError(f"LGpio handle açılamadı (gpiochip{chip}), hata kodu: {lgh}")
            print(f"DEBUG (motor_fire_module): gpiochip{chip} açıldı, LGpio handle: {lgh}")
            sys.stdout.flush()

            # Röle aktif/pasif değerleri, rölenizin tetikleme mantığına göre ayarlanmalı
            print(f"DEBUG (motor_fire_module): RELAY_ACTIVE: {RELAY_ACTIVE}, RELAY_INACTIVE: {RELAY_INACTIVE}")
            sys.stdout.flush()

            # Tüm motor pinlerini çıkış olarak ayarla
            # Motorları başlangıçta ETKİNLEŞTİR (ENABLE LOW) - Kullanıcının isteği üzerine
            LGpio.gpio_claim_output(lgh, YAW_ENA_PIN, LGPIO_LOW) # ENABLE LOW = Enabled (DRV8825 için)
            LGpio.gpio_claim_output(lgh, PITCH_ENA_PIN, LGPIO_LOW) # ENABLE LOW = Enabled (DRV8825 için)

            LGpio.gpio_claim_output(lgh, YAW_DIR_PIN, LGPIO_LOW)
            LGpio.gpio_claim_output(lgh, YAW_STEP_PIN, LGPIO_LOW)
            LGpio.gpio_claim_output(lgh, PITCH_DIR_PIN, LGPIO_LOW)
            LGpio.gpio_claim_output(lgh, PITCH_STEP_PIN, LGPIO_LOW)

            print(
                "DEBUG (motor_fire_module): Motor GPIO pinleri başarıyla ÇIKIŞ olarak ayarlandı ve ETKİNLEŞTİRİLDİ.")
            sys.stdout.flush()

            # Ateşleme pini (başlangıçta güvenli durumda RELAY_INACTIVE)
            LGpio.gpio_claim_output(lgh, FIRE_PIN, RELAY_INACTIVE)
            print(
                f"DEBUG (motor_fire_module): FIRE_PIN ({FIRE_PIN}) başlangıçta RELAY_INACTIVE ({RELAY_INACTIVE}) yapıldı.")
            sys.stdout.flush()

            # SERVO TETİK: pini çıkış olarak al, dinlenme konumuna götür,
            # sonra darbeyi kes (servo gevşer, akım çekmez). tx_servo
            # darbelerini lgpio'nun kendi iş parçacığı ürettiği için bu
            # bekleme step motor üretimini etkilemez.
            if FIRE_MODE == 'servo':
                LGpio.gpio_claim_output(lgh, FIRE_SERVO_PIN, LGPIO_LOW)
                # 'hiz' modunda dinlenme = NOTR (dur); konum yazilamaz.
                _bekleme = (FIRE_SERVO_NEUTRAL_US
                            if FIRE_SERVO_MODE == 'hiz' else FIRE_SERVO_REST_US)
                _servo_darbe(_bekleme)
                time.sleep(0.5)              # dinlenmeye oturması için
                _servo_darbe(0)              # darbeyi kes
                print(
                    f"DEBUG (motor_fire_module): SERVO TETİK hazır "
                    f"(GPIO{FIRE_SERVO_PIN}, mod={FIRE_SERVO_MODE}, "
                    f"bekleme {_bekleme} us).")
                sys.stdout.flush()

            # Acil durdurma pini (giriş olarak ayarla, pull-up direnci ile)
            LGpio.gpio_claim_input(lgh, EMERGENCY_STOP_PIN, LGpio.SET_PULL_UP)
            print(
                f"DEBUG (motor_fire_module): EMERGENCY_STOP_PIN {EMERGENCY_STOP_PIN} giriş olarak ayarlandı (PULL_UP).")
            sys.stdout.flush()

            _gpio_initialized = True
            print(
                "DEBUG (motor_fire_module): Tüm GPIO pinleri başarıyla başlatıldı.")
            sys.stdout.flush()
        except ModuleNotFoundError:
            print(
                "Hata (motor_fire_module): lgpio modülü bulunamadı. Raspberry Pi üzerinde olduğunuzdan emin olun ve lgpio'yu yükleyin.")
            sys.stdout.flush()
            lgh = None
            LGpio = None
            _gpio_initialized = False
        except Exception as e:
            print(f"Hata (motor_fire_module): GPIO başlatılırken genel hata oluştu: {e}")
            sys.stdout.flush()
            traceback.print_exc()
            if lgh is not None and lgh >= 0:
                LGpio.gpiochip_close(lgh)  # Hata durumunda da kapatma
            lgh = None
            LGpio = None
    else:
        print("DEBUG (motor_fire_module): Simülasyon modu: GPIO başlatma atlandı.")
        sys.stdout.flush()
        _gpio_initialized = True
        # Simülasyon modunda röle değerlerini varsayılan olarak ayarla
        RELAY_ACTIVE = 0 # Simülasyon modunda 0 aktif, 1 pasif olarak kabul edelim
        RELAY_INACTIVE = 1


def set_motors_enabled(enable):
    """
    Motorların ENABLE pinlerini kontrol eder.
    True: Motorları etkinleştir (güç ver, tutma torku sağla)
    False: Motorları devre dışı bırak (güç kes, tutma torkunu kaldır)
    """
    if not _gpio_initialized or lgh is None:
        print(f"UYARI (set_motors_enabled): GPIO başlatılmadı, ENABLE pini kontrol edilemez.")
        sys.stdout.flush()
        return

    try:
        if enable:
            # Motorları etkinleştir (ENABLE LOW = Enabled)
            LGpio.gpio_write(lgh, YAW_ENA_PIN, LGPIO_LOW)
            LGpio.gpio_write(lgh, PITCH_ENA_PIN, LGPIO_LOW)
            print("DEBUG (set_motors_enabled): Motorlar ETKİNLEŞTİRİLDİ (ENABLE LOW).")
            sys.stdout.flush()
        else:
            # Motorları devre dışı bırak (ENABLE HIGH = Disabled)
            LGpio.gpio_write(lgh, YAW_ENA_PIN, LGPIO_HIGH)
            LGpio.gpio_write(lgh, PITCH_ENA_PIN, LGPIO_HIGH)
            print("DEBUG (set_motors_enabled): Motorlar DEVRE DIŞI BIRAKILDI (ENABLE HIGH).")
            sys.stdout.flush()
        time.sleep(0.000001)  # Kısa bir gecikme
    except Exception as e:
        print(f"HATA (set_motors_enabled): Motor ENABLE pinleri ayarlanırken hata: {e}")
        traceback.print_exc()
        sys.stdout.flush()


def _direction_value(steps, invert):
    """
    Adım işaretinden DIR pini değerini üretir; eksen bazlı çevirmeyi uygular.
    Pozitif adım = ileri (yaw için sağ, pitch için yukarı).
    """
    is_forward = steps >= 0
    if invert:
        is_forward = not is_forward
    return DIR_CW if is_forward else DIR_CCW


def _ramped_step_loop(max_steps, abs_steps_yaw, abs_steps_pitch):
    """
    Yamuk (trapez) hız profiliyle adım darbeleri üretir.

    Rampa HAREKET BAŞINA sıfırlanır; çağrılar arasında taşınmaz. PID komutları
    arasında yön değişebildiği için bayat bir yüksek hızla kalkış tehlikelidir.
    Küçük hareketlerde profil doğal olarak "yavaş ve güvenli"ye dönüşür, büyük
    yönelimlerde tam hıza çıkar.

    Yön pinlerinin çağrıdan ÖNCE ayarlanmış olması gerekir.
    """
    current_delay = MAX_DELAY

    for i in range(max_steps):
        remaining_steps = max_steps - i
        # Mevcut hızdan duruş hızına inmek için kaç adım gerekiyor?
        decel_steps_needed = (MAX_DELAY - current_delay) / DECEL_STEP

        if remaining_steps > decel_steps_needed:
            current_delay = max(MIN_DELAY, current_delay - ACCEL_STEP)
        else:
            current_delay = min(MAX_DELAY, current_delay + DECEL_STEP)

        # Sadece ilgili motor için adım sinyali gönder
        if i < abs_steps_yaw:
            LGpio.gpio_write(lgh, YAW_STEP_PIN, LGPIO_HIGH)
        if i < abs_steps_pitch:
            LGpio.gpio_write(lgh, PITCH_STEP_PIN, LGPIO_HIGH)
        time.sleep(current_delay)

        LGpio.gpio_write(lgh, YAW_STEP_PIN, LGPIO_LOW)
        LGpio.gpio_write(lgh, PITCH_STEP_PIN, LGPIO_LOW)
        time.sleep(current_delay)


def move_steppers_simultaneous(steps_yaw, steps_pitch):
    """
    İki step motoru aynı anda, belirtilen adım sayısı kadar döndürür.
    Bu fonksiyon, control1.py'deki eşzamanlı hareket mantığını kullanır.
    Bu fonksiyon çağrıldığında motorların zaten etkin (enabled) olduğu varsayılır.
    :param steps_yaw: Yaw motoru için atılacak adım sayısı (pozitif veya negatif).
    :param steps_pitch: Pitch motoru için atılacak adım sayısı (pozitif veya negatif).
    """
    if not _gpio_initialized or lgh is None:
        print("DEBUG (move_steppers_simultaneous): GPIO başlatılmamış veya handle yok, hareket atlandı.")
        sys.stdout.flush()
        return

    # Yön pinlerini ayarla. Eksen bazlı çevirme INVERT_*_DIR ile uygulanır.
    dir_yaw_gpio_value = _direction_value(steps_yaw, INVERT_YAW_DIR)
    dir_pitch_gpio_value = _direction_value(steps_pitch, INVERT_PITCH_DIR)

    try:
        LGpio.gpio_write(lgh, YAW_DIR_PIN, dir_yaw_gpio_value)
        LGpio.gpio_write(lgh, PITCH_DIR_PIN, dir_pitch_gpio_value)
        time.sleep(0.000001)  # Yön sinyalinin oturması için kısa gecikme

        abs_steps_yaw = abs(int(steps_yaw))
        abs_steps_pitch = abs(int(steps_pitch))
        max_steps = max(abs_steps_yaw, abs_steps_pitch)

        if max_steps == 0:
            print("DEBUG (move_steppers_simultaneous): 0 adım için hareket yok.")
            sys.stdout.flush()
            return

        print(
            f"DEBUG (move_steppers_simultaneous): Motorlar hareket ediyor. Yaw: {abs_steps_yaw} adım (Yön: {'CW' if dir_yaw_gpio_value == DIR_CW else 'CCW'}), Pitch: {abs_steps_pitch} adım (Yön: {'CW' if dir_pitch_gpio_value == DIR_CW else 'CCW'}). Rampa: {MAX_DELAY} -> {MIN_DELAY}")
        sys.stdout.flush()

        _ramped_step_loop(max_steps, abs_steps_yaw, abs_steps_pitch)

        print("DEBUG (move_steppers_simultaneous): Motor hareketi tamamlandı.")
        sys.stdout.flush()

    except Exception as e:
        print(f"KRİTİK LGpio hatası (move_steppers_simultaneous): {e}")
        sys.stdout.flush()
        traceback.print_exc()


def set_motor_angles(yaw_angle, pitch_angle):
    """
    Taretin yatay (yaw) ve dikey (pitch) açılarını ayarlar.
    Bu fonksiyon eşzamanlı adım atma fonksiyonunu kullanır.
    """
    global _simulated_yaw, _simulated_pitch
    print(f"DEBUG (motor_fire_module): set_motor_angles çağrıldı. Hedef Yaw: {yaw_angle}, Hedef Pitch: {pitch_angle}")
    sys.stdout.flush()

    target_yaw = float(yaw_angle)
    target_pitch = float(pitch_angle)

    if _gpio_initialized and lgh is not None:
        current_yaw, current_pitch = get_current_angles()
        print(f"DEBUG (motor_fire_module): Mevcut Açı: Yaw {current_yaw:.3f}°, Pitch {current_pitch:.3f}°")
        sys.stdout.flush()

        # Açısal farkı hesapla ve -180 ile 180 arasına normalize et
        delta_yaw = target_yaw - current_yaw
        delta_yaw = (delta_yaw + 180) % 360 - 180  # Normalizasyon

        delta_pitch = target_pitch - current_pitch
        delta_pitch = (delta_pitch + 180) % 360 - 180  # Normalizasyon

        print(f"DEBUG (motor_fire_module): Delta Açı: Yaw {delta_yaw:.3f}°, Pitch {delta_pitch:.3f}°")
        sys.stdout.flush()

        # Adım sayılarını hesapla
        steps_yaw = int(round(delta_yaw * STEPS_PER_DEGREE_YAW))
        steps_pitch = int(round(delta_pitch * STEPS_PER_DEGREE_PITCH))
        print(f"DEBUG (motor_fire_module): Hesaplanan Adım: Yaw {steps_yaw}, Pitch {steps_pitch}")
        sys.stdout.flush()

        if steps_yaw != 0 or steps_pitch != 0:
            # Motorlar zaten initialize_gpio() tarafından etkinleştirildi, tekrar etkinleştirmeye gerek yok.
            print(
                f"DEBUG (motor_fire_module): Motorlar hareket ettiriliyor: Yaw {steps_yaw} adım, Pitch {steps_pitch} adım.")
            sys.stdout.flush()
            move_steppers_simultaneous(steps_yaw, steps_pitch)

            # SİMUULE EDİLMİŞ AÇILARI GERÇEKLEŞEN ADIMLARA GÖRE GÜNCELLE
            _simulated_yaw += steps_yaw / STEPS_PER_DEGREE_YAW
            _simulated_pitch += steps_pitch / STEPS_PER_DEGREE_PITCH

            # Açıları -180 ile 180 aralığında tut
            _simulated_yaw = (_simulated_yaw + 180) % 360 - 180
            _simulated_pitch = (_simulated_pitch + 180) % 360 - 180

            print(
                f"DEBUG (motor_fire_module): Simüle edilmiş açılar güncellendi: Yaw {_simulated_yaw:.3f}°, Pitch {_simulated_pitch:.3f}°")
            sys.stdout.flush()
        else:
            print("DEBUG (motor_fire_module): Hedef açılara zaten ulaşıldı veya adım sayısı 0, hareket yok.")
            sys.stdout.flush()


def set_manual_move_direction(yaw_direction, pitch_direction, degrees_to_move):
    """
    Manuel hareket için motorların hareket yönünü ve her adımda hareket edilecek derece miktarını ayarlar.
    Bu değerler perform_manual_move_step tarafından kullanılır.
    :param yaw_direction: -1 (sol), 0 (dur), 1 (sağ)
    :param pitch_direction: -1 (aşağı), 0 (dur), 1 (yukarı)
    :param degrees_to_move: Her adımda hareket edilecek derece miktarı.
    """
    global _yaw_moving_direction, _pitch_moving_direction, _manual_degrees_to_move
    global _manual_last_command_time, _servo_active

    degisti = (yaw_direction != _yaw_moving_direction or
               pitch_direction != _pitch_moving_direction)

    _yaw_moving_direction = yaw_direction
    _pitch_moving_direction = pitch_direction
    _manual_degrees_to_move = degrees_to_move
    # Watchdog'u besle: bu komut geldiği sürece hareket sürebilir.
    _manual_last_command_time = time.time()

    # Manuel hareket başlarsa servoyu devreden çıkar. Aksi halde kullanıcı
    # manuel sürdükten sonra servo, artık geçersiz olan ESKİ hedefine geri
    # dönmeye çalışır. Servo yalnızca yeni bir hedef komutuyla tekrar devreye girer.
    if yaw_direction != 0 or pitch_direction != 0:
        _servo_active = False

    # Yalnızca yön DEĞİŞTİĞİNDE yazdır. Arayüz canlılık komutu gönderdiği için
    # her komutta yazdırmak (üstelik flush ile) SSH üzerinde ciddi yük yaratır.
    if degisti:
        print(f"DEBUG (motor_fire_module): Manuel yön: Yaw {yaw_direction}, Pitch {pitch_direction}")
        sys.stdout.flush()


def perform_manual_move_step():
    """
    Manuel modda TEK BİR adım darbesi üretir ve açıyı o kadar ilerletir.

    Önceki sürüm her çağrıda "1 derece git" şeklinde bloklayan bir hareket
    yapıyordu; rampa her seferinde sıfırlandığı için tam hıza hiç ulaşılamıyor
    ve elde edilen hız donanım tavanının ~%8'inde kalıyordu. Şimdi hareket
    sürekli bir akış: rampa çağrılar arasında korunuyor, hız kademeli olarak
    MIN_DELAY'e çıkıyor.

    Bu fonksiyon rpi_motor_server'daki manual_move_loop tarafından sıkı bir
    döngüde çağrılmalıdır; adım zamanlamasının kendisi burada yapılır.

    :return: Adım atıldıysa True, hareket yoksa False (çağıran kısa uyuyabilir).
    """
    global _simulated_yaw, _simulated_pitch, _manual_current_delay

    # Watchdog: komut akışı kesildiyse hareketi durdur.
    komut_bayat = (time.time() - _manual_last_command_time) > MANUAL_COMMAND_TIMEOUT

    hareket_var = ((_yaw_moving_direction != 0 or _pitch_moving_direction != 0)
                   and _manual_degrees_to_move > 0
                   and not komut_bayat)

    if not hareket_var:
        # Duruş: bir sonraki kalkışın yavaş hızdan başlaması için rampayı geri sal.
        _manual_current_delay = min(MAX_DELAY, _manual_current_delay + DECEL_STEP)
        return False

    # Hızlan
    _manual_current_delay = max(MIN_DELAY, _manual_current_delay - ACCEL_STEP)

    yaw_aktif = _yaw_moving_direction != 0
    pitch_aktif = _pitch_moving_direction != 0

    if not _gpio_initialized or lgh is None:
        # Simülasyon modu: adım süresi kadar bekle, açıyı bir adım ilerlet.
        time.sleep(2 * _manual_current_delay)
        if yaw_aktif:
            _simulated_yaw += _yaw_moving_direction / STEPS_PER_DEGREE_YAW
            _simulated_yaw = (_simulated_yaw + 180) % 360 - 180
        if pitch_aktif:
            _simulated_pitch += _pitch_moving_direction / STEPS_PER_DEGREE_PITCH
            _simulated_pitch = (_simulated_pitch + 180) % 360 - 180
        return True

    # Yön pinlerini ayarla (yalnızca aktif eksenler için)
    if yaw_aktif:
        LGpio.gpio_write(lgh, YAW_DIR_PIN, _direction_value(_yaw_moving_direction, INVERT_YAW_DIR))
    if pitch_aktif:
        LGpio.gpio_write(lgh, PITCH_DIR_PIN, _direction_value(_pitch_moving_direction, INVERT_PITCH_DIR))

    # Tek darbe
    if yaw_aktif:
        LGpio.gpio_write(lgh, YAW_STEP_PIN, LGPIO_HIGH)
    if pitch_aktif:
        LGpio.gpio_write(lgh, PITCH_STEP_PIN, LGPIO_HIGH)
    time.sleep(_manual_current_delay)

    if yaw_aktif:
        LGpio.gpio_write(lgh, YAW_STEP_PIN, LGPIO_LOW)
    if pitch_aktif:
        LGpio.gpio_write(lgh, PITCH_STEP_PIN, LGPIO_LOW)
    time.sleep(_manual_current_delay)

    # Açıyı atılan adım kadar ilerlet
    if yaw_aktif:
        _simulated_yaw += _yaw_moving_direction / STEPS_PER_DEGREE_YAW
        _simulated_yaw = (_simulated_yaw + 180) % 360 - 180
    if pitch_aktif:
        _simulated_pitch += _pitch_moving_direction / STEPS_PER_DEGREE_PITCH
        _simulated_pitch = (_simulated_pitch + 180) % 360 - 180

    return True


def set_target_angles(yaw_angle, pitch_angle):
    """
    Otonom hedef açısını ayarlar. BLOKLAMAZ, yazdırmaz — sunucunun sıcak
    yolunda (saniyede onlarca kez) çağrılabilir.

    set_motor_angles ile farkı: o, hareketi çağıran iş parçacığında bloklayarak
    tamamlar (menü testleri için uygundur). Bu ise yalnızca hedefi kaydeder;
    hareketi perform_servo_step() ayrı bir döngüde yürütür. Yeni hedef eskisinin
    yerine geçtiği için komut kuyruğu oluşamaz.
    """
    global _target_yaw, _target_pitch, _servo_active
    _target_yaw = (float(yaw_angle) + 180) % 360 - 180
    _target_pitch = (float(pitch_angle) + 180) % 360 - 180
    _servo_active = True


def perform_servo_step():
    """
    Hedef açıya doğru TEK BİR adım darbesi üretir. Rampa çağrılar arasında
    korunur; yaklaşırken frenler, böylece hedefe mekanik olarak aşmadan oturur.

    :return: Adım atıldıysa True, hedefe varılmış/servo kapalıysa False.
    """
    global _simulated_yaw, _simulated_pitch, _servo_current_delay, _servo_active
    global _servo_bres_yaw, _servo_bres_pitch

    if not _servo_active:
        _servo_current_delay = min(MAX_DELAY, _servo_current_delay + DECEL_STEP)
        return False

    # Kalan açıyı en kısa yol üzerinden hesapla
    kalan_yaw_derece = (_target_yaw - _simulated_yaw + 180) % 360 - 180
    kalan_pitch_derece = (_target_pitch - _simulated_pitch + 180) % 360 - 180

    adim_yaw = int(round(kalan_yaw_derece * STEPS_PER_DEGREE_YAW))
    adim_pitch = int(round(kalan_pitch_derece * STEPS_PER_DEGREE_PITCH))

    if adim_yaw == 0 and adim_pitch == 0:
        # Hedefe varıldı: servoyu kapat, rampayı duruş hızına sal.
        # Ölü bant bir adımdır; bu, hedef etrafında titremeyi engeller.
        _servo_active = False
        _servo_current_delay = min(MAX_DELAY, _servo_current_delay + DECEL_STEP)
        _servo_bres_yaw = _servo_bres_pitch = 0.0
        return False

    # Bu hareketteki eksen oranlarına göre izin verilen en kısa periyot.
    # Saf tek eksen hareketinde o eksen tam hıza çıkabilir; çapraz harekette
    # sınırı en kısıtlayıcı eksen belirler.
    kalan_adim = max(abs(adim_yaw), abs(adim_pitch))
    alt_gecikme = _servo_gecikme_siniri(abs(adim_yaw) / kalan_adim,
                                        abs(adim_pitch) / kalan_adim)

    # Yamuk profil: frenleme mesafesi kaldıysa yavaşla, yoksa hızlan.
    frenleme_icin_gereken = (MAX_DELAY - _servo_current_delay) / DECEL_STEP
    if kalan_adim > frenleme_icin_gereken:
        _servo_current_delay = max(alt_gecikme, _servo_current_delay - ACCEL_STEP)
    else:
        _servo_current_delay = min(MAX_DELAY, _servo_current_delay + DECEL_STEP)
    # Yön değişince oran değişebilir; sınırı her tikta uygula.
    _servo_current_delay = max(_servo_current_delay, alt_gecikme)

    # --- ORANTILI (Bresenham) DARBE DAĞITIMI ---
    # Önceden kalan adımı olan HER eksen her tıkta darbe alıyordu. İki eksen
    # ortak darbe saatini paylaştığı için bu, ikisinin de aynı ADIM hızında
    # gitmesi demekti; yaw 26.667, pitch 17.778 adım/derece olduğundan pitch
    # derece cinsinden 1.5 kat hızlı gidip önce varıyordu. Sonuç: çapraz
    # hareket düz bir çizgi değil, önce çapraz sonra tek eksen olan BÜKÜK bir
    # yol. Ölçümde 10°+10° hareketin %31'i saf yaw olarak geçiyordu.
    #
    # Şimdi az adımı kalan eksen, oranı kadar seyrek darbe alıyor; böylece iki
    # eksen hedefe AYNI ANDA varıyor ve yol düz çapraz oluyor. Oran her tıkta
    # güncel kalan adımdan hesaplanır, dolayısıyla hedef hareket ederken de
    # (takip sırasında) doğru kalır.
    buyuk = max(abs(adim_yaw), abs(adim_pitch))
    _servo_bres_yaw += abs(adim_yaw) / buyuk
    _servo_bres_pitch += abs(adim_pitch) / buyuk

    yaw_aktif = _servo_bres_yaw >= 1.0
    pitch_aktif = _servo_bres_pitch >= 1.0
    if yaw_aktif:
        _servo_bres_yaw -= 1.0
    if pitch_aktif:
        _servo_bres_pitch -= 1.0

    yon_yaw = 1 if adim_yaw > 0 else -1
    yon_pitch = 1 if adim_pitch > 0 else -1

    if not _gpio_initialized or lgh is None:
        # Simülasyon modu
        time.sleep(2 * _servo_current_delay)
        if yaw_aktif:
            _simulated_yaw = (_simulated_yaw + yon_yaw / STEPS_PER_DEGREE_YAW + 180) % 360 - 180
        if pitch_aktif:
            _simulated_pitch = (_simulated_pitch + yon_pitch / STEPS_PER_DEGREE_PITCH + 180) % 360 - 180
        return True

    if yaw_aktif:
        LGpio.gpio_write(lgh, YAW_DIR_PIN, _direction_value(yon_yaw, INVERT_YAW_DIR))
    if pitch_aktif:
        LGpio.gpio_write(lgh, PITCH_DIR_PIN, _direction_value(yon_pitch, INVERT_PITCH_DIR))

    if yaw_aktif:
        LGpio.gpio_write(lgh, YAW_STEP_PIN, LGPIO_HIGH)
    if pitch_aktif:
        LGpio.gpio_write(lgh, PITCH_STEP_PIN, LGPIO_HIGH)
    time.sleep(_servo_current_delay)

    if yaw_aktif:
        LGpio.gpio_write(lgh, YAW_STEP_PIN, LGPIO_LOW)
    if pitch_aktif:
        LGpio.gpio_write(lgh, PITCH_STEP_PIN, LGPIO_LOW)
    time.sleep(_servo_current_delay)

    if yaw_aktif:
        _simulated_yaw = (_simulated_yaw + yon_yaw / STEPS_PER_DEGREE_YAW + 180) % 360 - 180
    if pitch_aktif:
        _simulated_pitch = (_simulated_pitch + yon_pitch / STEPS_PER_DEGREE_PITCH + 180) % 360 - 180

    return True


def perform_motion_step():
    """
    Hareketin TEK giriş noktası. STEP pinlerinin tek sahibi olmalıdır; iki ayrı
    döngü aynı pinleri sürerse darbeler birbirine karışır.

    Öncelik manueldedir: kullanıcı butona bastığında otonom hedef beklemez.

    :return: Adım atıldıysa True, hareket yoksa False (çağıran kısa uyuyabilir).
    """
    if _yaw_moving_direction != 0 or _pitch_moving_direction != 0:
        return perform_manual_move_step()
    return perform_servo_step()


def _servo_darbe(genislik_us):
    """
    Servo darbe genişliğini ayarlar; 0 = darbeyi kes (servo gevşer).

    lgpio.tx_servo darbeleri kütüphanenin KENDİ iş parçacığında üretir —
    çağrı anında döner, Python tarafını bloklamaz. Yazılım zamanlı olduğu
    için ~onlarca µs titreşim olabilir (~1-2 derece); 30 derecelik kaba
    git-gel için önemsiz. Rahatsız ederse GPIO12 donanım PWM'e bağlı,
    kablo değişmeden yazılım donanım PWM'e çevrilebilir.
    """
    # DARBEYI KESMEK ICIN tx_servo(..., 0) KULLANILMAZ. lgpio'nun bazi
    # surumlerinde 0 gecerli bir darbe genisligi degil ve
    #     lgpio.error: 'bad PWM micros'
    # atiyor (sahada Pi 5 uzerinde goruldu). Bu istisna initialize_gpio()
    # icinde yakalanmadigi icin TUM GPIO baslatmasini dusurur, yani motorlar
    # da calismaz. Dogru yol PWM'i durdurmak: tx_pwm frekansi 0.
    if genislik_us and int(genislik_us) > 0:
        LGpio.tx_servo(lgh, FIRE_SERVO_PIN, int(genislik_us),
                       FIRE_SERVO_FREQ, 0, 0)
        return
    try:
        LGpio.tx_pwm(lgh, FIRE_SERVO_PIN, 0, 0)      # frekans 0 = PWM dur
    except Exception:
        try:
            LGpio.gpio_write(lgh, FIRE_SERVO_PIN, 0)  # son care: pin LOW
        except Exception:
            pass


def _servo_ates():
    """
    Servo tetiği FIRE_SERVO_CYCLES kez çekip bırakır.

    Süre bütçesi: cycle başına 2 x FIRE_SERVO_LEG_SEC (varsayılan 0.4 sn).
    Bu çağrı Pi komut döngüsünde BLOKLAR — tek atışta kabul edilebilir;
    CYCLES büyütülürse ayrı iş parçacığına alınmalı.

    PC tarafındaki imha doğrulama penceresi (FIRE_CONFIRM_DELAY_SEC) bu
    mekanik gecikmeyi kapsayacak şekilde ayarlandı: mermi, röleye göre
    ~FIRE_SERVO_LEG_SEC daha geç çıkar.
    """
    if FIRE_SERVO_MODE == 'hiz':
        # SÜREKLİ DÖNÜŞ SERVOSU: konum yazılamaz, yalnızca "şu hızda şu süre
        # dön" denebilir — açık döngü.
        #
        # SIRA ÖNEMLİ: önce ÇEK, sonra BIRAK. İlk sürümde önce nötrün üstü
        # (ileri) veriliyordu; sahada o yönün tetiği BIRAKTIĞI görüldü, yani
        # ateşleme ters sırayla çalışırdı.
        cek = FIRE_SERVO_NEUTRAL_US + FIRE_SERVO_PULL_DIR * FIRE_SERVO_SPEED_US
        birak = FIRE_SERVO_NEUTRAL_US - FIRE_SERVO_PULL_DIR * FIRE_SERVO_SPEED_US
        print(
            f"DEBUG (motor_fire_module): SERVO(hiz) ateşleme: "
            f"{FIRE_SERVO_CYCLES} çevrim | çek {cek}us ({FIRE_SERVO_PULL_SEC}s) "
            f"-> tut {FIRE_SERVO_HOLD_SEC}s -> bırak {birak}us "
            f"({FIRE_SERVO_RELEASE_SEC}s) | nötr {FIRE_SERVO_NEUTRAL_US}us")
        sys.stdout.flush()

        # ATEŞTEN ÖNCE REFERANSA DÖN.
        # Açık döngüde kol nerede kaldıysa oradan başlanır; önceki atıştan
        # kalan sapma bu atışa taşınır ve hatalar birikir. Kısa bir bırakma
        # darbesiyle kolu dayanağa yaslayıp HER ATIŞA AYNI NOKTADAN
        # başlıyoruz. Dayanak yoksa bu adım zararsızdır (kol biraz daha
        # bırakma yönüne gider, çekme onu zaten geri alır).
        if FIRE_SERVO_HOME_SEC > 0:
            _servo_darbe(birak)
            time.sleep(FIRE_SERVO_HOME_SEC)
            _servo_darbe(FIRE_SERVO_NEUTRAL_US)
            time.sleep(0.05)

        for _ in range(FIRE_SERVO_CYCLES):
            _servo_darbe(cek)
            time.sleep(FIRE_SERVO_PULL_SEC)
            # Nötr = DUR. Sürekli dönüş servosunda nötrde tork yoktur, yani
            # tetik yayı kolu geri itebilir; bekleme kısa tutuluyor.
            _servo_darbe(FIRE_SERVO_NEUTRAL_US)
            time.sleep(FIRE_SERVO_HOLD_SEC)
            _servo_darbe(birak)
            time.sleep(FIRE_SERVO_RELEASE_SEC)
            _servo_darbe(FIRE_SERVO_NEUTRAL_US)     # DUR
            time.sleep(0.05)
    else:
        print(
            f"DEBUG (motor_fire_module): SERVO(konum) ateşleme: "
            f"{FIRE_SERVO_CYCLES} çevrim, "
            f"{FIRE_SERVO_PULL_US}us <-> {FIRE_SERVO_REST_US}us")
        sys.stdout.flush()
        for _ in range(FIRE_SERVO_CYCLES):
            _servo_darbe(FIRE_SERVO_PULL_US)
            time.sleep(FIRE_SERVO_LEG_SEC)
            # ÇEKİLİ BEKLEME. Standart servoda bu bekleme boyunca servo
            # konumu AKTİF OLARAK TUTAR (tork uygular), yani tetik yayı
            # kolu geri itemez. 'hiz' modunda bu mümkün değildi: orada
            # nötr = dur = tork yok.
            time.sleep(FIRE_SERVO_HOLD_SEC)
            _servo_darbe(FIRE_SERVO_REST_US)
            time.sleep(FIRE_SERVO_LEG_SEC)

    # Dinlenmeye oturduktan sonra darbeyi kes: servo gevşer, ısınmaz.
    # 'hiz' modunda nötr zaten "dur" demek, darbeyi kesmek de aynı sonucu
    # verir ama akım çekmeyi tamamen bitirir.
    time.sleep(0.1)
    _servo_darbe(0)
    print("DEBUG (motor_fire_module): Servo ateşleme tamamlandı.")
    sys.stdout.flush()


def fire_weapon():
    """
    Ateşleme mekanizmasını tetikler.
    """
    print("DEBUG (motor_fire_module): fire_weapon() çağrıldı.")
    sys.stdout.flush()
    if not _gpio_initialized or lgh is None or RELAY_ACTIVE is None or RELAY_INACTIVE is None:
        print("Hata (motor_fire_module): GPIO veya FIRE_PIN başlatılmadı, ateşleme mümkün değil (Simülasyon).")
        sys.stdout.flush()
        return

    try:
        if FIRE_MODE == 'servo':
            _servo_ates()
            return
        print(
            f"DEBUG (motor_fire_module): GPIO {FIRE_PIN} -> RELAY_ACTIVE ({RELAY_ACTIVE}) yapılıyor (Ateşleme Başladı).")
        sys.stdout.flush()
        LGpio.gpio_write(lgh, FIRE_PIN, RELAY_ACTIVE)
        time.sleep(PULSE_TIME)
        print(
            f"DEBUG (motor_fire_module): GPIO {FIRE_PIN} -> RELAY_INACTIVE ({RELAY_INACTIVE}) yapılıyor (Ateşleme Bitti).")
        sys.stdout.flush()
        LGpio.gpio_write(lgh, FIRE_PIN, RELAY_INACTIVE)
        time.sleep(0.1) # Rölenin tamamen kapanması için kısa bir bekleme
        print("DEBUG (motor_fire_module): Ateşleme tamamlandı.")
        sys.stdout.flush()
    except Exception as e:
        print(f"KRİTİK LGpio hatası (motor_fire_module): {e}. Pin: {FIRE_PIN}")
        sys.stdout.flush()
        traceback.print_exc()


def get_current_angles():
    """
    Taretin mevcut yatay (yaw) ve dikey (pitch) açılarını döndürür.
    Gerçek bir sistemde, sensörlerden (örn: enkoderler) okunmalıdır.
    Şimdilik simüle edilmiş değerleri döndürüyoruz.
    """
    global _simulated_yaw, _simulated_pitch
    return _simulated_yaw, _simulated_pitch


def reset_current_angles():
    """
    Taretin mevcut simüle edilmiş açılarını 0.0 yaw ve 0.0 pitch olarak sıfırlar.
    Bu, taretin mevcut konumunu yeni 'sıfır' noktası olarak ayarlamak için kullanılır.
    """
    global _simulated_yaw, _simulated_pitch, _target_yaw, _target_pitch, _servo_active
    _simulated_yaw = 0.0
    _simulated_pitch = 0.0

    # Servo hedefi de sıfırlanmalı, yoksa taret FIRLAR: servo
    # (_target - _simulated) farkına bakıyor. Hedef 30°'deyken mevcut açıyı
    # sıfırlamak, servoya "30° gitmem lazım" dedirtir. Pozisyon servosuna
    # geçişte ortaya çıkan bir yan etkiydi; eski bloklayan yapıda hedef diye
    # bir durum yoktu.
    _target_yaw = 0.0
    _target_pitch = 0.0
    _servo_active = False

    print("DEBUG (motor_fire_module): Taret açıları ve servo hedefi 0.0 olarak sıfırlandı.")
    sys.stdout.flush()


def get_emergency_stop_pin():
    """Acil durdurma pin numarasını döndürür."""
    return EMERGENCY_STOP_PIN


def get_lgpio_instance():
    """LGpio handle'ını döndürür."""
    return lgh


def cleanup_gpio():
    """
    Tüm GPIO pinlerini temizler.
    Bu fonksiyon, GPIO kaynaklarını serbest bırakır ancak motorları devre dışı bırakmaz.
    Motorların tutma torkunu korumak için ENABLE pinleri LOW'da kalır.
    """
    global _gpio_initialized, lgh
    print("DEBUG (motor_fire_module): cleanup_gpio() çağrıldı.")
    sys.stdout.flush()
    if _gpio_initialized and lgh is not None and lgh >= 0:
        try:
            # set_motors_enabled(False) # KALDIRILDI: Kullanıcının isteği üzerine motorlar devre dışı bırakılmayacak.
            if FIRE_MODE == 'servo':
                # Servoyu dinlenmeye götürüp darbeyi kes — tetik çekili
                # kalmasın. Kapanışta 0.4 sn beklemek kabul edilebilir.
                try:
                    _servo_darbe(FIRE_SERVO_NEUTRAL_US
                                 if FIRE_SERVO_MODE == 'hiz'
                                 else FIRE_SERVO_REST_US)
                    time.sleep(0.4)
                    _servo_darbe(0)
                    print("DEBUG (motor_fire_module): Servo tetik dinlenmede, darbe kesildi.")
                    sys.stdout.flush()
                except Exception as _se:
                    print(f"Uyarı (motor_fire_module): servo dinlendirme hatası: {_se}")
                    sys.stdout.flush()
            if FIRE_PIN is not None and RELAY_INACTIVE is not None:
                LGpio.gpio_write(lgh, FIRE_PIN, RELAY_INACTIVE) # Ateşleme pinini güvenli duruma getir
                print(
                    f"DEBUG (motor_fire_module): Fire pin ({FIRE_PIN}) RELAY_INACTIVE ({RELAY_INACTIVE}) yapıldı (Güvenli Durum).")
                sys.stdout.flush()

            LGpio.gpiochip_close(lgh)
            print("DEBUG (motor_fire_module): LGpio handle kapatıldı.")
            sys.stdout.flush()
            lgh = None
            _gpio_initialized = False
        except Exception as e:
            print(f"Hata (motor_fire_module): GPIO temizlenirken hata oluştu: {e}")
            sys.stdout.flush()
            traceback.print_exc()
    else:
        print("UYARI (motor_fire_module): lgpio kullanılamıyor veya handle yok, GPIO temizlenemedi.")
        sys.stdout.flush()


def test_single_motor_step(motor_type, direction_input, num_steps):
    """
    Tek bir motoru belirli bir yönde ve adım sayısında test etmek için.
    :param motor_type: 'yaw' veya 'pitch'
    :param direction_input: 1 (ileri/sağ/yukarı) veya 0 (geri/sol/aşağı)
    :param num_steps: Atılacak adım sayısı
    """
    print(
        f"DEBUG (motor_fire_module): test_single_motor_step çağrıldı. Motor: {motor_type}, Yön Girişi: {direction_input}, Adım: {num_steps}")
    sys.stdout.flush()
    if not _gpio_initialized or lgh is None:
        print(f"Hata (motor_fire_module): GPIO başlatılmadı veya kullanılamaz durumda. Test yapılamaz.")
        sys.stdout.flush()
        return False

    if num_steps <= 0:
        print(f"DEBUG (motor_fire_module): 0 veya negatif adım sayısı ({num_steps}) için hareket yok.")
        sys.stdout.flush()
        return True

    steps_yaw = 0
    steps_pitch = 0

    # direction_input (1 veya 0) değerini kullanarak adım yönünü ayarla
    # 1: pozitif adım (sağ/yukarı), 0: negatif adım (sol/aşağı)
    if motor_type == 'yaw':
        steps_yaw = num_steps if direction_input == 1 else -num_steps
    elif motor_type == 'pitch':
        steps_pitch = num_steps if direction_input == 1 else -num_steps
    else:
        print("Hata (motor_fire_module): Geçersiz motor tipi. 'yaw' veya 'pitch' olmalı.")
        sys.stdout.flush()
        return False

    print(f"DEBUG (motor_fire_module - test): Hesaplanan Adım: Yaw {steps_yaw}, Pitch {steps_pitch}")
    sys.stdout.flush()

    try:
        # Motorlar zaten initialize_gpio() ile etkinleştirildi.
        move_steppers_simultaneous(steps_yaw, steps_pitch)

        # Test fonksiyonunda da simüle edilmiş açıları güncelle
        if motor_type == 'yaw':
            _simulated_yaw += steps_yaw / STEPS_PER_DEGREE_YAW
            _simulated_yaw = (_simulated_yaw + 180) % 360 - 180
        elif motor_type == 'pitch':
            _simulated_pitch += steps_pitch / STEPS_PER_DEGREE_PITCH
            _simulated_pitch = (_simulated_pitch + 180) % 360 - 180

        print(
            f"DEBUG (motor_fire_module): {motor_type} motoru {num_steps} adım test edildi. Mevcut Açı: Yaw {_simulated_yaw:.3f}°, Pitch {_simulated_pitch:.3f}°")
        sys.stdout.flush()
        return True
    except Exception as e:
        print(f"Hata (motor_fire_module): {motor_type} motor testi sırasında hata oluştu: {e}")
        sys.stdout.flush()
        traceback.print_exc()
        return False


def run_calibration_test(motor_type, degrees_to_move):
    """
    Motor kalibrasyonu için belirli bir derece hareket ettirir ve kullanıcıdan geri bildirim alır.
    Bu fonksiyonu doğrudan motor_fire_module.py dosyasını çalıştırarak kullanabilirsiniz.
    """
    if not _gpio_initialized:
        print("Hata: GPIO başlatılmadı, kalibrasyon testi yapılamaz.")
        sys.stdout.flush()
        return

    print(f"\n--- {motor_type.upper()} Motor Kalibrasyon Testi ---")
    print(f"Hedef: {degrees_to_move} derece hareket ettirilecek.")
    print(
        f"Mevcut {motor_type} STEPS_PER_DEGREE: {STEPS_PER_DEGREE_YAW if motor_type == 'yaw' else STEPS_PER_DEGREE_PITCH}")
    sys.stdout.flush()

    initial_yaw, initial_pitch = get_current_angles()
    print(f"Başlangıç Açılar: Yaw {initial_yaw:.1f}°, Pitch {initial_pitch:.1f}°")
    sys.stdout.flush()

    # Motorlar zaten initialize_gpio() ile etkinleştirildi.

    if motor_type == 'yaw':
        target_yaw = initial_yaw + degrees_to_move
        set_motor_angles(target_yaw, initial_pitch)
    elif motor_type == 'pitch':
        target_pitch = initial_pitch + degrees_to_move
        set_motor_angles(initial_yaw, target_pitch)

    time.sleep(2)  # Motorun hareketini tamamlaması için bekle

    final_yaw, final_pitch = get_current_angles()
    print(f"Bitiş Açılar (Simüle Edilmiş): Yaw {final_yaw:.1f}°, Pitch {final_pitch:.1f}°")
    sys.stdout.flush()

    print("\n!!! DİKKAT: Lütfen taretin fiziksel olarak ne kadar döndüğünü ölçün. !!!")
    print(f"Hedeflenen hareket: {degrees_to_move} derece.")
    sys.stdout.flush()
    actual_movement_str = input(f"Fiziksel olarak {motor_type} motoru kaç derece döndü? (örn: 58.5): ")
    try:
        actual_movement = float(actual_movement_str)
        if actual_movement == 0:
            print("Hata: Motor hiç hareket etmedi. Bağlantıları veya güç kaynağını kontrol edin.")
            sys.stdout.flush()
            return

        if motor_type == 'yaw':
            current_steps_per_degree = STEPS_PER_DEGREE_YAW
            pulses_per_rev = PULSES_PER_REV_YAW
            current_ratio = GEAR_RATIO_YAW
        else:
            current_steps_per_degree = STEPS_PER_DEGREE_PITCH
            pulses_per_rev = PULSES_PER_REV_PITCH
            current_ratio = GEAR_RATIO_PITCH

        new_steps_per_degree = (current_steps_per_degree / actual_movement) * degrees_to_move
        # STEPS_PER_DEGREE artık türetilmiş bir değer; elle düzenlenemez.
        # Formüle giren gerçek parametre redüksiyon oranıdır, onu öneriyoruz.
        implied_ratio = new_steps_per_degree * 360.0 / pulses_per_rev

        print(f"\n--- KALİBRASYON SONUCU ---")
        print(f"Mevcut {motor_type} STEPS_PER_DEGREE: {current_steps_per_degree:.3f} "
              f"({pulses_per_rev} pulse/rev x {current_ratio} oran / 360)")
        print(f"Fiziksel olarak dönülen derece: {actual_movement:.1f}° (hedef: {degrees_to_move}°)")
        print(f"ÖNERİLEN {motor_type} STEPS_PER_DEGREE: {new_steps_per_degree:.3f}")
        print(f"ÖNERİLEN GEAR_RATIO_{motor_type.upper()}: {implied_ratio:.4f}")
        print(f"Lütfen motor_fire_module.py içindeki 'GEAR_RATIO_{motor_type.upper()}' değerini bununla güncelleyin.")
        print("(Sapma çok büyükse önce sürücünün SW1-SW4 pulse/rev ayarını ve "
              f"PULSES_PER_REV_{motor_type.upper()} = {pulses_per_rev} değerinin eşleştiğini doğrulayın.)")
        print("Bu testi birkaç kez tekrarlayarak ve ortalama alarak daha doğru bir değer bulabilirsiniz.")
        print("Motor adım kaçırıyorsa veya titriyorsa MAX_DELAY'i büyütün (örn: 0.002) "
              "veya ACCEL_STEP'i küçültün (örn: 0.00002).")
        sys.stdout.flush()

    except ValueError:
        print("Geçersiz giriş. Lütfen sayısal bir değer girin.")
        sys.stdout.flush()
    except Exception as e:
        print(f"Kalibrasyon sırasında hata oluştu: {e}")
        sys.stdout.flush()
        traceback.print_exc()


def stop_all_motors():
    """
    Tüm motor hareketlerini durdurur ve motorları devre dışı bırakır.
    Bu fonksiyon acil durdurma durumlarında veya motorların tamamen durdurulması istendiğinde çağrılmalıdır.
    """
    # Step pinlerini LOW yaparak motor adımlarını durdur
    if LGpio and lgh is not None and _gpio_initialized:
        try:
            LGpio.gpio_write(lgh, YAW_STEP_PIN, LGPIO_LOW)
            LGpio.gpio_write(lgh, PITCH_STEP_PIN, LGPIO_LOW)
            print("DEBUG (motor_fire_module): Tüm motor hareketleri durduruldu (STEP pinleri LOW).")
            sys.stdout.flush()
        except Exception as e:
            print(f"HATA (stop_all_motors): STEP pinleri LOW yapılırken hata: {e}")
            traceback.print_exc()
            sys.stdout.flush()
    else:
        print("UYARI (motor_fire_module): lgpio kullanılamıyor veya handle yok, motorlar durdurulamadı.")
        sys.stdout.flush()
    #set_motors_enabled(False)  # Motorları durdurduktan sonra devre dışı bırak


# YENİ: Doğrudan Yaw motoru testi için fonksiyon
def test_direct_yaw_movement_steps(steps, direction):
    """
    Yaw motorunu doğrudan belirli adım sayısı ve yönde hareket ettirir.
    Bu fonksiyon, kalibrasyon testinden daha temel bir seviyede motoru test etmek içindir.
    :param steps: Atılacak adım sayısı.
    :param direction: 0 (geri/sol) veya 1 (ileri/sağ).
    """
    print(f"\n--- Doğrudan YAW Motoru Adım Testi ---")
    print(f"Hedef: {steps} adım {'ileri/sağ' if direction == 1 else 'geri/sol'} yönde hareket ettirilecek.")
    sys.stdout.flush()

    if not _gpio_initialized or lgh is None:
        print(f"Hata (test_direct_yaw_movement_steps): GPIO başlatılmadı veya kullanılamaz durumda. Test yapılamaz.")
        sys.stdout.flush()
        return False

    if steps <= 0:
        print(f"DEBUG (test_direct_yaw_movement_steps): 0 veya negatif adım sayısı ({steps}) için hareket yok.")
        sys.stdout.flush()
        return True

    dir_gpio_value = _direction_value(1 if direction == 1 else -1, INVERT_YAW_DIR)

    try:
        set_motors_enabled(True) # Test için motoru etkinleştir
        LGpio.gpio_write(lgh, YAW_DIR_PIN, dir_gpio_value)
        time.sleep(0.000001) # Yön sinyalinin oturması için kısa gecikme

        print(f"DEBUG (test_direct_yaw_movement_steps): Yaw motoru hareket ediyor. {steps} adım. Rampa: {MAX_DELAY} -> {MIN_DELAY}")
        sys.stdout.flush()

        # Gerçek hareket profilini test etmek için ana hareket fonksiyonuyla aynı rampa
        _ramped_step_loop(steps, steps, 0)

        print("DEBUG (test_direct_yaw_movement_steps): Yaw motoru hareketi tamamlandı.")
        sys.stdout.flush()
        return True
    except Exception as e:
        print(f"HATA (test_direct_yaw_movement_steps): Yaw motoru testi sırasında hata oluştu: {e}")
        sys.stdout.flush()
        traceback.print_exc()
        return False
    finally:
        set_motors_enabled(False) # Test sonrası motoru devre dışı bırak

# YENİ: Doğrudan Pitch motoru testi için fonksiyon
def test_direct_pitch_movement_steps(steps, direction):
    """
    Pitch motorunu doğrudan belirli adım sayısı ve yönde hareket ettirir.
    Bu fonksiyon, kalibrasyon testinden daha temel bir seviyede motoru test etmek içindir.
    :param steps: Atılacak adım sayısı.
    :param direction: 0 (geri/aşağı) veya 1 (ileri/yukarı).
    """
    print(f"\n--- Doğrudan PITCH Motoru Adım Testi ---")
    print(f"Hedef: {steps} adım {'ileri/yukarı' if direction == 1 else 'geri/aşağı'} yönde hareket ettirilecek.")
    sys.stdout.flush()

    if not _gpio_initialized or lgh is None:
        print(f"Hata (test_direct_pitch_movement_steps): GPIO başlatılmadı veya kullanılamaz durumda. Test yapılamaz.")
        sys.stdout.flush()
        return False

    if steps <= 0:
        print(f"DEBUG (test_direct_pitch_movement_steps): 0 veya negatif adım sayısı ({steps}) için hareket yok.")
        sys.stdout.flush()
        return True

    dir_gpio_value = _direction_value(1 if direction == 1 else -1, INVERT_PITCH_DIR)

    try:
        set_motors_enabled(True) # Test için motoru etkinleştir
        LGpio.gpio_write(lgh, PITCH_DIR_PIN, dir_gpio_value)
        time.sleep(0.000001) # Yön sinyalinin oturması için kısa gecikme

        print(f"DEBUG (test_direct_pitch_movement_steps): Pitch motoru hareket ediyor. {steps} adım. Rampa: {MAX_DELAY} -> {MIN_DELAY}")
        sys.stdout.flush()

        # Gerçek hareket profilini test etmek için ana hareket fonksiyonuyla aynı rampa
        _ramped_step_loop(steps, 0, steps)

        print("DEBUG (test_direct_pitch_movement_steps): Pitch motoru hareketi tamamlandı.")
        sys.stdout.flush()
        return True
    except Exception as e:
        print(f"HATA (test_direct_pitch_movement_steps): Pitch motoru testi sırasında hata oluştu: {e}")
        sys.stdout.flush()
        traceback.print_exc()
        return False
    finally:
        set_motors_enabled(False) # Test sonrası motoru devre dışı bırak


if __name__ == '__main__':
    # Bu bölüm, motor_fire_module.py'yi doğrudan çalıştırdığınızda test etmenizi sağlar.
    print("motor_fire_module.py doğrudan çalıştırıldı. GPIO başlatılıyor.")
    sys.stdout.flush()
    initialize_gpio() # Motorlar burada etkinleştirilecek
    if _gpio_initialized:
        reset_current_angles()
        print("\n--- Motor Kalibrasyon ve Test Menüsü ---")
        print("1. Yaw Motoru Kalibrasyonu (örn: 90 derece)")
        print("2. Pitch Motoru Kalibrasyonu (örn: 30 derece)")
        print("3. Ateşleme Testi")
        print("4. Doğrudan YAW Motoru Adım Testi")
        print("5. Doğrudan PITCH Motoru Adım Testi") # Yeni seçenek
        print("6. Çıkış") # Seçenek numarası güncellendi
        sys.stdout.flush()

        while True:
            choice = input("Seçiminizi yapın (1-6): ") # Seçenek aralığı güncellendi
            if choice == '1':
                try:
                    degrees = float(input("Yaw motorunu kaç derece hareket ettirmek istersiniz? (örn: 90): "))
                    run_calibration_test('yaw', degrees)
                except ValueError:
                    print("Geçersiz derece girişi.")
                    sys.stdout.flush()
            elif choice == '2':
                try:
                    degrees = float(input("Pitch motorunu kaç derece hareket ettirmek istersiniz? (örn: 30): "))
                    run_calibration_test('pitch', degrees)
                except ValueError:
                    print("Geçersiz derece girişi.")
                    sys.stdout.flush()
            elif choice == '3':
                print("Ateşleme testi yapılıyor...")
                sys.stdout.flush()
                fire_weapon()
                time.sleep(1)
                print("Ateşleme testi tamamlandı.")
                sys.stdout.flush()
            elif choice == '4':
                try:
                    steps = int(input("Yaw motorunu kaç adım hareket ettirmek istersiniz? (örn: 1600): "))
                    direction_str = input("Yön (ileri/sağ için 1, geri/sol için 0): ")
                    direction = int(direction_str)
                    if direction not in [0, 1]:
                        print("Geçersiz yön girişi. Lütfen 0 veya 1 girin.")
                        sys.stdout.flush()
                        continue
                    test_direct_yaw_movement_steps(steps, direction)
                except ValueError:
                    print("Geçersiz adım veya yön girişi.")
                    sys.stdout.flush()
            elif choice == '5': # Yeni doğrudan Pitch testi seçeneği
                try:
                    steps = int(input("Pitch motorunu kaç adım hareket ettirmek istersiniz? (örn: 1600): "))
                    direction_str = input("Yön (ileri/yukarı için 1, geri/aşağı için 0): ")
                    direction = int(direction_str)
                    if direction not in [0, 1]:
                        print("Geçersiz yön girişi. Lütfen 0 veya 1 girin.")
                        sys.stdout.flush()
                        continue
                    test_direct_pitch_movement_steps(steps, direction)
                except ValueError:
                    print("Geçersiz adım veya yön girişi.")
                    sys.stdout.flush()
            elif choice == '6': # Çıkış seçeneği güncellendi
                print("Çıkılıyor...")
                sys.stdout.flush()
                break
            else:
                print("Geçersiz seçim.")
                sys.stdout.flush()
            time.sleep(0.5)
    else:
        print("GPIO başlatılamadığı için testler yapılamadı.")
        sys.stdout.flush()
    cleanup_gpio() # Çıkışta motorları devre dışı bırakmaz, sadece GPIO kaynaklarını temizler
    print("motor_fire_module.py betiği tamamen kapatıldı.")
    sys.stdout.flush()
