# BUKREK Hava Savunma Sistemi — Proje Durumu ve Devir Belgesi

> Bu belge, bir oturum boyunca yapılan tüm çalışmanın özetidir. Yeni bir
> konuşmada bağlam olarak paylaşılabilir. Son güncelleme: 2026-08-14.
>
> **En güncel durum için önce en sondaki "FAZ 3" bölümünü okuyun.** Belge
> kronolojik büyüyor; aşağıdaki eski bölümlerde geçen bazı sayılar FAZ 3'te
> güncellendi.

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
| pulse/rev (sürücü DIP) | 3200 | 3200 |
| Redüksiyon | 3.0 (10→30 diş) | **5.0 (PLF060 planet redüktör)** |
| adım/derece | 26.667 | **44.444** |
| **1 tam tur** | **9600 adım** | **16000 adım** |
| Yön çevirme | `True` | `False` |
| tepe hız (manuel) | 125°/s | **75°/s** |
| tepe hız (otonom) | 100°/s | **75°/s (kırpılmış)** |

> Pitch redüktörü FAZ 3'te eklendi; gerekçesi ve ölçümleri en sondaki
> bölümde. Planet redüktör yön çevirmez, bu yüzden `INVERT_PITCH_DIR`
> değişmedi (o bayrak 2026-08-14'te ayrı bir sebeple `False` yapılmıştı).

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

> 1. ve 4. maddeler FAZ 2'de (ateş kilidi), 5. madde FAZ 3'te (angajman
> makinesi hedefin tek sahibi) kapandı. Kalanlar:

1. ~~Aşama 3 görülmeyen hedefe ateş edebilir.~~ **ÇÖZÜLDÜ** —
   `engagement.ates_serbest_mi()` dokuz koşulu birden arıyor.
2. **`is_aimed_at_target` bayat hatadan hesaplanıyor.** Ölü zaman telafisinden
   sonra gerçek anlık hata `error_yaw_degree`, ama nişan kontrolü hâlâ çekilme
   anındaki piksel hatasını kullanıyor. Otonom ateş doğruluğunu etkiler.
   **AÇIK.**
3. **Ateşleme Pi'nin soket döngüsünü 0.2 sn blokluyor** (`fire_weapon` içinde
   `sleep`, `process_command`'dan çağrılıyor). **AÇIK.**
4. ~~Ateşsiz bölge varsayılanı (0,0) tam 0.0°'de ateşi engelliyor.~~
   **ÇÖZÜLDÜ** — başlangıç = bitiş ise bölge tanımsız sayılıyor.
5. ~~Sessiz hedef değiştirme.~~ **ÇÖZÜLDÜ** — otonom aşamalarda hedefi artık
   yalnızca angajman makinesi seçiyor; `dogrulanan_sinif` ile eşleşen çift
   tercih ediliyor. Eski "sınıf + yakınlık" takip dalı yalnızca hedef bir
   kare kaybolduğunda tahmin için devreye giriyor.

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

---

## Son Değişiklik: Uyarlamalı Hız Yumuşatma

**Sorun.** `VELOCITY_SMOOTHING` tek başına iki çelişen ihtiyaca hizmet ediyordu.
Sahada ölçüldü:

- **0.3** — sabit hedefe oturma temiz, ama hareketli hedefte nişangah kutunun
  iç sınırında kalıyor.
- **0.5 / 0.6** — hareketli hedefte merkeze biraz daha yaklaşıyor, ama hedef
  çerçeveye girince ufak salınımlar başlıyor, oturma bozuluyor.

**Sebep.** Sabit hedefte hız tahmini saf tespit gürültüsüdür; hızlı yumuşatma
bu gürültüyü feedforward'a geçirir. Hareketli hedefte ise el hareketi sabit
hızlı değil sürekli ivmelenir; yavaş yumuşatma 2-3 kare (80-120 ms) geriden
gelir ve feedforward hep bir önceki hızı telafi eder.

**Çözüm.** Katsayı artık hızın büyüklüğüne göre seçiliyor
(`bukrek_main._hiz_alfa`):

| Durum | Katsayı |
|---|---|
| Hız azalıyor (hedef duruyor) | `VELOCITY_DECAY_SMOOTHING = 0.6` |
| Hız >= `VELOCITY_FAST_THRESHOLD` (10 °/s) | `VELOCITY_FAST_SMOOTHING = 0.6` |
| Altında (sabit hedef, gürültü baskın) | `VELOCITY_SMOOTHING = 0.3` |

**Doğrulama** (simülasyon; 3.2 °/s tespit gürültüsü, 33 ms kare):

| | sabit hedef: ölü bandı aşan kare | ivmelenen hedef: ort. hız hatası |
|---|---|---|
| 0.3 | 8/70 | 7.7 °/s |
| 0.5 düz | 20/70 | 3.6 °/s |
| **uyarlamalı** | **8/70** | **2.6 °/s** |

Yani sabit hedef davranışı 0.3 ile birebir aynı kalırken hareketli hedefteki
tahmin hatası 0.5'ten de düşük.

**Sahada denenecek.** Sadece `VELOCITY_FAST_THRESHOLD` oynatılmalı:
- Sabit hedefte hâlâ küçük salınım varsa → 15 veya 20 yap (hızlı moda daha geç
  geçer).
- Yavaş gezdirilen balonda hâlâ geride kalıyorsa → 6-7 yap. 
  `FEEDFORWARD_VELOCITY_DEADBAND` (2.0) altına inmemeli.

**Denenmiş ve işe yaramayan yollar** (tekrar denemeye gerek yok):
- `KP` yükseltme — 0.7/0.9/1.1 taramasında hareketli hedef hatası
  10/13/14 px, fark yok.
- `FEEDFORWARD_GAIN` yükseltme — 45 °/s hedefte 0.3 → 10 px, 1.0 → 37 px,
  yani daha kötü.

---

## Kök Neden: Açı Geçmişi Sızıntısı (hssCiftDeneme.mp4 analizi)

Bu, hem sabit hedefteki salınımın hem de hareketli hedefteki kalıcı gecikmenin
**ortak sebebi**. Ekran kaydından kare kare ölçüldü.

### Ölçüm 1 — kalan gecikme sabit ve büyük

Taretin gerçek dönüş hızı, arka planın (sabit tavan/kirişler) kayma miktarından
optik akışla çıkarıldı. Kararlı takipte taret hızı = hedef hızı olduğundan,
kalan piksel hatası / hedef hızı = etkin ölü zaman:

| video kesiti | hedef hızı | kalan hata | ima edilen gecikme |
|---|---|---|---|
| 8-11 s | 7-13 °/s | 36-55 px | 205-259 ms |
| 13-18 s | 5-11 °/s | 24-43 px | 200-402 ms |
| 21-24 s | 7-9 °/s | 25-42 px | 196-300 ms |
| 26-29 s | 6-16 °/s | 18-68 px | 173-235 ms |

14 kesitte **ortanca 0.22 s**, yön ve hızdan bağımsız — yani saf ölü zaman.
Buna karşılık etkin feedforward telafisi `GAIN x LEAD = 0.3 x 0.10 = 0.03 s`
idi; ölçülenin yedide biri.

### Ölçüm 2 — hız tahmini gürültüsü sinyal kadar büyük

Hedef GERÇEKTEN sabitken sistemin hesapladığı dünya hızı sıfır olmalı:

| faz | taret hızı RMS | ölçülen "hedef hızı" RMS |
|---|---|---|
| tam durgun (36.5-41 s) | 0.2 °/s | **0.4 °/s** — temiz |
| oturmuş ama mikro hareketli (5-6.5 s) | 7.8 °/s | **8.1 °/s** |
| salınım fazı (2.8-4.8 s) | 34.0 °/s | **14.4 °/s** |

Taret hareket ettiği anda sahte hedef hızı ortaya çıkıyor ve büyüklüğü taret
hızıyla orantılı. Elde gezdirilen balonun gerçek hızı 5-15 °/s olduğuna göre
**gürültü sinyal kadar büyüktü**.

### Kaynak

`bukrek_main._angle_at()` açı geçmişinden **en yakın önceki kaydı olduğu gibi**
döndürüyordu (sıfırıncı derece tutma) ve Pi açıları **20 Hz** ile gönderiyordu.
Ortalama 25 ms'lik sistematik gecikme, taret 40 °/s'de dönerken 1.0° = 19 px
açı hatası demek. Kare kare türevi alınınca sahte hız çıkıyor.

Simülasyon ölçümü birebir doğruladı (5-6.5 s fazı: model 8.8 °/s, saha 8.1 °/s).

| örnekleme | sahte hız RMS (oturmuş) | (hareketli) |
|---|---|---|
| 20 Hz tutma (eskisi) | 8.8 °/s | 18.7 °/s |
| 20 Hz aradeğerleme | 4.8 °/s | 14.6 °/s |
| **50 Hz aradeğerleme** | **1.2 °/s** | **3.1 °/s** |

### Neden feedforward artışı daha önce işe yaramamıştı

Videodan çıkarılan **gerçek hedef yörüngesi** kapalı döngüde tekrar oynatıldı
(ortalama hata, px):

| yapılandırma | hareketli | sabit |
|---|---|---|
| eski hali | 45.0 | 7.5 |
| sadece açı düzeltmesi | 39.8 | 6.5 |
| açı düzeltmesi + ff artışı | **21.7** | 6.5 |
| **sadece ff artışı (açı düzeltmesi YOK)** | **67.0** | **48.3** |

Son satır sahada gözlenen "feedforward'ı açınca kötüleşiyor" davranışını
birebir üretiyor. Açı düzeltmesi ön koşuldu.

### Yapılan değişiklikler

| yer | eski | yeni |
|---|---|---|
| `bukrek_main._angle_at` | sıfırıncı derece tutma | **lineer aradeğerleme** |
| `rpi_motor_server.angle_sender_loop` | 20 Hz | **50 Hz** |
| `FEEDFORWARD_LEAD_TIME` | 0.10 | **0.22** (ölçülen) |
| `FEEDFORWARD_GAIN` | 0.3 | **0.8** |
| `FEEDFORWARD_MAX_DEGREE` | 3.0 | **5.0** |
| `FEEDFORWARD_VELOCITY_DEADBAND` | 2.0 | **4.0** |
| `VELOCITY_FAST_THRESHOLD` | 10.0 | **4.0** |
| `VELOCITY_DECAY_SMOOTHING` | 0.6 | **0.75** |

Son ikisi ve ölü bant, ff artışının yan etkilerini kapatmak için tarandı;
seçilen değerler dört fazın **dördünde birden** eski değerlerden iyi:

| video fazı | eski | yeni |
|---|---|---|
| hareketli takip (7-29 s) | 45.0 px | **25.4 px** (-43%) |
| edinme salınımı (5-6.5 s) | 7.5 px | **6.8 px** (-8%) |
| hedefi durdurma (30-32 s) | 4.1 px | **2.9 px** (-29%) |
| tam oturmuş (36.6-41 s) | 2.4 px | **1.4 px** (-39%) |

> **`rpi_motor_server.py` Pi tarafında.** Değişikliğin etkili olması için
> dosyanın Pi'ye kopyalanıp sunucunun yeniden başlatılması gerekir. Yalnızca
> PC tarafı güncellenirse aradeğerleme 20 Hz veriyle çalışır — yine de eskisinden
> iyidir (39.8 px) ama tam kazanç alınmaz.

### Sahada sıradaki düğme

Kalan hareketli hedef hatası ~25 px. Etkin ileri görüş şu an 0.176 s, ölçülen
gecikme 0.22 s. `FEEDFORWARD_GAIN` 0.8 -> 1.0 yapmak farkı kapatır. Sabit hedefte
titreme başlarsa geri düşürün. `KP` ve `VELOCITY_SMOOTHING` bu iş için denendi
ve kaldıraç değiller — tekrar denemeye gerek yok.

---

# FAZ 2: Çift Kamera Mimarisi (yeni hedef konsepti)

Motor/denetim optimizasyonu tamamlandı. Bu faz yeni hedef konseptine, çift
kamera mimarisine ve yeni görev aşamalarına geçişi kapsıyor.

## Yeni hedef konsepti

Hedef artık tek nesne değil bir **çift**: üstte dost/düşman maketi, hemen
altında kırmızı balon. `data.yaml`'da tek bir `balon` sınıfı var — yani balon
dost/düşman bilgisi **taşımıyor**, karar zorunlu olarak üstteki maketten
geliyor.

```
nc: 6
names: ['balon', 'dost-F16', 'dost-Helikopter',
        'dusman-Drone', 'dusman-F16', 'dusman-Fuze']
```

Üç aşama da **tek YOLO modelini** kullanıyor (`best.engine`, ana dizinde).

| aşama | içerik |
|---|---|
| 1 | tamamen manuel |
| 2 | hızlı imha; üç yoldan yalnızca düşman gelir |
| 3 | dost/düşman ayrımı; iki mavi bir kırmızı maket |

## Çift kamera

| | gözcü (spotter) | avcı (hunter) |
|---|---|---|
| konum | gövdeye sabit | taret üzerinde |
| zoom | yok | sabit 3x |
| işlev | OpenCV renk analizi | YOLO |
| °/piksel yaw | 0.0535 | 0.01783 |
| görüş açısı | 68.5 x 39.9° | 22.8 x 13.3° |

15 metrede: balon avcıda 30 px / gözcüde 10 px, maket avcıda 96 px.

Gözcü gövdeye sabit olduğu için çıktısı **mutlak açı**; taretin hareketi
ölçümünü etkilemez. Geçen fazda uğraştığımız açı-geçmişi sızıntısı bu hatta
yapısal olarak yok.

## Kritik bulgu 1: "en büyük kırmızı = düşman" kuralı çalışmıyor

Örnek görselden ölçülen kırmızı piksel alanları:

| hedef | toplam kırmızı |
|---|---|
| yakın **dost** (mavi heli + kırmızı balon) | ~16.200 |
| yakın **düşman** (kırmızı drone + balon) | ~43.300 |
| uzak **düşman** (kırmızı F16 + balon) | ~3.600 |

Uzak düşman, yakın dostun 4.5 katı daha az kırmızı veriyor — kural dostu
seçer. Sebep: dostun altında da kırmızı balon var (kırmızı tabanı sıfır
değil) ve alan mesafenin karesiyle ters orantılı.

**Çözüm: geometri.** Balonun üstünde, balonun **kendi piksel çapıyla**
ölçeklenen bir pencerede mavi/kırmızı **oranına** bakılıyor. Oran mesafeden
bağımsız. Birim testi bu senaryoyu doğruluyor: yeni kural doğru seçiyor,
eski kural dostu seçiyor.

Gözcünün kararı yine de **nihai değil** — yalnızca sıralama. Karar avcının
YOLO'sunda; dost çıkarsa hedef kara listeye girer.

## Kritik bulgu 2: hedefler beklenenden 10 kat yavaş

Hedefler 0.4 m/s ile **tarete doğru** geliyor. Hareket büyük ölçüde radyal
olduğu için açısal hız çok düşük (7.5 m yanal ofsetli yol için):

| mesafe | açısal hız | ff'siz kalan hata |
|---|---|---|
| 15 m | 0.6 °/s | 8 px |
| 8 m | 1.4 °/s | 18 px |
| 5 m | 2.1 °/s | 26 px |

Elde gezdirilen balonda 5-15 °/s ölçmüştük. `FEEDFORWARD_VELOCITY_DEADBAND`
4.0 iken feedforward **hiç çalışmazdı**. 1.0'a indirildi.

## 3x zoomun eşiklere etkisi

Kural: eşik neye karşı koruyorsa onun biriminde tanımlı olmalı.

| ayar | durum |
|---|---|
| `KP_*`, `FEEDFORWARD_LEAD_TIME/GAIN` | derece uzayında — aynen geçerli |
| `PID_DEADBAND_PIXELS`, `MIN_OUTPUT_PIXELS` | tespit gürültüsüne karşı — aynen geçerli |
| `FEEDFORWARD_ERROR_GATE_PIXELS` | **açısal** olgu — (30,120) -> **(90,360)** |
| `FEEDFORWARD_VELOCITY_DEADBAND` | 4.0 -> **1.0** |
| `VELOCITY_FAST_THRESHOLD` | 4.0 -> **1.5** |
| `MAX_TARGET_RATE_DEG_S` | 80 -> **30** |
| `PREDICTION_MAX_RATE_DEG_S` | 20 -> **8** |
| nişan toleransı | sabit 15 px -> **balon yarıçapının %35'i** |

## Yeni dosyalar

- **`spotter_module.py`** — gözcü süreci: renk maskeleri, balon blobları,
  "maviyi üstte ara" testi, kalıcı izler, açı + açısal hız.
- **`engagement.py`** — hedef çifti modeli, geometrik eşleştirme, kara liste,
  durum makinesi (BOSTA -> TARAMA -> YÖNELME -> DOĞRULAMA -> KİLİT -> ATEŞ),
  ateş kilidi. UI'dan bağımsız, simüle edilebilir.

## Devir teslim öngörüsü

Gözcü gecikmesi (~0.05 s) + yalpalama süresi (0.34-0.45 s) yaklaşık 0.5 s.
Avcının dikey yarı görüş açısı yalnızca ±6.65°. Bu yüzden taret gözcünün
**ölçtüğü** değil **tahmin ettiği** açıya gönderiliyor.

## Ateş kilidi

Eski otomatik ateş yolları **tamamen kaldırıldı**. Aşama 2 artık var olmayan
`red_balloon` sınıfına bakıyordu; Aşama 3 ise hiçbir sınıf kontrolü yapmadan
tahmin edilmiş hedefe ateş edebiliyordu. Tek karar noktası
`engagement.ates_serbest_mi()` ve dokuz koşul birden aranıyor: maket bu
karede gerçekten tespit edildi, sınıfı `dusman-`, güven eşik üstü, doğrulanan
sınıfla aynı, balon bu karede gerçekten tespit edildi, nişan tolerans içinde,
ateşsiz bölge dışında, durum ATEŞ.

Ateşsiz bölge (0,0) varsayılanının tam 0.0°'de ateşi engellediği eski hata da
düzeltildi (başlangıç = bitiş ise bölge tanımsız sayılıyor).

## SAHADA YAPILMASI GEREKENLER (kod hazır, ölçüm bekliyor)

1. **`HUNTER_DPP_YAW/PITCH`** — şu an gözcününkinin üçte biri olarak
   *hesaplandı*, ölçülmedi. "Derece/Piksel Ölç" ile doğrulanmalı.
2. **`SPOTTER_YAW_OFFSET` / `SPOTTER_PITCH_OFFSET`** — gözcü-avcı hizalaması.
   Şu an 0.0; ölçülmeden devir teslim isabetsiz olur.
3. **`CAPTURE_LATENCY_OFFSET`** — avcı kamera için yeniden ölçülmeli.
4. **Kamera pozlaması ~10 ms'ye sabitlenmeli**, otomatik pozlama ve otomatik
   beyaz dengesi kapatılmalı. 33 ms pozlamada taret 89 °/s'de dönerken
   bulanıklık 165 piksel; balon 30 piksel, tamamen sıvanır.
5. **İki kamera aynı anda açılabiliyor mu** — USB bant genişliği testi.
   `SPOTTER_CAMERA_INDICES` ve `HUNTER_CAMERA_INDICES` doğru ayarlanmalı.
6. **`BALLISTIC_PITCH_OFFSET`** — 15 metrede mermi düşüşü.

---

# FAZ 3: Saha kaydı çözümlemesi, redüktör ve yeni avcı kamera (2026-08-14)

## 1. Ekran kaydından bulunan dört hata

`AnalizVideo.mp4` (35 sn, 1062 kare) kare kare çözümlendi: durum çubuğu, açı
okuması ve avcı görüntüsü ayrı ayrı çıkarıldı. Üç şikâyetin **üç ayrı kök
nedeni** vardı, üstüne hepsini görünmez kılan bir dördüncü.

### A. Aşama 3'te taret hiç kıpırdamıyordu — ölü QR kapısı

`update_frame` içindeki

```python
if active_task == 'task3' and waiting_for_new_engagement_command \
        and not is_ready_to_engage_from_qr:
```

koşulu `task3()` sonrası **her karede doğruydu**. Sistem artık var olmayan bir
QR kodunu bekliyor, angajman makinesine giden `elif` dalına hiç ulaşılmıyordu.
Kilit kalıcıydı: `waiting_for_new_engagement_command` yalnızca o dalda
temizlenebiliyordu. Kayıtta yaw 29-35 sn arası 3.7°'de çakılı kaldı.

**Kaynak:** `018750b` commit'i `task3()`/`_task3_baslat()` ekledi, eski QR
kapısı yerinde kaldı. Blok ve ona bağlı "eve dön" yolu kaldırıldı.

### B. Aşama 2'de taret sola dönüp duruyordu — gözcü hizalaması

Bu bir hata değildi: `tarama_adimi` gözcünün ilk izini seçip mutlak açıya
gitti (9.3° → -21.0°, 0.6 sn, kare 651-662). Sorun hedefin orada olmaması.
Yalpalama sırasında kare 658'de (yaw -10.2) avcı gerçek düşman çiftini
**0.82/0.83 güvenle çerçeveleyip önünden geçti**.

Duran karelerden ölçüldü:

| kaynak | gözcünün dediği | avcıdan ölçülen gerçek |
|---|---|---|
| mavi dost-F16 | ≈ +3.0° | ≈ **+11.5°** |
| kırmızı düşman + balon | −20.7° | ≈ **−8.5°** |

Doğrusal uydurma: `avcı ≈ 0.84 × gözcü + 9.0`. Yani **hem ofset hem kazanç**
yanlış: `SPOTTER_YAW_OFFSET ≈ +9°` (şu an 0.0) ve `SPOTTER_DPP_YAW ≈ 0.045`
(şu an 0.0535 — gözcünün gerçek yatay görüş açısı ~58°, varsayılan 68.5°
değil). Pitch için ≈ −2.4°. **Bunlar tahmin, ölçüm değil — sahada
doğrulanmalı.**

İkincil: doğrulama zaman aşımı adayı kara listeye almadığı için TARAMA aynı
izi tekrar seçiyordu; taret 4 saniye boş duvara baktı.
`BLACKLIST_VERIFY_TTL_SEC = 5.0` eklendi.

### C. "Derece/Piksel Ölç" hiç ilerlemiyordu — erişilemez durum makinesi

`_calibration_tick`'in tek çağıranı `process_tracking`, o da
`active_task in OTONOM_MODLAR` kapısının arkasındaydı; kalibrasyon ise
`task1` şartı arıyordu. **Birbirini dışlıyorlardı.** Buton ilk mesajı
yazıyor, tick bir kez bile çalışmıyor, 60 sn sonra zaman aşımına düşüyordu.
Kayıtta durum 10-16 sn arası "ölçüm başlıyor..." satırında dondu.

**Kaynak:** `ea368a0` servolamayı `OTONOM_MODLAR` ile sınırladı, `44ca604`
kalibrasyonun *kilit* şartını düzeltti ama tick çağrısı erişilemez yolda kaldı.

### D. Durum çubuğu her şeyi eziyordu

`update_frame` sonundaki `elif self.active_task != 'task3_setup'` dalı
Aşama 2/3 dahil **her karede koşulsuz** "Durum: Hazır." yazıyordu. `task2()`'nin
mesajı ve angajman makinesinin bütün ara durumları 40 ms sonra siliniyordu.
Bu, `8044af5`'in kalibrasyon butonu için çözdüğü hatanın aynısıydı; görev
durumlarına uygulanmamıştı. Otonom aşamalarda tek yazar artık
`_angajman_adimi`.

### E. Bonus: makine kilitlendikten sonra donuyordu

`_angajman_adimi` yalnızca "hedef edinme" dalından çağrılıyordu; hedefe
kilitlenir kilitlenmez o dal devre dışı kalıyor, makine DOĞRULAMA'da
donuyordu — KİLİT'e hiç geçilemediği için `kilit_adimi` ve **otonom ateş
fiilen erişilemezdi**. Adım artık daldan bağımsız, her karede bir kez atılıyor.

Buna bağlı ikinci düzeltme: `_nisan_tespiti` balonun üstüne nişan alıp kutuya
**maketin** sınıf adını yazıyor; eski takip dalı hedefi sınıf adıyla yeniden
bulduğu için maket kutusunu seçiyor ve taret **balona değil maketin kendisine**
nişan alıyordu. Yeni `_otonom_hedefi_benimse` bunu kapatıyor.

## 2. Yapısal rezonans ölçümü (hssMotorDeneme.mp4 / 2.mp4)

Motor enerjiliyken elle itme testi. Kamera sarsıntısı optik akış + RANSAC
afin kestirimiyle giderildi, sonra her piksel için düşey hız zaman serisi
2-6 Hz bandına süzülüp referansla korelasyona sokuldu.

**Sehpa ve taban suçsuz.** Taret tabanı AC salınımı 1.8 px — ölçüm gürültü
tabanının (2.8 px) altında. Namlu 12.6, tüp arkası 17.2 px.

**Düğüm tam pitch ekseninde.** Sütun profili x≈350'de belirgin minimum
(0.18 px) veriyor, iki yana doğru 1.0'a çıkıyor; faz haritasında namlu tarafı
kırmızı, tüp tarafı mavi (ters faz). Yakın çekim videosunda pivot kelepçesi
yoke'a göre ötelenmiyor (3.2 px ≈ iki kanat arası gürültü 2.3 px). Yani
**hareket saf dönme; esneklik pitch tahrik hattında.**

**Frekans ve sönüm** — beş bağımsız sönüm treni:

| itme | frekans | ζ | başlangıç genliği |
|---|---|---|---|
| 2.40-2.93 s | 2.81 Hz | 0.053 | 22.2 px |
| 4.03-4.97 s | 2.68 Hz | 0.046 | 25.7 px |
| 6.70-7.33 s | 3.16 Hz | 0.072 | 20.3 px |
| 8.10-9.27 s | 2.57 Hz | 0.059 | 29.0 px |
| 10.07-11.37 s | 2.31 Hz | 0.062 | 36.4 px |

**f ≈ 2.7 Hz, ζ ≈ 0.058 (Q ≈ 8.6).** 1/20'ye inmesi 3.0 saniye; 1°'lik
çınlamanın nişan toleransı altına inmesi ~1.9 saniye.

**Frekans genlikle monoton düşüyor** (20.3 px → 3.16 Hz ... 36.4 px → 2.31 Hz;
beş noktanın beşi sıralı). Yumuşayan yay = boşluklu/sürtünmeli bağlantı;
doğrusal malzeme esnekliği böyle davranmaz.

### Henüz uygulanmayan, ölçümden çıkan iki kod maddesi

1. **PID bu modu besliyor olabilir.** Ölü zaman 0.22 sn, modun periyodu
   0.37 sn → **214° faz gecikmesi**, neredeyse tam ters faz. "KD 0.001→0.03
   aşımı 6 px'den 25 px'e ÇIKARIYOR" ölçümünün açıklaması bu olabilir.
2. **`AIM_HOLD_FRAMES = 3` çok kısa.** ~20 fps'de 0.15 sn; salınım periyodu
   0.37 sn. Sistem namlu salınımın ortasından geçerken "nişan tamam" diyebilir.
   Bir tam periyodu kapsaması için ~8 kare olmalı.

Bunlar **redüktör takılıp yeniden ölçüldükten sonra** ele alınacak.

## 3. Pitch redüktörü: PLF060-L1-5 (1:5)

Elde 1:5 vardı, o takıldı. Sahada doğrulandı: motor enerjiliyken silahı elle
itmek artık çok zor.

| | eski (doğrudan) | **1:5** |
|---|---|---|
| adım/derece | 17.778 | **44.444** |
| çözünürlük | 0.0563°/adım | **0.0225°/adım = 1.0 px** |
| yansıyan yük ataleti | ×1 | **÷25** |
| çıkış torku | ×1 | **×4.85** |
| manuel tepe hız | 187°/s | **75°/s** |

DIP **3200'de kaldı**. 6400 seçilseydi adım/derece 88.9 olur, donanım tavanı
(3333 darbe/sn) pitch'i 37.5°/s'ye düşürürdü.

`SERVO_MAX_DEG_PER_SEC` hâlâ 100; saf pitch hareketinde
`_servo_gecikme_siniri` bunu donanım tavanına **kırpıyor** (75°/s). Kırpma
bilinçli — 20°'lik en kötü pitch yolu 0.27 sn sürüyor, `ENGAGE_SLEW_TIMEOUT`
2.5 sn. Yavaş pitch 2.7 Hz'lik modu da daha az uyarır. Yaw etkilenmiyor.

Ayrıca `_servo_gecikme_siniri` ve `SERVO_MIN_DELAY` artık `MIN_DELAY` tabanını
uyguluyor: dişli oranı veya DIP değişikliği bir daha sessizce donanım
tavanının üstünde darbe hızı isteyemez.

**Beklenen sonuç (sınanabilir):** sertlik 25 kat arttıysa çınlama frekansı
2.7 → ~13 Hz olmalı. Frekans değişmediyse yumuşak eleman motor değil,
braket/kaplin demektir.

## 4. Yeni avcı kamera: Arducam B0495C (AR0234) + 12 mm

Zoomlu Logitech'in yerine geçti. Global shutter, 2.3 MP, USB3, UVC
(tak-çalıştır).

```
AR0234 piksel 3.0 um, odak 12 mm -> sensör piksel başına 0.014324 derece
tam genişlik 1920 x 3.0 um = 5.76 mm -> yatay görüş açısı 27.0 derece
1280 genişlikte: 0.014324 x 1920/1280 = 0.021486 derece/piksel
```

**Çözünürlük 1280x720'de kaldı.** Belirleyici olan model girişi: motor
**1056x608** olarak export edilmiş (`convert_to_engine.py`).

| kaynak | küçültme | en/boy bozulması |
|---|---|---|
| **1280x720** | **1.21x** | **%2.4** |
| 1920x1080 | 1.82x | %2.4 |
| 1920x1200 | 1.82x | %8.5 |

`_preprocess` varsayılan `INTER_LINEAR` kullanıyor; 1.82 katta örnekleme
atlanır (aliasing), 1.21 katta pratikte sorun yok. Ayrıca **çözünürlük
artırmak hedefi büyütmez**: modele giren karede nesnenin boyutu yalnızca
görüş açısına bağlıdır (balon 15 m'de her iki halde de 20.5 px). Buna karşılık
1920x1080 her karede 2.25 kat piksel = daha fazla ölü zaman.

**Bir varsayıma dayanıyor:** modülün 1280x720 modunun tam genişliği
ÖLÇEKLEDİĞİ varsayıldı. KIRPIYORSA görüş açısı 18.3°'ye düşer, doğru değer
0.014324 olur ve açısal eşikler 1.5 katına çıkmalıdır. Ayırt etme testi
`config.py`'daki yorumda.

### Buna bağlı yeniden ölçeklenen eşikler

Açısal olguyu koruyanlar (derece/piksel ile ters orantılı):

| ayar | eski (0.01783) | yeni (0.021486) | açı |
|---|---|---|---|
| `FEEDFORWARD_ERROR_GATE_PIXELS` | (90, 360) | **(75, 299)** | 1.61° / 6.42° |
| `LOCK_CONFIRM_TOL_PX` | 120 | **100** | 2.15° |
| `MAX_REACQUISITION_DISTANCE_PIXELS` | 250 | **208** | 4.47° |

Tespit gürültüsüne bağlı olanlar (`PID_DEADBAND_PIXELS`, `MIN_OUTPUT_PIXELS`,
`AIM_TOLERANCE_MIN_PIXELS`) **değişmedi**: bunlar kaynak çözünürlüğe bağlı,
lense değil, ve 1280x720'de kaldık.

### Uyarılar

- **Global shutter bulanıklığı çözmez.** Yalnızca rolling shutter çarpılmasını
  kaldırır. Pozlama yine ~10 ms'ye elle sabitlenmeli.
- **Yeni lens eskisinden biraz geniş** (27.5° vs hesaplanan 22.8°): 15 m'de
  balon modele giren karede ~%17 daha küçük (25 px yerine 20.5 px). Tespit
  zayıflarsa çözüm 16 mm lens; yazılımda ayarlanacak bir şey yok.
- **`CAPTURE_LATENCY_OFFSET` hâlâ 0.08** — Logitech + MJPG için ölçülmüştü.
  USB3 global shutter büyük olasılıkla daha kısa. 0.04'ten başlayıp tara.
- `HUNTER_USE_MJPG = False` (YUY2) denemeye değer: USB3'te bant genişliği
  yeterli, JPEG çözme gecikmesi kalkar. Kare hızı düşerse geri al.
- **Kamera indeksleri kaydı.** `python kamera_tani.py` ile yeniden ayarla.

## 5. Test durumu

```bash
python tests_yeni_mimari.py     # 11 bölüm, tamamı geçiyor
```

9. bölüm doğrulama zaman aşımı + kara liste, 10. bölüm redüktör (adım/derece,
darbe tavanı, devir teslim bütçesi), 11. bölüm yeni kamera (optik tutarlılığı,
model girişi uyumu, küçültme çarpanı, model uzayında hedef boyutu) eklendi.

Ayrıca scratchpad'de `verify_arayuz.py`: gerçek `update_frame` döngüsünü
offscreen Qt + sahte kuyruklarla çalıştırıp yukarıdaki A/C/D/E maddelerini
davranış olarak doğruluyor (20 kontrol). Zinciri baştan sona sürüyor:
Aşama 3 → gözcü izine açı komutu → YÖNELME → DOĞRULAMA → KİLİT → ATEŞ →
`fire` → kara liste → TARAMA; dost reddi; Aşama 1'de kalibrasyonun ilk
tick'te gerçekten komut göndermesi.

## 6. SAHADA SIRADAKİ ADIMLAR (sıra zorunlu)

| # | iş | neden bu sırada |
|---|---|---|
| 1 | Pitch sürücüsü DIP = **3200** | kod buna göre |
| 2 | `motor_fire_module.py` + `rpi_motor_server.py` Pi'ye, sunucuyu yeniden başlat | Pi tarafı |
| 3 | **Pitch'e +30° ver, açıölçerle ölç** | açı defteri komut edilen adımlardan üretiliyor; yanlış oran KENDİ KENDİNİ tutarlı kılar, kalibrasyon aracı yakalayamaz |
| 4 | `kamera_tani.py` → yeni avcı indeksi | görüntü gelmezse hiçbir şey ölçülemez |
| 5 | 12 mm lensin odağını ~15 m'ye ayarla ve halkayı kilitle | sabit lens, bir kez |
| 6 | Manuel pozlama ~10 ms, oto beyaz dengesi kapalı | bulanıklık |
| 7 | 1280x720 KIRPIYOR mu ÖLÇEKLİYOR mu (30 sn'lik test) | `HUNTER_DPP` bunun üstüne kurulu |
| 8 | **Aşama 1 + Derece/Piksel Ölç** → gerçek `HUNTER_DPP` | 9 ve 10 buna bağlı |
| 9 | `CAPTURE_LATENCY_OFFSET` tara (0.04 → 0.06 → 0.08) | |
| 10 | **Gözcü ofset + DPP ölç** | Aşama 2/3 devir teslimi buna bağlı |
| 11 | Redüktörlü çınlama frekansını yeniden ölç | 2. bölümdeki iki kod maddesinin kaderi buna bağlı |
| 12 | `KP_PITCH` ince ayarı | en son |

## 7. İster uyumu denetimi ve üç düzeltme (2026-08-15)

Şartname maddeleri kodla tek tek eşleştirildi. Üç gerçek boşluk çıktı ve
düzeltildi; bir sapma bilinçli olarak korundu.

### Düzeltme 1 — Avcı hedefi zaten görüyorsa gözcüye gidilmiyor

İster: *"eğer baktığı yerde imha etmesi gereken balon-hedef ikilisi YOKSA
gözcüden gelen açıyla döner."* Kod ise TARAMA'da **yalnızca gözcü izlerine**
bakıyordu. İki yanlış davranış üretiyordu:

- avcı hedefi merkezde görürken taret gözcünün başka adayına savruluyordu
  (kayıtlı: kare 658'de düşman çifti 0.82/0.83 güvenle çerçevelendi, sistem
  yanından geçip boş duvara baktı),
- gözcü iz üretemediğinde (balon blobu çıkmadıysa) avcı hedefi tam merkezde
  tutsa bile sistem TARAMA'da bekliyor, hiç angaje olmuyordu.

`tarama_adimi(izler, ciftler, acilar)` artık önce avcıya bakıyor. Angaje
edilebilirlik şartları: maket var, güven >= `VERIFY_MIN_CONFIDENCE`, çiftin
dünya açısı biliniyor ve **kara listede değil**. Son şart kritik: onsuz, az
önce reddedilmiş bir dost her karede yeniden doğrulamaya alınır ve sonsuz
döngü oluşur. Açı `bukrek_main._cift_acilari` ile kare ÇEKİLME anındaki taret
açısı kullanılarak hesaplanıyor.

### Düzeltme 2 — Aşama 3'te gözcünün "dost" dediği aday elenmiyor, sona sıralanıyor

Eskiden `aday_sirala` bu izleri listeden **siliyordu**. Risk asimetrik: gözcü
düşmanı yanlışlıkla dost sayarsa hedef bir daha hiç denenmez (görev
başarısız); sona sıralamanın maliyeti ise yalnızca zamandır, çünkü dostun
vurulması zaten `ates_serbest_mi` tarafından imkânsız kılınmış durumda.
Sıra artık: `dusman -> kararsiz -> dost`. Bu, sınıfın kendi ilkesiyle de
tutarlı ("gözcünün kararı nihai değil, yalnızca sıralama").

### Düzeltme 3 — Dost kara liste ömrü aşamaya göre

`BLACKLIST_FRIEND_TTL_SEC = 600` aşamadan bağımsız uygulanıyordu. Aşama 2'de
ortamda dost **yok**, yani "dost" verdicti tanımı gereği bir YOLO hatası; ona
600 saniyelik ceza vermek gerçek bir düşmanı turdan siliyordu. Yeni
`_dost_ttl()`: Aşama 3'te 600 sn, Aşama 2'de `BLACKLIST_VERIFY_TTL_SEC` (5 sn).

### Korunan bilinçli sapma — "en büyük kırmızı = düşman"

Şartname bunu Aşama 3'ün temel mantığı olarak veriyor. FAZ 2'deki ölçüm
çuvalladığını gösteriyor (uzak düşman 3.600 kırmızı piksel, yakın dost
16.200 — 4.5 kat). Sebep şartnamenin kendi metninde: dostun altında da
kırmızı balon var ve alan mesafenin karesiyle düşüyor. Kod yerine geometrik
mavi/kırmızı ORAN testi kullanıyor; sıralama yine `kirmizi_alan`'a göre,
yani şartnamenin sıralama mantığı korunuyor, değişen yalnızca
sınıflandırma. **Sunumda açıklanmalı.**

### Denetimde çıkan, henüz kapatılmamış maddeler

| konu | durum |
|---|---|
| Gözcü izi yalnızca "balon benzeri" kırmızı bloblardan doğuyor (en-boy 0.5-2.0, alan >= 30 px). Balon görünmezse hedef gözcüde HİÇ oluşmaz | açık — 15 m'de balon 10 px / 78 px², eşiğe 2.6 kat pay |
| İmha doğrulaması yok: ateşten sonra hedef 12 sn kara listede, patlamadıysa geri kazanım yavaş | açık |
| `BALLISTIC_PITCH_OFFSET = 0.0` — 15 m'de mermi düşüşü telafi edilmiyor | ölçüm bekliyor |
| `AIM_HOLD_FRAMES = 3` (0.15 sn) yapısal çınlama periyodundan (0.37 sn) kısa | redüktör ölçümünden sonra |
| `is_aimed_at_target` bayat piksel hatasından hesaplanıyor | açık |
| Ateşleme Pi'nin soket döngüsünü 0.2 sn bloklıyor | açık |

Testlere 12. bölüm eklendi (avcı önceliği, kara liste etkileşimi, dost
sıralaması, aşamaya göre ceza); 4. bölüm yeni davranışa göre güncellendi.

## 8. Aşama 2 saha koşumu ve dört düzeltme (2026-08-15)

`Aşama2Hedef.mp4` kare kare çözümlendi; nişan hatası kırmızı balon blobu
izlenerek ölçüldü.

### Ölçüm

| faz | yaw RMS | pitch RMS | ort. hata |
|---|---|---|---|
| gözcü açısına yalpalama | 1.5 px | 33.6 px | 0.50° |
| kilit ilk 3 sn | 82.8 px | 39.7 px | 1.47° |
| kilit sonraki 3 sn | 45.4 px | 4.0 px | 0.67° |
| **ateş öncesi son 1.3 sn** | **10.7 px** | **0.9 px** | **0.22°** |

**Kilit fazının yalnızca %3.2'si nişan toleransının (14 px) içinde geçti.**
Devir teslim 1.8 sn, doğrulama 0.5 sn, ama kilitten ateşe **12.7 saniye**.

Kritik gözlem: çift sağlamken pitch RMS 0.9 piksele iniyor — yani PID sağlam,
sorun **hedef sürekliliğinde**. PID kazançlarına dokunulmadı.

### Kök neden

Durum satırlarında 19 örneğin 9'unda `0 çift` veya `Hedef kaybedildi` var.
Otonom modda maket olmadan çift kurulmuyor; YOLO maketi aralıklı kaçırıyor
(ve güven filtresi kalanı eliyordu). Çift kırılınca eski "takip" dalı
devralıp TAHMİN yürütüyor. Nişan noktası balonun merkezinden hayalete
atlıyor — ölçülen pitch sıçramaları ±80–124 piksel.

Yaw'ın temiz, pitch'in vahşi olmasının sebebi: nişan noktasının üç kaynağı
(balon merkezi / maketten türetilen yedek nokta / tahmin) **aynı x'te ama
farklı y'de**. Her kaynak değişimi saf bir pitch sıçraması üretiyor.

### Uygulanan düzeltmeler

| # | düzeltme |
|---|---|
| **R1** | `PAIR_MAX_HORIZONTAL_OFFSET` 1.0 → **0.4** ve **karşılıklı en yakınlık** kuralı. 1.0 iken düşmanın maketi DOSTUN balonuyla çift kurabiliyordu; çiftin sınıfı maketten geldiği için ateş kilidinin dokuz koşulu birden geçiyordu → dostun balonuna ateş. Ölçülen gerçek `dx/mw` 0.02–0.08 |
| **R2** | KİLİT'te "doğrulanan sınıfla eşleşen çift yoksa merkeze en yakınına düş" kaldırıldı. O çift dostun çifti olabiliyor, taret onu ortalamaya başlıyordu |
| **A** | **KİLİT köprüsü**: maket bir kare görünmezse doğrulanmış hedefin balonu tek başına takip edilir. Üç kapı: dünya açısında ≤ `LOCK_BRIDGE_MAX_DEG` (0.8°), en fazla `LOCK_BRIDGE_MAX_FRAMES` (5) kare, ve kilit açısında BAŞKA sınıftan maket belirirse kilit bırakılır |
| **B** | Göreli güven filtresi otonom yoldan kaldırıldı. Maket ve balon farklı sınıflar, farklı güven seviyeleri; sahada maket 0.56 / balon 0.81 ölçüldü, eşik 0.66 oldu ve maket elendi. Ayrıca yakın bir DOST uzak bir DÜŞMANI silebiliyordu |
| **C** | `PREDICTION_MAX_RATE_DEG_S` 8.0 → **2.5**. 8.0, FAZ 1'de sabit hedefte ölçülen sahte hız (8.1 °/s) ile aynıydı — hiçbir koruma sağlamıyordu |
| — | `ates_serbest_mi` artık `cift.balon is None` kontrolünü de kendisi yapıyor; "balon görüldü" bilgisini yalnızca çağıranın bayrağına bırakmıyor |

### Yeni mod: HEDEF TAKİP (ateşsiz)

Arayüze **"Hedef Takip (ateşsiz)"** butonu eklendi (`active_task = 'takip'`).

- Angajman makinesi **hiç başlatılmaz** → gözcü devir teslimi yok,
  dost/düşman doğrulaması yok, **otonom ateş yolu tamamen kapalı**
- `SERVO_MODLAR = OTONOM_MODLAR + ('takip',)` → PID çalışır, taret hedefi
  nişangahta tutar
- Hedef seçimi çift üzerinden (`tek_balon=True`): maket+balon varsa balona,
  yalnız maket varsa yedek noktaya, yalnız balon varsa balona
- Kayıpta **tahmin yürütmez** — kilidi bırakıp son açıyı tutar; mod bir
  ölçüm aracı olduğu için tespit sürekliliğini olduğu gibi göstermeli
- Durum çubuğuna canlı nişan hatası **piksel ve derece** cinsinden,
  tolerans içinde olup olmadığıyla birlikte yazılır

### Kalan ve ölçülmesi gereken

Ateş öncesi en iyi pencerede **pitch RMS 0.9 px, yaw RMS 10.7 px** — yaw
pitch'ten 12 kat kötü. Pitch'te 1:5 planet redüktör (boşluk 1–2 açı dakikası),
yaw'da 10:30 düz dişli çifti var. Kalibrasyondaki saçılma da aynı yönde
(yaw %16, pitch %2). **Kalan yaw kalıntısı büyük olasılıkla dişli boşluğu ve
yazılımla çözülmez.** 0.145° = 15 metrede 3.8 cm; balon yarıçapı 7 cm, yani
vuruş olur ama tolerans sınırında gidip gelir.

Yukarıdaki düzeltmelerden sonra yeniden ölçülmeli; yaw hâlâ pitch'in 10 katıysa
yaw dişli boşluğu ayrıca ölçülüp ya redüktöre geçilmeli ya da tolerans gerçeğe
göre ayarlanmalı. Şimdi toleransı gevşetmek sorunu ölçülemez hale getirir.

## 9. Gozcu mavi esigi, boyut kapisi ve nisan noktasi karari (2026-08-16)

Bu bolum `a39a281`, `e1aa1e5`, `9db6af7`, `115e450` ve `1909891` commit'lerini
kapsar.

### Saha ayarlari (`a39a281`)

Kamera indeksleri sahada yeniden atandi (`HUNTER_CAMERA_INDICES = [1, 3, 4]`,
`SPOTTER_CAMERA_INDICES = [2, 3, 4]`) ve yaw eksenine olculmus bir olcek trimi
girildi: `HUNTER_DPP_YAW = 0.01430`. Bu trim yaw'daki **mekanik disli
boslugunu** telafi ediyor; pitch'te 1:5 planet redukto oldugu icin oradaki
olcek dokunulmadan birakildi. Testlerdeki "yaw ve pitch olcegi ayni
buyuklukte" kontrolu bu yuzden tam esitlik yerine **%10 tolerans** ile
calisiyor -- kasitli trimi yanlis pozitif olarak isaretlemesin diye.

### Gozcude mavi neden hic taninmiyordu (`e1aa1e5`)

Saha gozlemi: gozcu kirmizilari cok iyi buluyor, mavileri hic bulmuyordu.
`gozcu_tani.py` yazilip gercek kare uzerinde HSV taramasi yapildi.

Olculen: mavi maketin **doygunlugu S medyan 32**, %90'lik dilim 60. Eski esik
`S >= 140` bunun **2-4 kati**. Sonuc: maket penceresinde 0 mavi piksel,
`mavi_oran = 0.00`, ve DOST maket `dusman` isaretleniyordu.

24 esik kombinasyonu karsilastirildi (dost penceresi 125 kirmizi, dusman
penceresi 64 kirmizi iceriyordu):

| esik | dost mavi_oran | dusman mavi_oran | karar |
|---|---|---|---|
| S>=40 | yuksek | **yuksek** | siyah perde de mavi okunuyor -> DUSMAN DOST SANILIR, tehlikeli yon |
| **S>=80, V>=45** | **0.79** | **0.00** | **en genis marj -- secildi** |
| S>=140 (eski) | 0.37 kararsiz, temizlikten sonra 0 | 0.00 | dost hic taninmiyor |

`SPOTTER_BLUE_RANGES = [((90, 80, 45), (135, 255, 255))]` yapildi.
`inference_module._MAVI` de **ayni degere** cekildi: orada kati kalirsa
YOLO'nun `dost-*` tespitleri renk tutarlilik kontrolunden elenir ve dost
avcida da hic taninmaz.

### Sinif bazli acisal boyut kapisi (`9db6af7`)

Sahada 0.1-0.2 saniye suren, guveni 0.6'ya cikan, karenin buyuk bir kismini
kaplayan sahte etiketler goruldu. Mevcut alan orani kapisi cok gevsekti:
1920x1105'te 728x728'e kadar her kutu geciyordu ve 50 cm'lik bir maket bu
boyuta ancak **2.7 metrede** ulasir -- yani pratikte hicbir hayaleti kesmiyordu.

Hedeflerin gercek boyutu ve mesafe araligi belli oldugu icin bir tespitin
piksel boyutu keyfi olamaz:

    GERCEK_BOYUTLAR_M = {'balon': 0.14, 'maket': 0.50}
    TARGET_MIN_RANGE_M = 4.0 ... TARGET_MAX_RANGE_M = 20.0
    DETECTION_SIZE_MIN_MARGIN = 0.40 ... DETECTION_SIZE_MAX_MARGIN = 1.40

Kapi `DEGREES_PER_PIXEL` uzerinden tanimli, yani cozunurluk veya lens
degisince **kendiliginden olcekleniyor**. Alt sinir kasitli olarak gevsek
birakildi (uzak/kismen ortulu hedefi elememek icin).

### Gozcu balon suzgecine dolgunluk sarti

En-boy orani tek basina yetmiyordu: kirmizi F16 maketinin kutusu da kabaca
kare cikabildigi icin "balon" sayilip iz aciliyordu (`gozcu_tani.py` aday #0).
Olculen dolgunluk (blob / kendi kutusu): **gercek balon 0.70, kirmizi maket
0.37**. Daire icin teorik deger pi/4 = 0.785.
`SPOTTER_BALLOON_MIN_FILL = 0.50` ikisini ayirir, kismen ortulen balona da pay
birakir.

### Kilit iptaline zamansal onay

"Kilit acisinda baska siniftan maket belirirse kilidi birak" korumasinin onayi
yoktu; tek karelik bir hayalet iyi bir kilidi dusurup TARAMA'ya
gonderebiliyordu. `LOCK_ABORT_CONFIRM_FRAMES = 3` eklendi; arada dogru sinif
gorulurse sayac sifirlaniyor.

### Tanilama araclarinda PNG yazimi

`cv2.imwrite` Windows'ta **ASCII olmayan yollarda sessizce basarisiz oluyor**:
istisna atmiyor, sadece `False` donuyor. Proje yolunda `barış` oldugu icin
`gozcu_tani.py` ve `kamera_kalite.py` hicbir goruntu yazamiyor ama arac
"calisiyor" gorunuyordu. `cv2.imencode` + normal dosya yazimi ile duzeltildi.

### Nisan noktasi: analiz yapildi, sonra MERKEZE geri alindi (`115e450`)

Avci kamera namlunun **5.5 cm ustunde** ve eksenler **paralel**. Paralel
olduklari icin mermi her mesafede kamera ekseninin 5.5 cm altindan gecer.
Duzeltme **mesafeden bagimsiz** olurdu, cunku gereken ofset ile balonun
yaricapi ayni mesafedeki iki fiziksel uzunluk ve oranlari sabit:

    5.5 / 7.0 = 0.786 yaricap = kutu yuksekliginin 0.393'u  ->  oran 0.893

Mekanizma `engagement._nisan_yuksekligi()` olarak yazildi ve once 0.75
denendi. **Saha karari bunu geri cevirdi:** `AIM_POINT_HEIGHT_RATIO = 0.5`,
yani nisan noktasi tespitin **tam ortasi**. 0.5'te fonksiyon matematiksel
olarak ozdeslik donuyor -- kod yolu eskisiyle birebir ayni.

Mekanizma yerinde birakildi. Telafi istenirse tek yapilacak sey sayiyi
buyutmek; testler orana bagli yazildigi icin (`oran == 0.5` -> "TAM MERKEZ",
`> 0.5` -> "merkezin USTUNDE") elle guncelleme gerekmez.

**Balistik dusus bilerek eklenmedi**: 15 metrede sapma ihmal ediliyor.

### Depo hijyeni (`1909891`)

GitHub'da en son `463a109` gorunuyordu cunku **13 commit hic push
edilmemisti** (commit != push; `git status -sb` "ahead 13" diyordu). Push
edildi. Ayrica:

- `convert_to_onnx.py` / `convert_to_engine.py` takip disindaydi -> repoya
  alindi. Modelin giris boyutunun (**1056x608**) tek kaynagi
  `convert_to_engine.py` ve `config.py`'deki kirpma/olcekleme kararlari buna
  dayaniyor.
- `gozcu_tani/`, `kamera_kalite/`, `yolo_kalite/` `.gitignore`'a eklendi
  (tanilama ciktisi PNG'leri, saha kosumuna ozel).

## 10. Davranis referansi: Asama 2 / Asama 3 / Hedef Takip

Bu bolum "butona bastiktan sonra ne olur" sorusunun tek referansi. Kod
degistiginde burasi da guncellenmeli.

### Gozcu ekraninda ne cizilir (sik sorulan)

`spotter_module.balon_adaylari()` adaylari **YALNIZCA KIRMIZI MASKEDEN**
cikarir. Mavi maske hicbir zaman aday uretmez; yalnizca balonun ustundeki
pencerede **siniflandirmada** kullanilir.

Sonuc:

- Tek basina duran mavi bir cisim (dost maket dahil) **hic cizilmez**.
- Mavi maketin **altinda kirmizi balon varsa**, o balon aday olur ve daire
  cizilir; dairenin **rengi** `dost` sinifi icin mavi/turkuazdir. Yani
  ekranda gordugun mavi daire "mavi tespit edildi" degil, "kirmizi balon
  bulundu, ustu mavi cikti -> DOST" demektir.
- Kirmizi bir cismin aday olabilmesi icin uc kapiyi gecmesi gerekir:
  alan >= 30 px, en-boy orani 0.5-2.0, **dolgunluk >= 0.50**.

Daire renkleri: dusman kirmizi, dost mavi/turkuaz, kararsiz sari.
Cizim `iz['yaw']/['pitch']` acilarindan piksele geri donusturulur, yani
gordugun daire izin **filtrelenmis** konumudur, ham blob degil.

### Ortak akis (Asama 2 ve 3 ayni durum makinesini kullanir)

    BOSTA -> TARAMA -> YONELME -> DOGRULAMA -> KILIT -> ATES -> (imha) -> TARAMA

Durum makinesi **her karede bir adim** ilerler. Butonlarin fark yarattigi yer
yalnizca uc noktadir: aday siralamasi, dost cezasinin omru, ve gorev metni.

**TARAMA -- once avci, sonra gozcu.** Ister acikca soyle: "baktigi yerde imha
etmesi gereken balon-hedef ikilisi YOKSA gozcuden gelen aciyla doner."
`avcida_hazir_hedef_var()` su uc sarti arar: `ciftler[0]` maketli, guven
>= 0.55, ve acisi kara listede degil. Saglaniyorsa **aci komutu hic
gonderilmez**, dogrudan DOGRULAMA'ya gecilir. Saglanmiyorsa gozcu adaylari
siralanir (gorulme >= 2 ve kara liste disi olanlar), ilk aday secilir ve
taret onun **tahmin edilen** acisina gider (`SPOTTER_LATENCY` 0.05 sn +
yalpalama suresi; hedef bu surede yol alir ve avcinin yari gorus acisi yaw'da
+-13.75, pitch'te yalnizca +-7.7 derece).

**YONELME.** Hata <= 1.0 derece olunca DOGRULAMA. 2.5 saniyede oturmazsa
TARAMA'ya doner.

**DOGRULAMA -- kimlik burada belirlenir.** Merkeze en yakin **maketli** cift
alinir; maketsiz kayit dogrulanamaz cunku kimlik bilgisini yalnizca maket
tasir. Guven >= 0.55 ve **4 ardisik karede ayni sinif** sarti aranir.
`dost-*` cikarsa hedef kara listeye girer ve TARAMA'ya donulur -- gozcu
yanilsa bile dostun vurulmasini imkansiz kilan katman budur. `dusman-*`
cikarsa KILIT. 1.5 saniyede karar cikmazsa 5 saniyelik kisa ceza ile TARAMA
(ceza olmadan ayni aday sonsuz donguye giriyordu; sahada taret 4 saniye bos
duvara bakip kalmisti).

**KILIT -- hedef secimi uc kademeli** (`kilit_hedefi_sec`):

1. Dogrulanan sinifla **eslesen** maketli cift -> normal takip.
2. Maketsiz ama son kilit acisina <= 0.8 derece yakin balon -> **KOPRU**
   (en fazla 5 kare). YOLO maketi bir kare kacirdiginda kilit dusmesin diye.
3. Kilit acisinda **baska siniftan** maket 3 ardisik kare gorulurse kilit
   birakilir.

Hicbiri tutmuyorsa **hedef yoktur** -- eskiden burada "merkeze en yakin cifte
dus" vardi ve o cift dostun cifti olabiliyordu.

Nisan hatasi `max(9 px, 0.35 x yaricap)` toleransinin icinde **3 ardisik kare**
kalirsa ATES. 8 saniyede olmazsa TARAMA.

**ATES -- dokuz kosul birden** (`ates_serbest_mi`): durum ATES, cift var,
maket bu karede tespit edildi, sinif `dusman-`, guven >= 0.55, sinif
dogrulananla ayni, **cifte balon eslesmis**, balon bu karede gercekten
gorundu, nisan tolerans icinde, ve yaw atessiz bolgede degil. Biri bile
tutmazsa durum cubuguna gerekce yazilir ve 1.5 saniye sonra KILIT'e donulur.
Ates sonrasi hedef 12 saniye kara listeye girer.

### Asama 2 -- "Hizli Imha"

Ortamda **yalnizca dusman** var. Iki fark:

- **Aday siralamasi:** gozcunun dost/dusman karari **yok sayilir**, sadece
  `-kirmizi_alan` ile siralanir -> **en buyuk (= en yakin) hedef once**.
- **Dost cezasi kisa (5 sn).** Ortamda dost olmadigi icin "dost" verdicti
  tanimi geregi bir YOLO hatasidir; 600 saniyelik ceza gercek bir dusmani
  turdan tamamen silerdi.

**Sik sorulan: dogrudan balona mi kilitleniyor? HAYIR.** Asama 2'de de maket
zorunludur. Kimlik maketten, nisan noktasi balondan gelir. Tek basina duran
bir kirmizi leke listeye girer (kopru kullanabilsin diye) ama dogrulanamaz ve
ates kilidi ona **asla** izin vermez.

Senaryolar:

| durum | beklenen davranis |
|---|---|
| Avci hedefi zaten goruyor | Gozcuye **hic gidilmez**, taret donmez, dogrudan DOGRULAMA |
| Avci bos, gozcude 2 iz | Buyuk (yakin) olan once; tahmin edilen aciya yalpala |
| Gozcu hic iz uretmiyor, avci goruyor | Yine angaje olur (avci onceligi) |
| Ikisi de bos | TARAMA'da bekler, durum cubugu "gozcude uygun aday yok (N iz)" |
| Maket var, balon yok | Cift kurulur, yedek nisan noktasi ile takip edilir; **ates edilmez** ("cifte balon eslesmemis") |
| Balon var, maket yok | Listeye girer, PID takip edebilir; dogrulanamaz, **ates edilmez** |
| YOLO maketi 1-4 kare kacirdi | **Kopru**: balon tek basina takip edilir, kilit dusmez |
| YOLO maketi 6+ kare kacirdi | Kopru butcesi doldu -> TARAMA |
| YOLO yanlislikla "dost" dedi | 4 ardisik kare tutarsa 5 sn ceza, sonra tekrar denenir |
| Ates edildi | 12 sn kara liste, TARAMA, sonraki hedefe |

### Asama 3 -- "Dost/Dusman"

Ortamda **iki dost bir dusman** var. Iki fark:

- **Aday siralamasi:** gozcunun `dusman` dedigi izler once, `kararsiz`
  ikinci, `dost` dedigi **en sona**. Dostlar listeden **silinmez** -- risk
  asimetrik: gozcu bir dusmani yanlislikla dost sayarsa o hedef bir daha hic
  denenmez ve gorev basarisiz olur. Sona siralamanin maliyeti yalnizca
  zamandir, cunku dostun vurulmasi `ates_serbest_mi` tarafindan zaten
  imkansiz kilinmis durumda.
- **Dost cezasi 600 sn** -- ortamda gercekten iki dost var, onlari pratikte
  kalici elemek dogru.

Senaryolar (yukaridaki ortak tablonun **uzerine**):

| durum | beklenen davranis |
|---|---|
| Gozcu dusmani dogru siraladi | En hizli yol: dusman once denenir |
| Gozcu dusmani "dost" sandi | Once iki gercek dost denenir, ikisi de DOGRULAMA'da elenir ve 600 sn ceza alir, sonra sira dusmana gelir -- **gorev yine tamamlanir**, sadece gec |
| Gozcu dostu "dusman" sandi | Taret ona doner, avci YOLO'su `dost-*` okur, 600 sn ceza, sirakine gecer |
| Dost ve dusman yan yana (1 m) | `PAIR_MAX_HORIZONTAL_OFFSET = 0.4` + **karsilikli en yakinlik** kurali capraz eslesmeyi keser; dusmanin maketi dostun balonuyla cift kuramaz |
| Kilitliyken dusman balonu patladi | Kilit acisinda dostun maketi belirirse 3 ardisik kare sonra kilit birakilir; ates zaten sinif esitligi sartinda takilir |
| 4 turluk akista dusman gorunmedi | Sistem TARAMA'da kalir, **sikmaz** -- bilincli davranis, degistirilmedi |

**Asama 3'un gorev mantigi (butce / erken durma) bilerek degistirilmedi.**
Yarismada 3 yoldan iki dost bir dusman geliyor ve 4 turluk akista "kontrol
eder, sikmaz" davranisi dogru olan.

### Hedef Takip (atessiz)

Bir **olcum araci**, gorev modu degil. `active_task = 'takip'`.

- Angajman makinesi **hic baslatilmaz** -> gozcu devir teslimi yok,
  dost/dusman dogrulamasi yok, otonom ates yolu **tamamen kapali**.
- `SERVO_MODLAR = OTONOM_MODLAR + ('takip',)` -> PID calisir.
- Hedef secimi cift uzerinden, `tek_balon=True`: maket+balon varsa balona,
  yalniz maket varsa yedek noktaya, yalniz balon varsa balona.
- Kayipta **tahmin yurutmez** -- kilidi birakip son aciyi tutar. Mod tespit
  surekliligini oldugu gibi gostermeli.
- Durum cubuguna canli nisan hatasi **piksel ve derece** cinsinden yazilir.

## 11. Guncel test durumu

| paket | kapsam | durum |
|---|---|---|
| `tests_yeni_mimari.py` | 13 bolum: config tutarliligi, nisan noktasi, cift eslestirme, durum makinesi, ates kilidi, gozcu, kara liste, avci onceligi, capraz eslesme + kilit koprusu | **hepsi geciyor** |
| `verify_arayuz.py` (scratchpad) | A-F: Asama 3 kapisi, durum zinciri, dost reddi, kalibrasyon, fare tiklamasi, Hedef Takip | **hepsi geciyor** |

Nisan noktasi testleri `AIM_POINT_HEIGHT_RATIO`'ya **bagli** yazildi; oran
degisirse testler kendiliginden dogru dali dogrular.

## 12. Saha kaydi cozumlemesi: asama2-3-hedefTakip.mp4 (2026-08-16)

51.3 saniye, 1539 kare, guncel kodla cekildi (video 06:43, son commit 04:25).
Durum satirlari kare kare cikarildi (398 metin degisimi), nisan hatasi
kirmizi balon blobu izlenerek olculdu, cizilen kutular kenar bazinda
olculdu. Ekran -> kare piksel olcegi nisangahin bilinen boyutundan
(`crosshair_size = 10`) kalibre edildi: **1 ekran px = 1.05 kare px**.

### Olculen nisan hatasi

| faz | zaman | ort. hata | std |
|---|---|---|---|
| Asama 3 yalpalama | 1.1-2.5 sn | 370 px | 85 |
| Asama 3 oturma | 2.5-5.0 sn | 21-26 px | **12-14** |
| **Asama 3 oturmus** | **5-13 sn** | **2.1 px** | **0.2** |
| Hedef Takip | 26-29 sn | 15-36 px | 1.6-8.7 |
| Asama 2 oturma | 45-47 sn | 19-25 px | **11-15** |
| **Asama 2 oturmus** | **48-51 sn** | **5.7 px** | **0.1** |

Yani PID nihai olarak **cok kararli** (std 0.1-0.2 px). Sorun oturma
fazindaki 2-3 saniyelik salinim.

### Salinimin kok nedeni: nisan noktasi KAYNAK DEGISIMI

Durum satirlarindan alinan ardisik hata degerleri (Asama 2, 45.9-46.8 sn):

    yaw:   +26, +7, -18, -11, -10, -5, -5, -5, -5, -5, -5, -6, -5
    pitch: +12, -6, -15, +22, +17, -49, -52, -4, +8, -18, -50, +5, +17

**Yaw oturuyor (-5 px sabit), pitch -52 ile +22 arasinda ziplyor.** Bu
asimetri tesadufi degil: nisan noktasinin iki kaynagi **ayni x'te ama farkli
y'de**.

Olculdu (uc ayri kareden):

| kare | maket kutusu | balon merkezi y | yedek nisan y | **fark** |
|---|---|---|---|---|
| 150 | 172x208 | 561 | 536 | **-25 px** |
| 300 | 167x202 | 569 | 540 | **-29 px** |
| 1445 | 162x208 | 570 | 536 | **-34 px** |

Balon goruldugunde nisan = balon merkezi. Balon kacirildiginda nisan =
`maket_merkez_y + PAIR_FALLBACK_AIM_OFFSET (0.75) x maket_genisligi`, yani
**25-34 piksel YUKARIDA**. Taret bir noktaya oturur, kaynak degisir, hata
bir anda ~30 px olur, taret geri doner. Salinim budur.

`_ciftleri_sirala` her karede bagimsiz calisiyor -- hicbir sureklilik yok.
KILIT koprusu yalnizca "maket yok, balon var" durumunu kapatiyor; TERSI
("maket var, balon yok") hala yedek formule dusuyor.

### Hedef Takip'te hedefin ortalanamamasi

26-29 saniye arasi olculen hata 15-36 px ve dusmuyor. Uc ayri sebep:

1. **O sahnede balon YOK** (k872 goruntusu). Nisan noktasi maketten
   turetiliyor ve kutunun **altina** dusuyor -- kasitli davranis (balonun
   olmasi gereken yer), ama kullanicinin bekledigi "kutunun tam ortasi"
   degil. Hedef Takip bir olcum araci oldugu icin burada tahmin yurutmek
   yanlis.
2. **Rakip tespit hedefi calyor**: k825'te tek karede **yaw hatasi +400 px**
   olcusuldu, sonraki karede 0'a dondu. `ciftler[0]` (merkeze en yakin cift)
   kare kare degisiyor.
3. Kaynak degisimi (yukaridaki madde) burada da calisiyor.

### Ates neden yalnizca BIR kez geliyor

Asama 3'te ates **4.07 saniyede** verildi (`ATES - dusman-F16 (1. hedef)`).
Hemen ardindan k123'ten itibaren, 10.5 saniyeye kadar kesintisiz:

    Durum: TARAMA - gozcude uygun aday yok (1-3 iz).
    Hedef: TARAMA | 1-2 cift | imha 1

Gozcu izi goruyor, avci cifti goruyor, ama sistem angaje **olmuyor**.
Sebep: `_otonom_ates_denemesi` ates komutunu gonderir gondermez
`imha_edildi()` cagiriyor; o da hedefi `BLACKLIST_TTL_SEC = 12` saniye kara
listeye aliyor. `avcida_hazir_hedef_var` da kara liste kontrolu yaptigi icin
avci hedefi merkezde gorse bile 12 saniye boyunca dokunmuyor.

**Sistemde imha DOGRULAMASI yok: "ates ettim" = "imha ettim" varsayiliyor.**
Sarjor takili degilken (veya iska gectiginde) sistem bunu asla ogrenmiyor.
Ayni desen Asama 2'de de goruldu (48 sn ates, sonrasi ayni).

### Kilitli hedefin kutusu neden kirmizi olmuyor

Cizim kurali (`bukrek_main.py` ~2283):

    if current_tracked_target_class and det['class_name'] == current_tracked_target_class:
        if current_target_bbox_for_pid and det['bbox'] == current_target_bbox_for_pid:
            renk = KIRMIZI
        else:
            renk = SARI
    else:
        renk = YESIL

Otonom yolda `current_target_bbox_for_pid`, `_nisan_tespiti`'nin urettigi
**SANAL** kutudur: `(cx-r, cy-r, 2r, 2r)`, sinif adi **maketin** adi. Bu kutu
hicbir gercek tespitin bbox'i degil, dolayisiyla esitlik **asla** tutmuyor:

- maket tespiti  -> sinif tutuyor, bbox tutmuyor -> **SARI**
- balon tespiti  -> sinif tutmuyor ('balon' vs 'dusman-f16') -> **YESIL**

Yani otonom modda **hicbir kutu kirmizi olamaz**. Islevsel bir hata degil,
ama operator kilidi goremiyor. Videoda gozlenen tam olarak budur.

### False positive durumu

Cizilen kutular kare kare sayildi:

| kutu/kare | kare | oran |
|---|---|---|
| 0 | 589 | %38.3 |
| 1 | 212 | %13.8 |
| 2 | 678 | %44.1 |
| 3+ | 60 | %3.9 |

Sahnede gercek hedef 2 kutu (maket + balon). %3.9 fazladan kutu = false
positive. **%38.3'te hic kutu yok** -- bunun bir kismi kameranin hedefe
bakmadigi geciler, ama tespit sureksizligi de burada.

Boyut kapisi **calisiyor ama sinirda**: k872'deki devasa sahte
`dusman-fuze (0.74)` kutusu olculdu -> **693x592 kare px**. Kapi maket icin
40..700 px. 693 < 700, yani **7 piksel farkla geciyor**. Tum videoda kapiyi
asan kutu yalnizca 17 karede goruldu (en buyuk 720 px).

Kapinin ust siniri `TARGET_MIN_RANGE_M = 4.0` metreden geliyor:

    50 cm @ 4 m  -> 500 px, x1.40 marj = 700 px

Sahada en yakin hedef 7.5 metre. `TARGET_MIN_RANGE_M = 7.5` yapilirsa:

    50 cm @ 7.5 m -> 267 px, x1.40 marj = 373 px

693, 487, 464, 445 px'lik sahte kutularin **hepsi** elenirdi. Olculen gercek
maket kutusu 162-172 px, yani 373 sinirinin cok altinda -- kayip yok.

### Balonun gercek boyutu 14 cm degil

Olculen balon kutusu 78x74 kare px, maket kutusu 162x208 px. Maket 50 cm
kabul edilirse mesafe 9.6 m cikiyor; ayni mesafede 78 px'lik balonun gercek
capi **18.7 cm**. `GERCEK_BOYUTLAR_M['balon'] = 0.14` bu yuzden olcumle
uyusmuyor. Su anda zarari yok (balon kapisi 11..196 px, 78 px rahat geciyor)
ama yakin mesafede balonu elemeye baslayabilir.

## 13. Gozcu renk ayarlari: "maket taninmayan, balon taninan" set (2026-08-16)

Kullanicinin saha gozlemi: gozcude balon surekli tespit ediliyor, F16 maketi
cok az, fuze neredeyse hic. **Bu bilincli bir tasarim sonucudur, hata
degildir** -- ve istenirse geri donulebilsin diye mevcut set burada
arsivleniyor.

### Neden maketler taninmiyor

`spotter_module.balon_adaylari()` adaylari **yalnizca kirmizi maskeden**
cikarir ve uc kapi uygular:

    SPOTTER_MIN_BLOB_AREA    = 30      # alan
    SPOTTER_BALLOON_ASPECT   = (0.5, 2.0)   # en/boy
    SPOTTER_BALLOON_MIN_FILL = 0.50    # dolgunluk (blob / kendi kutusu)

- **F16 maketi**: olculen dolgunluk **0.37** -> dolgunluk kapisinda elenir.
- **Fuze**: ince uzun, en/boy orani 0.5-2.0 araliginin disinda -> elenir.
- **Balon**: dolgunluk 0.70 (daire icin teorik 0.785) -> gecer.

Yani gozcu **kasten yalnizca balon ariyor**. Mavi maske hicbir zaman aday
uretmez; sadece balonun ustundeki pencerede siniflandirmada kullanilir.

### Arsivlenen ayar seti (su an yururlukte)

```python
SPOTTER_RED_RANGES  = [((0, 120, 70), (10, 255, 255)),
                       ((170, 120, 70), (179, 255, 255))]
SPOTTER_BLUE_RANGES = [((90, 80, 45), (135, 255, 255))]
SPOTTER_MIN_BLOB_AREA    = 30
SPOTTER_BALLOON_ASPECT   = (0.5, 2.0)
SPOTTER_BALLOON_MIN_FILL = 0.50
SPOTTER_MODEL_WINDOW_ABOVE = (0.2, 3.5)
SPOTTER_MODEL_WINDOW_WIDTH = 2.5
SPOTTER_FRIEND_BLUE_RATIO  = 0.60
SPOTTER_ENEMY_BLUE_RATIO   = 0.25
```

**Bu set ile olculen davranis** (uc hedef gozcu acisindayken, `gozcu_tani.py`):

    kirmizi piksel : 1537 (%0.167)   mavi piksel : 504 (%0.055)
    BALON ADAYI    : 1 tane -> yaw +5.8, pitch +1.5, cap 22 px, alan 343 px2
      maket penceresi: kirmizi 929 | mavi 0 -> mavi_oran 0.000 -> DUSMAN (dogru)
    Solda kirmizi F16 (265 px kirmizi) : ADAY DEGIL (balonu yok)
    Ortada mavi F16                    : ADAY DEGIL (balonu yok, mavi aday uretmez)

### Alternatif: "maketlere de git, balonu yoksa gec"

Kullanicinin onerisi. Su anki davranista balonu gozcude blob vermeyen bir
hedef **hic denenmiyor** -- taret oraya gitmiyor. Alternatifte maket de aday
olur, taret doner, avci bakar, balon yoksa kara listeye alinip gecilir.

| | su anki (balon-merkezli) | onerilen (makete de git) |
|---|---|---|
| bos yere donme | yok | olur (her balonsuz maket icin ~2 sn) |
| balonu gozcude gorunmeyen hedef | **kacirilir** | bulunur |
| Asama 3'te dost maketler | hic ziyaret edilmez | ziyaret edilir, elenir |

Uygulanacaksa dolgunluk/en-boy kapilari **aday uretiminde** gevsetilip
`sinif` alanina "balonsuz" isareti eklenmesi ve `aday_sirala`'da bunlarin
**sona** konmasi yeterli; balon adaylari onceligini korur.

**Karar: su an degistirilmiyor.** Bu bolum ayarlara geri donulebilsin diye
kayit altina alinmistir.

### `gozcu_tani.py` ciktisindaki yaniltici satir

Arac su satiri **sabit metin** olarak yazdiriyor (`gozcu_tani.py:198`):

    (mevcut ayar: S>=140, V>=60 -> yukaridaki tabloda son satir)

Gercek ayar `S>=80, V>=45`. Metin 9. bolumdeki esik degisikliginde
guncellenmemis; ciktinin ust kismindaki `SPOTTER_BLUE_RANGES` dogru
basiliyor. Duzeltilmeli, yoksa esik taramasi yanlis satirdan okunur.

## 14. 12. bolumdeki bes bulgunun uygulanmasi (2026-08-16)

Her madde icin: NE degisti, NEDEN, ve sahada NE BEKLENMELI.

### D1 -- Boyut kapisi daraltildi

`TARGET_MIN_RANGE_M` 4.0 -> **7.5**, `GERCEK_BOYUTLAR_M['balon']` 0.14 -> **0.19**.

Ikisi BIRLIKTE zorunlu. Yalnizca mesafe degistirilseydi balon ust siniri
105 px'e inerdi; balon 7.5 metrede 100 px olarak gorunuyor, yani %5 pay
kalir ve gercek balonlar elenmeye baslardi. Olculen gercek cap 18.7 cm.

| sinif | eski kapi | yeni kapi |
|---|---|---|
| maket | 40 .. 700 px | 40 .. **374** px |
| balon | 11 .. 196 px | 15 .. **142** px |

**Beklenen davranis:** kayitta olculen sahte kutularin (693 / 487 / 464 /
445 px) hicbiri artik cizilmez. Gercek maket 162-172 px, gercek balon
78-100 px -- ikisi de rahat gecer. Ekranda arka planda beliren dev
`dusman-fuze` kutulari **kaybolmali**. Kutu sayisi 3+ olan kare orani
(olculen %3.9) belirgin dusmeli.

**Dikkat:** 7.5 metreden yakin atis yapilacaksa bu deger geri buyutulmeli,
yoksa yakin hedefler elenir. Balonu cetvelle olcmek de iyi olur: 0.19
degeri maketin 50 cm oldugu varsayimindan turetildi.

### D2 -- Imha dogrulamasi

`_otonom_ates_denemesi` artik ates komutundan sonra `imha_edildi()`
cagirmiyor. Yerine bir **dogrulama penceresi** aciliyor
(`AngajmanMakinesi.ates_kaydet` / `ates_dogrulama_adimi`).

Yeni sabitler: `FIRE_CONFIRM_SEC = 0.7`, `FIRE_CONFIRM_MAX_SEEN = 1`,
`FIRE_MAX_ATTEMPTS = 3`.

Pencere boyunca balonun kac karede goruldugu sayiliyor; karar pencerenin
SONUNDA veriliyor, boylece tek karelik bir kacirma "imha" sanilmiyor.

    balon kayboldu        -> 'onaylandi' -> imha_edildi()  (12 sn kara liste)
    balon hala duruyor    -> 'tekrar'    -> ayni hedefe yeniden ates
    butce doldu (3 atis)  -> 'pes'       -> imha_edilemedi() (5 sn kara liste)

Ayrica `_process_rpi_response` artik OTONOM modlarda `target_destroyed`
bayragini KALDIRMIYOR. Pi'nin "ates komutu calisti" yaniti balonun
patladigi anlamina gelmiyor; ustelik o bayrak servolama kosulunda
(`not self.target_destroyed`) yer aldigi icin taret dogrulama penceresi
boyunca hedefi birakiyordu ve `reset_pid_state()` tam da ikinci atis
gerekebilecek anda kilidi sifirliyordu.

**Beklenen davranis:** balon patlamazsa ~0.7 saniye sonra **ikinci atis**
gelir, gerekirse ucuncu. Sarjor takili degilken durum cubugunda
"ATES - imha dogrulaniyor (1. atis)" -> "(2. atis)" -> "(3. atis)" ->
"Balon duruyor ama atis butcesi doldu" gorulmeli. Balon patlarsa
"IMHA DOGRULANDI - balon kayboldu" yazip sonraki hedefe gecmeli.
Kayittaki "bir ates, sonra 12 saniye hicbir sey" davranisi bitmeli.

### D3 -- Nisan noktasi surekliligi (salinimin kok nedeni)

`HedefCifti.olculen_ofset()` eklendi: balon goruldugunde maket kutusuna
gore bagil konumu (maket genisligine normalize) olculuyor.
`nisan_noktasi(ogrenilen_ofset=...)` balon kayboldugunda sabit
`PAIR_FALLBACK_AIM_OFFSET` formulu yerine bu olcumu kullaniyor.
Makine ofseti `nisan_ofseti` alaninda tutuyor, TARAMA'ya gecince sifirliyor.

Birim testinde olculen (saha geometrisiyle):

    sabit formul  -> kaynak degisiminde 44.5 px sicrama
    ogrenilen     -> 0.00 px

**Beklenen davranis:** kilit oturma fazindaki 2-3 saniyelik salinim
belirgin azalmali. Ozellikle **pitch** hatasinin -52..+22 arasi ziplamasi
bitmeli; yaw zaten oturuyordu. Nisan hatasi std'sinin oturma fazinda
12-15 px'ten tek haneye inmesi beklenir. Kilitten atese gecen sure
kisalmali.

Sabit formul yalnizca balon HIC gorulmemisken (ofset ogrenilmemisken)
devrede kalir -- yani ilk kilitte, ilk balon tespitine kadar.

### D4 -- Kilitli hedefin kutusu

`_nisan_tespiti` artik nisan noktasini URETEN gercek tespitlerin kutularini
da donduruyor (`kaynak_bbox`, `nisan_bbox`). Cizim kurali sanal kutuyla
karsilastirma yapmiyor:

    kirmizi  = nisan alinan kutu (balon)
    turuncu  = kilitli ciftin kimlik kutusu (maket)
    sari     = ayni siniftan diger hedefler
    yesil    = gerisi

**Beklenen davranis:** kilitlenince balonun kutusu **kirmizi**, maketin
kutusu **turuncu** olmali. Onceden otonom modda hicbir kutu kirmizi
olamiyordu (maket sari, balon yesil). Manuel ve Asama 1 yolu degismedi:
orada hedef zaten gercek bir tespit oldugu icin kirmizi cizilmeye devam
eder.

### D5 -- Hedef Takip modu

Iki degisiklik:

1. `_nisan_tespiti(..., maket_merkezine=True)` -- balon yoksa **maketin tam
   ortasina** nisan alinir. Onceden "balonun olmasi gereken yer" tahmin
   ediliyordu ve nisangah kutunun altina dusuyordu. Bu mod bir olcum araci;
   gorulmeyen bir seyin yerini tahmin etmemeli.
2. `_takip_hedefi_sec()` -- hedef surekliligi. Secilen hedef bir sonraki
   karede `TRACK_REACQUIRE_PIXELS` (150 px) yaricapi icinde aranir;
   bulunamazsa yeni hedef secilir. Onceden her karede `ciftler[0]`
   (merkeze en yakin) aliniyordu ve merkeze yaklasan bir hayalet hedefi
   caliyordu -- kayitta tek karede **400 px** sicrama olculdu.

**Beklenen davranis:** nisangah tespit kutusunun **tam ortasina** oturmali
ve orada kalmali. Ani buyuk sicramalar bitmeli. Hedef gercekten kaybolana
kadar (150 px'lik pencerede hicbir cift kalmayana kadar) baska bir tespite
atlanmamali.

### Test durumu

`tests_yeni_mimari.py`'ye **14. bolum** eklendi (17 kontrol): nisan
surekliligi, sabit formulun sicrama uretmesi (regresyon tanigi), takip
modunun maket merkezine nisan almasi, imha dogrulama penceresinin dort
sonucu, atis butcesi, TARAMA'da sifirlanma, ve olculen gercek/sahte kutu
boyutlariyla kapi kontrolu. **Tum testler geciyor.**

UI mantigi (takip surekliligi + kutu renk kurali) PyQt5 olmadan izole
calistirilarak ayrica dogrulandi: hayalet hedefi calmiyor (sicrama 0 px),
kayipta yeni hedef seciliyor, balon kirmizi / maket turuncu ciziliyor.

### Bu turda DEGISTIRILMEYENLER

- PID kazanclari: olculen kararli hal std'si 0.1-0.2 px, yani PID saglam.
  Salinim tespit surekliligindendi.
- Asama 3 gorev mantigi (butce / erken durma).
- `AIM_POINT_HEIGHT_RATIO = 0.5` (tam merkez).
- Gozcu renk ayarlari -- 13. bolumde arsivlendigi gibi duruyor.

## 16. Gozcu gosterim dogrulamasi ve dolgunluk esiginin zayifligi (2026-08-16)

Blob cizimi eklendikten sonra sahada dogrulandi: arayuz ekran goruntusu
(Asama 1, etiketler gorunur) + `gozcu_tani` ciktilari. Sahnede 3 maket vardi
(dusman-F16, dost-F16, dusman-Fuze) ve **hicbirinin balonu yoktu**.

### Gosterim/karar uyumu: TAM

Arayuz bilgi satiri `blob K4/M3` yazdi. Ayni kare (`gozcu_tani/ham.png`)
kendi kodumuzla cozuldugunde: 4 kirmizi blob, 3 mavi blob, 2 aday. Birebir
ayni. `balon_kapisi`nin tek kaynak olmasi calisiyor -- arayuz gercek karari
raporluyor, ayri bir hesap yapmiyor.

Cizim de dogru: elenen bloblar sebebiyle birlikte gorunuyor ("dolg 0.46",
"oran 0.37"), mavi bloblar ince mavi kutuyla, adaylar daireyle.

### AMA: dolgunluk kapisi maketin DURUSUNA bagli

Olculen kirmizi bloblar:

| # | konum | boyut | alan | en/boy | dolgunluk | karar |
|---|---|---|---|---|---|---|
| 0 | (830,296) | 34x42 | 601 | 0.81 | 0.42 | elendi (fuze) |
| 1 | (522,305) | 36x29 | 530 | 1.24 | **0.51** | **ADAY** |
| 2 | (0,370) | 6x19 | 102 | 0.32 | 0.89 | elendi (en/boy) |
| 3 | (152,366) | 6x8 | **43** | 0.75 | 0.90 | **ADAY** |

Sahnede balon YOKKEN gozcu **2 aday** uretti ve ikisi de yanlis:

- **#1 kirmizi F16 maketi**, dolgunluk 0.51 -- esik 0.50'yi **0.01 farkla**
  gecti. Sahada daha once olculen deger 0.37'ydi. Fark durus: o kayitta maket
  acili/yandan duruyordu, burada KARSIDAN (burun kameraya donuk) ve silueti
  kompakt. Yani 0.50 esigi maketin acisina gore basarili/basarisiz oluyor.
- **#3 43 piksellik minik leke** (6x8 px). `SPOTTER_MIN_BLOB_AREA = 30` cok
  dusuk: gozcude (DPP 0.0535) 19 cm'lik balon **20 metrede bile ~82 piksel**
  alan kaplar. 43 px hicbir mesafede balon olamaz.

Dolgunluk esigi duyarliligi (ayni kare):

    0.40 -> 3 aday      0.55 -> 1 aday
    0.46 -> 2 aday      0.60 -> 1 aday
    0.50 -> 2 aday  <-- su anki
    0.70 -> 1 aday

Olculen gercek balon dolgunlugu 0.70 (daire icin teorik pi/4 = 0.785).

### Zarar degerlendirmesi

Guvenlik sorunu DEGIL: taret bu adaya gider, avci bakar, balon yok, cift
kurulamaz, dogrulama 1.5 sn'de zaman asimina ugrar, 5 sn kara liste, siradaki
adaya gecilir. Ates kilidi maket+balon sart kostugu icin yanlis ates imkansiz.

Maliyet yalnizca ZAMAN: her yanlis aday ~2 saniye. Ilginc olan, bu davranisin
kullanicinin 13. bolumde tarif ettigi alternatife ("makete de git, balonu
yoksa gec") kazara benzemesi -- ama secilerek degil, esik sinirda oldugu icin.

### Onerilen (HENUZ UYGULANMADI, onay bekliyor)

1. `SPOTTER_BALLOON_MIN_FILL` 0.50 -> **0.60**. Gercek balon 0.70 olctugu icin
   pay kalir; karsidan duran maketi (0.51) eler. Kismen ortulen balon icin
   0.60 hala makul.
2. `SPOTTER_MIN_BLOB_AREA` 30 -> **60**. En uzak mesafede (20 m) balon ~82 px;
   60 hem pay birakir hem 43 px'lik gurultuyu keser.

### Avci tarafi: boyut kapisi tuttu

Ayni karede avci uc tespit uretti (0.87 / 0.80 / 0.81) ve **hicbiri sahte
degildi** -- onceki kayitlarda arka planda beliren dev `dusman-fuze` kutulari
yok. Olculen kutular ~145x169 ve ~131x210 px, yeni kapi 40-374 px.

Not: `dost-F16` KIRMIZI kutuyla cizildi. Bu dogru davranis -- Asama 1'de
kirmizi "su an PID/kalibrasyon hedefi" demek, "dusman" demek degil; nisangah
merkezdeydi ve merkeze en yakin tespit oydu. Yine de renk kodunun anlami
operator icin kafa karistirici olabilir.
