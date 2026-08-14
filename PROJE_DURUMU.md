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
