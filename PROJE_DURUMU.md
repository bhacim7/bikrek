# BUKREK Hava Savunma Sistemi — Proje Durumu ve Devir Belgesi

> Bu belge, bir oturum boyunca yapılan tüm çalışmanın özetidir. Yeni bir
> konuşmada bağlam olarak paylaşılabilir. Son güncelleme: 2026-08-10.

---

## 1. Sistem nedir, nasıl çalışır

Kamera ile balon tespit edip step motorlu bir tareti hedefe yönelten,
PC + Raspberry Pi 5 mimarili bir hava savunma sistemi prototipi.

### Mimari

| Birim | Nerede | Görevi |
|---|---|---|
| `camera_module.py` | PC, ayrı **süreç** | Kamerayı okur, kareyi **çekilme zamanıyla damgalayıp** kuyruğa koyar |
| `inference_module.py` | PC, ayrı **süreç** | YOLO/TensorRT çıkarımı, QR okuma, hayalet tespit filtresi |
| `bukrek_main.py` | PC, ana süreç | Arayüz + hedef seçimi + PID + kalibrasyon aracı |
| `rpi_communicator.py` | PC, **thread** | TCP soketi, satır sonu ile ayrılmış JSON protokolü |
| `rpi_motor_server.py` | Pi 5 | Soket sunucusu, hareket döngüsü thread'i |
| `motor_fire_module.py` | Pi 5 | GPIO, step motor sürüşü, ateşleme rölesi |
| `config.py` | PC | Tüm saha ayarları tek dosyada |

Kuyruklar `maxsize=2`; kare birikirse eskisi atılır (gerçek zamanlılık).

### Kontrol döngüsü — üç ayrı zaman referansı

Bu projedeki hataların çoğu bu üçünü karıştırmaktan çıktı:

```
kamera sensörü pozlar            → t_poz
      ↓ USB + MJPG boru hattı (~0.08 sn, CAPTURE_LATENCY_OFFSET)
camera_worker kareyi okur        → frame_time damgası
      ↓ çıkarım + IPC + arayüz (~0.16 sn)
UI kareyi işler, piksel hatasını ölçer
      ↓
hedefin DÜNYA açısı = (t_poz anındaki taret açısı) + hatanın derecesi
      ↓
PID hatası = dünya açısı − taretin ŞU ANKİ açısı
      ↓
Pi'ye MUTLAK hedef açı gönderilir (delta değil)
      ↓
Pi'de sürekli servo döngüsü rampalı olarak o açıya gider
```

`_angle_history` zaman damgalı bir tampon; `_angle_at(t)` istenen andaki
açıyı verir. `_piksel_to_dunya` / `_dunya_to_piksel` dönüşümleri **her zaman
kare çekilme anındaki açıyı** kullanır.

### Pi tarafı hareket

Tek giriş noktası `perform_motion_step()` — STEP pinlerinin tek sahibi.
Manuel yön verilmişse manuel adım, yoksa servo adımı atar. İkisi de **tek
darbe** üretir; rampa çağrılar arasında korunur. Soket döngüsü hiçbir zaman
motor hareketi için bloklanmaz.

---

## 2. Donanım

- **Motorlar:** Leadshine CS-M22323 kapalı çevrim step (120 W, 5 A), 2 eksen
- **Sürücüler:** Leadshine CS-D508 kapalı çevrim
- **Kart:** Raspberry Pi 5 (GPIO: yaw 17/27/22, pitch 24/23/25, röle 16)
- **Kamera:** Logitech BRIO 4K

| | Yaw | Pitch |
|---|---|---|
| pulse/rev (sürücü DIP) | 3200 | 6400 |
| Redüksiyon | 3.0 | 1.0 |
| adım/derece | 26.667 | 17.778 |
| **1 tam tur** | **9600 adım** | **6400 adım** |
| Yön çevirme | `True` | `True` |

**Pi 5 notu:** 40 pinli başlık `/dev/gpiochip0` DEĞİL. Kod chip'i etiketinden
(`pinctrl-rp1`) bulur; çekirdek güncellemesi numaraları kaydırsa da çalışır.

### Kamera ayarları (Logitech uygulaması)

- Görüş alanı **65°**, yakınlaştırma **%100**
- Pozlama **manuel**, HDR kapalı
- Odak **manuel**
- Uygulamada 1920x1080, `config.py`'da 1280x720 (bu kombinasyon deneyle
  daha iyi bulundu)

> **KURAL:** FOV, yakınlaştırma veya çözünürlükten biri değişirse
> `DEGREES_PER_PIXEL` **geçersizdir**, kalibrasyon tekrar çalıştırılmalı.

---

## 3. Bu oturumda ne yapıldı

### A. Multiprocess bölünmesinin denetimi

Monolitik `denemePro.py` beş dosyaya bölünmüştü. Bölme yapısal olarak
eksiksizdi ama dört gerçek hata vardı:

| Bulgu | Etkisi |
|---|---|
| `rpi_communicator`'da `'\n'` yerine `'\\n'` | **Sistem tamamen sağır** — hiçbir komut işlenmiyordu |
| Çözünürlük `1080x720` sabit yazılmış | Kamera farklı çözünürlük verirse nişan merkezi kayıyordu |
| Kilitli hedef renk kodlaması kaybolmuş | Operatör hangi hedefin kilitli olduğunu göremiyordu |
| `close_event` imzası `aboutToQuit` ile uyumsuz | Çıkışta `TypeError`, temizlik çalışmıyordu |

### B. Yeni motorlara geçiş

Adım/derece türetilmiş hale getirildi (`pulse/rev × redüksiyon / 360`),
ivme rampası eklendi (NEMA23 rotor ataleti sabit hızda kalkışta adım
kaçırıyordu), her iki eksende yön çevrildi, `gpiochip` etiketten bulunuyor.

### C. Manuel kontrol: ayrık hareketten sürekli akışa

**Ölçüm:** elde edilen hız 10.6°/s, donanım tavanı 125°/s — kapasitenin %8'i.

İki sebep: rampa her komutta sıfırlanıyordu (1° = 27 adım, tam hıza çıkmak
45 adım gerekiyor), ve arayüz saniyede 100 komut gönderirken Pi 10.6 tanesini
tüketebiliyordu (**9 kat birikme**) — "dur" komutu kuyruğun arkasında kalıyordu.

**Sonuç:** 10.6 → **121°/s**, bırakma tepkisi 0 ekstra adım. Sürekli hareketin
getirdiği risk için 0.35 sn watchdog eklendi.

### D. Otonom takip — sırayla ortaya çıkan altı hata

Her biri bir öncekini maskeliyordu.

**D1 — Kuyruk birikmesi.** PID komutları Pi'de bloklayarak işleniyordu.
3 saniyede 42 komut kuyrukta, taret hedefi **448 piksel** aşıyordu.
→ "Şu kadar dön" yerine "şu açıya git" (pozisyon servosu). Yeni hedef
eskisinin yerine geçtiği için kuyruk oluşamıyor.

**D2 — Kalibrasyon 4.3 kat yanlış.** `DEGREES_PER_PIXEL` eski optiğe göreydi.
`KP=0.7` yazılırken efektif kazanç **0.16**'ymış — "çok yavaş" şikâyetinin
sayısal karşılığı. Kalibrasyon aracı eklendi (iki kez düzeltmek gerekti:
görüntünün oturmasını beklemiyordu, ve tutarsız ölçümleri sessizce ortalıyordu).

**D3 — Ölü zaman.** Eski karede ölçülen hata taretin şu anki açısına
ekleniyordu; gecikme boyunca kat edilen yol **iki kez sayılıyordu**.
İmzası: aşım gecikmeyle büyüyor (0.10 sn'de 183 px, 0.20 sn'de 343 px).
→ Telafiyle aşım gecikmeden bağımsız: 10-11 px.

**D4 — Tahmin patlaması.** Hedef kaybolduğunda konum piksel uzayında tahmin
ediliyordu; piksel hızının neredeyse tamamı taretin kendi dönüşü. Dünya
uzayına taşındı — ve bu düzeltmede bir koordinat tutarsızlığı bırakıldı
(dönüşüm "şu anki" açıyla, yorum "çekilme anı" açısıyla) → hata **3.541.501
piksele** fırladı. Dönüşüm de çekilme anına bağlanınca çözüldü.

**D5 — Hayalet tespitler.** Tek balonlu sahnede karelerin **%41.7'sinde**
hayalet vardı (tavanda `red_balloon 0.66`, gerçek balon 0.44). Kural "kareye
en yakın tespit" olduğu için hayalet kazanıyordu.
→ Renk tutarlılık filtresi + boyut sınırı + güven skoruna göre ayıklama.

**D6 — Bükük çapraz yol.** İki eksen ortak darbe saatini paylaşıyor ve her
tıkta kalan adımı olan **her** eksen darbe alıyordu. Pitch derece cinsinden
1.5 kat hızlı gidip önce varıyordu: 10°+10° hareketin **%31'i saf yaw**.
→ Bresenham (orantılı) darbe dağıtımı: varış farkı 83 ms → 3 ms.

### E. Kamera boru hattı gecikmesi

`frame_time` sensörün pozladığı an değil, karenin **okunduğu** an. Aradaki
USB+MJPG gecikmesi telafi edilmiyordu. İmzası: aşım **taret hızıyla** büyüyor
(0.06 sn gecikmede 25°/s'de 27 px, 70°/s'de 75 px).

Sahadan doğrulandı: aynı sabit hedefin dünya açısı tahmini taret hızlıyken
13.3°, taret durunca 25.0°.

→ `CAPTURE_LATENCY_OFFSET`, sahada **0.08** olarak ayarlandı.

### F. Hız sınırları

- **Eksen başına tepe hız:** sabit alt gecikme pitch ekseninden türetildiği
  için yaw 46.7°/s'de kalıyordu. Artık her hareket için Bresenham oranlarına
  göre hesaplanıyor → saf yaw hareketinde yaw da sınıra çıkabiliyor.
- **Hız tahmini sınırı ayrıldı:** `MAX_TARGET_RATE_DEG_S` (feedforward) 80,
  `PREDICTION_MAX_RATE_DEG_S` (kayıpta tahmin) 20. 20'de kırpmak feedforward'ı
  çalışamaz hale getiriyordu (50°/s hedefte 33 px → 12 px).

---

## 4. Denenip ELENEN hipotezler

Bunlar ölçülerek elendi; tekrar denemeye gerek yok:

| Hipotez | Ölçüm |
|---|---|
| Kalan aşım feedforward'dan | Katkısı **+2 px** — ihmal edilebilir |
| Kalan aşım D'nin yetersizliğinden | KD 0.001→0.03 aşımı **6 px'den 25 px'e ÇIKARIYOR** (gürültüyü yükseltiyor) |
| Feedforward'ı artırmak hareketli takibi iyileştirir | Kötüleştiriyor: etkin 0.03 sn → 6 px, 0.24 sn → 34 px |
| Çözünürlüğü artırmak tespiti iyileştirir | Model girişi 1056x1056; aynı FOV'da balon her çözünürlükte aynı piksel boyutunda |
| Gecikme ofseti otomatik ölçülebilir | Yazıldı ve **kaldırıldı** — gerçeğin %42'sini buluyor (PID geri beslemesi regresyonu saptırıyor) |

**Not:** `KI` ve `KD` fiilen etkisiz (katkıları 0.002° ve 0.025°). Denetleyici
pratikte **saf P + feedforward**. `KD`'yi kurcalamanın anlamı yok.

---

## 5. Şu anki ayarlar (`config.py`)

```python
DEGREES_PER_PIXEL_YAW    = 0.05350   # sahada ölçüldü
DEGREES_PER_PIXEL_PITCH  = -0.05547
KP_YAW = 0.7 ; KP_PITCH = 0.6
CAPTURE_LATENCY_OFFSET   = 0.08      # sahada ayarlandı
FEEDFORWARD_GAIN = 0.3 ; FEEDFORWARD_LEAD_TIME = 0.10
VELOCITY_SMOOTHING = 0.3 ; VELOCITY_DECAY_SMOOTHING = 0.6   # asimetrik sönüm
FEEDFORWARD_VELOCITY_DEADBAND = 2.0 ; FEEDFORWARD_MAX_DEGREE = 3.0
MAX_TARGET_RATE_DEG_S = 80.0         # feedforward
PREDICTION_MAX_RATE_DEG_S = 20.0     # kayıpta tahmin
LOCK_CONFIRM_FRAMES = 3 ; MAX_MISSING_FRAMES = 5
PID_DEADBAND_PIXELS = 5.0 ; MIN_OUTPUT_PIXELS = 3.0
DETECTION_COLOR_CHECK = True ; DETECTION_COLOR_MIN_RATIO = 0.05
DETECTION_MAX_AREA_RATIO = 0.25 ; ACQUIRE_CONFIDENCE_MARGIN = 0.15
CAMERA_WIDTH = 1280 ; CAMERA_HEIGHT = 720 ; CAMERA_USE_MJPG = True
```

`motor_fire_module.py`: `SERVO_MAX_DEG_PER_SEC = 100` (Pi'de 100 ile test edildi)

### Türetilen değerler

- Görüş açısı: **68.5° yatay / 40° dikey**
- Ölü bant: 5 px = 0.27°
- Nişan toleransı: 15 px = **0.80°** (10 m'de 14 cm)
- Kayıpta tahmin üst sınırı: 5 kare × 20°/s = **4°**

---

## 6. Bilinen açık konular

### Kodda duran gerçek sorunlar

1. **Aşama 3 görülmeyen hedefe ateş edebilir.** Aşama 2'nin ateş koşulu
   `detected_class_status == "red_balloon"` kontrolü içeriyor, Aşama 3'ünki
   içermiyor. Hedef kaybolduğunda `current_target_bbox_for_pid` tahmin edilmiş
   bir kutu olur ve Aşama 3 ona ateş edebilir.
2. **`is_aimed_at_target` bayat hatadan hesaplanıyor.** Ölü zaman telafisinden
   sonra gerçek anlık hata `error_yaw_degree`, ama nişan kontrolü hâlâ çekilme
   anındaki piksel hatasını kullanıyor. Otonom ateş doğruluğunu etkiler.
3. **Ateşleme Pi'nin soket döngüsünü 0.2 sn blokluyor** (`fire_weapon` içinde
   `sleep`, `process_command`'dan çağrılıyor).
4. **Ateşsiz bölge varsayılanı (0,0) tam 0.0°'de ateşi engelliyor** — mantık
   bunu "0.0 derece yasak" diye yorumluyor.
5. **Sessiz hedef değiştirme.** Takip eşleştirmesi balonları ayırt etmiyor
   (sadece sınıf + 250 px yakınlık = 13°). Takip edilen balon bir kare
   kaybolursa, yakındaki başka bir balona sessizce geçilir. Çok balonlu
   testte beklenmelidir.

### Yanıltıcı ama hata olmayanlar

- Aşama 2'deki "dost hedef algılandı" dalı **ölü kod** (aday listesi zaten
  yalnızca kırmızı içeriyor).
- `engagement_home_position` hiç ayarlanmıyor, hep (0,0).
- Zamansal onay (`LOCK_CONFIRM_FRAMES`) yalnızca Aşama 1/2'de; Aşama 3 QR
  üzerinden kilitleniyor.

### Kök sebebi yazılımda olmayanlar

- **YOLO bu mesafede güvenilir değil.** Gerçek balon 0.44–0.81 arası, hayalet
  0.40–0.66. Renk + boyut filtresi bastırıyor ama çözmüyor. Kalıcı çözüm
  model tarafında (daha fazla veri).
- **Hareket bulanıklığı.** Kamera pozlaması kısaltılınca keskinlik
  dalgalanması 4.0 kattan 1.7 kata düştü, ama tam bitmedi.

---

## 7. Test/doğrulama yöntemi

Bu projede sahte GPIO ve sahte zaman kullanan bir test paketi var
(scratchpad'de, depoda değil). Her değişiklik bunlarla doğrulandı:

| Paket | Ne doğruluyor |
|---|---|
| `verify_manual` | Manuel hız, bırakma tepkisi, watchdog, iki eksen |
| `verify_servo` | Pozisyon servosu, tepe hız, titreme, manuel önceliği |
| `verify_deadtime` | Ölü zaman telafisi (aşım gecikmeden bağımsız mı) |
| `verify_lost` | Hedef kaybında dünya-uzayı tahmini |
| `verify_blowup` | Tahmin patlaması geri döndü mü |
| `verify_ff` | Feedforward, asimetrik sönüm, gürültü |
| `verify_cal` | Kalibrasyon durum makinesi |
| `verify_renk` | Renk filtresi (SAHA kayıtlarındaki gerçek kutularla) |
| `verify_asim` | Aşımın FF/KD/gecikme bileşenleri |

**Yöntem notu:** Video kayıtları kare kare incelenerek telemetri (açı + piksel
hatası) çıkarıldı; hipotezler bu veriyle doğrulandı veya elendi. Tahminle
parametre değiştirilmedi.

---

## 8. Sıradaki adımlar

**Hemen test edilecek** (son commit, sahada denenmedi):
- `MAX_TARGET_RATE_DEG_S` 20 → 80 ayrımı. Hareketli hedefte nişangahın balon
  merkezine oturması beklenir (ölçümde 50°/s'de 33 px → 12 px).

**Devam ederse:**

| Gözlem | Düğme |
|---|---|
| Hareketli hedefte hâlâ geride | `SERVO_MAX_DEG_PER_SEC` artır |
| Sabit hedefte küçük salınım | `PID_DEADBAND_PIXELS` 5 → 7 |
| Hedefi aşıp dönme | `CAPTURE_LATENCY_OFFSET` ince ayar (0.06–0.10) |
| Yavaş kilitlenme | `KP_YAW` 0.7 → 0.9 |

**Otonom ateşe geçmeden önce:** yukarıdaki 1., 2. ve 4. maddeler düzeltilmeli.

**Çok balonlu teste geçerken:** 5. madde (sessiz hedef değiştirme) devreye
girecek. Öneriler: kayıp penceresini zamanla büyüt (sabit 250 px yerine),
kutu boyutunu kimlik olarak kullan, hedef değişimini duruma yaz.

---

## 9. Depo

- Dal: `motor-cs-d508-port`, PR #2 (bhacim7/bikrek), **açık**
- `main`'e göre 24 commit, 5 dosya
- `denemePro.py` (monolitik referans) commit edilmedi

Pi'ye kopyalanması gerekenler: `motor_fire_module.py`, `rpi_motor_server.py`

```bash
scp motor_fire_module.py rpi_motor_server.py bukrek@raspberrypi:~/Desktop/raspberry/
```
