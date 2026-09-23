# BUKREK Hava Savunma Sistemi — Proje Durumu ve Devir Belgesi

> Bu belge, bir oturum boyunca yapılan tüm çalışmanın özetidir. Yeni bir
> konuşmada bağlam olarak paylaşılabilir. **Son güncelleme: 2026-09-09.**
>
> **En güncel durum için önce 27. bölümü (yaw enkoderi, dal `enkoder-yaw`) ve
> 26. bölümü ("Güncel durum özeti") okuyun**, sonra 19-25. bölümleri. Belge kronolojik büyüyor; aşağıdaki eski
> bölümlerde geçen bazı sayılar sonraki bölümlerde güncellendi. Özellikle
> 17. bölüm HATALIDIR (18. bölüme bakın).
>
> Yan belgeler: `ENKODER_ENTEGRASYON.md` (yaw enkoder sıralı yapılacaklar
> listesi), `VIDEO_KONUSMA_METNI.md` (görev kabiliyet gösterimi videosu).

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

## 17. (HATALI -- 18. BOLUME BAKIN) anavlizaşama2/3 ilk cozumlemesi

> **BU BOLUM YANILTICI.** Videolarin yalnizca bazi bolumleri incelendi;
> asama3'te 8. saniye ve asama2'de 52. saniye HIC acilmadi. Buradan
> "balon %0 goruluyor, hic ates edilmedi" gibi YANLIS sonuclar cikarildi.
> Gercekte her iki kayitta da balon var ve ates ediliyor; salinimin
> kaynagi da burada yazildigi gibi nisan noktasi degisimi DEGIL, mekanik
> rezonans. Dogru cozumleme 18. bolumde. Asagisi yalnizca kayit icin.


Iki kayit kare kare cozumlendi (858 + 2287 kare, 405 + 847 metin degisimi).

### En onemli bulgu: SAHNEDE BALON YOK

Her iki kayitta da balonlar zaten patlatilmis durumda; yerde balon parcalari
goruluyor. Olculen balon tespit orani:

| kayit | kilitli maket goruldu | **balon goruldu** |
|---|---|---|
| asama3 (k400-858) | %89 | **%0** |
| asama2 (k1900-2280) | %77 | **%13** |

Durum satiri bunu dogruluyor: kesintisiz
`Ates engellendi: cifte balon eslesmemis (nisan noktasi tahmini)`.
Asama 3 kaydinda video boyunca **hic ates edilmemis**.

### Sorun 1 -- Balonsuz hedeften CIKIS YOLU YOK (kritik)

Kullanicinin "patlattiktan sonra digerlerine gitmiyor" ve "balonu olmamasina
ragmen kilitlenmis gibi durdu" sikayetlerinin tek bir kok nedeni var.

Dongu:

    KILIT: nisan toleransi saglanir (balon o karede goruldu) -> ATES
    ATES : ates_serbest_mi -> "cifte balon eslesmemis" -> engellenir
           1.5 sn sonra -> KILIT
    ...bastan

Her gecis `_gec()` cagiriyor, o da **`durum_zamani`yi sifirliyor**. Yani
`ENGAGE_LOCK_TIMEOUT` (8 sn) hicbir zaman dolmuyor -- sayac surekli basa
donuyor.

Simulasyonla dogrulandi (60 saniye, balon ARALIKLI goruluyor):

| balon gorulme orani | sonuc |
|---|---|
| %0 | 8.1 sn'de TARAMA'ya doner (timeout calisir) |
| %10 | 8.1 sn'de TARAMA'ya doner |
| **%25** | **60 sn TAKILI KALDI** (20 kez ATES gecisi) |
| **%50** | **60 sn TAKILI KALDI** (34 kez ATES gecisi) |

Sahada olculen oran %13 (asama2) -- yani tam sinirda; balon ara sira
gorulunce sistem sonsuza kadar o hedefte kaliyor.

**Bu, Asama 3 gorev mantigiyla ILGILI DEGIL.** `imha_edildi()` zaten
TARAMA'ya donup siradaki hedefe geciyor. "Bir tane patlatip bekliyor"
davranisi bilincli bir kural degil, bu takilmanin sonucu.

### Sorun 2 -- Salinimin gercek kaynagi

Balon gorulmedigi icin nisan noktasi MAKETTEN turetiliyor
(`maket_merkez_y + 0.75 x maket_genisligi`). Maket kutusunun kendisi ise
kare kare oynuyor:

| olcum | asama2 | asama3 |
|---|---|---|
| kutu merkez y, ardisik kare farki (ort.) | 7.6 px | 7.8 px |
| en buyuk sicrama | **67 px** | **56 px** |
| >20 px sicrayan kare orani | %14.8 | %15.1 |
| kutu YUKSEKLIGI std | 10.0 px | 23.7 px |
| maket kaybolma olayi | 23 kez | 26 kez |

Turetme formulu kutu genisligini CARPAN olarak kullandigi icin (0.75 x mw)
genislik gurultusu de buyutulerek nisan noktasina geciyor. Durum satirinda
olculen pitch hatalari bununla tutarli: **+72, -53, -46, +57, -49, -45**;
yaw ayni pencerede -8..+4 arasinda sabit.

**D3 (nisan surekliligi) duzeltmesi bu kayitlarda DEVREYE GIREMEDI**:
`nisan_ofseti` ancak balon VE maket ayni karede gorulunce ogreniliyor.
Asama 3'te balon %0 goruldugu icin ofset hic ogrenilemedi, sabit formul
devrede kaldi. Duzeltme yanlis degil, ama on kosulu bu sahnede saglanmiyor.

### Sorun 3 -- Ates karari verilemiyor

Asama 2 ikinci denemesinde balon %13 karede goruluyor. Ates icin
`AIM_HOLD_FRAMES = 3` ARDISIK kare gerekiyor ve `kilit_adimi` balon
gorulmeyen karede sayaci sifirliyor. %13 oranla 3 ardisik kare olasiligi
~%0.2 -- pratikte imkansiz. Kullanicinin "bir turlu emin olamiyor"
gozlemi tam olarak bu.

### Onerilen duzeltmeler (UYGULANMADI, onay bekliyor)

1. **Balonsuz hedeften cikis** (kritik): KILIT/ATES'te secilen ciftin balonu
   yoksa bir sayac artsin, esigi asinca hedef kara listeye alinip TARAMA'ya
   donulsun. `LOCK_NO_BALLOON_MAX_FRAMES ~ 60` (2 sn). Bu, 1. sorunu
   dogrudan kapatir.
2. **Salinimdan bagimsiz toplam sure siniri**: KILIT'e ILK girildigi an
   damgalansin; ATES<->KILIT gecisleri onu sifirlamasin. Boylece hangi
   sebeple olursa olsun bir hedefte en fazla N saniye kalinir.
3. **Turetilen nisan noktasina yumusatma**: kutu gurultusu 7.6 px ortalama;
   basit bir ustel yumusatma (a=0.3) bunu ~2.5 px'e indirir. Yalnizca
   TURETILEN noktaya uygulanmali; balon gercekten goruldugunde ham deger
   kullanilmali.

Ates icin balon sarti KALMALI -- o bir guvenlik katmani, gevsetilmemeli.

## 18. anavlizaşama2/3 TAM cozumlemesi (2026-08-16)

Her iki kaydin HER KARESI olculdu (858 + 2287 kare). Cizim renk koduna gore
kare kare: nisan alinan kutu (kirmizi = balon), kilitli maket (turuncu),
nisangah konumu. Kritik anlarin durum metni ayrica okundu.

| | asama3 | asama2 |
|---|---|---|
| sure | 28.6 sn | 76.2 sn |
| balon kutusu goruldu | %19 | **%40** |
| kilitli maket goruldu | %79 | %63 |
| balonun son goruldugu an | **8.10 sn** | -- |

### BULGU 1 -- Imha dogrulama KILITLENMESI (kritik; 14. bolumdeki D2 hatasi)

Asama 3, durum metninden birebir:

    7.6 sn  ATES - dusman-Fuze (1. hedef, 1. atis)      <- ATES EDILDI
    7.7 sn  ATES - imha dogrulaniyor (1. atis)
    8.1 sn  Atesleme basarili, imha dogrulaniyor...
    8.3 sn  ATES - imha dogrulaniyor (1. atis)
    8.4 sn  Ates engellendi: guven dusuk 0.55           <- PENCERE DOLDU
    8.5 sn  Ates engellendi: maket bu karede tespit edilmedi
    ...
   28.5 sn  Ates engellendi: cifte balon eslesmemis     <- 20 SANIYE TAKILI

Balon 8.10 saniyede kayboldu (patladi) ama sistem 20 saniye ATES durumunda
kaldi ve TARAMA'ya HIC donmedi.

Kok neden (`ates_dogrulama_adimi` + `_otonom_ates_denemesi`): ates aninda
balon goruluyor (zaten ates sarti) ve ateste sonraki 0.7 saniyelik pencerede
birkac kare DAHA goruluyor (patlama ani + YOLO gecikmesi).
`FIRE_CONFIRM_MAX_SEEN = 1` bunu "balon hala orada" sayip `'tekrar'`
donduruyor. Sonrasi kapali devre:

    'tekrar' -> ates_serbest_mi -> balon artik YOK -> ENGELLENDI
             -> ates_kaydet() CAGRILMIYOR
             -> ates_sayisi artmiyor          => 'pes' asla tetiklenmiyor
             -> son_ates_zamani guncellenmiyor => pencere hep dolu
             -> _ates_balon_gorulme sifirlanmiyor => hep 'tekrar'
             -> ates_sayisi > 0 oldugu icin KILIT'e de donulmuyor

Yani **'tekrar' karari verildikten sonra ates edilemezse cikis yolu yok.**

Asama 2'de ayni hata TETIKLENMEDI, cunku orada balon hala goruluyordu:

    51.3 sn  ATES - imha dogrulaniyor (1. atis)
    51.5 sn  ATES - imha dogrulaniyor (2. atis)    <- tekrar atesledi
    52.3 sn  ATES - imha dogrulaniyor (3. atis)    <- ucuncu
    53.0 sn  Aday secildi, yoneliniyor: -8.8, -0.9 <- BUTCE DOLDU, CIKTI
    53.2 sn  YONELME | 3 cift | imha 0

Butce dolunca `'pes'` -> `imha_edilemedi()` -> TARAMA -> yeni hedef. Tasarim
boyle calismali; asama 3'te ates edilemedigi icin bu yol hic isletilemedi.

### BULGU 2 -- Salinim MEKANIK: yapisal rezonans

17. bolumde salinimin "nisan noktasi kaynak degisimi"nden geldigi
soylenmisti; **bu yanlis**. Balon ve maket kutulari ayni sahnede oldugu icin
taret saliniyorsa BIRLIKTE kayar, YOLO gurultusuyse bagimsiz titrerler.

| | asama3 | asama2 |
|---|---|---|
| korelasyon (balon vs maket hareketi) | **+0.934** | **+0.852** |
| ortak mod (taret) std | 14.7 px | 12.7 px |
| fark mod (kutu gurultusu) std | 2.9 px | 3.9 px |
| **salinimin taretten gelen payi** | **%96** | **%91** |

FFT ile frekans:

| pencere | RMS genlik | baskin frekans | periyot |
|---|---|---|---|
| a3 k101-243 | 21.9 px | **3.15 Hz** | 0.318 sn |
| a2 k1424-1584 | 21.9 px | **2.24 Hz** | 0.447 sn |

FAZ 3'te olculen yapisal rezonans **2.7 Hz (0.37 sn)** -- ayni bant. PID,
taretin mekanik dogal frekansini uyariyor.

### BULGU 3 -- Ates karari neden verilemiyor

Balon GORULEN karelerde:

| | asama3 | asama2 |
|---|---|---|
| pitch hatasi ort / std | +19 / 33 px | +24 / 44 px |
| tolerans max(9, 0.35 x r) | 9.9 px | 9.2 px |
| **tolerans icinde kare** | %37.9 | %22.5 |
| **3+ kare ARDISIK seri** | **4 tane** | **16 tane** |
| pitch kare kare degisim (ort) | 9.8 px | 10.0 px |
| >20 px sicrayan kare | %19.5 | %17.8 |

Salinim genligi (22 px RMS) toleransin (9-10 px) iki kati. Sinuzoidal bir
salinimda genligin %45'inin altinda kalinan sure orani ~%30; olculen %22-38
bununla birebir tutarli. `AIM_HOLD_FRAMES = 3` (0.1 sn) ise rezonans
periyodunun (0.32-0.45 sn) dortte biri -- hedef tolerans penceresinden bu
kadar surede gecip gidiyor.

### Kullanicinin sorusuna cevap

"Asama 3 sadece bir tane patlatip bekliyor mu?" -- **Hayir.** Gorev
mantiginda boyle bir kural yok; `imha_edildi()` TARAMA'ya donup siradaki
hedefe gecer (asama 2'de 53.0 sn'de calistigi goruluyor). Asama 3'te
beklemenin sebebi yukaridaki dogrulama kilitlenmesi -- sistem kendi kendine
cikmayacakti.

### Onerilen duzeltmeler (UYGULANMADI)

1. **Dogrulama kilidini kir** (kritik): `'tekrar'` donduyu halde ates
   edilemeyen kareler sayilsin; birkac kare ust uste ates edilemezse `'pes'`
   donsun. Cikis her durumda garanti olur.
2. **`FIRE_CONFIRM_MAX_SEEN` gevset** (1 -> 3-4) veya pencereyi atesten
   ~0.2 sn SONRA baslat. Patlamis balon birkac kare daha goruldugu icin
   "patlamamis" sayiliyor.
3. **Rezonansi sondur** (asil salinim kaynagi): PID cikisina 2-3.5 Hz
   bandinda sonumleme -- turev terimi, cikis egim siniri veya notch.
   Kazanc dusurmek en basiti ama yalpalama suresini uzatir.

Not: `AIM_HOLD_FRAMES`'i veya toleransi buyutmek salinimi GIZLER, cozmez;
ates dogrulugu duser. Once rezonans sondurulmeli.


---

# BOLUM 19-26: 18. BOLUMDEN SONRASI (2026-08-16 .. 2026-09-02)

> Bu blok, 18. bolumun yazildigi andan bugune kadar yapilan HER SEYI kapsar:
> arayuz yerlesimi, olculen uc duzeltmenin uygulanmasi, balonsuz hedefte
> kilitlenmenin cozumu, elektronik tetikten servo tetige gecis, gorev
> kabiliyet gosterimi videosu metni, taret hizlarinin sahada dusurulmesi ve
> yaw enkoder plani.
>
> **Numaralandirma notu:** belgede 15. bolum yoktur (14'ten 16'ya atlar).
> Eksik bir icerik degil, yalnizca numaralandirma hatasidir; geriye donuk
> duzeltilirse mevcut baslik referanslari bozulur, o yuzden birakildi.

## 19. Arayuz yerlesimi (2026-08-16)

Uc adimda yapildi; ilk iki adim sirasiyla birbirinin hatasini duzeltti.

**19.1 Ilk deneme (`6ecf309`) — HATALIYDI.** Avci paneli 1280x737'ye
SABITLENDI. Pencere `showMaximized()` ile aciliyor; 2560x1440 ekranda panel
1280'de kaldi, icerik sol uste sikisti ve **ekranin %73'u bos kaldi.**

**19.2 Duzeltme (`1cf0c39`).** `camera_label` esnek yapildi
(`setMinimumSize` + `QSizePolicy.Expanding`), artan alan germe payi 1 ile
avciya verildi, bosa giden `addStretch` cagrilari kaldirildi.

| | onceki | sonraki |
|---|---|---|
| avci paneli (2560x1440'ta) | 1280x737 (sabit) | 1814x1043 |
| ekran doluluk | %27 | %74 |
| `DISPLAY_WIDTH` | 1280 | 1600 |
| gerilme | %41 | %13 |
| IPC kare boyutu | 2.8 MB | 4.4 MB |

**19.3 Ferahlatma (`9a10e25`).** Gozcu 660 -> **760** (760x427), sag panel
804. Avci esnek oldugu icin kendiliginden 1710x984'e kisildi, gerilme %7'ye
dustu. Buton dolgusu/fontu buyutuldu, layout araliklari tanimlandi (hicbiri
tanimli degildi), `QGroupBox` stili tek bir `grup_stili` yardimcisinda
toplandi.

**Kritik nokta — bu degerler matematigi BOZMAZ.** Tespit, PID, kalibrasyon
ve nisan hesabinin tamami HAM kare koordinatlarinda yurur; arayuze giden
kare salt okunur bir gosterim kopyasidir. Tek bagli nokta fare tiklamasidir
ve `_etiket_to_kare` pixmap geometrisini **calisma aninda okur**, sabit sayi
kullanmaz. Uc pencere boyutunda dogrulandi (min / orta / maksimize): merkeze
tiklama ham merkeze **0.00 px** hatayla dusuyor, letterbox ofseti
(maksimizede ust/alt 129 px) dogru hesaplaniyor. Sarti: `camera_label`'in
`Qt.AlignCenter` hizalamasi korunmali.

Ilgili ayarlar `config.py` > ARAYUZ YERLESIMI: `UI_AVCI_GENISLIK = 1280`,
`UI_GOZCU_GENISLIK = 760`, `UI_SAG_PANEL_PAYI = 44`, `DISPLAY_WIDTH = 1600`.
Gozcu onizlemesi bu genislikte **URETILIR** (`spotter_module`), yani
buyutunce gerilme olmaz, gercekten netlesir.

## 20. 18. bolumdeki uc duzeltmenin uygulanmasi (`b5998fc`)

18. bolum uc oneri birakmisti (UYGULANMADI notuyla). Kullanici "ilk ucunu
uygula" dedi; ucu de uygulandi.

**D1 — Imha dogrulama kilidi kirildi (kritik).** 18. bolumde olculen
**20 saniyelik takilmanin** dogrudan caresi. Eski hata zinciri: `'tekrar'`
karari verildikten sonra ates edilemezse `ates_kaydet()` cagrilmiyordu ->
sayac artmiyordu -> `'pes'` asla tetiklenmiyordu -> `ates_sayisi > 0` oldugu
icin KILIT'e de donulmuyordu. Sistem ATES durumunda kilitli kaliyordu.
Artik engellenen her kare `AngajmanMakinesi.ates_engellendi()` ile sayiliyor;
`FIRE_RETRY_GIVEUP_FRAMES = 45` (1.5 sn) asilinca `imha_edilemedi()` cagrilip
TARAMA'ya donuluyor. **Cikis her durumda garanti.** Basarili ates ve TARAMA
gecisi sayaci sifirliyor.

**D2 — Patlama penceresi.** Saha olcumu: ates 7.60 sn'de verildi, balon
8.10'da kayboldu — patlamis balon **0.5 saniye (15 kare) daha gorundu**
(mermi ucus suresi + patlama + YOLO'nun kutuyu birakmasi). Gecikmesiz
sayimda bu kareler "balon hala orada" sayilip patlamis hedefe tekrar ates
ediliyordu. Sayim artik atesten `FIRE_CONFIRM_DELAY_SEC` kadar SONRA
basliyor, `FIRE_CONFIRM_MAX_SEEN` 1 -> **4**.

**D3 — Rezonans sonumleme.** Olculdu: salinimin **%91-96'si taretin KENDI
hareketi** (balon ve maket kutulari **+0.93 korelasyonla** birlikte kayiyor),
baskin frekans **2.24-3.15 Hz** — FAZ 3'te olculen yapisal rezonansla
(2.7 Hz) ayni bant. Denetleyici saf oransal (KD=0.001, etkisiz) ve donguda
~185 ms olu zaman var; bu birlesim o frekansta salinim uretir.

PID cikisina birinci derece alcak geciren suzgec eklendi,
`PID_OUTPUT_SMOOTHING = 0.30` (fc = **1.70 Hz**):

| frekans | ne | kazanc |
|---|---|---|
| 0.5 Hz | yonelme | 0.96 — oturma hizi korunuyor |
| 2.7 Hz | rezonans | 0.53 — salinim ~%47 bastiriliyor |

Beklenen: 21.9 px RMS -> ~11.7 px. Suzgec hafizasi `reset_pid_state`'te
sifirlanir; `0.0` yazilirsa suzgec kapanir (eski davranis).

**Bilerek YAPILMAYAN:** tolerans buyutulmedi. Kullanicinin saha beyani
"sistem her mesafede nisangahin tam ortasina vuruyor" oldugu icin paralaks
kalemi butceden cikarildi; 16.2 m'de 95 mm balon yaricapina karsi tolerans
20 px'e (80 mm) cikabilirdi — **ama once salinim sonmeli**, cunku salinim
tepesi (31 px = 124 mm) balonun disinda kaliyor. Tolerans buyutmek salinimi
GIZLER, cozmez.

## 21. Balonsuz hedefte "sanal kilitlenme" (`5591871`, `302c33e`)

**Saha kaydi:** `analizasama3.mp4`, 1285 kare, 97 durum blogu kare kare
cozumlendi. Sistem **balonsuz** bir dusman-F16'ya kilitlendi ve **42 saniye
cikamadi**; ayni karede avci, balonu GORUNEN baska bir dusman hedefi de
goruyordu. Videoda balona nisan alinan kare orani **5/1285 (%0.4)**.

Kullanicinin sorusu "sanal kilitlenmeyi mi kaldirsak" idi. **Kaldirilmadi** —
sanal nisan noktasi KILIT'te takip koprusu icin gerekli. Ayrim netlestirildi:

> **DOGRULAMA'da balon SART** (hedef secimi kararidir).
> **KILIT'te gecici kayip TOLERE EDILIR** (takip kararidir).

**C1 — Dogrulamaya balon sarti.** `dogrulama_adimi` yalnizca SINIFA
bakiyordu, balonun varligini hic sormuyordu. Artik dogrulama penceresinde
balon en az `VERIFY_MIN_BALLOON_FRAMES` (1) kez gorulmeli.

**C2 — KILIT zaman asiminda kara liste.** Eskiden timeout TARAMA'ya donuyor
ama kara listeye ALMIYORDU; `avcida_hazir_hedef_var` ayni hedefi aninda geri
seciyordu — kisir dongu.

**Kara liste artik KAYIT BASINA yaricap tutuyor.** Sebep, kullanicinin
sordugu tam nokta: kara liste hedef degil **ACI** tutar, genis yaricap
KOMSU hedefi de kapatir.

| mesafe | 1.0 m yanal ayrim | 4.0 der yaricap |
|---|---|---|
| 7.5 m | 7.59 der | guvenli |
| 16.0 m | **3.58 der** | **komsuyu KAPATIR** |

Bu yuzden: balonsuz/timeout icin `BLACKLIST_NO_BALLOON_RADIUS_DEG = 1.5` +
`BLACKLIST_NO_BALLOON_TTL_SEC = 3.0` (16 m'de ~0.42 m bolge, 3 saniye sonra
hedef tekrar acilir); imha ve dost icin eski `4.0` derece korunuyor.

**C3 — Gozcu esikleri GERI ALINDI.** `SPOTTER_MIN_BLOB_AREA` 60 -> **30**,
`SPOTTER_BALLOON_MIN_FILL` 0.60 -> **0.45**. 60/0.60 sahada **gercek balonu
eliyordu**: gozcu panelinde fuzenin altindaki balon "alan 34<60" ve
"dolg 0.50" etiketleriyle elenmis gorunuyordu. O degerler tek bir karedeki
maket olcumune gore onerilmisti — **hatali oneriydi**. Artik gevsek taraf
tercih ediliyor: kacirmanin bedeli gorev basarisizligi, bosuna gidisin
bedeli ~1.5 saniye.

**C4 — Durum cubugu ezilmesi.** "Hedefe nisan alindi" satiri otonom modda
durum makinesinin mesajini eziyordu (2.6-11.8 sn arasi kesintisiz), sistemin
KILIT'te takildigi ekrandan okunamiyordu. Artik yalnizca manuel/Asama 1'de
yaziliyor. KILIT mesajina "balon VAR/BALON YOK | nisan TAMAM/bekliyor"
eklendi.

### 21.1 Cikis hizlandirmasi ve yakalanan regresyon (`302c33e`)

Saha geri bildirimi: "takilma bitti ama siradaki hedefe gecis beklenenden
uzun suruyor." Darbogaz olculdu: balon sarti `dusman_mi(sinif)` blogunun
ICINDE calisiyordu, yani ancak `VERIFY_CONFIRM_FRAMES` kadar ARDISIK ayni
sinif toplandiktan sonra devreye giriyordu; maket araliklı goruluyorsa karar
`ENGAGE_VERIFY_TIMEOUT`'a kadar sarkiyordu.

  - `VERIFY_NO_BALLOON_GIVEUP_SEC = 0.40` **(YENI)** — dogrulamada balon bu
    sure boyunca HIC gorulmediyse sinif tutarliligini beklemeden birak.
  - `ENGAGE_VERIFY_TIMEOUT` 1.5 -> **1.0**
  - `BLACKLIST_NO_BALLOON_TTL_SEC` 4.0 -> **3.0**

**Bu degisiklik bir REGRESYON uretmisti, testte yakalandi ve duzeltildi:**
sinif tutarliligi 4 karede (0.13 sn) saglaniyor ve balon sarti balona HIC
SURE TANIMADAN tetikleniyordu. Balon YOLO icin kucuk nesnedir ve ilk
karelerde kacirilir (olcum: karelerin %19-40'inda goruluyor), yani balonu
GERCEKTEN olan bir hedef yanlislikla elenirdi. Artik balon sarti da
`VERIFY_NO_BALLOON_GIVEUP_SEC` dolmadan karar vermiyor.

Olculen davranis:

| senaryo | sonuc |
|---|---|
| balonlu hedef (balon hemen) | 3 kare (0.10 sn) -> **KILIT** |
| balon 0.30 sn sonra goruldu | 9 kare (0.30 sn) -> **KILIT** (kacirilmiyor) |
| balon 0.60 sn sonra goruldu | 12 kare (0.40 sn) -> TARAMA (esik asildi) |
| balonsuz hedef | 12 kare (0.40 sn) -> TARAMA |
| maket araliklı, balon yok | 12 kare (0.40 sn) -> TARAMA (eskiden 1.5 sn) |

Sure butcesi: tipik cikis **~0.70 sn** (yalpalama 0.30 + dogrulama 0.40),
en kotu **2.90 sn** (onceden 4.00).

**Kullanicinin "hangi deger bekleme suresini gosterir" sorusunun cevabi:**
`VERIFY_NO_BALLOON_GIVEUP_SEC` (balonsuz hedefi birakma) ve
`ENGAGE_VERIFY_TIMEOUT` (en kotu hal tavani). Kisaltmak isterse once
`VERIFY_NO_BALLOON_GIVEUP_SEC` dusurulur — ama 0.30'un altina inilmemeli,
balonun kacirilma orani oraya kadar tolere edilebilir.

## 22. Elektronik tetikten SERVO tetige gecis (dal: `servo-tetik`)

Kullanici roleli elektronik tetigi birakip mekanik tetigi **hobi servosuyla**
cekmeye gecti. Is **ayri bir dalda** yapildi (`servo-tetik`), calisan sistem
bozulmadan durdu.

### 22.1 GPIO16 -> GPIO12

| | GPIO16 | GPIO12 |
|---|---|---|
| kullanim | role (ac/kapat) | servo (PWM) |
| donanim PWM | yok | **var** (RP1 PWM0) |
| gerekli mi | — | zorunlu degil ama titresimi azaltir |

Kodda tek degisiklik `FIRE_SERVO_PIN = 12`. Elektrik olarak servo sinyal
ucu (turuncu/sari) GPIO12'ye, GND ortak; **servo beslemesi ayri olmali**
(asagida).

### 22.2 Pi 5 tuzagi: `pigpio` CALISMAZ

Pi 5'in GPIO'su RP1 yardimci yongasindan gecer; `pigpio` bunu bilmez.
Kullanilan kutuphane **`lgpio`**. Bu belgeye yazilmasinin sebebi: internetteki
servo orneklerinin cogu `pigpio` kullanir ve Pi 5'te sessizce hicbir sey
yapmaz.

### 22.3 Yasanan hatalar ve cozumleri

| hata | belirti | cozum |
|---|---|---|
| `gpio_get_chip_info` yanlis alan | "gpiochip bulunamadi" | etiket `bilgi[3]`'te, `bilgi[2]` degil (`06a29c5`) |
| `tx_servo(h, pin, 0)` | `lgpio.error: 'bad PWM micros'` | sifir icin `tx_pwm(h, pin, 0, 0)` (`5e4dcdb`) — **bu cokme `motor_fire_module`'un tum GPIO baslatmasini da oldururdu** |
| acilista 1500 us darbe | surekli donus servosu kendiliginden donuyordu | acilista darbe verilmiyor + `k` ile notr kalibrasyonu (`c6c81d9`) |
| `input()` Enter bekliyordu | tus basimlari tek satirda birikiyordu | termios raw mod, **tek tus** girisi (`dba7ad4`) |
| ates dizisi ters | once biraktiriyor, sonra cekiyordu | `FIRE_SERVO_PULL_DIR` (`64a2fdf`) |
| konum kaymasi | birkac atistan sonra baslangic yerinde degil | birakma yonunde dayanaga yaslanma payi (`7c3a3f7`) |

### 22.4 360 derece (surekli donus) servo yanlis parcaydi

Kullanicinin ilk aldigi servo **surekli donus (360)** modeliydi. Bu servoda
darbe genisligi **konum degil HIZ** demektir:

  - 1500 us civari = dur, altinda bir yone, ustunde diger yone doner
  - **Konum kavrami yoktur** — "30 derece git gel" ancak "su kadar sure don"
    ile taklit edilir, ve sure/gerilim/yuk degistikce **konum kayar**

Kullanicinin gozlemi tam olarak buydu: "bazen az cekilip kaliyor, geri
salmiyor; birkac kez yaptigimda baslangic yerinde degil." Sebep servonun
tipiydi, kodun hatasi degildi. `FIRE_SERVO_MODE = 'hiz'` bu servo icin
yazildi ve calisti, ama **tekrar edilebilirligi dusuktu**.

**Cozum: standart 180 derece servoya gecildi** (`732707f`). O servoda darbe
genisligi = **konum**; servo her komutta ayni aciya gidip orada TUTAR, yani
konum kaymasi **yapisal olarak imkansiz**. `FIRE_SERVO_MODE = 'konum'`.
Kod degisikligi gerekmedi — iki mod da zaten yazilmisti, yalnizca sabit
degisti.

### 22.5 Guncel (sahada calisan) ayarlar

```python
FIRE_SERVO_MODE   = 'konum'
FIRE_SERVO_PIN    = 12
FIRE_SERVO_REST_US = 1600      # tetik serbest   (99.0 derece)
FIRE_SERVO_PULL_US =  833      # tetik cekili    (75.0 derece)  -> strok ~69 derece
FIRE_SERVO_LEG_SEC = 0.20      # tek yon hareket suresi
FIRE_SERVO_CYCLES  = 1
FIRE_SERVO_FREQ    = 50
```

**"Dinlenme neden 1500 degil?"** — 1500 us servonun kendi orta noktasidir;
tetigin nerede serbest kaldigiyla **ilgisi yoktur**. Dogru deger montaj
geometrisine baglidir (kol boyu, takilma acisi, tetik stroku). Bu sistemde
tetik 1600'de tam serbest kaliyor, 1500'de hala hafif cekili duruyordu.
1600 dogru degerdir.

**Mekanik sinira pay:** 500-2500 us araliginda PULL tarafinda 75 derece,
REST tarafinda 81 derece bos pay var — servo hicbir konumda sinira
dayanmiyor. Dayanmak surekli tork demektir, servoyu isitip dislisini
asindirir.

**`FIRE_CONFIRM_DELAY_SEC` 0.4 -> 0.6** bu dalda buyutuldu: tetik artik
mekanik cekiliyor ve mermi roleye gore ~0.2 sn (`FIRE_SERVO_LEG_SEC`) daha
gec cikiyor; patlama penceresi bu gecikmeyi de kapsamali. **Role moduna
donulurse 0.4'e cekilmeli.**

### 22.6 Besleme uyarisi (acik konu)

Servo su an **Pi 5'in 5V pininden** besleniyor. MG996R sinifi bir servo
kalkista 1-2 A cekebilir; Pi'nin 5V pini bunu garanti etmez. Belirtisi
kullanicinin da yasadigi turden davranistir: servo aciya varamadan komut
biter, tetik yarim cekili kalir. **Onerilen: servoya ayri 5-6 V besleme,
GND Pi ile ortak.** Enkoder (50 mA) icin Pi 5V yeterlidir, servo icin
degildir.

### 22.7 `servo_tani.py` (yeni tanilama araci)

Pi'de tek basina calisan, `motor_fire_module`'a dokunmadan servoyu deneme
araci. Tek tus girisi (Enter gerekmez):

| tus | is |
|---|---|
| `x` | tani: gpiochip, pin, mod, mevcut ayarlar |
| `k` | notr (DUR) kalibrasyonu — surekli donus servosu icin |
| yon tuslari | konum/hiz komutu ver |

Saha kalibrasyonu bu araclarla yapildi. Servo ayarlari degisecekse **once
bu arac** kullanilmali, `motor_fire_module` sonra guncellenmeli.

## 23. Gorev Kabiliyet Gosterimi videosu konusma metni (`734b3db`)

Sartname (`2026 Sartname TR v1.5`, madde 2.4.4.1) yedi yetenek istiyor.
`VIDEO_KONUSMA_METNI.md` bu yediyi **sirasiyla ve eksiksiz** karsilayan
konusma metnini icerir.

| yetenek | icerik |
|---|---|
| 1 | Arayuz tum fonksiyonlariyla anlatilir (entegre sistem uzerinden — pozitif degerlendiriliyor) |
| 2 | Duragan halde 15 m'deki balonun patlatilmasi |
| 3 | Iki eksende hareket ederken Acil Durdur |
| 4 | Ates ederken Acil Durdur |
| 5 | Iki eksende hareket eden hedefin takibi |
| 6 | 5/10/15 m'de tespit + siniflandirma (F16, Mini/Micro IHA, Fuze, Helikopter) |
| 7 (ops.) | 10 m'de 1 kirmizi + 2 mavi; otonom imha, 10 sn bekle, Acil Durdur, 10 sn bekle, kapat |

Belgede ayrica: **4:30-4:50 hedef sure** (sartname siniri en az 2, en fazla
5 dakika), zaman damgali **YouTube aciklamasi** (aciklamada gosterim
noktalarinin belirtilmesi zorunlu) ve cekim oncesi **kontrol listesi** var.

Sartnamenin atlanmamasi gereken maddeleri: en az 720p, **tek** video,
**yalnizca YouTube** ("Liste disi" yuklenebilir), yetenekler **belirtilen
sirayla** ve videonun ilgili kisminda **kacinci yetenek oldugu yazili**
olmali. Link T3 KYS formuna eklenir; **linkte sorun olursa takim elenir.**

## 24. Taret donus hizlari: nereden ayarlanir (`197793c`)

Kullanicinin sorusu: "otonom modlarda hiz hic degismeden sadece manuel modda
butonlarla kontrolde donus hizlarini nerden ayarliyorum."

**Cevap: manuel ve otonom AYNI dort sabiti paylasir.** Ikisi
`motor_fire_module.py` icindeki tek bir darbe motorunu kullanir; sadece
manuel icin ayri bir hiz ayari **yoktur**.

```python
MIN_DELAY  = 0.00040   # en yuksek hiz  (darbeler arasi YARIM periyot)
MAX_DELAY  = 0.0015    # kalkis ve durus hizi
ACCEL_STEP = 0.00003   # hizlanma ivmesi
DECEL_STEP = 0.00008   # frenleme ivmesi
```

`MIN_DELAY` **kucultmek hizlandirir**, buyutmek yavaslatir (yarim periyot).
Rampa zorunludur: CS-M22323 (NEMA23) rotor ataleti yuksek, sabit hizda
kalkis adim kacirir.

Otonom tarafta **ek** bir tavan var: `SERVO_MAX_DEG_PER_SEC`. Gercek otonom
hiz **ikisinin kucugudur**.

### 24.1 Sahada yapilan dusurme (kullanici olcumu)

| sabit | onceki | **guncel** | etkisi |
|---|---|---|---|
| `MIN_DELAY` | 0.00015 | **0.00040** | darbe tavani 3333 -> **1250** darbe/sn |
| `SERVO_MAX_DEG_PER_SEC` | 100.0 | **50.0** | otonom yazilim tavani |

Ortaya cikan gercek hizlar (`STEPS_PER_DEGREE_YAW = 26.667`,
`STEPS_PER_DEGREE_PITCH = 44.444`):

| eksen | onceki tepe | **guncel tepe** | baglayan |
|---|---|---|---|
| yaw | 125 der/sn | **46.9 der/sn** | **DONANIM** (MIN_DELAY) |
| pitch | 75 der/sn | **28.1 der/sn** | donanim |

**Dikkat edilecek nokta:** `MIN_DELAY` 0.00040'a cekilince yaw'da donanim
tavani (46.9) yazilim sinirinin (50) **ALTINA** dustu — yani
`SERVO_MAX_DEG_PER_SEC` yaw'da artik **baglayici degil**. Hatali bir durum
degildir, ama yaw'i hizlandirmak icin `SERVO_MAX_DEG_PER_SEC`'i buyutmek
**hicbir sey yapmaz**; `MIN_DELAY` kucultulmelidir.

Testteki "yaw tam hizina cikabiliyor" kontrolu iki tavanin esit olmasini
varsayiyordu; gercek degismezi (**ikisinin kucugu**) olcecek sekilde
guncellendi. Devir teslim butcesi hala geciyor: pitch'te 20 derece /
28.1 = **0.71 sn** < `ENGAGE_SLEW_TIMEOUT`/2.

### 24.2 Ayni committeki tetik ayarlari

`FIRE_SERVO_PULL_US` 933 -> **833** (REST 1600 ile strok ~69 derece),
`FIRE_SERVO_LEG_SEC` 0.28 -> **0.20**. MG996R katalogunda 69 derece
~0.20 sn eder, yani **tam sinirda**; sahada sorunsuz calisiyor ama gerilim
sarkarsa (bkz. 22.6) servo aciya varmadan sonraki komut gelir. **Tetik yarim
cekili kalirsa ilk bakilacak yer burasidir** — 0.24'e cikarilir.

## 25. Yaw enkoder entegrasyonu — plan (`ENKODER_ENTEGRASYON.md`)

**Sorun:** yaw eksenindeki 1:3 dislide asinmadan kaynakli **bosluk** var.
Olcum: yaw kalinti **10.7 px RMS**, pitch **0.9 px**. Pitch'te direkt tahrik
+ 1:5 planet reduktor oldugu icin sorun yok; **pitch'e dokunulmayacak.**

**Donanim:** Wachendorff **WDGA 36A** mutlak CANopen enkoder
(CiA 301 / CiA 406 V3.2 class C2). Siparis kodundaki `12` = **12 bit
singleturn** (4096 adim/tur), `00` = **multiturn YOK**. Donusturucu
Waveshare **USB-CAN-A** (CH340, `/dev/ttyUSB0`). Baglanti M12 5-pin:
`1 Vcc` · `2 GND` · `3 CAN_H` · `4 CAN_L` · `5 CAN_GND`. Enkoderde dahili
120 ohm sonlandirma **yok** (siparis kodunda `AEO` yok), bu yuzden
Waveshare uzerindeki anahtar **ON** olmali.

| olcu | deger |
|---|---|
| enkoder adimi | 0.0879 der |
| 1:3 disli ile taret | 0.0293 der |
| kamera | 0.0143 der/piksel -> **enkoder 2 kat kaba** |
| olculecek bosluk | ~0.153 der -> enkoder 5 adimda gorur |
| taret araligi | +-90 der -> enkoder **+-270 der** -> **SARMA VAR** |

**Iki kritik risk:**

1. **Sarma takibi.** Multiturn olmadigi icin enkoder 360'ta sifirlanir;
   taret +-90 derece donunce enkoder 1.5 tur doner. 180 derece esikli
   unwrapping gerekir (pay 48 kat, guvenli). **Guc kesilince tur sayaci
   sifirlanir** — bilinen konumda referans alma proseduru sart.
2. **`HUNTER_DPP_YAW = 0.01430` GERI ALINACAK.** Bu deger su an boslugu
   telafi etmek icin **kasten** pitch olceginden kaydirilmis durumda
   (pitch -0.01360). Enkoder gercek aciyi verdiginde **cifte duzeltme**
   yapar. Bu adim (`ENKODER_ENTEGRASYON.md` Faz 5.1) **atlanamaz**;
   unutulursa sistem bozulur.

**Yol haritasi 8 fazdir** ve tam sirali kontrol listesi
`ENKODER_ENTEGRASYON.md` dosyasindadir: FAZ 0 donanim -> FAZ 1 CAN hatti
dogrulama -> FAZ 2 enkoderi tani (`0x6501`, `0x6502`, 16 bit denemesi,
PDO 10 ms) -> FAZ 3 **sadece oku ve goster** -> FAZ 4 boslugu olc ->
FAZ 5 telafi -> FAZ 6 kapali dongu (opsiyonel) -> FAZ 7 saglamlastirma.

**Tasarim karari — asamali gecis.** FAZ 3'un sonunda sistem **aynen eskisi
gibi** calisir; enkoder yalnizca ekranda gorunur
(`Yaw 12.3 der (enk 12.1, fark 0.2)`). Veriye guvenmeden once onu izlemek
icin. `get_current_angles()` ancak FAZ 6'da enkodere baglanir ve o faz
**opsiyoneldir**: FAZ 5'teki ileri besleme telafisi yeterliyse hic
gerekmeyebilir. Sistemde zaten ~185 ms olu zaman ve 2.2-3.2 Hz rezonans var;
enkoder gecikmesi eklenince kararlilik bozulabilir.

**Guncel durum (2026-09-02):** enkodere **henuz guc verilmedi**, montaj
yapilmadi. USB donusturucu takildi, `/dev/ttyUSB0` gorundu, `slcand` ile
`can0` arayuzu **olustu** (`UP`, `ERROR-ACTIVE`) — ama hatta **gercek CAN
trafigi henuz dogrulanmadi**. `bitrate 0` gorunmesi normaldir; slcan'de hizi
`slcand`'in `-s6` parametresi belirler, cekirdek bilmez. Sonraki adim:
**FAZ 0.1**.

## 26. Guncel durum ozeti (2026-09-02)

### Dallar

| dal | icerik | durum |
|---|---|---|
| `main` | — | geride |
| `motor-cs-d508-port` | onceki calisan surum | guvenli geri donus noktasi |
| **`servo-tetik`** | servo tetik + saha hizlari + enkoder plani | **aktif** |
| `enkoder-yaw` | enkoder isi burada yapilacak | **henuz acilmadi** |

### Testler

`tests_yeni_mimari.py` — **tum testler geciyor** (17 bolum). Enkoder icin
yeni bolum FAZ 7.1'de eklenecek.

### Acik konular

1. **Servo beslemesi** — Pi 5V pininden besleniyor, ayri besleme onerilir
   (bkz. 22.6). Tetik guvenilirligini dogrudan etkiler.
2. **Enkoder** — guc/montaj bekliyor, CAN trafigi dogrulanmadi (bkz. 25).
3. **`HUNTER_DPP_YAW` trimi** — enkoder devreye girerken geri alinmali.
4. **`denemePro.py`** — depoya alinmadi, karar bekliyor.
5. **`convert_to_engine.py` / `convert_to_onnx.py`** — model cozunurlugu
   608x1056 -> **736x1280** guncellendi (yeni `yeniDATA1280` modeli) ama
   dosyalarda **mutlak yerel yol** var; depoya alinmadan once yol
   parametrelestirilmeli.
6. Belgede **15. bolum yoktur** (numaralandirma atlamasi, icerik eksigi
   degil).

### Sahada yapilacak ilk uc is

1. Servoya ayri besleme cek, tetigi 20-30 atis boyunca dogrula.
2. Gorev kabiliyet gosterimi videosunu cek
   (`VIDEO_KONUSMA_METNI.md` kontrol listesiyle).
3. Enkoderi besle ve `ENKODER_ENTEGRASYON.md` FAZ 0 -> FAZ 1'i yurut.


## 27. Yaw enkoderi: FAZ 0'dan FAZ 5'e (2026-09-07 .. 2026-09-08, dal `enkoder-yaw`)

Tam sirali kontrol listesi ve olculen degerler `ENKODER_ENTEGRASYON.md`'de;
burasi ozet ve karar kaydidir.

### 27.1 Donanim ve okuma yolu (FAZ 0-2)

| | sonuc |
|---|---|
| enkoder | Wachendorff WDGA 36A CANopen, dugum 127, 12 V harici besleme |
| donusturucu | Waveshare USB-CAN-A. **slcan CALISMIYOR** (arayuz kurulur, tele hicbir sey cikmaz); **python-can seeedstudio da cikmadi**. Calisan tek yol cihazin **kendi seri protokolu** (`encoder_module.py`) |
| bit hizi | **250 k sabit** (500k'da hata; otomatik algilama yok). Kirmizi hizli titreme = "gecerli cerceve gormuyorum" |
| cozunurluk | fiziksel **14 bit** (0x6501 = 16384; siparis kodundaki "12" cikis olcegiymis). 0x6001/0x6002 = 16384, preset 8192 yazilip `save` edildi, guc kesintisini atlatti |
| PDO | TPDO1 (her degisimde) kapatildi, hatti boguyordu. Konum SYNC-tetiklemeli TPDO2'den, 100 Hz |
| oran | kasnak ~1:2 (1:3 sanilmisti). **R = 2.0** -> 91.0 sayim/derece, 0.011 derece/sayim |
| yon | yaw + komutunda sayim artiyor (`ENCODER_INVERT = False`) |
| sarma | bir enkoder turu = 180 derece taret; taret +-90'da ham 0<->16383 sarar, kod cozer. Sunucu taret +-90 icindeyken baslamali |

Yasanan tuzaklar: eski `slcand` sureci portu tutuyordu (`write: I/O error`);
otomatik bit hizi icin bizim cerceve gondermemiz gerektigi sanildi, aslinda
hiz sabitti; multimetre 100 us'lik CAN darbelerini goremez (adaptor
testi icin anlamsiz).

### 27.2 Mekanik olcum (FAZ 4) — asil bulgu

`config.ENCODER_LOG` ile adim sayaci ve enkoder yan yana kaydedildi;
`enkoder_analiz.py` duruslari bulup `enk = a x sayac + b_yon` modelini cozdu
(0 -> +60 -> -62, 10'ar derece, 20 durus):

| | deger | anlami |
|---|---|---|
| **olcek a** | **0.997** | R = 2 dogru; olcek sorunu yok |
| **bosluk** | **1.49 derece** | yon degisiminde taret komutu gec izliyor |
| **kacirma** | **0.46 derece RMS, max 1.0** | rastgele; olculup telafi EDILEMEZ |
| sabit kayma | +1.2 derece | sifirlamadan sonraki ilk hareketle geliyor, kalici |

Adim sayaci kosu boyunca gercegi **0.7-3.6 derece** yanlis biliyordu. Elle
sallama testinde 105 sayim (4.8 derece) serbest oynama goruldu ama 5
derecelik motor adimlarinda yon donusu kisa gelmedi -> o oynama motor->taret
dislisinde degil; yeri bulunamadi (kapali govde). Kutup atlatma testi
(taret elle 50-60 derece zorlandi) motor 1:3 oranini ve 21.8 sayim/dereceyi
bagimsiz dogruladi; ayrica gosterdi ki elle zorlanan taret adim sayacinin
gercegi kaybetmesine yol acar.

### 27.3 Karar: "olc, ileri besle" yerine "durunca hizala" (FAZ 5')

Rastgele 0.46 derecelik kisim ileri beslemeyle duzelmez; sadece gercek
aciya kapanan bir dongu duzeltir. "Direkt enkoderden oku" ise zamanlama
yuzunden reddedildi: servo 0.4-1.5 ms'de bir adim atiyor, enkoder 10 ms'de
bir ornek veriyor; 47 derece/sn'de 0.5 derece bayat okuma = salinim. Ve 1.5
derecelik boslukta hedef etrafinda kapali dongu geri donus limit cevrimi
uretir.

Uygulanan (`motor_fire_module.enkoder_hizala`, sunucudan 50 Hz):

1. taret **duruyorken** (0.15 sn adim yok; servo/manuel/bloklayan hareket
   yok) adim sayaci := enkoder. Fark < 0.05: dokunma. Fark > 10: supheli,
   uygulanmaz, uyari.
2. o an gecerli bir **otonom** hedef varsa ve kalan > 0.10 derece: servo
   tekrar acilir, kucuk duzeltme hareketi; hedef basina en fazla 3.
3. manuel surus / reset / stop hedefi gecersiz kilar: yalnizca sayac duzelir.
4. hareket SIRASINDA hicbir sey degismez. Takipte taret nadiren durdugu icin
   **takip davranisi aynidir**.
5. `ENCODER_REST_SNAP = False` -> FAZ 3 (yalnizca goster).

### 27.4 Etkileri

| durum | onceki | simdiki |
|---|---|---|
| gozcuden hedefe yonelme | 1.5-3 derece eksik/fazla varir, PID toparlar | 0.1 derece icinde varir; +0.2-0.4 sn (bekleme + kucuk hareket), PID'nin isi azalir |
| kara liste / atessiz bolge / ana konum | 3 dereceye kadar kayik acilarla | gercek aci |
| gorsel kilit (PID) | piksel | piksel, degismedi |
| kilitte yon degisimindeki 1.5 derece olu bolge | PID icinde saliniyor | **DEGISMEDI** — FAZ 6 |
| enkoder yok / dustu | — | hicbir sey olmaz, `enk: YOK`, adim sayaciyla devam |

`HUNTER_DPP_YAW = 0.01430` trimi bu fazda geri alinmadi. **Bu karar 27.8'de
duzeltildi:** trim tek atimlik komutlarda (tiklama, gozcuden yonelme) artik
%5 fazlalik uretiyor; uzakta yeniden olculup pitch olcegine cekilecek.

### 27.5 Sahada dogrulama (yapilacak)

- ekrandaki delta taret her durdugunda 0.00'a cekilmeli
- otonom yonelmede varistan sonra ufak "ikinci hareket" gorulmeli
- kayit acik kalsin; `enkoder_analiz` ile bosluk/kacirma artiginin sifira
  indigi gorulsun
- kabloyu cek: `enk: YOK` + uyari, sistem bozulmadan devam; tak: geri gelsin

### 27.6 Sonrasi (FAZ 6, yalnizca kilitteki salinim rahatsiz ediyorsa)

Hareket halinde, son yaklasimda (kalan < 2-3 derece) enkodere kapali dongu.
Sart: hedefe hep ayni yonden yaklas, asinca geri donme (boslukta geri donus
limit cevrimi). Once `HUNTER_DPP_YAW` pitch olcegine geri alinacak (cifte
duzeltme). Girdi olarak FAZ 5' kayitlari kullanilacak: delta artik her
durusta, yon yon, konum konum olculuyor.

### 27.7 Dosyalar

`encoder_module.py` (yeni), `enkoder_analiz.py` (yeni), `motor_fire_module.py`
(ENCODER_* sabitleri, `enkoder_hizala`), `rpi_motor_server.py`,
`rpi_communicator.py`, `bukrek_main.py` (panelde `enk +12.10 (delta -0.20)`,
CSV kaydi), `config.py` (`ENCODER_LOG`), testler 18-19. bolum (47 kontrol).
Gecici Pi betikleri (`~/enk_ham.py`, `~/enk_sdo.py`, `~/enk_olc.py`,
`~/enk_seg.py`, `~/enk_ayar.py`) depoda degil; islevleri `encoder_module`'e
tasindi.

### 27.8 Saha dogrulamasi: tiklayarak nisan videosu (2026-09-08, `enkoderManuelDeneme.mp4`)

23 saniyelik ekran kaydi kare kare cozumlendi (bilgi satirindaki Yaw/enk
0.5 sn'de bir okundu; her tiklamada tiklanan noktanin sablonu alinip hareket
sonrasi karede nereye dustugu olculdu). Hedef ~50 cm'deki priz.

**Hizalama calisiyor.** 10 tiklamanin 8'inde taret komut edilen aciya
0.05 derece icinde oturdu; "ikinci hareket" videoda net (delta once +0.2..0.4,
yarim saniye sonra 0.00). Iki tiklamada (0.29 ve 0.16 derece kalinti)
0.2-0.3 derecelik duzeltme hareketi (6-8 motor adimi) tareti hic oynatmadi:
surtunme, motor disliyi gerdi ama taret kopmadi (FAZ 4'teki "1 derece
adimlarin %40-80'i geciyor" bulgusuyla ayni). Uc denemeden sonra pes edildi.

**Ama nisangah tiklanan delige oturmuyor — sebep enkoder DEGIL, mesafe.**
Sekiz tiklamada, iki yonde de, goruntu tiklanan mesafenin **1.21-1.33 kati**
kaydi (ort. 1.29): nisangah deligi gecip 60-90 px otede duruyor. Sistematik.
Taret istenen aciya gitti (enkoder dogruluyor), yani istenen acinin kendisi
%30 fazla. Iki bilesen:

- **Paralaks (~%23):** kamera donus ekseninin ~10 cm disinda. Taret donerken
  kamera yana da kayiyor; 50 cm'deki hedefte bu ek goruntu kaymasi acinin
  dortte biri. 15 m'de ayni etki %0.7, yok sayilir. Piksel->derece donusumu
  uzak hedef icin dogru; 50 cm'de yanlis olmasi normal. **Bu test yakin
  mesafede yapilamaz.**
- **`HUNTER_DPP_YAW` trimi (%5):** deger bosluk telafisi icin kasten pitch'ten
  %5 buyuk tutuluyordu. Hizalama komut edilen aciya gercekten vardirdigi icin
  bu %5 tek atimlik komutlarda fazlalik oldu. 27.4'teki "FAZ 6'ya kalsin"
  karari yanlisti; uzakta `Derece/Piksel Olc` ile yeniden olculup (hizalama
  sayesinde artik GERCEK derece/piksel cikar, pitch'in 0.0136'sina yakin
  beklenir) config'e yazilacak.

Kod degisikligi yapilmadi. Sonraki adimlar bu belgede degil, is listesinde
(kullanici istegi).

## 28. Dataset ve egitim: v16 analizi ve kararlar (2026-09-03 .. 09-08)

Tam analiz `DATASET_ANALIZ.md`'de; burasi karar kaydi.

**Analiz edilen:** Roboflow HSS v16 (12 890 goruntu), `yy2.py`, mevcut
`.pt`/`.onnx` modellerin egitim argumanlari, `ultralytics 8.4.123` kaynak kodu.

**Dogrulanan bulgular:**
- `rect=True`, ultralytics'te mosaic/mixup'i ve DataLoader shuffle'ini
  kapatiyor (`dataset.py:314`, `train.py:95`); `yeniDATA1280.pt` icindeki
  `train_args` bunu gosteriyor (`mosaic: 0.0`). `copy_paste` kutu etiketiyle,
  `erasing` detect gorevinde etkisiz. Betikteki yorumlar RoboBoat projesinden
  kopya.
- Balon kutu genisligi medyan 32 px / p10 21 px (1920'de). 1056 giriste
  11.5 px'e iniyor (stride-8 siniri); 1280 ile deploy uyumu saglandi.
- `data.yaml` 7 sinif (`dusman-Helikopter` eklendi); `config.CLASSES` 6.
  **Yeni model deploy edilmeden `CLASSES`'a 7. sinif eklenmeli**, yoksa
  dusman helikopter `Unknown` olarak sessizce duser.
- ONNX cikisi `[1, 4+nc, N]` (YOLO26'nin ucta-uca basi export'ta kullanilmiyor);
  `_postprocess` ile uyumlu, 7 sinifta `[1, 11, N]` olur, kod `4:` dilimlediginden
  kendiliginden uyar.
- Yaprak/bitki fotograflarindan olusan arka plan seti sahayla ilgisiz;
  negatifler avci kamerasindan gelmeli.

**Kullanicinin kararlari (uygulandi):**
- `rect=True` **korunuyor** (16:9 tercih, mosaic'siz). Bilinen bedeli: mosaic
  ve shuffle kapali, `mosaic`/`close_mosaic` satirlari etkisiz.
- Split videoya gore kullanici tarafindan yapilmis; ayni dosya adli kareler
  farkli arka planli (`masked-bg`) versiyonlar. Analizdeki "birebir ayni
  dosya" ifadesi dosya adina bakilarak yazilmisti, **yanlisti**.
- Roboflow x2 (x3 yerine), test seti train'e katildi: train 5 831 / valid
  2 620 kaynak kare. Valid yuzdesinin x2 sonrasi kucuk gorunmesi kozmetik.
- `imgsz=1280`; egitim baska PC'de (24 GB), 63. epoch'ta mAP50 0.98 /
  mAP50-95 0.771, plato; kosinus kuyrugundan +1-3 puan bekleniyor.
- Bekleyen: Roboflow'da `Resize 1280x720 Stretch` ve motion blur 10 -> 5 px
  (yeni versiyonda), `hsv_s/v` acilmasi, `degrees=0`, `cache='ram'`
  KULLANILMAYACAK (12k kare 1280'de ~33 GB RAM, PC kapandi).

## 29. Asama 3 hareketli hedef kosumu: `aşama3Denem.mp4` cozumlemesi (2026-09-16)

**Duzenek:** IR-cut lens takildi (perde artik siyah; `HUNTER_MAGENTA_KIR`,
`HUNTER_KIRMIZI_ESIK`/`GUC` kullanici tarafindan `None` yapildi, bu bolumle
commit'lendi). Model v23 (7 sinif). Enkoder FAZ 5' (durunca hizala) acik.
Hedef: rayli arabada `dusman-Fuze` maketi + kirmizi balon, 15 m'den 9 m'ye
yaklasiyor, direk sallaniyor (maket egimi kareden kareye +-35 derece).
Iki kosum: t=3.0-22.0 (araba geri donunce manuel) ve t=33.0-51.5.

**Yontem:** 54.8 sn'lik kayit 2 fps'de 110 kareye bolundu, her karede avci
gorunumu + gozcu + baslik satiri (sayac yaw/pitch, enk, kare sayaci) + durum
satirlari okundu. `enkoder_kayit/enkoder_20260916_142911.csv` (21 ms, 7450
satir) videoyla hizalandi (sayacin 1.3'ten ayrildigi an = video 3.2 s).
Bulgular bu iki kaynagin ustuste bindirilmesinden cikiyor.

### 29.1 Zaman cizelgesi (ozet)

| video t | durum satiri | sayac yaw | enk | ne oldu |
|---|---|---|---|---|
| 0-2.5 | Hazir | +1.3 | +1.33 | maket 15 m'de, avci kutu cizmiyor (Asama 3 basilmadi) |
| 3.0 | DOGRULAMA 0.2/1.0 sn, hata yaw -367 px | +0.8 | +1.33 | Asama 3 basildi; avci ciftini goruyor (Fuze 0.52), dogrudan dogrulamaya girdi |
| 3.2-3.9 | DOGRULAMA 0.8/1.0 | +1.3 -> **-8.4** | -6.9 | hedef dunya acisi ~-3.9; taret 0.65 sn'de 9.7 derece dondu, **4.5 derece asti**, kare bulanik |
| 4.0 | TARAMA, gozcude aday yok (0 iz) | -6.9 | -5.6 | dogrulama 1 sn'de 4 tutarli kare toplayamadi -> `dogrulanamadi`, aci **5 sn kara listede** |
| 4.5-8.5 | TARAMA, 1 cift, imha 0 | -7.0 | -6.93 | avci Fuze 0.77-0.86 / balon 0.71-0.76 goruyor, **5 saniye hicbir sey yapilmadi** (kara liste) |
| 9.0-9.5 | DOGRULAMA 0.0 -> 0.6/1.0 | -7.0 -> -6.4 | | kara liste doldu, yeniden dogrulama |
| 10.0 | Hedef kaybedildi, tahmin (2 kare kaldi) | -4.1 | -5.26 | tespit dustu; 0.5 sn'de +2.3 derece hareket |
| 10.5 | KILIT, BALON YOK, nisan bekliyor | -5.3 | | ilk kilit (Asama 3 basildiktan 7.5 sn sonra) |
| **11.0** | KILIT, balon VAR, **nisan TAMAM** (yaw 8 px, pitch 0) | -5.6 | -6.14 | atese en yakin an; bir sonraki karede hata 42 px, tutulamadi |
| 12.0-13.0 | Hedef kaybedildi (4 -> 0 kare) | -3.4 / -5.1 / -6.4 | | nisangah balonun ustunde ama YOLO kutu vermiyor; taret +-1.5 derece geziyor |
| 13.5-14.5 | KILIT nisan bekliyor (124 px, -34 px) -> kayip | -6.1 / -5.1 / -6.9 | | salinim |
| 15.0 | TARAMA, hedef bu karede yok (0 kayit) | -7.5 | -7.42 | kilit tamamen dustu; kayip -> tahmin -> "yeni hedef araniyor" |
| **16.0** | KILIT, **nisan TAMAM** (-17 px, 4 px) | -7.5 | -7.42 | ikinci ve son "nisan TAMAM"; sonraki kare kayip |
| 18.0 -> 18.5 | KILIT (86 px) -> kayip | -6.8 -> **-3.0** | -7.20 -> -4.22 | 1.2 derecelik hata icin **+3.8 derece** komut |
| 19.0-20.0 | KILIT, hedef bu karede yok; "yeni hedef araniyor" | -3.9 | -3.93 | taret duruyor, hedef karede 2 derece solda, YOLO kutu yok (direk egik) |
| 20.5-21.5 | Aday dogrulaniyor 1/3 -> KILIT (-116 px pitch) -> kayip | -3.9 -> -8.2 -> -9.6 | | yine asim; t=21.0 karesi hareket bulanikligi |
| 22.0-24.5 | Hazir / Tam manuel | | | kullanici mudahalesi, araba geri aliniyor |
| 33.0 | Aday dogrulaniyor 1/3, TARAMA 2 cift | +0.6 | +0.63 | ikinci kosum; **arabanin sasesine `dusman-Drone 0.67` sahte kutu** |
| 33.5 -> 34.0 | KILIT (-79 px) -> kayip | +0.6 -> -4.4 -> **-7.9** | -6.1 | hedef ~-2.1; **5.8 derece asim**, kare bulanik |
| 34.5-40.0 | KILIT / kayip donusumlu | -5.7 ... -2.4 ... -5.8 | | fark sayac-enk **-1.1..-1.8 derece 4 sn boyunca** (dinlenme yok, hizalama yok) |
| 37.5 | KILIT (61 px) | -6.5 -> **-5.3** (hizalama) -> -3.6 | -5.10 | ilk dinlenme; sayac +1.25 sicradi, ardindan +2.3 derece komut |
| 40.0-50.0 | KILIT / kayip / yeniden edinme (3 dongu) | -5.8 ... -1.5 | | nisan TAMAM hic yok; hata 1..124 px arasinda geziyor |
| 49.0-49.5 | kayip (62 px) -> KILIT (-114 px) | -5.2 -> **-1.5** | -6.88 -> -3.38 | 0.9 derece hata icin +3.7 derece |
| 50.0-51.0 | TARAMA (1 iz) -> DOGRULAMA 0.6/1.0 | -3.4 -> -5.0 | | |
| 51.5 | Hazir, pitch 5.2 | -7.1 -> -8.4 | | kullanici durdurdu (kare bulanik: pitch 3 derece/kare) |

### 29.2 Sayilar

| olcum | deger | not |
|---|---|---|
| avci kare hizi | **15.0 fps** (kare 850 -> 1666 / 54.5 sn) | config 30 bekliyor; ekran kaydi da PC'yi yukluyor |
| KILIT/kayip donemlerinde YOLO'nun kutu VERMEDIGI ornek kare | kosum 1: 15/27 (%56), kosum 2: 14/35 (%40) | hedef karede, 40-60 px, cogu egik direk (>= 25 derece) veya bulanik kare |
| "nisan TAMAM" goruldugu ornek kare | 2 (t=11.0, 16.0) | ikisinde de bir sonraki karede kayip; `AIM_HOLD_FRAMES=3` hic dolmadi |
| ates | 0 | |
| ilk KILIT'e kadar gecen sure | 7.5 sn (kosum 1), 0.5 sn (kosum 2) | fark: kosum 1'de dogrulama basarisiz -> 5 sn kara liste |
| edinme asimi (ilk buyuk hareket) | +4.5 derece (kosum 1), +5.8 derece (kosum 2) | hedef 2-4 derece uzaktayken taret 8-10 derece dondu |
| yaw yon degisimi (CSV) | **70** / 55 sn | takipte kabaca her 0.5 sn'de bir; genlik +-1..2 derece |
| tepe yaw hizi (enkoder) | 395 derece/sn | 10 ms pozlamada 4 derece = 280 px bulaniklik |
| sayac - enkoder farki, hareket halinde | -1.1..-1.8 (sola gidince), +0.5..+1.0 (saga gidince) | bosluk 1.49 (27.2) + rapor gecikmesi ~80 ms |
| KILIT'te 150 ms'den uzun durus | 11/245 ve 8/369 komut araligi | FAZ 5' hizalama takip sirasinda **neredeyse hic** devreye girmiyor |
| hedefin gercek acisal hizi | <= 0.5 derece/sn (dunya yaw 12 sn'de ~3 derece) | feedforward olu bandi 1 derece/sn, tam acilma 2 |

### 29.3 Bulgular (etki sirasina gore)

**B1 - Tespit surekliligi: kilit dususlerinin dogrudan sebebi.** Kilit
dongusunun her kirilmasi ("Hedef kaybedildi" -> 5 kare tahmin -> "Takip
Kayboldu" -> "Aday dogrulaniyor 1/3" -> KILIT) YOLO'nun karede acikca
duran 40-60 px'lik maketi vermemesiyle basliyor. Kutusuz karelerin ortak
ozelligi: direk 25-45 derece egik (maket capraz veya "+" gorunumde) ya da
taret donerken cekilmis bulanik kare. Dik direkli, net karelerde guven
0.74-0.86. Egitimde `degrees=5`; sahada direk +-35 derece salliyor.
Kullanicinin "dataset ile ilgili" tespiti dogru, ama bulanikligin payi da
var (t=21.0, 33.5, 51.5 kareleri). Her kayip dongusu 0.5-1 sn'ye ve
`reset_pid_state` ile filtre/hiz hafizasinin sifirlanmasina mal oluyor.

**B2 - Cikis suzgeci artimli komutta asim uretiyor (kod).**
`process_tracking` her karede DELTA komutu gonderiyor
(`set_proportional_angles_delta`: hedef = mevcut + delta).
`PID_OUTPUT_SMOOTHING = 0.30` bu deltalar uzerinde birinci derece IIR:
`y = 0.3 u + 0.7 y_onceki`. Konum komutunda DC kazanci 1 olan bir suzgec
zararsizdir; ARTIMLI komutta ise suzgecin hafizasi, hata sifirlandiktan
sonra da `0.7^k x son_cikis` buyuklugunde deltalar gondermeye devam eder
(toplam 2.33 x son cikis). Olu bant da bunu kesmiyor: olu bantta `u=0`
yapiliyor ama suzgec `0.7 y_onceki`yi yine gonderiyor (yalnizca 0.056
derecenin altinda kesiliyor). Simulasyon (15 fps, 2 kare gecikme, tam olu
zaman telafisi, KP 0.7): 2.7 derecelik adimda suzgecsiz asim 0, oturma
0.13 sn; suzgecle asim +0.85 derece, oturma 1.0 sn; 1.2 derecelik adimda
+0.38 derece. Sahadaki asimlar (4.5 / 5.8 / 3.8 / 3.7) bundan buyuk; kalan
kisim B3 ve B4'ten. Suzgec 2.7 Hz rezonans icin konmustu (bkz.
`process_tracking` yorumu); o gerekce durusta gecerli, edinme ve duzeltme
hareketlerinde bedeli asim.

**B3 - Feedforward bu hedefte yalnizca gurultu tasiyor.** Hedefin gercek
acisal hizi <= 0.5 derece/sn; olu bant 1, tam acilma 2 derece/sn.
`_angle_at` yorumunda sahada olculmus rakam var: hedef GERCEKTEN sabitken
sistemin hesapladigi sahte hiz 8.1-14.4 derece/sn. Bu hiz 0.22 x 0.8 =
0.176 sn ile carpilip HER KAREDE delta olarak ekleniyor: 14 derece/sn ->
2.5 derece/kare (sinir 5). Hata kapisi 112 px altinda tam acik, yani tam
KILIT'te. Yon degisimi sayisi (70) ve "1.2 derecelik hata icin 3.8 derece"
olculeri bununla tutarli. `FEEDFORWARD_GAIN=0` ile kapatilip olculmeli;
bu hedef profili icin kazanci yok.

**B4 - Edinme yalpalamasi dogrulamayi bozuyor, kara liste 5 sn yiyor.**
Avci hedefi gorunce `avcida_hazir_hedef_var` dogrudan DOGRULAMA'ya
geciyor ve ayni anda PID delta komutlariyla 9 derece donuyor (tepe 395
derece/sn). Dogrulama 1.0 sn icinde 4 tutarli, >= 0.55 guvenli kare
istiyor; donus sirasinda kareler bulanik, ilk kare 0.52 idi -> zaman
asimi -> `dogrulanamadi` -> `BLACKLIST_VERIFY_TTL_SEC = 5.0`. Bu 5 sn
boyunca avci hedefi 0.86 ile gorurken `tarama_adimi` (kara liste
kontrolu avci ciftine de uygulaniyor) hicbir sey yapmiyor; gozcu 15 m'de
iz uretemiyor (0 iz). 15 m -> 9 m yaklasmasi ~20 sn suruyorsa 5 sn
pencerenin dortte biri. Dogru davranis: ilk buyuk hareketi TEK mutlak aci
komutu olarak vermek (gozcu adaylari icin zaten YONELME yolu bu), taret
oturunca (enkoder hizalamasi da burada dogal olarak devreye girer)
dogrulamaya baslamak; ve avcinin su an cift gordugu aciyi kara listeye
almamak.

**B5 - Bosluk 1.5 derece: enkoder hizalamasi KILIT'te calismiyor; calisinca
tek sekme yapiyor. Kullanicinin sorusu ("enkoderle son adimi attirmanin
alakasi var mi") - dogrudan yok, dolayli var:**
- Takip sirasinda taret 150 ms hic durmuyor (11/245 ve 8/369 aralik), FAZ
  5' hizalamasi devreye girmiyor. Sayac ile enkoder arasindaki 1.1-1.8
  derecelik fark 4 saniye boyunca kaliyor (t=33-37.5). Bu fark sabitken
  P terimini bozmaz (dunya acisi da mevcut aci da sayaca gore); yon
  degisiminde bozar: taret 1.5 derece boyunca fiziksel olarak durur,
  kamera ayni hatayi gormeye devam eder, dongu komut biriktirir, bosluk
  bitince biriken hareket bir anda gelir. 70 yon degisiminin her biri bu
  bedeli oduyor.
- t=37.53'te ilk dinlenme: sayac -6.54 -> -5.29 (+1.25) hizalandi. PC
  tarafinda mevcut aci aniden 1.25 derece degisince, onceki karelerden
  hesaplanan dunya acisiyla hata 1.25 derece sicradi ve taret +2.3 derece
  gitti (video: t=37.5 61 px -> t=38.0 -47 px). Yani hizalama dogru bilgiyi
  getiriyor ama PC'nin dunya acisi tahmini eski sayaca gore oldugundan
  bir sekme uretiyor. Kosum boyunca 2-3 kez oldu; salinimin ana kaynagi
  degil, ama duzeltilmeli: hizalama aninda PC `_last_world_yaw` ve
  `_son_gorulen_dunya_yaw`'i ayni farkla kaydirmali (veya hizalama
  yalnizca hedef yokken yapilmali).
- Asil cozum FAZ 5'': Pi'de yon degisiminde bosluk kadar adimi
  SAYMADAN atmak (klasik bosluk telafisi). Bosluk miktari enkoderle
  kalibre edilir (27.2: 1.49; bu CSV'de yone gore -1.4 / +1.0 goruluyor,
  rapor gecikmesi karisik). Telafi dogruysa CSV'de her yon degisiminden
  sonra durusta fark < 0.2 kalmali.

**B6 - Nisan toleransi fiziksel isabet payindan cok dar.** Tolerans
`max(9 px, 0.35 x balon yaricapi)`; balon 9-15 m'de 30-40 px -> 9-10 px =
0.13 derece = 10 m'de 2.2 cm. Balon yaricapi ~7.5 cm = 10 m'de 0.43 derece
= 30 px. Uzerine `AIM_HOLD_FRAMES=3` (15 fps'de 0.2 sn) ve sallanan direk.
Sahada hata 1-42 px arasinda geziyor, 3 ardisik kare <= 9 px hic olmadi.
Tolerans 0.6 x yaricap (~20 px, 0.28 derece, 10 m'de 5 cm - balonun
icinde) ve 2 kare makul; ates dagilimi olculmedigi icin ust sinir bu.

**B7 - Kayip yonetimi tareti bosuna gezdiriyor.** "Hedef kaybedildi,
tahminle takip" sirasinda taret hareket ediyor (t=10.0 +2.3, t=18.5 +3.8,
t=34.0 -3.5 derece). Hedefin gercek hizi <= 0.5 derece/sn olduguna gore
`PREDICTION_MAX_RATE_DEG_S = 2.5` ile 5 kare (0.33 sn) tahmin en fazla
0.8 derece olmali; olculen hareketler bunun 3-4 kati, yani kayip aninda
gonderilen komutlar tahminden degil B2/B3'ten geliyor. Kayipta en guvenli
davranis: hizi 1 derece/sn ile sinirlamak ve `MAX_MISSING_FRAMES`i 15
fps'ye gore 8'e cikarmak (0.5 sn) ki her kisa YOLO boslugu "Takip
Kayboldu + yeniden edinme (3 kare) + PID sifirlama" dongusune donusmesin.

**B8 - Gozcu bu mesafede katki vermiyor, sahte tespit riski var.** 15 m'de
gozcu 0-2 iz, edinme iki kosumda da avcidan geldi. t=33.0'da arabanin
sasesine `dusman-Drone 0.67` kutusu cikti (kilit oncesi, zarar vermedi ama
ray/araba negatifleri datasete girmeli).

**B9 - Pitch kucuk sorun.** Ilk yalpalamada pitch -3.2'ye dustu (t=3.5),
sonra 0.5 civarinda kaldi; pitch hatasi cogunlukla < 25 px. t=21.0'daki
-116 px yeni edinmenin ilk karesi. Once yaw duzelmeli.

### 29.4 Plan - paketler halinde, her paket tek kosumla olculur

Olcut her paket icin ayni: `enkoder_kayit` CSV'de yaw yon degisimi sayisi
(simdi 70/55 sn), edinme asimi (simdi 4.5-5.8 derece), ekran kaydinda
"nisan TAMAM" kare sayisi ve ates.

**Paket 1 - yalnizca `config.py`, kod yok (once bu):**
- `FEEDFORWARD_GAIN = 0.0` (B3). Hedef 0.5 derece/sn; ff'nin telafi edecegi
  gecikme yolu 0.1 derece, gurultusu 2.5 derece.
- `PID_OUTPUT_SMOOTHING = 0.0` ve `MAX_OUTPUT_DEGREE` 15 -> 2.0 (B2).
  Suzgecin isi olan rezonans sonumu icin komut basina 2 derece siniri
  hiz sinirlamasi gorevi gorur; rezonans geri gelirse suzgec yerine olu
  bantta hafizayi sifirlayan tek satir (`_pid_cikis_yaw = 0`) denenir.
- `BLACKLIST_VERIFY_TTL_SEC` 5.0 -> 1.5 (B4).
- `VERIFY_MIN_CONFIDENCE` 0.55 -> 0.45, `CONF_THRESHOLD` 0.4 -> 0.3 (B1;
  egik maket 0.42-0.56 veriyor).
- `MAX_MISSING_FRAMES` 5 -> 8, `PREDICTION_MAX_RATE_DEG_S` 2.5 -> 1.0 (B7).
- `AIM_TOLERANCE_RATIO` 0.35 -> 0.6, `AIM_TOLERANCE_MIN_PIXELS` 9 -> 14,
  `AIM_HOLD_FRAMES` 3 -> 2 (B6).
- Kamera: pozlama 10 ms -> 3-4 ms (kazanc artirilarak), konsoldaki
  "gerceklesen format ve fps" satiri kontrol edilip 15 fps'nin sebebi
  bulunmali (1920x1200 YUY2 mi, ekran kaydi mi).

**Paket 2 - kod (Paket 1 olculdukten sonra):**
- Avci-kaynakli edinmede tek mutlak aci komutu + oturma bekleme, sonra
  DOGRULAMA (B4). Mevcut YONELME yolu avci cifti icin de kullanilir;
  `ENGAGE_SLEW_TOLERANCE_DEG` 1.0 zaten var.
- Avcinin bu karede cift gordugu aciyi `dogrulanamadi` kara listesine
  almama (B4).
- Hizalama sicramasinin PC'de dunya acisi tahminine yansitilmasi (B5).

**Paket 3 - Pi, FAZ 5'' bosluk telafisi (B5).** Yon degisiminde
`BACKLASH_DEG` kadar adim sayilmadan atilir; deger enkoderle kalibre
edilir (ayni CSV: durustaki fark). Beklenen: yon degisimi basina 1.5
derecelik komut birikmesi kalkar.

**Paket 4 - dataset (B1, paralel yurur):** rotasyon +-35 derece
(direk salinimi), hareket bulanikligi, avci kamerasindan egik direkli
kareler, ray/araba/sase negatifleri. Bu kosumun karelerinden kutusuz
kalanlar dogrudan ornek.

Kod degisikligi yapilmadi; bu bolum ve lens config'i commit'lendi.

### 29.5 Paket 1 uygulandi (2026-09-16)

Yalnizca sabit degerler degisti; akis/mantik degismedi. On bir deger, dordu
tespit-surekliligi ve angajman tarafinda, yedisi kontrol tarafinda.

| # | Sabit | Once | Sonra | Dosya | Bulgu |
|---|---|---|---|---|---|
| 1 | `CONF_THRESHOLD` | 0.4 | **0.3** | config | B1 |
| 2 | `VERIFY_MIN_CONFIDENCE` | 0.55 | **0.45** | config | B4 |
| 3 | `BLACKLIST_VERIFY_TTL_SEC` | 5.0 | **1.5** | config | B4 |
| 4 | `MAX_MISSING_FRAMES` | 5 | **8** | config | B7 |
| 5 | `PREDICTION_MAX_RATE_DEG_S` | 2.5 | **1.0** | config | B7 |
| 6 | `FEEDFORWARD_GAIN` | 0.8 | **0.0** | config | B3 |
| 7 | `PID_OUTPUT_SMOOTHING` | 0.30 | **0.0** | config | B2 |
| 8 | `MAX_OUTPUT_DEGREE` | 15.0 | **2.0** | bukrek_main | B2 |
| 9 | `AIM_TOLERANCE_RATIO` | 0.35 | **0.6** | config | B6 |
| 10 | `AIM_TOLERANCE_MIN_PIXELS` | 9.0 | **14.0** | config | B6 |
| 11 | `AIM_HOLD_FRAMES` | 3 | **2** | config | B6 |

Her degerin gerekcesi ilgili satirin ustunde, kodun icinde yaziyor.
`MAX_OUTPUT_DEGREE` config'te degil `bukrek_main.py`'de tanimli oldugu icin
"yalnizca config" hedefi bir satirlik sabitle bozuldu; mantik degismedi.

**Testler:** `tests_yeni_mimari.py` TUM TESTLER GECTI. Tek bir test guncellendi:
16(c) "PID cikis suzgeci ETKIN" sartini kosuyordu; artimli komuttaki kuyruk
bulgusundan (B2) sonra bu sart tersine cevrildi — artik "hata bitince fazladan
yol gonderilmiyor" ((1-a)/a <= 0.5) kontrol ediliyor, suzgec yeniden acilirsa
kesim frekansi kontrolleri devrede kaliyor.

**Kapali dongu simulasyonu** (15 fps, 2 kare olu zaman, tam telafi, KP 0.7;
gercek tespit gurultusu YOK, yani yalnizca kontrol davranisini gosterir):

| hedef adimi | once (a=0.30, max 15, ff acik) | sonra (a=0, max 2, ff kapali) |
|---|---|---|
| 2.7 derece | asim +0.83, oturma 0.93 sn | asim -0.07, oturma **0.13 sn** |
| 1.2 derece | asim +0.35, oturma 0.53 sn | asim -0.03, oturma **0.07 sn** |
| 0.5 derece | asim +0.18, oturma 0.13 sn | asim -0.05, oturma **0.00 sn** |

Bosluk 1.5 derece eklendiginde asim yine olusmuyor ama oturma 0.27-0.40 sn'ye
cikiyor — bu kalan bedel Paket 3'un (FAZ 5'' bosluk telafisi) isi.

**Beklenti (bir sonraki kosumda olculecek):**

| olcut | 2026-09-16 kosumu | Paket 1 beklentisi |
|---|---|---|
| yaw yon degisimi | 70 / 55 sn | **< 25** |
| edinme asimi | +4.5 / +5.8 derece | **< 1.5 derece** |
| tepe yaw hizi | 395 derece/sn | **~30 derece/sn** (komut siniri) |
| "nisan TAMAM" ornek kare | 2 | **> 10** |
| ates | 0 | **>= 1** |
| ilk KILIT'e kadar | 7.5 sn (1. kosum) | **< 3 sn** |
| YOLO kutusuz kare orani | %40-56 | %30-45 (yalnizca esik etkisi) |

**Beklenmeyen ama olabilecekler — kosumda bunlara bakilacak:**
- **Yavas yonelme.** Komut basina 2 derece siniri, avci gorus acisinin
  kenarindaki (13.75 derece) bir hedefe donusu 0.47 saniyeye cikarir. Taret
  "agir" gorunurse sinir 3.0'a alinir; 4.0 uzerine cikmak asimi geri getirir.
- **2-3 Hz hizli titreme.** Suzgec kapatildi. Titreme geri gelirse cozum
  suzgeci geri acmak DEGIL (asim geri gelir), olu banda girildiginde suzgec
  hafizasini sifirlamaktir (Paket 2).
- **Yanlis pozitif artisi.** `CONF_THRESHOLD` 0.3 ile ray/araba/tavan
  hayaletleri cogalabilir (t=33.0'da 0.67 ile `dusman-Drone` cikmisti).
  Cift eslestirme + 3 karelik onay bunlari elemeli; elemiyorsa esik 0.35'e
  cekilir ve dataset negatifleri (Paket 4) beklenir.
- **Erken ates.** Tolerans genisledi (9 -> 14 px) ve onay 3 -> 2 kareye indi.
  Isabet olculmedigi icin bu yonun ust siniri budur; iska varsa once
  `AIM_HOLD_FRAMES` 3'e geri alinir, sonra tolerans 12'ye.

**Bu pakette KASTEN degistirilmeyenler:** `KP_YAW/KP_PITCH` (0.7/0.6),
`CAPTURE_LATENCY_OFFSET` (0.08), `PID_DEADBAND_PIXELS` (7.0),
`LOCK_CONFIRM_FRAMES` (3), `VERIFY_CONFIRM_FRAMES` (4). Ayni anda cok sey
degisirse hangisinin ise yaradigi olculemez; bunlar Paket 1 sonucuna gore
sirayla denenecek.

**Kamerada ELLE yapilacak (config'ten ayarlanamiyor):** pozlama 10 ms ->
3-4 ms, kazanc artirilarak. `KAMERA_KONTROLLERI['hunter']` icinde
`exposure`/`auto_exposure` `None` (surucu ne diyorsa o) ve config yorumunda
belirtildigi gibi DirectShow'un `CAP_PROP_EXPOSURE` davranisi guvenilmez —
deger korlemesine yazilmadi. `kamera_renk.py` ile ayarlanip ('e' otomatik
pozlamayi kapatir, '[' / ']' pozlamayi degistirir, 'g' / 'h' kazanc) aracin
"TUTMADI" uyarisi vermedigi deger config'e yazilmali. Ayrica kamera acilis
satirindaki gerceklesen fps okunmali: sahada 15 fps olculdu, config 30
bekliyor; sebep 1920x1200 sikistirmasiz akis ya da ekran kaydinin yuku olabilir.

### 29.6 Paket 1 sonrasi kosum: `aşama3Deneme2.mp4` (2026-09-16 15:25)

20.8 saniye, 3 fps'de 62 kare tek tek okundu; `enkoder_kayit/
enkoder_20260916_152053.csv` (21 ms) videoya hizalandi (taret video t=3.75'te
-1.89'dan ayriliyor). Ayni duzenek, ayni mesafe, tek kosum.

**SISTEM ILK KEZ ATES ETTI.** Asama 3'e basildiktan 4.0 saniye sonra,
nisan hatasi yaw -2 piksel / pitch -10 piksel iken (0.03 / 0.14 derece).
Onceki kosumda 55 saniyede hic ates edilememisti.

#### 29.6.1 Zaman cizelgesi

| video t | durum | sayac yaw | enk | not |
|---|---|---|---|---|
| 0.0-0.7 | Tam Manuel | -1.89 | -1.89 | Asama 3'e t=0.65'te basildi |
| 1.0-1.7 | DOGRULAMA — **0 cift** goruluyor (0.1 -> 0.8/1.0 sn) | -1.89 | -1.89 | girer girmez tespit dustu; **taret hic kimildamiyor** |
| 2.0-3.3 | TARAMA — gozcude aday yok (0 iz), 0-1 cift | -1.89 | -1.89 | dogrulama zaman asimi -> aci 1.5 sn kara listede; avci hedefi 0.77 ile goruyor |
| 3.7 | Aday hedef dogrulaniyor (1/3), 1 cift | -1.89 | -1.89 | kara liste doldu (1.5 sn) |
| 4.0 | **KILIT** — BALON YOK, hata -52 px | -4.5 | -4.13 | taret 0.3 sn'de 2.6 derece dondu |
| 4.3 | KILIT — BALON YOK, hata -30 px | -5.5 | -4.78 | tepe -5.49; hedef dunya acisi ~-5.2 -> **asim 0.3 derece** |
| **4.65** | **ATES — imha dogrulaniyor (1. atis)** | -5.3 | -4.41 | hata **-2 px / -10 px**; fark sayac-enk -0.86 |
| 5.0-5.7 | ATES — imha dogrulaniyor | -5.3..-3.8 | | balon HALA yerinde -> pencere 'tekrar' dedi |
| 6.0-9.3 | **Ates engellendi** (2/45 -> 43/45) | -4.3..-5.9 | | 3.5 saniye bosa bekleme; gerekce donusumlu "maket bu karede tespit edilmedi" / "nisan tolerans disinda" |
| 9.7 | Aday dogrulaniyor (1/3), TARAMA | -6.2 | -6.29 | 45/45 doldu -> `imha_edilemedi` -> kara liste |
| 10.3 | **KILIT — balon VAR, nisan TAMAM**, hata 24 px | -5.4 | -5.17 | ikinci nisan; sonraki karede tespit dustu |
| 10.7-11.0 | Hedef kaybedildi (6 -> 1 kare kaldi) | -4.3 | | |
| 11.3 | KILIT — hedef bu karede yok | -3.4 | -3.77 | maket **`dusman-Drone` 0.40** olarak etiketlendi (yanlis sinif) |
| 12.0 | KILIT — balon VAR, nisan bekliyor, hata -102 px | -4.2 | -3.53 | |
| 12.3 | Hedef kaybedildi | -5.3 | -4.46 | **karton kutu `dusman-Drone` 0.39** |
| 12.7-14.0 | Hedef kaybedildi (5,7,6,2,4,0 kare) | -6.6..-6.5 | | maket yine `dusman-Drone` 0.39 |
| 14.3-15.3 | Aday dogrulaniyor -> KILIT [kopru] -> BALON YOK | -6.5..-6.7 | | pitch hatasi -69 px ile +48 px arasinda sicradi |
| 15.7-16.7 | Hedef kaybedildi / KILIT hedef yok | -7.1..-6.9 | | t=16.3'te **karton kutu `dusman-Drone` 0.77** |
| **17.0-18.7** | KILIT — hedef bu karede yok / Aday dogrulaniyor (1/3) | **-6.99 sabit** | -6.99 | **taret tamamen duruyor**, hedef karede 1.5 derece solda; 3 ardisik kare hic toplanamadi |
| 19.0-20.3 | Hazir | -6.99 | -6.99 | kullanici Gorevi Durdur'a basti |

#### 29.6.2 Olcum karsilastirmasi

| olcut | ONCE (Denem) | SONRA (Deneme2) | yon |
|---|---|---|---|
| ates | 0 | **1** | iyi |
| ilk KILIT'e kadar | 7.5 sn | **3.3 sn** | iyi |
| edinme asimi | +4.5 / +5.8 derece | **+0.3 derece** | iyi |
| en buyuk tek komut (sayac adimi) | 1.25 derece | **0.75 derece** | iyi |
| \|sayac-enk\| en buyuk | 2.96 derece | **1.60 derece** | iyi |
| kara liste tikanmasi | 5.0 sn | **1.5 sn** | iyi |
| **titresim RMS** | 0.121 derece | **0.345 derece** | **kotu (2.9 kat)** |
| **titresim tepeden tepeye** | 0.51 derece | **1.44 derece** | **kotu** |
| **titresim frekansi (FFT tepe)** | 0.66 Hz | **3.45 Hz** | **kotu** |
| **nisan bandi (0.198 derece) disinda gecen zaman** | %9.4 | **%49.5** | **kotu** |
| yaw yon degisimi (55 sn'ye normalize) | 74.8 | **244.4** | kotu |
| p99 enkoder hizi | 24.3 derece/sn | 83.8 derece/sn | kotu |
| avci kare hizi | 15.0 fps | 15.0 fps | degismedi |

#### 29.6.3 Bulgular

**B10 — `PID_OUTPUT_SMOOTHING = 0` KARARI YANLISTI, GERI ALINDI.**
29.3 B2'deki kuyruk analizi matematiksel olarak dogru: artimli komutta suzgec
hafizasi hata bittikten sonra (1-a)/a = 2.33 kat fazladan yol gonderir. Ama
ONCELIK yanlis konmustu — suzgecin sonumleme degeri, kuyrugunun bedelinden
buyukmus. Suzgec kapatilinca 2.7 Hz yapisal rezonans 3.45 Hz'te geri geldi,
genligi iki bucuk katina cikti ve taret zamanin yarisini nisan bandinin
disinda gecirdi. Kullanicinin "gelisme yok gibi" izlenimi dogrudan bu:
gozle gorulen sey taretin surekli titremesi.

DOGRU COZUM IKISINI AYIRMAK, ve uygulandi: suzgec `0.30`'a geri alindi,
kuyruk ise `process_tracking` icinde OLU BANDA GIRILDIGINDE hafizanin da
sifirlanmasiyla kesildi (`_olu_yaw` / `_olu_pitch`). Boylece hedefe oturunca
artik komut kalmiyor (asim yok), takip sirasinda sonumleme calismaya devam
ediyor. `MAX_OUTPUT_DEGREE = 2.0` yerinde kaldi — asimi 5.8 dereceden 0.3
dereceye indiren asil degisiklik oydu, titremeyle ilgisi yok.

**B11 — ATES ISABET ETMEDI; ARTIK DARBOGAZ YAZILIM DEGIL MEKANIK.**
Ates aninda nisan hatasi -2 px / -10 px, yani 0.03 / 0.14 derece — 10
metrede 0.5 / 2.4 santim. Nisangah videoda gorunur sekilde balonun uzerinde.
Buna ragmen balon yerinde kaldi ve imha dogrulama penceresi 'tekrar' dedi.
Nisan alma tarafi ISINI YAPTI; sorun namlu ile kamera ekseni arasinda
(boresight) veya mermi dususunde (`BALLISTIC_PITCH_OFFSET = 0.0`).
Enkoderle ilgisi yok: fark -0.86 derece ama kamera taretin uzerinde, yani
kameranin gordugu nisan FIZIKSEL nisandir.
**Once su ayrilmali:** ates komutunda mermi gercekten cikti mi? Ciktiysa
duvara sabit mesafeden (9 ve 15 metre) nisangah isaretli bir noktadayken
5'er atis yapilip vurus merkezi olculmeli; yaw kaymasi boresight, pitch
kaymasi `BALLISTIC_PITCH_OFFSET` olarak config'e girer.

**B12 — Basarisiz atistan sonra 3.5 saniye tikanma.**
`FIRE_RETRY_GIVEUP_FRAMES = 45` yorumunda "~1.5 sn @30fps" yaziyordu; saha
15 fps oldugu icin 3 saniye demekti. Olculen tikanma t=6.0 -> t=9.5.
**22'ye indirildi** (1.5 sn @15fps).

**B13 — `CONF_THRESHOLD = 0.3` iki yeni sorun getirdi.**
- Karton kutu `dusman-Drone` olarak cikiyor: t=8.3'te 0.74, t=9.7'de 0.47,
  t=12.3'te 0.39, **t=16.3'te 0.77**. 0.77 esigi yukseltmekle elenmez;
  dataset negatifi gerekiyor (Paket 4). Su an zarar vermedi cunku cift
  kurulumu maketin ALTINDA balon ariyor, kutunun altinda balon yok.
- Maketin KENDISI `dusman-Drone` olarak etiketleniyor (t=11.3'te 0.40,
  t=12.7'de 0.39). Bu daha tehlikeli: `kilit_hedefi_sec` dogrulanan sinifla
  eslesmeyen maketi "yabanci maket" sayar ve ucuncu maddeden kilidi
  dusurur. Esigi geri yukseltmek bunu COZMEZ (dusuk guvenli dogru tespitleri
  de atar); cozum egik/bulanik ornekle egitim.

**B14 — Kilit onayi dusen her tespitte sifirlaniyor; kosumun sonunda sistem
donuyor.** t=17.0-18.7 arasinda taret tamamen duruyor (sayac ve enkoder
-6.99'da sabit, fark 0.00), hedef karede 1.5 derece solda ve YOLO onu
araliklarla 0.31-0.38 guvenle goruyor. Durum satiri "Aday hedef dogrulaniyor
(1/3)" ile "KILIT — hedef bu karede yok" arasinda gidip geliyor.
Sebep: otonom modda durum makinesi hedef vermedigi her karede
`_aday_ardisik = 0` yapiliyor, yani `LOCK_CONFIRM_FRAMES = 3` ARD ARDA
TESPIT gerektiriyor. Tespit surekliligi ~%50 iken bunun olasiligi %12.
Ustelik bu onay otonom yolda GEREKSIZ: durum makinesi zaten
`VERIFY_CONFIRM_FRAMES = 4` ardisik tutarli kare ile sinifi dogrulamis ve
hedefi ACIYLA takip ediyor. Hayalet korumasi orada zaten var.
**Paket 2'ye alindi** (otonom modda kilit onayini atla veya sifirlamak
yerine azalt).

**B15 — Bosluk artik en buyuk tek hata kaynagi.** Kapali dongu
simulasyonunda (sallanan hedef +-1 derece 0.7 Hz, olcum gurultusu 0.3
derece, 15 fps, 2 kare olu zaman) yalnizca boslugu kaldirmak nisan hatasi
RMS'ini **1.01'den 0.37 dereceye** dusuruyor ve nisan bandinda gecen zamani
%15'ten %33'e cikariyor — diger butun ayarlardan daha buyuk bir etki.
Sebep: olu zaman telafisi ADIM SAYACIYLA yapiliyor, kamera ise FIZIKSEL
aciyi goruyor; bosluk iki tarafta ayni olmadigi icin telafide iptal olmuyor
ve her yon degisiminde 1.5 dereceye kadar sahte hata giriyor.
**En temiz cozum FAZ 6'ya yaklasiyor:** enkoder saglikliyken PC'nin kontrol
dongusu `current_yaw_angle` olarak ADIM SAYACINI degil ENKODERI kullansin.
O zaman hata hesabi kameranin gordugu ile ayni cerceveye oturur ve bosluk
kontrol yolundan tamamen cikar. Pi tarafinda bosluk telafisi (FAZ 5'')
alternatif ama daha dolayli.

#### 29.6.4 Bu commit'te yapilanlar

| Sabit / kod | Once | Sonra | Bulgu |
|---|---|---|---|
| `PID_OUTPUT_SMOOTHING` | 0.0 | **0.30** (geri) | B10 |
| `process_tracking` olu bant | — | **suzgec hafizasi sifirlaniyor** | B10 |
| `FIRE_RETRY_GIVEUP_FRAMES` | 45 | **22** | B12 |

Paket 1'in geri kalani (MAX_OUTPUT 2.0, tolerans 14 px, AIM_HOLD 2,
CONF 0.3, VERIFY_MIN_CONF 0.45, kara liste 1.5 sn, MAX_MISSING 8,
PREDICTION 1.0) **oldugu gibi duruyor**; hepsi ya ise yaradi ya notr.

#### 29.6.5 Sirasi gelen isler

1. **Mekanik atis kalibrasyonu (B11) — artik en onemlisi.** Sabit mesafeden
   atis testi; boresight ve `BALLISTIC_PITCH_OFFSET`. Bu cozulmeden nisan
   iyilestirmelerinin sahada karsiligi olmaz.
2. **Bir kosum daha** (kod degismeden): titresimin 0.12 dereceye dondugu ve
   edinme asiminin 0.3 derecede kaldigi dogrulanmali. Olcum araci
   `kosum_olc.py` (kayit dosyasi verilmezse en yenisini alir ve otonom
   bolumu kendisi bulur):

       python kosum_olc.py
       python kosum_olc.py enkoder_kayit/eski.csv enkoder_kayit/yeni.csv

   Arac sisteme dokunmaz, yalnizca `enkoder_kayit/*.csv` okur. Kabul olcutu:
   titresim RMS < 0.15 derece ve frekans 2-4 Hz bandinda DEGIL.
3. **Paket 2 (kod):** otonom modda kilit onayini atla (B14); avci kaynakli
   edinmede tek mutlak aci komutu + oturma bekleme; hizalama sicramasini
   dunya acisina yansit.
4. **FAZ 6 (B15):** kontrol dongusu enkoder acisini kullansin. Simulasyona
   gore tek basina en buyuk kazanc.
5. **Kamera:** pozlama 10 -> 3-4 ms, 15 fps'in sebebi. Hala yapilmadi.
6. **Paket 4 (dataset):** egik direk (+-35 derece), hareket bulanikligi,
   **karton kutu / ray / araba negatifleri** (B13).

### 29.7 Ucuncu kosum: HEDEF IMHA EDILDI (2026-09-16 16:26)

`enkoder_20260916_162650.csv`, 132 saniye, dort tur. Kullanici bildirimi:
**3. turda hedef imha edildi.** Video yok; olcum tamamen enkoder kaydindan.

#### 29.7.1 Tur tur olcum

| tur | aralik | titresim RMS | frekans | nisan bandi disi | yon degisimi |
|---|---|---|---|---|---|
| 1 | 19.3-37.3 sn | 0.264 | 1.51 Hz | %18.6 | 107 / 55sn |
| 2 | 49.7-64.2 sn | **0.112** | 2.43 Hz | **%7.3** | 71 / 55sn |
| 3 | 80.8-103.5 sn (**imha**) | 0.215 | 2.50 Hz | %11.5 | 76 / 55sn |
| 4 | 110.9-129.3 sn | 0.317 | 1.80 Hz | %20.8 | 83 / 55sn |

Uc kosumun ORTANCA turu (olcum araci artik turlari ayirip ortancayi veriyor;
manuel surus bolumleri de "tur" gorunduğu icin en kotuyu almak yaniltiyordu):

| kosum | ayar | titresim RMS | frekans | bant disi |
|---|---|---|---|---|
| Denem (14:29) | ilk ayar | 0.155 | 0.57 Hz | %16.1 |
| Deneme2 (15:20) | suzgec KAPALI | 0.392 | 3.37 Hz | %30.9 |
| Deneme3 (16:26) | suzgec geri ACIK | **0.264** | **1.51 Hz** | %18.2 |

Suzgeci geri acmak isini yapti: **3.37 Hz'lik denetleyici rezonansi gitti**
(1.51 Hz artik hedefin kendi salinimina yakin), RMS ucte bir azaldi, nisan
bandi disinda gecen zaman %31'den %18'e indi. Ilk kosumun 0.155'ine
inilemedi; aradaki fark su an aciklanamiyor ve bir sonraki kosumda
izlenecek (ilk kosumda `MAX_OUTPUT_DEGREE` 15, feedforward acikti).

#### 29.7.2 Kullanicinin gozlemi ve kok neden

> "hedef hareketli oldugu icin bazen tam nisan almadan sikma gibi durumlar
> oluyor ama tam nisan almaya odaklanirsak da dataset kaynakli hedef
> kayboldugu icin tam nisana oturamiyoruz"

Ikisi ayri sorun ve ikisinin de sebebi bulundu.

**B16 — NISAN KARARI BAYATTI (duzeltildi).** `is_aimed_at_target` HAM piksel
hatasina bakiyordu: `error_yaw_pixel = target_x - center_x`, yani karenin
CEKILDIGI andaki hata. Taret o andan beri hareket etmis oluyor; olculen olu
zaman 0.22 saniye ve takipte tepe hiz 40-80 derece/sn, yani "nisan TAMAM"
bilgisi 8 dereceye kadar bayat olabiliyor. Ates kilidi de ayni bayrağa
baktigi icin sistem, taret hedefin icinden GECERKEN "nisan tamam" gorup ates
edebiliyordu.
Telafi edilmis hata (`error_*_degree` = hedefin dunya acisi eksi taretin
SIMDIKI acisi) zaten hesaplaniyordu — PID onu kullaniyor, nisan karari
kullanmiyordu. Artik nisan karari ve `kilit_adimi` de ondan besleniyor.
Boslugun bu hesapta iptal oldugu 29.6 B15'te gosterilmisti (sabit ofset iki
taraftan da dusuyor); yalnizca yon degisiminin hemen ardindan gecerli degil.

**B17 — ATES KAPISI: TARET DURURKEN ATES (eklendi).** Bayat nisan
duzeltilse bile ates komutundan sonra servo cekisi 0.20 saniye suruyor ve
taret o sirada donmeye devam ediyor. r derece/sn'de namlu 0.2 x r derece
kayiyor; balon 10 metrede +-0.43 derecelik bir hedef, yani 3 derece/sn'de
kayma zaten butun payi yiyor.
Yeni kosul `FIRE_MAX_TURRET_RATE_DEG_S = 3.0`: enkoderden olculen mutlak yaw
hizi bu sinirin ustundeyse ates serbest degil. **Bu kapi atesi engellemiyor**
— ayni kayittan olculdu, taret zamanin %75-86'sinda 3 derece/sn'nin altinda:

| tur | medyan hiz | p90 | 3 der/sn altinda |
|---|---|---|---|
| 1 | 0.9 | 7.1 | %74.9 |
| 2 | 0.0 | 3.5 | %86.0 |
| 3 | 0.9 | 4.3 | %82.1 |
| 4 | 0.0 | 7.0 | %79.6 |

Enkoder yoksa veya saglıksizsa kapi UYGULANMAZ (eski davranis) — enkoder bir
emniyet katmani, calismamasi sistemi durdurmamali. Hiz PC tarafinda ~100 ms
pencereyle olculuyor (`_update_encoder_state`).

**B18 — KAMERA POZLAMASI ARAYUZE HIC ULASMIYORDU (duzeltildi).** Kullanici
`kamera_renk.py` ile pozlamayi ayarladi ama `KAMERA_KONTROLLERI['hunter']`
icinde `exposure` ve `auto_exposure` **None** idi; None demek "bu denetime
DOKUNMA" demek, yani arayuz kamerayi kendi acinca surucunun OTOMATIK
pozlamasi geri geliyordu. Ic mekanda otomatik pozlama ~60 ms seciyor ve bu
tek basina iki sorunu birden acikliyor:
- **15 fps tavani**: 60 ms pozlama en fazla 16 kare/saniye demek. Sahada
  olculen 15.0 fps'in sebebi buydu; config 30 bekliyordu.
- **Hareket bulanikligi**: 400 derece/sn donuste 60 ms = 24 derece = kare
  genisliginin neredeyse tamami. 29.3 B1'de "kutusuz kareler bulanik" diye
  gecen gozlemin dogrudan sebebi.

Sahada secilen degerler config'e yazildi: `auto_exposure: 0.25` (DirectShow'da
0.25 = MANUEL), `exposure: -5`, `gain: 168`.

**POZLAMA DEGERININ ANLAMI (kullanicinin sorusu):** deger LOG2 SANIYEDIR.
`-5` = 2⁻⁵ = 1/32 s = **31 ms**. `-6` = 16 ms, `-7` = 8 ms, `-8` = 4 ms.
Yani sayi KUCULDUKCE (daha negatif) pozlama KISALIR ve bulaniklik azalir.
`-5` otomatiğin ~60 ms'sine gore iki kat iyilesme ama hedef `-6`/`-7`.
`e` tusu otomatik pozlamayi acip kapatir; ekranda `auto_exp -1` yaziyor
cunku bu surucu o alani OKUTMUYOR (beyaz dengesindeki `wb -1K` ile ayni
durum). Okunamamasi calismadigi anlamina gelmiyor — `[` / `]` ile goruntunun
degismesi manuel kipin etkin oldugunu gosteriyor.

**B19 — GEREKSIZ KILIT ONAYI KALDIRILDI (29.6 B14 uygulandi).** Otonom
modda durum makinesi hedefi zaten `VERIFY_CONFIRM_FRAMES = 4` ardisik ve
tutarli karede dogruluyor, ustelik cifte balon eslesmis oluyor. Bunun ustune
`_otonom_hedefi_benimse` bir de 3 ardisik kare konum onayi istiyordu ve sayac
tespit dusen HER karede sifirlaniyordu; tespit surekliligi ~%50 iken 3 ardisik
kare olasiligi %12. Artik makine dogruladiysa onay atlanıyor (manuel/Asama 1
yolundaki onay yerinde duruyor, orada makine calismiyor).

**B20 — SUZGEC SARMA ONLEME (eklendi).** Cikis suzgecinin hafizasi
HESAPLANAN degeri tutuyordu; `MAX_OUTPUT_DEGREE` 2.0'a indirildigi icin
buyuk hatada cikis kirpiliyor ve hafiza kirpilmamis degeri tasiyordu. Bu,
hata kapandiktan sonra birkac kare daha sinirdan komut gonderilmesi demek —
kirpma asimi onlemek yerine geciktirir. Hafiza artik GONDERILEN degerle
esitleniyor (standart anti-windup).

#### 29.7.3 Bu commit'te degisenler

| Ne | Once | Sonra |
|---|---|---|
| `is_aimed_at_target` ve `kilit_adimi` | ham piksel hatasi (bayat) | telafi edilmis hata |
| `FIRE_MAX_TURRET_RATE_DEG_S` | yok | **3.0 derece/sn** (enkoderli) |
| `KAMERA_KONTROLLERI['hunter']` pozlama | None (otomatik geri geliyordu) | manuel, exp -5, gain 168 |
| otonom kilit onayi | 3 ardisik kare | makine dogruladiysa atlanıyor |
| suzgec hafizasi | kirpilmamis cikis | gonderilen cikis (anti-windup) |

Test: 213 kontrol, TUM TESTLER GECTI. Yeni bolumler 22 (ates kapisi) ve
23 (nisan karari bayat degil).

#### 29.7.4 Sirasi gelen isler

1. **Kosum.** Bes degisiklik birden girdi; olcut: `kosum_olc.py` ortanca tur
   RMS'i (simdi 0.264) ve ates basina isabet orani. Ates sayisinin DUSMESI
   beklenir (kapi calisiyorsa), isabet oraninin ARTMASI beklenir.
   Ates engellendiginde durum cubugunda artik `taret hareketli: X derece/sn`
   yaziyor — cok sik gorunuyorsa sinir 5.0'a gevsetilir.
2. **Kamera acilis satiri.** Arayuz acilirken konsolda pozlamanin TUTUP
   tutmadigi ve gerceklesen fps yaziyor. 30 fps'e ciktiysa `exposure` -6'ya
   indirilebilir; goruntu fazla karanlik kalirsa `gain` artirilir.
3. **Dataset (degismedi, hala en buyuk kalan kalem):** egik direk, hareket
   bulanikligi, karton kutu negatifleri.
4. **FAZ 6 (29.6 B15):** kontrol dongusu adim sayaci yerine enkoder acisini
   kullansin. Simulasyona gore nisan hatasi RMS'ini yariya indiriyor.

### 29.8 `aşama3HedefImha2.mp4` — sabit hedefte nisan, hareketli hedefte imha (2026-09-16 gece)

31.2 saniye, 3 fps'de 94 kare tek tek okundu. Model **v25** (kullanici dataseti
gelistirdi). Iki bolum: t=1.3-11.7 sabit hedefe "Hedef Takip" (atessiz olcum
modu), t=14.5-30.7 hareketli hedefte Asama 3.

**Sonuc: hedef imha edildi.** Dort atis yapildi, dorduncusu tuttu. Asama 3'e
basildiktan imhaya kadar 14.3 saniye; hedef 15 metreden 10 metreye geldi.

#### 29.8.1 B21 — ONCEKI COMMIT'TE GETIRDIGIM OLU BOLGE (duzeltildi)

29.7'de eklenen sarma onleme (anti-windup) MIN_OUTPUT esigine de
uygulanmisti: cikis "cok kucuk" diye sifirlanınca suzgec hafizasi da
sifirlaniyordu. Bu, suzgecin birkac karede gonderilebilir bir komuta RAMPA
yapmasini imkansiz kildi ve ilk karede komut uretmek icin gereken hatayi
KALICI bir esige cevirdi:

    gereken hata = MIN_OUTPUT / (a x KP)
                 = 0.0564 / (0.30 x 0.70) = 0.269 derece = 19 piksel  (yaw)
                 = 0.0564 / (0.30 x 0.60) = 0.314 derece = 22 piksel  (pitch)

Nisan toleransi o sirada 14 pikseldi. Yani sistem toleransa **matematiksel
olarak giremiyordu**.

Sahada tam olarak boyle goruldu — sabit hedef, hic ruzgar yok:

| t | hata | taret yaw | enkoder |
|---|---|---|---|
| 3.0 | 16 px (yaw -7, pitch -14) | -4.4 | -4.37 |
| 3.3 | 16 px | -4.4 | -4.37 |
| 3.7 | 16 px | -4.4 | -4.37 |
| 4.0 | 17 px (yaw -7, pitch -15) | -4.4 | -4.37 |
| 4.3 | 16 px | -4.4 | -4.37 |
| 4.7 | 17 px | -4.4 | -4.37 |

Taret 1.7 saniye boyunca **hic kimildamadi**. Yaw hatasi 7 piksel (olu bandin
tam sinirinda, dogru davranis), pitch hatasi 14 piksel — olu bandin ustunde,
ama suzgec esiginin altinda. Kullanicinin "kusursuz nisan alinmadigini
gorebilirsin" dedigi sey birebir bu.

**Duzeltme:** sarma onleme artik YALNIZCA MAX doygunlugunda uygulanıyor.
Ayrim su: `MAX_OUTPUT_DEGREE` gercek bir doygunluktur (motor daha hizli
donemez), orada hafizayi kirpmak dogru. `MIN_OUTPUT` ise "cok kucuk komut
gonderme" kuralidir, doygunluk degil; hafizayi bozmamali.
Duzeltmeden sonra 14 piksellik pitch hatasi iki karede gonderilebilir komuta
ulasiyor ve olu banda kadar iniyor.

**Kalici test eklendi (24. bolum):** olu bandin hemen ustundeki her hata 8
kare icinde komut uretmeli; nisan toleransi kadar hata da komut uretmeli;
nisan toleransi olu banttan buyuk olmali; sarma onleme yalnizca MAX'ta olmali.
Bu dort kontrol ayni hatanin geri gelmesini engeller.

#### 29.8.2 B22 — ISKALAR: nisan toleransi cok genisti

Dort atisin nisan hatalari (ham piksel, ekrandan okundu):

| atis | t | yaw hatasi | pitch hatasi | sonuc |
|---|---|---|---|---|
| 1 | 18.0 | **+19** | -5 | iska |
| 2 | 23.3 | **+21** | -5 | iska |
| 3 | 25.0 | **-12** | -5 | iska |
| 4 | 27.7 | **+2** | -11 | **ISABET** |

Tek belirleyici degisken yaw hatasi. 12-21 piksel iska, 2 piksel isabet.

Sayisal karsiligi: 12 metrede 19 piksel = 0.27 derece = **5.6 santim**. Balon
yaricapi ~7.5 santim. Yani nisan hatasi TEK BASINA payin dortte ucunu yiyor;
uzerine namlu sapmasi ve merminin kendi dagilimi eklenince iska kaciniImaz
oluyor. 2 piksel = 0.6 santim ise bol bol yer birakiyor.

Sebep: `AIM_TOLERANCE_RATIO = 0.6` (29.5'te 0.35'ten yukseltilmisti) ve
`AIM_TOLERANCE_MIN_PIXELS = 14`. Hedef yaklastikca balonun piksel yaricapi
buyudugu icin tolerans da buyuyor — 12 metrede 21 piksele kadar cikiyordu ve
atis 19-21 piksel hatayla serbest kaliyordu.

O yukseltme O ZAMAN dogruydu: 29.3 B6'da sistem hic ates edemiyordu ve
tolerans darligi sebeplerden biriydi. Ama simdi B21 duzeldigi icin taret
gercekten dar bir toleransa oturabiliyor. **Geri cekildi:**
`AIM_TOLERANCE_RATIO` 0.6 -> **0.4**, `AIM_TOLERANCE_MIN_PIXELS` 14 -> **10**.
12 metrede tolerans 10 piksel = 3.4 santim. Olu bant eksen basina 7 piksel
oldugu icin taretin dogal durus hatasi bu bandin ICINDE kaliyor — yani hedef
ulasilabilir.

#### 29.8.3 B23 — Zaman nereye gitti (14.3 saniye)

| aralik | sure | ne oluyordu |
|---|---|---|
| 14.5-17.0 | 2.5 sn | maketin kendisi `balon` etiketi aliyor; cift kurulamiyor, kimlik yok |
| 17.0-18.0 | 1.0 sn | dogrulama + kilit (hizli, sorun yok) |
| 18.0-18.7 | 0.7 sn | 1. atis + imha dogrulama penceresi |
| 18.7-20.7 | 2.0 sn | "Ates engellendi" (nisan tolerans disinda / cifte balon eslesmemis) 22 kare dolana kadar |
| 20.7-22.3 | 1.6 sn | atis butcesi doldu -> kara liste |
| 22.3-23.3 | 1.0 sn | yeniden dogrulama + kilit |
| 23.3-25.0 | 1.7 sn | 2. atis + pencere + engellenen denemeler |
| 25.0-27.7 | 2.7 sn | 3. atis + pencere + engellenen denemeler (guven dusuk 0.36, maket yok) |
| 27.7-28.8 | 1.1 sn | 4. atis -> **imha** |

Iki buyuk kalem: **basarisiz atislarin ardindan gelen bekleme (toplam ~6
saniye)** ve **baslangictaki 2.5 saniyelik etiket karisikligi**. Ucuncu bir
atisa gerek kalmasaydi sure 14.3 yerine ~4 saniye olurdu. Yani **hizlanmanin
yolu iskalari bitirmekten geciyor**, bekleme surelerini kirpmaktan degil.

#### 29.8.4 B24 — "Fuzeye balon diyor" hatasinin bedeli olculdu

Kullanicinin fark ettigi etiket hatasi (t=14.7, 15.0, 16.0, 20.7, 21.0,
26.7): maketin KENDISI `balon` olarak etiketleniyor. Bunun bedeli sanildigindan
buyuk, cunku cift kurulumu "maketin altinda balon" ariyor:
- Iki tespit de `balon` olunca MAKET YOK demektir; kimlik bilgisi yalnizca
  makette oldugu icin `avcida_hazir_hedef_var` False doner ve sistem hedefi
  gormesine ragmen TARAMA'da bekler (t=14.7-17.0, 2.5 saniye; t=20.7-21.7).
- Ates kilidinde de `cifte balon eslesmemis (nisan noktasi tahmini)` gerekcesi
  bu yuzden cikiyor (t=20.0).

Yani dataset tarafinda oncelik artik "maket kacirilmasin"dan cok **"maket
balon sanilmasin"**. Ornek: balon ile maketin ust uste bindigi, maketin kisa
gorundugu (dik veya kameraya dogru) kareler.

#### 29.8.5 Iyilesenler

- Tespit surekliligi belirgin arti: KILIT donemlerinde maket neredeyse her
  karede 0.6-0.87 guvenle goruluyor (v23'te %40-56 kare kutusuzdu).
- Karton kutu yanlis pozitifi bu kosumda **hic gorulmedi** (v23'te 0.77'ye
  kadar cikiyordu).
- Enkoder farki (`sayac - enkoder`) ortalama 0.23-0.43, en buyuk 3.0 derece;
  KILIT sirasinda cogunlukla 0.00-0.30. Onceki kosumlarla ayni mertebede.
- Ates kapisi (B17) hicbir karede engelleme gerekcesi olarak gorunmedi — yani
  taret ates anlarinda zaten yavasti, kapi maliyet uretmiyor.

#### 29.8.6 Bu commit

| Ne | Once | Sonra | Bulgu |
|---|---|---|---|
| sarma onleme kapsami | MIN_OUTPUT + MAX | **yalnizca MAX** | B21 |
| `AIM_TOLERANCE_RATIO` | 0.6 | **0.4** | B22 |
| `AIM_TOLERANCE_MIN_PIXELS` | 14.0 | **10.0** | B22 |
| test bolumu 24 | yok | **olu bolge regresyon testi** | B21 |

#### 29.8.7 ENKODER: hangi faz yapildi, ne kaldi

| faz | konu | durum |
|---|---|---|
| FAZ 0 | donanim, kablolama | YAPILDI |
| FAZ 1 | hat kurulumu (Waveshare ham protokol, 250 kbit/s) | YAPILDI |
| FAZ 2 | enkoderi tani, kalici ayar (TPDO2/SYNC, preset 8192) | YAPILDI |
| FAZ 3 | sadece oku ve goster, kontrole karismaz | YAPILDI |
| FAZ 4 | boslugu ve olcegi olc (a=0.997, bosluk 1.49 derece) | YAPILDI |
| FAZ 5' | durunca hizala (rest-snap) | YAPILDI |
| **ates kapisi** | enkoder hiziyla ates kilidi (29.7 B17) | **YAPILDI (yeni)** |
| **FAZ 5''** | Pi'de bosluk telafisi (yon degisiminde sayilmayan adim) | **YAPILMADI** |
| **FAZ 6** | kapali dongu: kontrol adim sayaci yerine ENKODERI kullansin | **YAPILMADI** |
| FAZ 7 | saglamlastirma (kablo kopmasi, yeniden baglanma) | kismen (yeniden baglanma var) |

Kalan ikisi de ayni koke bagli: kontrol dongusu hala ADIM SAYACINI gercek aci
saniyor, kamera ise FIZIKSEL aciyi goruyor; aradaki 1.5 derecelik bosluk her
yon degisiminde sahte hata uretiyor. 29.6 B15'teki kapali dongu
simulasyonunda yalnizca boslugu kaldirmak nisan hatasi RMS'ini 1.01'den 0.37
dereceye indiriyordu — diger butun ayarlardan buyuk bir etki.

**FAZ 6 daha temiz ve daha az riskli:** PC tarafinda `current_yaw_angle` ve
`_angle_at()` enkoder acisini kullanir, komut yine delta olarak gider. Bosluk
hata hesabindan tamamen cikar. FAZ 5'' (Pi'de acik dongu telafi) ayni sorunu
dolayli cozer ve kalibrasyon gerektirir.

#### 29.8.8 Sirasi gelen isler

1. **Atis gruplama testi — artik olculmus bir gerekce var.** 12 metreden,
   sistem kilitliyken 10 atis; her vurusun nereye dustugu isaretlenir. Cikti:
   (a) namlu sapmasi (yaw/pitch ofseti, config'e girer), (b) merminin kendi
   dagilimi. Dagilim biliniyorsa nisan toleransinin DOGRU degeri hesaplanir —
   su an 0.4/10 piksel tahmin.
2. **Bir kosum** (B21 + B22 olculecek). Beklenti: sabit hedefte artik 16-17
   pikselde takilmaz, olu banda (7-10 piksel) iner; hareketli hedefte atis
   sayisi duser, isabet orani artar.
3. **Dataset:** maketin `balon` sanilmasi (B24). Ornek: balon-maket ust uste,
   maket dik/kisa gorundugu kareler.
4. **FAZ 6** (29.8.7).

### 29.9 `HedefSıkmaDeneme.mp4` — son iki tur, 3 atis 0 isabet; mimari degisiklik (2026-09-16 gece)

47.5 saniye, 3 fps'de 143 kare tek tek okundu (iki otonom tur: t=0-15 ve
t=27-47; arada manuel surus). Kayit `enkoder_20260916_213936.csv`, kullanici
`kosum_olc.py` ciktisini paylasti (6 tur; son ikisi bu video).

**Sonuc: iki turda uc atis, hicbiri isabet etmedi.** Titresim ise iyi durumda:
son iki turun RMS'i 0.172 ve 0.136 derece (hedef <0.15), frekans 2.26 ve
1.06 Hz. Yani kontrol dongusu artik sorun degil; sorun yukari katta.

#### 29.9.1 Zaman cizelgesi (ozet)

| t | durum | etiket (maket) | ne oldu |
|---|---|---|---|
| 0.0-1.3 | KILIT, balon VAR | Fuze 0.70 / 0.63 / 0.79 / 0.54 / **0.36** | nisan bekliyor, "guven dusuk 0.36" ile ates engellendi |
| 1.7 | KILIT | **dusman-Helikopter 0.60** | "maket bu karede tespit edilmedi" (sinif tutmadi) |
| **2.0** | **ATES 1. atis** | Fuze 0.43 | hata yaw -9 / pitch 4 px -> **iska** |
| 2.7-4.0 | imha dogrulaniyor / engellendi | **balon** 0.46 / 0.62 / 0.46 (maket balon sanildi) | "maket bu karede tespit edilmedi" 2/22 .. 11/22 |
| 4.3 | engellendi | Fuze 0.80 | "nisan tolerans disinda" 16/22, hata 70 px |
| 4.7 | **hedef birakiliyor** | **dusman-Helikopter 0.82** | 22/22 doldu -> kara liste 1.5 sn |
| 5.0-6.0 | TARAMA | Fuze 0.53 / 0.87 / 0.58 | kara liste bekleniyor (hedef 0.87 ile karede) |
| 6.3-6.7 | DOGRULAMA | **Helikopter 0.62**, Fuze 0.72 | |
| 7.0-7.3 | KILIT — hedef bu karede yok | **balon 0.56**, **Helikopter 0.76** | sinif tutmadi |
| 7.7-9.0 | Hedef kaybedildi, tahmin | — | |
| 9.3-9.7 | engellendi: tolerans disinda | Fuze 0.81 / 0.68 | hata 24 / 43 px |
| 10.0 | engellendi: maket yok | **Helikopter 0.65** | |
| **10.7** | **ATES 1. atis** (yeni kilit) | Fuze 0.78 | hata yaw 16 / pitch -1 -> **iska** |
| 11.0-11.3 | imha dogrulaniyor -> **DOGRULAMA** | **Drone 0.45**, **Helikopter 0.86** | kilit ATES sirasinda yabanci maket (3 kare) ile dustu |
| 12.0-15.0 | DOGRULAMA/TARAMA/Aday | balon 0.51, Drone 0.57/0.63 | kilit kurulamadi; kullanici durdurdu |
| 27.3 | DOGRULAMA | Fuze 0.42 | 2. tur basi |
| 28.3 | TARAMA (2 cift) | **balon 0.62 + balon 0.46** | maket yok -> kimlik yok |
| 30.0-30.7 | DOGRULAMA -> KILIT [kopru] | Fuze 0.71, **Helikopter 0.42**, Fuze 0.59 | |
| 31.0-32.3 | KILIT nisan bekliyor | Fuze 0.34-0.77, **balon** 0.63 | hata 74 / -45 / -70 / -7 / 59 px (direk saliniyor) |
| **32.7** | **ATES 1. atis** | Fuze 0.51 | hata **yaw 1 / pitch 1 px** -> **ISKA** |
| 33.0-35.3 | imha dogrulaniyor / engellendi | **balon** 0.46/0.70/0.50, Fuze 0.61 | "maket bu karede tespit edilmedi" 1..21/22 |
| 35.7 | TARAMA | **Drone 0.35** | 22/22 -> kara liste |
| 36.0-42.3 | TARAMA/DOGRULAMA/KILIT/kayip donguleri | Fuze, Helikopter, Drone karisik | ates yok |
| 45.3 | KILIT | **dusman-Drone** | BALON YOK |
| 46.3 | kayip | **karton kutu: dusman-F16 0.37** | |
| 46.7 | Hazir | | kullanici durdurdu |

Ornek karelerde maketin etiketi: ~%45 dusman-Fuze, ~%20 dusman-Helikopter,
~%15 dusman-Drone, ~%18 **balon**. Balonun kendisi ise ayni karelerin
neredeyse tamaminda 0.80-0.88 ile var. Kullanicinin gozlemi birebir dogru.

#### 29.9.2 Bulgular

**B25 — ETIKET KAYMASI KILIDIN VE ATESIN TEK BASINA EN BUYUK DUSMANIYDI
(mimari degisti).** Eski kural her karede "maket dogrulanan sinifla ayni
olmali" diyordu; bu sart uc ayri yerde atesi kesiyordu:
`kilit_hedefi_sec` ("hedef bu karede yok"), `ates_serbest_mi` ("maket bu
karede tespit edilmedi" / "sinif dogrulanandan farkli" / "guven dusuk") ve
yabanci-maket iptali (3 kare Helikopter -> kilit dustu, t=11.0). Ustelik
22 karelik engel butcesi dolunca hedef kara listeye giriyor ve 1.5 saniye
daha kaybediliyordu.

Uygulanan: **BALON CAPASI** (`config.LOCK_BALLOON_ANCHOR`). Kimlik
DOGRULAMA'da bir kez karara baglanir; KILIT/ATES'te hedef, son kilit
acisina en yakin BALONLU cifttir, maketin o karede ne etiket aldigi
(veya hic gorunmemesi) onemsizdir. Emniyet: capadaki maket 3 ardisik
karede >=0.60 guvenle DOST gorunurse kilit birakilir ve aci kara listeye
girer; tek karelik >=0.60 dost gorunumu ise sadece o karede atesi keser.
Ayni siniftan ama capa yaricapinin disindaki cift de artik alinmiyor —
3 hedefli senaryoda ikisi ayni tip olabilir.

**B26 — DOGRULAMA "4 kare birebir ayni etiket" istiyordu.** Etiket
dusman tipleri arasinda kayarken bu 2.7 saniye ve iki deneme surdu
(t=27.3-30.0). Yeni kural: son 6 karede ayni TARAF (dost-/dusman-) en az
4 kez ve cogunlukla -> kimlik o taraf, sinif en sik etiket. Dost/dusman
ayrimi hala 4 kare ister.

**B27 — NISAN KUSURSUZKEN ISKA: BALON SALLANIYOR.** t=32.7'de atis hatasi
yaw 1 / pitch 1 piksel, yine iska. Sebep atis gecikmesi: servo cekisi
0.20 sn + komut gecikmesi ~0.05 sn. Direk sarkac gibi saliniyor, genlik
~±1.5 derece, periyot ~1.3 sn -> tepe hizi ~7 derece/sn; 0.25 sn'de 1.75
derece = 12 metrede 37 cm. Balon yaricapi 7.5 cm. Yani salinimin
ortasinda acilan atis matematiksel olarak iska; **29.8 B22'deki "iska =
nisan hatasi" sonucu eksikti**, hedef hareketi de iska uretiyor.
Uygulanan: `FIRE_MAX_TARGET_RATE_DEG_S = 2.0` — hedefin dunya acisal hizi
(zaten hesaplanan `target_world_*_rate`) sinirin ustundeyse ates yok.
Sarkac uclarda durur; ates oraya tasinir (2 x 0.25 = 0.5 derece = 10 cm
ust sinir). Engel gerekcesi durum cubugunda "hedef hareketli: X" olarak
gorunur.

**B28 — FAZ 6 UYGULANDI (kontrol dongusu enkoderi kullaniyor).**
`ENCODER_CONTROL = True` iken PC tarafinda `current_yaw_angle` ve
`_angle_at()` yaw'i ENKODER gecmisinden okur (rapor gecikmesi
`ENCODER_LAG_SEC` = 0.05 sn geri alinarak damgalanir); pitch sayacta kalir;
komutlar yine delta olarak Pi'ye gider, Pi tarafi degismedi. Enkoder 0.3
sn rapor vermezse otomatik olarak sayaca donulur. Bosluk (1.5 derece) hata
hesabindan tamamen cikiyor; B27'deki hedef hizi olcumu de boslugun sahte
hizindan arinmis oluyor (feedforward'in eski derdi buydu).

**B29 — Kalanlar (kod degismedi):** karton kutu `dusman-F16 0.37` (t=46.3)
ve maketin `balon` sanilmasi (%18) dataset isi; 15 fps hala; ates sonrasi
22 kare + 1.5 sn kara liste artik B25 ile cok daha az tetiklenecek.

#### 29.9.3 Bu commit'te ne degisti, nerede, neden

| dosya / yer | ne | neden |
|---|---|---|
| `config.py` LOCK_BALLOON_ANCHOR, LOCK_ANCHOR_MAX_DEG 1.2, _GROW 0.4, _MAX_TOTAL 3.0, LOCK_FRIEND_ABORT_FRAMES 3, _CONF 0.60 | yeni | B25 balon capasi ayarlari |
| `config.py` VERIFY_WINDOW_FRAMES 6 | yeni | B26 dogrulama penceresi |
| `config.py` FIRE_MAX_TARGET_RATE_DEG_S 2.0 | yeni | B27 hedef hizi kapisi |
| `config.py` ENCODER_CONTROL True, ENCODER_LAG_SEC 0.05 | yeni | B28 FAZ 6 |
| `engagement.py` `kilit_hedefi_sec` | yeniden yazildi; eski govde `_kilit_hedefi_sec_eski` (bayrak False iken) | B25: capaya en yakin balonlu cift; dost israrinda birak; ayni sinif uzaktaysa alma |
| `engagement.py` `ates_serbest_mi` | `hedef_hizi=` parametresi; capa modunda maket-sart kosullari kaldirildi, dost-gorunumu kesici eklendi | B25, B27 |
| `engagement.py` `dogrulama_adimi` + `_taraf_cogunlugu` | 4 ardisik ayni -> 6'da 4 ayni taraf | B26 |
| `engagement.py` `AngajmanMakinesi.__init__`/`_gec` | `dost_ardisik`, `capa_kayip` alanlari | B25 |
| `encoder_module.py` `aci_at` | yeni saf fonksiyon | B28: zaman-aci aradegerleme (testlenebilir) |
| `bukrek_main.py` `_enkoder_kontrolde`, `_update_current_angles`, `_update_encoder_state`, `_angle_at`/`_sayac_aci_at` | FAZ 6 | B28 |
| `bukrek_main.py` `_hedef_hizi`, `_otonom_ates_denemesi` | ates kapisina hedef hizi | B27 |
| `bukrek_main.py` KILIT durum metni | "[köprü]" -> "[çapa]" | B25 |
| `tests_yeni_mimari.py` 6, 8, 13(e) | eski kural bayrakla sabitlendi; capa beklentileri eklendi | |
| `tests_yeni_mimari.py` 25, 26, 27 | yeni | capa, dogrulama penceresi, FAZ 6 aradegerleme, hedef hizi kapisi |

253 kontrol, tumu gecti.

#### 29.9.4 Ucuncu asama (3 hedef, tek turda) icin ne degisti

- Kimlik bir kez dogrulanip balon takip edildigi icin etiket kaymasi
  artik hedef degistirmez; ayni siniftan ikinci bir dusman capa
  yaricapinin (1.2-3.0 derece) disinda kaldigi surece ayri hedef sayilir.
- Imha sonrasi kara liste (12 sn) ve TARAMA'nin "merkeze en yakin cift"
  kurali siradaki hedefe gecisi sagliyor; bu kosumda olculemedi, 3 hedefli
  kurulumda olculmeli.
- Hiz sinirlayan kalemler ayni: 15 fps, dogrulama (~0.3 sn), sarkac
  penceresi bekleme (B27), atis gecikmesi 0.25 sn.

#### 29.9.5 Sirasi gelen isler

1. Kosum: beklenti — "maket bu karede tespit edilmedi" gerekcesi
   neredeyse hic gorunmemeli; ates aninda "hedef hareketli" gerekcesi
   gorunmeli ve atislar sarkac uclarina denk gelmeli; `kosum_olc.py`
   ile RMS <0.15 korunmali (FAZ 6 sonrasi dusmesi beklenir).
2. FAZ 6 ayari: taret hedefi asiyorsa `ENCODER_LAG_SEC` artir (0.08),
   yavas salinim varsa azalt (0.02).
3. Dataset: maketin balon sanilmasi, karton kutu negatifi.
4. 3 hedefli kurulum ile tek tur denemesi.

### 29.10 `görüntüTıklama.mp4` — "saga tikliyorum, taret sola donuyor" (2026-09-16 gece, FAZ 6 sonrasi)

15.2 saniye, Tam Manuel Kontrol modu, 30 fps'de kare kare okundu; kayit
`enkoder_20260916_222302.csv` (video 22:23:43-22:23:58) ile eslestirildi.

**Gozlem.** Taret -14.02 derecede 15 saniye duruyor. Operator nisangahin
hemen yanina (yaklasik 1-2 derece) tikliyor; taret 32 derece/sn ile
**-33.27'ye** gidiyor (-19.25 derece, SOLA). Sonraki tiklamalar -8.15 ve
-6.04 derece daha sola. "Sag" tusuyla -4.77'ye donuluyor; tiklamalar yine
-5.96, -6.04, -5.74 derece sola. Tiklama kodu (`mouse_press_event`,
`_etiket_to_kare`, `_piksel_to_dunya`) tek tiklamada en fazla +-13.5 derece
uretebilir (yarim kare x 0.01411); -19.25 bu yoldan cikamaz. Yani PC'nin
hesapladigi hedef DOGRU, Pi'nin gittigi yer YANLIS.

**Kok neden.** FAZ 6 (bc0a2fe) ile PC'nin "mevcut yaw"i ENKODER oldu.
Mutlak komut (`send_angle_command` -> Pi `set_angles`) ise Pi'nin ADIM
SAYACI cercevesinde yurutuluyor. Iki cerceve ayni sanilmisti ("FAZ 5'
hizalama durusta ikisini esitler"). Gunun kayitlari aksini gosteriyor:

| kayit | durusta sayac - enkoder (medyan) | en buyuk |
|---|---|---|
| 12:54 | +11.1 | 12.4 |
| 13:07 | +21.2 | 23.7 |
| 14:07 | +11.7 | 14.9 |
| 20:04 | +15.5 | 17.0 |
| 21:39 (HedefSikma kosumu) | +19.2 | 21.9 |

21:39 kaydinda fark 21:39:37'de +19.4, 21:39:56'da +21.8 ve 21:42:07'ye
("Acilari Sifirla") kadar oyle kaldi. Ilk tiklamanin -19.25 derecesi, o
anki +19.23'luk farkin ta kendisi: PC "enkoder -14.02 + 1.4 = -12.6" dedi,
Pi "sayacim +5.2, -12.6'ya gitmem icin 17.8 sola" dedi.

Fark neden kalici: Pi'de `ENCODER_SNAP_MAX_DEG = 10`. Hizli hareketlerde
kacirilan adimlar tek seferde 10 dereceyi asinca hizalama "supheli" diye
reddediliyor ve bir daha hic duzelmiyor. Kucuk farklar (0.5-3 derece)
duzeltiliyor (kayitlarda 27-225 sicrama), buyukler asla.

**Onceki testlerde neden gorulmedi.** Takip yolu delta komutu
(`set_proportional_angles_delta`) kullaniyor; delta cerceveden bagimsiz.
Tiklama, gozcu yonelmesi ve derece/piksel kalibrasyonu mutlak komut
kullaniyor; FAZ 6 acilana kadar mutlak komut da sayac cercevesinde
hesaplaniyordu, fark hic isin icine girmiyordu. FAZ 6'dan sonraki ilk
mutlak komut bu videodaki tiklama.

**Ikinci hasar: FAZ 4 kaydi kor kalmisti.** `_enkoder_kaydet` sayac
sutununa `current_yaw_angle` yaziyordu; FAZ 6'da o deger enkoder oldugu
icin 22:17'den sonraki uc kayitta "sayac" sutunu bir onceki satirin
enkoder degerini tekrar ediyor (satir satir dogrulandi: 918/918). Panelde
"delta +0.00" da ayni sebepten hep sifirdi.

**Kullanicinin sordugu UI kodu.** `setAlignment(Qt.AlignCenter)` ab0ec01
(2026-08-15), `setGeometry(60, 60, 2000, 1100)` 1cf0c39 (2026-08-16),
`spotter_cmd_q=None` imzasi 018750b (2026-08-13). bc0a2fe bu satirlara
dokunmadi; `git diff a85dd9b~1 HEAD -- bukrek_main.py` tiklama yolunda
tek satir degistirmiyor. Sorun UI'da degil, komut cercevesinde.

#### 29.10.1 Duzeltmeler

| dosya / yer | ne | neden |
|---|---|---|
| `encoder_module.py` `sayac_cercevesine(hedef_enk, sayac_yaw, enk_yaw)` | YENI saf fonksiyon: hedefe (sayac - enkoder) farkini ekler, sarar | mutlak komutu Pi'nin cercevesine cevirir; test edilebilir |
| `bukrek_main.py` `_sayac_yaw_son` | YENI alan; `_update_current_angles` her raporda yazar | FAZ 6'da `current_yaw_angle` enkoder oldugu icin sayac ayrica tutulmali |
| `bukrek_main.py` `send_angle_command` | enkoder kontroldeyken yaw `sayac_cercevesine` ile cevrilir; fark 0.5 dereceyi asarsa konsola yazar | tiklama, gozcu yonelme, kalibrasyon: hepsi bu tek noktadan gecer |
| `bukrek_main.py` `_enkoder_kaydet` | sayac sutununa `_sayac_yaw_son` | FAZ 4 cozumlemesi yeniden calissin |
| `bukrek_main.py` `_bilgi_panelini_yenile` | delta = enkoder - gercek sayac | fark artik panelde gorunur |
| `motor_fire_module.py` (Pi) `ENCODER_SNAP_MAX_DEG` 10 -> 45 | hizalama 45 dereceye kadar uygulanir | 10-22 derecelik fark saatlerce kaliyordu; oran 2 oldugu icin +-90 icinde belirsizlik yok |
| `tests_yeni_mimari.py` 28 | donusum (fark yok / ileri / geri / sarma / bilinmiyor) + kaynak kontrolleri | |

Degismeyen: tiklama kodu, `_etiket_to_kare`, `_piksel_to_dunya`, UI
hizalamasi, delta komut yolu, FAZ 6'nin kendisi.

**Beklenti:** tiklama tiklanan yere gider (fark ne olursa olsun). Konsolda
"FAZ 6: mutlak yaw ... -> ..." satiri fark 0.5 dereceyi asinca gorunur;
Pi guncellenince fark 45 dereceye kadar durusta kendiliginden kapanir ve
bu satir nadirlesir.

### 29.11 `Aşama2Deneme.mp4` + `HedefKilit.mp4` — "yalpali kilit" (2026-09-17, FAZ 6 + cerceve duzeltmesi sonrasi)

Kayit `enkoder_20260917_174120.csv` (sayac sutunu yine gercek sayac).
Asama2: 17.7 sn, 3 sabit hedef (Fuze-Drone-Helikopter, altlarinda balon),
17:49:03-17:49:23. HedefKilit: 2.07 sn, Hedef Takip modu (gozcu yok, PID
tek basina 390 px'ten yaklasiyor), 17:53:04.6-17:53:06.6. Iki video da
30 fps'de kare kare okundu; durum cubugu ve baslik (yaw) seritleri
cikarildi; balonlarin goruntudeki konumu renk blob'uyla izlendi.

#### 29.11.1 Asama2 zaman cizelgesi (durum cubugundan)

| t (sn) | durum | not |
|---|---|---|
| 0.75 | YONELME +4.6 (su an -4.6) | gozcu devir teslimi |
| 1.25 | Taret yerlesti | enkoder 3.35, sayac 4.63: **1.28 derece eksik** |
| 1.5 | DOGRULAMA, hata 56 px | PID kalan yolu suruyor |
| 1.75 | KILIT Helikopter, 6 px | |
| 2.0 | ATES 1. atis | |
| 2.25-3.25 | imha dogrulaniyor, hata -14, -27, -17, -4, +6 px | taret 5.37 -> 4.64 -> 4.89 |
| 3.5 / 4.75 | 2. ve 3. atis (11 px, 6 px) | hata 3-17 px arasinda dolasiyor |
| 6.25 | YONELME -3.2 (Fuze) | |
| 7.25 | KILIT Fuze | 3 atis 7.5-10.5 |
| 11.75-13.0 | TARAMA "gozcude uygun aday yok" 1.25 sn | |
| 13.75 | DOGRULAMA Drone, hata 10 / 180 px | pitch 3.5 -> 1.1 iniyor |
| 14.4 | 1. atis, ham pitch hatasi 21 px | pitch hala hareketli (0.8 derece/sn) |
| 14.5-17.5 | 2. ve 3. atis; yaw hatasi +7..+34 px, taret 0.56 -> 2.00 sagra suruklenir | |

Balon blob izleme: Helikopter fazinda uc balonun birbirine uzakligi
237-250 px (+-6 px) — **balon sallanmiyor**. Yalpa taretin kendisi.

#### 29.11.2 Bulgular

**B30 — Devir teslim eksik iniyor (adim kaybi).** Pi 'set_angles' ile
sayacini hedefe goturuyor, fiziksel taret geride kaliyor: Asama2'de 1.28
derece (8 derecelik hareket), HedefKilit'te 50 Hz kayitta sayac 2.59'da
dururken enkoder 5.55 (**2.96 derece**, 10 derecelik hareket, ~40
derece/sn). Duruşta fark kalici, yani esneme degil adim kaybi. FAZ 6
oncesi bu gorunmezdi (PC sayaca inaniyordu). Sonuc: her devir teslimden
sonra PID 1-3 dereceyi ~1.6 derece/sn ile suruyor (1.3 sn kayip).

**B31 — Pi'nin "yeniden yaklasma"si PID ile kavga ediyor.** HedefKilit
17:53:06.36: taret durunca FAZ 5' hizalamasi sayaci 4.54 -> 7.05 yapti,
ardindan `ENCODER_REENGAGE` eski (bayat) hedef 4.54'e dogru servoyu
yeniden acti ve taret FIZIKSEL olarak 7.24 -> 4.26 gitti (3 derece
sapma), PID geri getirdi, 07.39'da ayni sey 1.1 derece ile tekrarlandi.
Bu tam olarak "hedefi asip geri gelme". Delta komutlari da hedefi
"gecerli" isaretledigi icin her durusta tetiklenebiliyor. FAZ 6 ile dis
dongu PC'de; Pi'nin ikinci bir denetleyici gibi davranmasi zararli.

**B32 — Hizli yaklasmada asim.** HedefKilit: hata 390 px'ten sifira,
sonra +113 px (1.6 derece) asim, geri donus, -45 px. Iki kaynak:
(a) `ENCODER_LAG_SEC` = 0.05 fazla: hareket halinde sayac-enkoder farkinin
adim kaybi disindaki kismi ~0.8 derece / 40 derece/sn = **~20 ms**.
Gecikme fazla yazilinca gecmis kaydi zamanda geriye kayar, `_angle_at`
kare anindaki aciyi ILERIDE okur, dunya acisi ileri kayar, taret asar.
ENKODER_ENTEGRASYON'daki "asiyorsa artir" notu YANLISTI, tersi dogru.
(b) `current_yaw_angle` ham son enkoder degeri; 40 derece/sn'de 20 ms =
0.8 derece bayat.

**B33 — Kilitte +-0.3-0.4 derece, ~1.5 sn periyotlu avlanma.** Asama2
Helikopter: 5.37 -> 4.64 -> 4.89 -> 5.50. Mekanizma: yon degisiminde
motor ~0.45 derece (32 px) bosluk boyunca doner, kafa kimildamaz; PC bu
surede her karede KP x hata delta gondermeye devam eder (3 kare x 0.2-0.35
derece); bosluk bitince kafa birikmis komut kadar gider = 15-35 px asim,
ters yonde ayni sey. Uzerine B31 biniyor. Balon sabit oldugu icin bu
yalpa tamamen tarete ait.

**B34 — Pitch hizi ates kapisinda yok.** Drone'a 1. atis pitch 3.5'ten
1.1'e inerken, ham pitch hatasi 21 px iken acildi (tolerans 10 px);
`FIRE_MAX_TURRET_RATE_DEG_S` yalniz yaw hizina bakiyor.

**B35 — Derece/piksel supheli.** Zemin sablonuyla olculen sahne kaymasi,
enkoderin ima ettigi kaymanin Helikopter fazinda ~%75'i, Drone fazinda
~%45'i (12 mm lens icin `HUNTER_DPP_YAW` = 0.01411 teorik). Ya DPP kucuk
(gercek ~0.018?) ya da kafa enkoderin dedigi kadar donmuyor. Ikisi de PID
kazancini dusurur (surunme) ve gozcu/tiklama hedefini kisa birakir.
Sahada 1 dakikalik test: manuel modda nisangahin 500 px sagina tikla;
hedef nisangaha tam oturmuyorsa DPP yanlis (eksik kaliyorsa DPP buyutulmeli).

**B36 — Adim kaybi hizla ilgili.** 40-50 derece/sn'de 10 derecelik
harekette 3 derece kayip. `SERVO_MAX_DEG_PER_SEC` = 50 (Pi). Kosum
olcumunde "|sayac - enkoder| en buyuk" bu kaybin gostergesi (tur 8: 3.64).

#### 29.11.3 Oneri (Paket 4) — uygulanmadi, kullanici karari bekleniyor

PC tarafi:
1. `ENCODER_LAG_SEC` 0.05 -> 0.02 (B32a); `current_yaw_angle` = enkoder +
   hiz x gecikme (B32b).
2. Kapali dongu YONELME: taret durdu ve |enkoder - hedef| > 0.5 derece ise
   mutlak komutu (cerceve donusumuyle) yeniden gonder, en fazla 3 kez (B30).
3. Ates kapisina pitch hizi (sayac gecmisinden) (B34).
4. Yon degisiminde bosluk enjeksiyonu: PC, komut isareti degisince o
   yonde bir kez `YAW_BACKLASH_DEG` (0.4) ekler; enkoder fazlasini duzeltir
   (B33). Bayrakla, kapatilabilir.
5. DPP saha testi (B35); gerekirse `HUNTER_DPP_YAW` olculen degere.

Pi tarafi (elle yuklenecek):
6. `ENCODER_REENGAGE = False` (B31) — en onemli Pi degisikligi.
7. `ENCODER_SNAP_MAX_DEG` 10 -> 45 (29.10, hala yuklenmemis olabilir).
8. `SERVO_MAX_DEG_PER_SEC` 50 -> 30 denemesi; kosum_olc ile |sayac-enkoder|
   en buyuk degeri 1 derecenin altina inene kadar (B36).

#### 29.11.4 Paket 4 UYGULANDI (2026-09-17)

| dosya / yer | ne | onceki -> simdi | neden |
|---|---|---|---|
| `config.py` `ENCODER_LAG_SEC` | gecikme | 0.05 -> 0.02 | olculen rapor gecikmesi ~20 ms; fazlasi asim yapiyor (B32a) |
| `config.py` `ENCODER_RATE_EXTRAPOLATE` | yeni | True | `current_yaw_angle` = enkoder + hiz x gecikme (B32b) |
| `config.py` `YONELME_TEKRAR_MIN_DEG / _MAX / _ARALIK_SEC / YONELME_DURUS_HIZI_DEG_S` | yeni | 0.5 / 3 / 0.3 / 1.5 | kapali dongu yonelme (B30) |
| `config.py` `YAW_BACKLASH_DEG`, `PITCH_BACKLASH_DEG` | yeni | 0.4, 0.0 | bosluk enjeksiyonu (B33); 0 = kapali |
| `encoder_module.py` `hiz_isaretli()` | yeni saf fonksiyon | | isaretli hiz; ileri alma ve kapi icin |
| `encoder_module.py` `bosluk_enjeksiyonu()` | yeni saf fonksiyon | | yon degisiminde bir kez bosluk ekler; testli |
| `bukrek_main.py` `_update_encoder_state` | isaretli hiz + ileri alma | | ham enkoder 20 ms bayat |
| `bukrek_main.py` `_angajman_adimi` TARAMA/YONELME | tekrar sayaci; durunca ve >0.5 derece uzaksa mutlak komut yeniden | | Pi adim kacirinca eksik inis (B30); hareket halinde gonderilmez |
| `bukrek_main.py` `_taret_pitch_hizi`, `_taret_hizi` | yeni; ates kapisina max(yaw, pitch) | | pitch inerken ates acilmasin (B34) |
| `bukrek_main.py` `process_tracking` | MAX sinirindan sonra bosluk enjeksiyonu | | B33 |
| `bukrek_main.py` `send_angle_command` | son hareket yonu guncellenir | | mutlak komuttan sonraki ters delta da bosluk gecer |
| `motor_fire_module.py` (Pi) `ENCODER_REENGAGE` | | True -> False | hizalama sonrasi bayat hedefe yeniden yaklasma PID ile kavga (B31) |
| `motor_fire_module.py` (Pi) `SERVO_MAX_DEG_PER_SEC` | | 50 -> 30 | 40-50 derece/sn'de 10 derecede 3 derece adim kaybi (B36) |
| `tests_yeni_mimari.py` 29 | hiz, bosluk dizisi, config, kaynak, Pi hizalama-sonrasi servo kapali | | |

**Sahada bakilacaklar:** konsolda "YONELME tekrar N" satirlari (1-2 olmali,
3'e dayaniyorsa DPP/gozcu sorunu); `kosum_olc.py` "|sayac - enkoder| en
buyuk" < 1 derece (hiz 30 yeterli mi); kilitte yaw yon degisimi sayisi ve
RMS dusmeli; "taret hareketli" gerekcesi pitch inerken de gorunmeli.
Bosluk enjeksiyonu asim yaratirsa `YAW_BACKLASH_DEG` 0.25'e dusur, hala
avlanma varsa 0.6'ya cikar; 0 kapatir.

### 29.12 `aşama2son.mp4` — "merkezden takip edemiyoruz" (2026-09-23, Paket 4 sonrasi)

31.2 saniye, Asama 2, 3 hedef (F16 / Drone / Fuze), silah ve kamera
kalibrasyonu kullaniciya gore tamam (15 metrede sapma 1-2 cm). Video 30
fps'de kare kare okundu; baslik cubugu (yaw + enkoder) ve durum cubugu
(durum, nisan hatasi px) seritleri cikarildi. Enkoder kaydiyla eslestirme:
video t=0 = `enkoder_20260923_164354.csv` icinde 16:44:46 (4 fps'te okunan
64 yaw degeri ile arama, ortalama fark 0.133 derece).

**Iyi haber once: DATASET GERCEKTEN DUZELDI.** Kilit suresince sinif bir kez
bile kaymadi — F16 angajmani boyunca "dusman-F16", Drone boyunca
"dusman-Drone", Fuze boyunca "dusman-Fuze". Onceki kosumda (29.9) maket
karelerin %45'inde Fuze, %20'sinde Helikopter, %15'inde Drone, %18'inde
balon etiketi aliyordu ve her kayma kilidi dusuruyordu. `[capa]` yazisi tum
videoda yalnizca 2 karede gorundu, yani balon capasina neredeyse hic
ihtiyac kalmadi. Guvenler 0.85-0.95.

#### 29.12.1 Olculen: nisan hatasi HIC sifiri gecmiyor

Kullanicinin isaret ettigi 2.96-6.56 sn araligi (F16 takibi), durum
cubugundan 15 fps'te 56 ornek:

| olcum | deger |
|---|---|
| yaw nisan hatasi | ort **+14.1 px**, medyan +14, aralik +2 .. +24 |
| isaret degisimi | **0** (56 karenin hepsi ayni tarafta) |
| 10 px tolerans icinde | karelerin **%25**'i |
| pitch nisan hatasi | ort -6.5 px (o da tek tarafli) |
| hedefin gercek acisal hizi | 0.44 derece/sn |
| taretin tamamen durdugu kare | **%55** |
| taret hareketi | 0.1-0.4 derecelik basamaklar, aralarinda 0.3-0.7 sn duraklama |

Yani taret hedefi ortalamada yakaliyor (1.7 derece / 3.6 sn = 0.47 derece/sn
vs hedefin 0.44) ama bunu MERDIVEN cikarak yapiyor: duruyor, hata birikiyor,
firliyor. Nisangah hedefin uzerine ancak salinimin bir fazinda denk geliyor
ve ates tam o anda aciliyor — kullanicinin "ortaya denk geldigi an sikiyor"
gozlemi birebir dogru.

#### 29.12.2 Kok neden zinciri (dordu birden)

**B37 — Olu bant feedforward'i da olduruyordu ve suzgec hafizasini siliyordu.**
`output = KP*hata + ... + feedforward` tek bir toplamdi ve olu bant bu
TOPLAMI sifirliyordu. Hedef hareketliyken hata bandin altina duser dusmez
taret tamamen duruyor. Ustune 29.6'da eklenen "olu banda girince suzgec
hafizasini bosalt" kurali vardi: tek karelik bir dip bile hafizayi siliyor,
cikinca suzgec sifirdan rampa yapiyor ve
`ilk gonderilebilir komut = MIN_OUTPUT / (a x KP)` esigine ulasana kadar
4-5 kare (0.30 sn) HIC komut gitmiyordu. Olculen %55 durus ve 0.3-0.7 sn'lik
duraklamalar tam olarak bu.

**B38 — Feedforward'in birimi yanlisti, o yuzden kapaliydi.** Eski formul
`ff = hiz x LEAD_TIME x GAIN` bir KONUM (derece) uretiyordu ama bu deger HER
KAREDE delta komut olarak gonderiliyordu. Delta komutta taret hizi
`delta x kare_hizi` oldugu icin eski formul taret hizini hedefin
`0.22 x 0.8 x 15 = 2.6 KATINA` cikariyordu. "Feedforward acinca taret
savruluyor" deneyimi (Paket 1'de kazancin 0'a cekilme sebebi) fikrin degil
birimin hatasiydi. Ayrica `FEEDFORWARD_VELOCITY_DEADBAND = 1.0` derece/sn
idi ve hedefin gercek hizi 0.44 derece/sn — yani kazanc acik olsa bile
feedforward karelerin %87'sinde TAM SIFIR olurdu.

**B39 — Hedefin olu zaman boyunca gittigi yol telafi edilmiyordu.**
`_angle_at(capture_t)` TARETIN kare cekilirkenki acisini telafi ediyor ama
HEDEFIN o andan beri gittigi yolu etmiyor. Kalan hata = hedef_hizi x
olu_zaman. `FEEDFORWARD_LEAD_TIME` yorumundaki 0.22 sn'lik saha olcumu
(kalan piksel hatasi / hedef hizi, 14 kesitte ayni cikmis) tam olarak budur
ama hicbir yerde KULLANILMIYORDU.

**B41 — Esik altindaki komutlar sessizce atiliyordu.** `MIN_OUTPUT_PIXELS`
altindaki cikis sifirlaniyor ve KAYBOLUYOR. Pi de ayni seyi yapiyor:
`set_proportional_angles_delta` hedefi her karede MEVCUT aciden yeniden
kurdugu icin yarim adimlik artik oraya da tasinmiyor. 0.44 derece/sn'de
kare basina gereken komut 15 fps'te 2.0 px, 30 fps'te 1.0 px — esik 4 px
oldugu icin ikisi de atiliyor. Bu yuzden **kare hizini yukseltmek tek
basina takibi iyilestirmezdi**, once bu duzelmeliydi.

**B40 — Kamera 15 fps.** Baslik cubugundaki kare sayaci: 236 kare / 15.75 sn
= 15.0 fps. Kod `CAP_PROP_FPS`'e hic dokunmuyordu, surucu varsayilani
geliyordu. Denetim dongusu kamera hizinda calistigi icin bu, komutlar arasi
67 ms ve takibin basamakli gorunmesinin yapisal tavani.

**B42 — Suzgec katsayisi kare hizina bagliydi.** `PID_OUTPUT_SMOOTHING`
KARE BASINA tanimli; 15 fps'te ayarlanmisti. 30 fps'te ayni katsayi suzgeci
gercek zamanda iki kat hizlandirip sonumu dusuruyor (benzetimde 9 derece/sn
hedefte hata 28.6 -> 35.5 px). Kare hizini yukseltmeden once bu da
duzelmeliydi.

#### 29.12.3 Benzetim: olculen 14 px yeniden uretildi

Gercek zinciri taklit eden kapali dongu benzetimi (olu bant -> suzgec ->
MIN_OUTPUT -> MAX, 0.15+1/fps saniyelik olu zamanli geri besleme)
`tests_yeni_mimari.py` 30. bolume eklendi. Sonuclar (kalici yaw hatasi, px):

| hedef hizi | ESKI (15 fps) | YENI (15 fps) | YENI (30 fps) |
|---|---|---|---|
| 0.44 derece/sn (sahadaki F16) | **+15.6** (olculen +14.1) | +3.1 | +2.1 |
| 1.5 derece/sn | +31.4 | +0.8 | +1.0 |
| 4 derece/sn | +83.7 | +12.7 | +11.1 |
| sabit hedef | 0.0 | 0.0 | 0.0 |

Benzetimin eski ayarla sahadaki sayiyi yeniden uretmesi, mekanizmanin dogru
teshis edildiginin kanitidir.

#### 29.12.4 Videodaki diger bulgular

- **Devir teslim hala uzak biniyor.** YONELME sonrasi DOGRULAMA/KILIT
  anindaki hatalar: 142, 153, 162, 126 px (~2 derece). Paket 4'un kapali
  dongu yonelmesi calisti ("tekrar 1" durum cubuginda goruldu) ama bir
  tekrar yetmemis.
- **Ates penceresinde hata cok buyuyor.** "imha dogrulaniyor" sirasinda
  20, 45, 56, 60, 67, 84 px'e kadar cikan hatalar var; "Ates engellendi:
  nisan tolerans disinda" 22 kez ust uste sayilip **hedef birakiliyor**
  ("Ates aclamiyor — hedef birakiliyor"). Sebeplerden biri asagidaki.
- **"cifte balon eslesmemis (nisan noktasi tahmini)"** gerekcesi goruldu:
  balon esleismeyince nisan noktasi maketten TURETILIYOR ve her kaynak
  degisimi nisan noktasinda sicrama uretiyor.
- **"ATES — None (3. hedef, 2. atis)"**: durum metninde sinif None. Kilitli
  cift kaybolmusken ATES durumunda kalinmis; zararsiz ama hedefin gercekten
  ne oldugu belirsiz.
- **Hedef kaybi tahmini** bir kez devreye girdi ("tahminle takip, 7 kare
  kaldi") ve toparladi.

#### 29.12.5 Paket 5 UYGULANDI

| dosya / yer | ne | onceki -> simdi | neden |
|---|---|---|---|
| `config.py` `FEEDFORWARD_GAIN` | birim degisti, acildi | 0.0 -> 1.0 | ff artik `hiz x delta_time`; 1.0 = tam hiz eslemesi (B38) |
| `config.py` `FEEDFORWARD_VELOCITY_DEADBAND` | | 1.0 -> 0.30 | gercek hedef hizi 0.44; eski bant ff'i %87 kapatiyordu (B38) |
| `config.py` `FEEDFORWARD_MAX_DEGREE` | | 5.0 -> 1.0 | yeni formulde ust sinir zaten 2 derece |
| `config.py` `FEEDFORWARD_MAX_STEP_DEGREE` | | 0.25 -> 0.10 | yeni ff eskisinin 0.38'i; eski sinir hic baglamiyordu |
| `config.py` `TARGET_LEAD_TIME_SEC`, `TARGET_LEAD_MAX_DEG` | yeni | 0.15, 0.6 | hedefin olu zamanda gittigi yol (B39) |
| `config.py` `PID_DEADBAND_PIXELS` | | 7.0 -> 5.0 | olu bandin maliyeti hareketli hedefte kalici hata (B37) |
| `config.py` `PID_DEADBAND_SETTLE_FRAMES` | yeni | 3 | hafiza ancak hedef GERCEKTEN durunca silinir (B37) |
| `config.py` `MIN_OUTPUT_PIXELS` | | 4.0 -> 2.5 | ~1 motor adimi; artik artik kaybolmuyor (B41) |
| `config.py` `PID_SMOOTHING_REF_FPS` | yeni | 15.0 | suzgec katsayisi kare suresiyle olceklenir (B42) |
| `config.py` `HUNTER_FPS`, `SPOTTER_FPS` | yeni | 30 | kare hizi artik ISTENIYOR (B40) |
| `camera_module.py` kamera acilisi | `CAP_PROP_FPS` ayarlaniyor | | B40 |
| `bukrek_main.py` `process_tracking` PID | cikis P/I/D ve feedforward olarak AYRILDI; ff olu bant ve suzgecin disinda, en sonda ekleniyor | | B37/B38 |
| `bukrek_main.py` olu bant | `_olu_ardisik_*` sayaci; hafiza yalniz yerlesince silinir | | B37 |
| `bukrek_main.py` hata hesabi | hedefin dunya acisina konum ondelemesi (`world_yaw` HAM kalir) | | B39 |
| `bukrek_main.py` MIN_OUTPUT | esik alti artik `_min_kalan_*` ile birikiyor | | B41 |
| `bukrek_main.py` suzgec katsayisi | `delta_time` ile olcekleniyor | | B42 |
| `tests_yeni_mimari.py` | olu bant olcutu yeniden tanimlandi; kuyruk/hafiza kontrolleri guncellendi; 30. bolum (kapali dongu benzetimi, esik birikimi, kaynak kontrolleri) | | |

**Ayar sirasi (biri digerini maskeler, teker teker degistirin):**
1. Taret hedefin ONUNE geciyorsa once `TARGET_LEAD_TIME_SEC` 0.10'a, sonra
   gerekirse `FEEDFORWARD_GAIN` 0.8'e.
2. Taret GERIDE kaliyorsa `FEEDFORWARD_GAIN` 1.2, sonra
   `TARGET_LEAD_TIME_SEC` 0.20.
3. Kilitte titreme/avlanma baslarsa `PID_DEADBAND_PIXELS` 7.0'a geri,
   sonra `FEEDFORWARD_VELOCITY_DEADBAND` 0.5.
4. Kamera 30 fps vermiyorsa (acilis satirinda yazar) `HUNTER_USE_MJPG`
   True denenir; goruntu bozulursa geri alinir.

### 29.13 `aşama2Son1.mp4` — Paket 5 sonrasi KARARSIZLIK (2026-09-23 aksam)

34.8 saniye, Asama 2, 3 hedef. Kayit `enkoder_20260923_191030.csv`;
video t=0 = 19:24:36.38 (4 fps'te okunan 36 yaw degeriyle arama, ortalama
fark **0.032 derece** — eslesme kesin). Sonuc: **4 atis, 0 imha.**

Kullanicinin kritik gozlemi: **ayni kodla bundan onceki kosumda uc hedefin
ucu de 10 metreye gelmeden vuruldu.** Yani kod bozuk degil, sistem KARARSIZ.

#### 29.13.1 Olculen

| olcum | aşama2son (29.12, Paket 4) | aşama2Son1 (Paket 5) |
|---|---|---|
| kilitte titresim RMS | 0.27 derece | **0.75-0.79 derece** |
| kilitte tepeden tepeye | ~0.6 derece | **5.1-6.2 derece** |
| nisan hatasi isaret degisimi | **0 / 56 kare** | surekli (+56 .. -61 px) |
| komut yon degisimi (kilit) | — | **50 / 271** ve **47 / 248** |
| baskin salinim frekansi | — | **0.72-0.92 Hz** |
| imha | 3 (bir onceki kosumda) | **0** |

Durum cubugundan okunan nisan hatasi dizisi (Fuze kilidi): -19, -8, 13,
-17, 8, -8, -2, -28, 3, -21, 4, 34, 27, -1, 24, 35, -25, 56, -1, -26, 2,
-25, 27, 26, 21, -18, 23, 5, -29 px. 29.12'deki tek tarafli +14 px'lik
kalici hatanin yerini simetrik bir SALINIM almis.

#### 29.13.2 B43 — Kok neden: bosluk enjeksiyonu bir ROLE

Paket 4'te eklenen `YAW_BACKLASH_DEG = 0.4` (29.11 B33), komut isareti her
degistiginde tarete **0.4 derece = 28 piksellik** bir tekme atiyor. Bu bir
role (relay) nonlineeritesidir:

1. Tespit gurultusu (~3 px) nisan hatasinin isaretini dondurur.
2. Role 28 px'lik tekmeyi atar, hata ters tarafa gecer.
3. Isaret yine doner, tekme yine gelir. Dongu kendini besler.

Olu zamanli bir dongude role tipik olarak `1/(4T)` frekansinda limit cevrim
uretir: T = 0.22 sn -> **1.1 Hz**. Sahada olculen baskin frekans
**0.72-0.92 Hz**. Benzetim (tests 31. bolum, ayni gurultu ve ayni sabitler):

| kosul | hata std | tepeden tepeye | isaret degisimi |
|---|---|---|---|
| enjeksiyon KAPALI, gurultu 3 px | 2.0 px | 9.0 px | 32 |
| enjeksiyon 0.4 derece, gurultu 3 px | **12.7 px** | **40.7 px** | 44 |
| enjeksiyon 0.4 derece, gurultu YOK | 1.0 px | 2.1 px | **0** |

Son satir **ikili davranisin aciklamasi**: enjeksiyon yalnizca isaret
degisirse tetiklenir. 29.12 olcumunde hata 56 karede hic isaret
degistirmemisti (tek tarafli +14 px), yani role hic devreye girmedi ve o
kosum duzgun gecti. Paket 5 dongunun tepkisini artirinca hata sifiri
gecmeye basladi ve role kilitlendi. "Ayni kodla bir kosum mukemmel, digeri
felaket" tam olarak budur.

Ayrica enjeksiyon FAZ 6 ile **cifte telafi**: enkoder kafanin kimildamadigini
zaten soyluyor, denetleyici komut vermeye devam ediyor, bosluk kapali
dongude kendiliginden kapaniyor.

**Duzeltme: `YAW_BACKLASH_DEG` 0.4 -> 0.0.** Mekanizma kodda duruyor, sabit
sifir; test sifir oldugunu guvenceye aliyor.

#### 29.13.3 B44 — Ates kapilari yanlis seyi olcuyordu

`FIRE_MAX_TURRET_RATE_DEG_S = 3.0` ve `FIRE_MAX_TARGET_RATE_DEG_S = 2.0`
MUTLAK hizlara bakiyordu. Ama hedefi duzgun takip eden bir taret, hedefin
hizinda doner — yani kapilar tam da istenen davranisi ("hedefle birlikte
giderken sik") imkansiz kiliyordu. Sahada gorulen gerekceler:
"taret hareketli: 3.2 derece/sn", "hedef hareketli: 2.8 derece/sn".

Isabeti belirleyen sey mutlak hiz degil, mermi ucusu (~0.25 sn) boyunca
nisan noktasinin hedefe gore **ne kadar kayacagi**. Taret hedefle birlikte
kusursuz giderse bu sifirdir; taret salinyorsa buyuktur.

Yeni kapi: `|hata_degisim_hizi| x FIRE_SHOT_LATENCY_SEC <=
FIRE_MAX_ERROR_DRIFT_PIXELS` (10 px). Eski kapilar emniyet sinirina cekildi
(taret 12, hedef 8 derece/sn) — yalnizca devir teslim slew'ini ve elle
savrulan hedefi keserler.

#### 29.13.4 B45 — Balon tespiti titriyor, ates bu yuzden kesiliyor

F16 kilidinde durum cubugu **kare kare** "balon VAR" / "BALON YOK" arasinda
gidip geldi (karelerin yaklasik yarisi). Balon 15 metrede yalnizca ~30
piksel. Bunun iki sonucu var:
- `ates_serbest_mi` iki ayri kosulda ("cifte balon eslesmemis", "balon bu
  karede tespit edilmedi") atesi kesiyor. Sahada "cifte balon eslesmemis
  (nisan noktasi tahmini)" gerekcesi 22'lik butcenin 3, 5, 15, 20.
  karelerinde sayildi ve hedef birakildi.
- BALON YOK karelerinde nisan noktasi maketten turetildigi icin pitch
  hatasi siciriyor (-60, +27, +22, -31 px ardisik karelerde).

Balon 0.2 saniyede kacamayacagina gore **son 3 karede gercekten gorulmus
olmasi** ates icin yeterli sayiliyor (`FIRE_BALLOON_GRACE_FRAMES = 3`);
nisan noktasi o sirada `nisan_ofseti` ile balonun **en son olculen** yerinden
turetiliyor, yani hayali bir noktaya degil son gercek olcume ates ediliyor.
Kimlik kontrolu (dusman_mi, dost gorunumu) degismedi.

#### 29.13.5 Diger gozlemler

- **Kamera 30 fps'i kabul etmedi.** Baslik cubugundaki kare sayaci: 13114
  (t=0) -> 13615 (t=33.5) = 501 kare / 33.5 sn = **14.96 fps**. Paket 5'te
  eklenen `CAP_PROP_FPS = 30` istegi surucu tarafindan yok sayilmis.
  Sonraki adim: `HUNTER_USE_MJPG = True` denemek (acilis satirinda
  gerceklesen format ve fps yaziliyor).
- **Ekrandaki "Hata" ile ates karari ayni sayi degil.** Durum cubugundaki
  "Hata: Yaw Xpx" HAM piksel hatasi (kare cekilme anindaki), ates karari ise
  olu zaman telafili hatayi kullaniyor. Operator "tolerans icinde gorunuyor
  ama sikmiyor" diye okuyor. Durum cubuguna artik **kayma** (mermi ucusu
  boyunca beklenen kayma / sinir) yaziliyor; ates kararini belirleyen sayi
  bu.
- **Devir teslim hala uzak biniyor**: YONELME sonrasi ilk hatalar 166 px,
  104 px. Son hedefte (Drone) sistem hedefi tamamen kaybetti
  ("KILIT — hedef bu karede yok (0 kayit)" dort kare ust uste).

#### 29.13.6 Paket 6 UYGULANDI

| dosya / yer | ne | onceki -> simdi | neden |
|---|---|---|---|
| `config.py` `YAW_BACKLASH_DEG` | **kapatildi** | 0.4 -> 0.0 | role gibi davranip 0.72-0.92 Hz limit cevrim uretiyordu (B43) |
| `config.py` `TARGET_LEAD_TIME_SEC` | | 0.15 -> 0.10 | ondeleme hiz gurultusunu hataya tasiyor; marj birakildi |
| `config.py` `FIRE_MAX_TURRET_RATE_DEG_S` | emniyet sinirina cekildi | 3.0 -> 12.0 | hedefle birlikte donen taret ates edebilmeli (B44) |
| `config.py` `FIRE_MAX_TARGET_RATE_DEG_S` | emniyet sinirina cekildi | 2.0 -> 8.0 | ayni gerekce (B44) |
| `config.py` `FIRE_SHOT_LATENCY_SEC`, `FIRE_MAX_ERROR_DRIFT_PIXELS` | yeni | 0.25, 10.0 | asil isabet kapisi: nisan hatasinin ucus boyunca kaymasi (B44) |
| `config.py` `FIRE_BALLOON_GRACE_FRAMES` | yeni | 3 | balon tespiti kare kare titriyor (B45) |
| `engagement.py` `ates_serbest_mi` | `hata_hizi` ve `balon_yakin` parametreleri; kayma kapisi; balon grace | | B44, B45 |
| `bukrek_main.py` `process_tracking` | nisan hatasinin degisim hizi (EMA) olculuyor; balon kayip kare sayaci | | B44, B45 |
| `bukrek_main.py` `_balon_yakin_zamanda()` | yeni | | B45 |
| `bukrek_main.py` KILIT durum metni | "balon N kare once" ve "kayma X/Y px" | | operator ates sebebini ekrandan gorsun |
| `tests_yeni_mimari.py` 31 | role benzetimi (enjeksiyon acik/kapali/gurultusuz), ates kapilari, balon grace, kaynak kontrolleri | | |

**Beklenti:** kilitte titresim 0.75 dereceden 0.25 derece altina inmeli
(role kalkinca benzetim 12.7 px -> 2.0 px veriyor); nisan hatasi salinim
yerine tek tarafli kucuk bir artiga donmeli; hedefle birlikte giderken ates
serbest kalmali.

**Sahada bakilacaklar:** durum cubugunda "kayma X/10 px" — X surekli 10'un
ustundeyse takip hala salinyor demektir (once `TARGET_LEAD_TIME_SEC` 0.05,
sonra `KP_YAW` 0.55). "balon N kare once" yazisi sik gorunuyorsa balon
tespiti dataset isi. `kosum_olc.py` ile titresim RMS < 0.25 derece.
