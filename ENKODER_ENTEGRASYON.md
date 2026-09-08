# Yaw Enkoder Entegrasyonu — Sıralı Yapılacaklar

> **GÜNCEL DURUM (2026-09-08): ENKODER OKUNDU.** Montaj yapıldı, 12 V harici
> besleme, Waveshare üzerinden Pi'de konum akışı alındı (`~/enk_ham.py`).
> Sıradaki adım: **2.2–2.4** (SDO ile çözünürlük/tur sayısı) ve 10° ölçümü.

**Amaç:** yaw ekseninde dişli boşluğundan kaynaklanan açı hatasını ölçmek ve düzeltmek.

**Neden sadece yaw:** pitch ekseninde direkt tahrik + 1:5 planet redüktör var; ölçümde
pitch RMS 0.9 px çıktı (yaw 10.7 px). Pitch'te sorun yok, **dokunulmayacak**.

**Donanım:**

| parça | model | not |
|---|---|---|
| enkoder | Wachendorff **WDGA 36A-06-1200-COA-B00-CB5** | mutlak, CANopen |
| çözünürlük | **12 bit** singleturn (4096 adım/tur) | sipariş kodundaki `12` |
| multiturn | **YOK** | sipariş kodundaki `00` |
| arayüz | CANopen, CiA 406 V3.2 class C2 | node ID varsayılan **127** |
| dönüştürücü | Waveshare **USB-CAN-A** (CH340) | `/dev/ttyUSB0`, slcan ile `can0` oldu |
| bağlantı | 1:3 dişli, boşluksuz kasnak | step motorla aynı oran |

**Ölçüler:**

```
enkoder adımı              0.0879°
1:3 dişli ile taret        0.0293°
kamera                     0.0143°/piksel   -> enkoder 2 kat kaba
ölçülecek boşluk       ~   0.153°           -> enkoder 5 adımda görür
taret aralığı            ±90°  ->  enkoder ±270°  -> SARMA VAR, tur takibi gerekli
```

---

## FAZ 0 — DONANIM (kod yok)

- [ ] **0.1** Enkoder beslemesi hazırla (4.75–32 V, 50 mA). Pi'nin 5V pini yeterli —
      servo gibi 1–2 A çekmiyor. GND'ler ortak olmalı.
- [ ] **0.2** M12 5-pin kabloyu bağla:
      `pin1 Vcc(+)` · `pin2 GND` · `pin3 CAN_H` · `pin4 CAN_L` · `pin5 CAN_GND`
- [ ] **0.3** Waveshare üzerindeki **OFF/ON anahtarını ON** yap
      (120 Ω sonlandırma; sipariş kodunda `AEO` yok = enkoderde dahili direnç YOK)
- [ ] **0.4** Enkoderi 1:3 dişliyle taretin dönen üst gövdesine bağla, kasnağı boşluksuz sık
- [ ] **0.5** Enkoder şaftına radyal yük binmediğini kontrol et (max 80 N, ama hizasızlık
      rulmanı öldürür — esnek kaplin kullanılabilir)

## FAZ 1 — HAT KURULUMU ve DOĞRULAMA (kod yok, sadece komut)

- [x] **1.1** ~~`can0` / slcan~~ **ÇALIŞMADI, TERK EDİLDİ.** Waveshare USB-CAN-A slcan
      konuşmuyor: `slcand` arayüzü kurar ama tele hiçbir şey çıkmaz (candump'taki
      `080` satırları yalnızca çekirdek yankısıydı). `python-can`'in `seeedstudio`
      sürücüsü de tele çıkmadı. **Çalışan yol: Waveshare'in kendi seri protokolü**
      (`0xAA 0x55 0x12 …` ayar çerçevesi, `0xAA 0xCx id data 0x55` veri çerçevesi,
      seri 2 000 000 baud). `encoder_module` bu protokolle yazılacak; SocketCAN yok.
      ```bash
      sudo slcand -o -c -s6 /dev/ttyUSB0 can0 && sudo ip link set can0 up
      ```
      Not: `ip -d link` çıktısında `bitrate 0` görünmesi **normaldir** — slcan'de
      hızı `slcand`'ın `-s6` parametresi belirler, çekirdek bilmez. Arayüzün
      oluşması hattın çalıştığını **kanıtlamaz**; kanıt 1.2'dedir.
- [ ] **1.2** Trafiği dinle, bu sırada enkoderin gücünü kes-ver:
      ```bash
      timeout 15 candump -td can0
      ```
      Beklenen: `77F [1] 00` (boot-up) ve/veya `1FF [4] ...` (pozisyon)
- [ ] **1.3** Sessizse NMT start dene: `cansend can0 000#0100`
- [ ] **1.4** Hâlâ sessizse bit hızlarını sırayla dene: `-s5` (250k), `-s4` (125k)
- [ ] **1.5** **Karar noktası:** veri geliyorsa slcan yolu kullanılacak.
      Gelmiyorsa Waveshare'in kendi seri protokolü yazılacak (plan B, `encoder_module`
      içinde kalır, üst katman etkilenmez)
- [ ] **1.6** `slcand`'ı kalıcı yap: systemd servisi ya da `rc.local`.
      **Pi her açılışta `can0` kendiliğinden gelmeli**, yoksa saha koşumunda unutulur

## FAZ 2 — ENKODERİ TANI (kod: küçük tanılama aracı)

- [ ] **2.1** `encoder_tani.py` yaz (Pi'de çalışan, `servo_tani.py` tarzı bağımsız araç)
- [ ] **2.2** SDO ile cihaz kimliğini oku: `0x1018` (vendor, product, revision, serial)
- [ ] **2.3** **`0x6501` oku** → bir turdaki adım sayısı. Sipariş kodundan beklenen **4096**
- [ ] **2.4** **`0x6502` oku** → ayırt edilebilir tur sayısı. Beklenen **1** (multiturn yok).
      1'den büyükse şansımız var, sarma sorunu yok demektir
- [ ] **2.5** **16 bit denemesi:** `0x6001` (measuring units per revolution) SDO ile
      **65536** yazılmayı dene, sonra `0x6501`'i tekrar oku.
      Kabul edilirse çözünürlük 4 katına çıkar (0.0293° → 0.0073°) ve kameradan
      **hassas** hale gelir. Reddedilirse 12 bit ile devam, sorun değil
- [ ] **2.6** PDO periyodunu ayarla: `0x1800` alt-indeks 5 (event timer) → **10 ms**.
      SDO talep-yanıt yavaş kalır; kontrol döngüsü için PDO şart
- [ ] **2.7** Ayarları kalıcı kaydet: `0x1010` (store parameters) — yoksa her güç
      kesintisinde tekrar ayarlamak gerekir
- [ ] **2.8** Ölçülen değerleri buraya yaz: çözünürlük ___ , multiturn ___ , node ID ___

## FAZ 3 — SADECE OKU ve GÖSTER (kontrol değişmiyor)

> Bu fazın sonunda sistem **aynen eskisi gibi** çalışıyor olacak; enkoder yalnızca
> ekranda görünecek. Amaç veriye güvenmeden önce onu izlemek.

- [x] **3.1** `encoder_module.py` yaz (Waveshare seri protokolu, SocketCAN yok) (Pi tarafı, yeni dosya):
      - `baslat()` / `kapat()`
      - `_ham_oku()` — CAN'dan ham adım
      - `_sarma_takibi()` — 360° sarmasını çöz (eşik 180°, pay 48 kat)
      - `taret_acisi()` — ham → tur → **/3 dişli** → ofset → derece
      - `sifirla()` — mevcut açıyı sıfır kabul et
      - `saglikli_mi()` — son veri yaşı; **kopukluk sessizce yutulmamalı**
- [x] **3.2** `motor_fire_module.py` sabitleri ekle:
      `ENCODER_ENABLED`, `ENCODER_BITS`, `ENCODER_GEAR_RATIO = 3.0`,
      `ENCODER_OFFSET_DEG`, `ENCODER_INVERT`
- [x] **3.3** `rpi_motor_server.py`: başlatmada `encoder_module.baslat()`,
      kapanışta `kapat()`
- [x] **3.4** `angle_sender_loop` yanıtına iki alan ekle: `encoder_yaw`, `encoder_ok`
      (mevcut `current_yaw` **DEĞİŞMEYECEK** — hâlâ adım sayımından)
- [x] **3.5** PC tarafı `bukrek_main.py`: bilgi paneline enkoder açısını ve **farkı** yaz:
      `Yaw 12.3° (enk 12.1°, Δ0.2°)`
- [x] **3.6** Enkoder düşerse durum çubuğunda uyar
- [ ] **3.7** **Sahada doğrula:** tareti elle sağa-sola sür, iki açı birlikte hareket
      ediyor mu, yön doğru mu (`ENCODER_INVERT` gerekebilir), ölçek doğru mu

## FAZ 4 — BOŞLUĞU ÖLÇ — YAPILDI (2026-09-08)

Kayıt: `config.ENCODER_LOG=True` → `enkoder_kayit/*.csv`; çözümleme
`python enkoder_analiz.py <csv>`. Saha koşusu 0 → +60 → −62, 10°'lik adımlar,
20 duruş:

```
ÖLÇEK    a = 0.997      -> R = 2.0 DOĞRU, ölçek sorunu yok
BOŞLUK   1.49 derece    -> + yönden gelince Δ ≈ +1.2, − yönden gelince Δ ≈ +2.7
KAÇIRMA  0.46 derece RMS, max 1.0  -> rastgele, ölçülüp telafi EDİLEMEZ
sabit    +1.2 derece    -> sıfırlamadan sonraki ilk hareketle geldi, kalıcı
```
Adım sayacı koşu boyunca gerçeği 0.7–3.6° yanlış biliyordu.

- [x] 4.1–4.3 ölçüm (tek koşu; hız değişimi denenmedi, gerekirse tekrar)
- [x] 4.4 sonuç `motor_fire_module` FAZ 5' yorumuna yazıldı
- [x] 4.5 kayıt `enkoder_kayit/enkoder_20260908_203459.csv` (git dışı)

## FAZ 5' — DURUNCA HİZALA — YAPILDI (2026-09-08)

Plan "ölç, ileri besle" idi; rastgele 0.46°'lik kısım ileri beslemeyle
düzelmediği için yerine **enkodere hizalama** kondu:

- taret **duruyorken** (ENCODER_REST_SEC = 0.15 sn adım yok, servo/manuel/
  bloklayan hareket yok) `_simulated_yaw := enkoder`
- fark < 0.05° → dokunma; fark > 10° → şüpheli, uygulanmaz, uyarı
- o an geçerli bir **otonom** hedef varsa ve kalan > 0.10° → servo tekrar
  açılır, düzeltme hareketi; hedef başına en fazla 3
- manuel sürüş / reset / stop hedefi geçersiz kılar → yalnızca sayaç düzelir
- hareket SIRASINDA hiçbir şey değişmez; takipte taret nadiren durduğu için
  takip davranışı aynı
- `ENCODER_REST_SNAP = False` ile FAZ 3 davranışına dönülür

Sunucu yanıtına `encoder_snap_n` / `encoder_snap_last` eklendi. Testler:
19. bölüm (22 kontrol).

**5.1 (`HUNTER_DPP_YAW` trimi) BU FAZDA GERİ ALINMADI.** Trim görsel kilit
sırasında (hareket halinde) çalışıyor; hizalama ise yalnızca duruşta. Çifte
düzeltme yok. Trim FAZ 6'da (hareket halinde kapalı döngü) geri alınacak.

**Etkisi:** yönelme sonunda taret gözcünün verdiği açıya 0.1° içinde oturur
(eskiden 1.5–3° eksik/fazla); kara liste, ateşsiz bölge, ana konum gerçek
açıyla çalışır. Yönelme başına +0.2–0.4 sn (150 ms bekleme + küçük hareket),
karşılığında PID'nin toparlama süresi düşer. Kilitteki 1.5° ölü bölge
DEĞİŞMEDİ.

**Sahada doğrulama:** ekrandaki Δ taret her durduğunda 0.00'a çekilmeli;
otonom yönelmede varıştan sonra ufak ikinci hareket görülmeli; kayıt açık
kalsın, `enkoder_analiz` ile boşluk/kaçırma artığının sıfıra indiği görülsün.

## FAZ 6 — KAPALI DÖNGÜ (opsiyonel, riskli)

> **Bu faza geçmeden önce Faz 5'in sonucunu ölç.** Telafi yeterliyse buraya
> hiç gerek olmayabilir.

- [ ] **6.0** `HUNTER_DPP_YAW = 0.01430` → pitch ölçeğine GERİ AL (FAZ 5.1 buraya taşındı; kapalı döngüyle çifte düzeltme olur)
- [ ] **6.1** son yaklaşımda (kalan < 2–3°) enkodere kapalı döngü; **hedefe hep aynı yönden yaklaş, aşınca geri dönme** (1.5° boşlukta geri dönüş limit çevrimi üretir)
- [ ] **6.2** PID geri beslemesini gerçek açıya bağla
- [ ] **6.3** **Gecikme kontrolü:** sistemde zaten ~185 ms ölü zaman var ve
      2.2–3.2 Hz'de rezonans ölçüldü. Enkoder gecikmesi eklenince kararlılık
      bozulabilir — `PID_OUTPUT_SMOOTHING` yeniden ayarlanması gerekebilir
- [ ] **6.4** Hedefe varış kontrolü: `perform_servo_step` enkoderden doğrulasın
- [ ] **6.5** Salınım frekansını yeniden ölç (FFT), rezonans bandı kaymış mı bak

## FAZ 7 — SAĞLAMLAŞTIRMA

- [x] **7.1** (18. bolum, 25 kontrol) Testlere yeni bölüm: sarma takibi, dişli dönüşümü, ofset, sağlıksızlıkta
      geri düşme
- [ ] **7.2** Güç kesintisi senaryosu: açılışta tur sayacı sıfır — bilinen konumda
      "Açıları Sıfırla" ile referans alma prosedürü yazılsın
- [ ] **7.3** CAN kopması senaryosu: kabloyu çek, sistem adım sayımına düşüyor mu,
      arayüz uyarıyor mu, otonom mod ne yapıyor
- [ ] **7.4** `PROJE_DURUMU.md`'ye ölçülen değerlerle birlikte yeni bölüm

---

## RİSKLER ve KARAR NOKTALARI

| risk | etki | önlem |
|---|---|---|
| **Sarma takibi** (multiturn yok) | ±90°'de enkoder 1.5 tur döner | 180° eşikli unwrapping; pay 48 kat, güvenli. Güç kesilince referans alınmalı |
| **12 bit çözünürlük** | kameradan 2 kat kaba (0.0293° vs 0.0143°) | Faz 2.5'te 16 bit denenecek; olmazsa yine iş görür |
| **Waveshare slcan** | protokol elle yazılabilir | `can0` oluştu, trafik testi bekliyor. Olmazsa plan B hazır |
| **Enkoder dişli boşluğu** | ölçüme karışır | boşluksuz kasnak (kullanıcı hallediyor); ideal olan dişlisiz doğrudan bağlantı |
| **Ek gecikme** | rezonans kötüleşebilir | PDO 10 ms; Faz 6 öncesi ölçüm şart |
| **`HUNTER_DPP_YAW` trimi** | çifte düzeltme → sistem bozulur | Faz 5.1, **atlanamaz** |

## AYRI DAL ÖNERİSİ

Servo tetikte olduğu gibi enkoder işi de **ayrı dalda** yapılmalı:

```bash
git checkout -b enkoder-yaw
```

Çalışan sistem `servo-tetik` / `motor-cs-d508-port` dallarında bozulmadan kalır;
yarışma yaklaşırken enkoder oturmazsa geri dönmek tek komut olur.

---

## KOMUT KARTI — FAZ 0-2'yi terminalden yürütme (kod yok)

Sıra zorunlu. Her adımın "beklenen" çıktısı var; gelmezse bir sonrakine geçme.

**Önemli bilgi:** veri sayfasına göre enkoder **otomatik bit hızı algılar**
("automatic bit rate detection"). Yani hatta trafik görmeden konuşmaz;
sadece `candump` ile dinlemek yetmez, **biz frame göndermeliyiz**.
Bu yüzden 4. adımda SYNC üreteci çalıştırılır.

### 0. Kablolama (her şey kapalıyken)

| enkoder M12 pin | nereye |
|---|---|
| 1 Vcc (+) | Pi 5V (pin 2 veya 4) — 50 mA, yeterli. **3.3V DEĞİL** (min 4.75 V) |
| 2 GND | Pi GND (pin 6) |
| 3 CAN_H | Waveshare **H** |
| 4 CAN_L | Waveshare **L** |
| 5 CAN_GND | Pi GND (aynı GND) |

Waveshare 120 Ω anahtarı **ON**. Enkoderde dahili direnç yok.
LED (CiA 303-3): yeşil yanıp sönüyor = pre-operational, yeşil sabit =
operational, kırmızı = hata / bit hızı bulunamadı.

### 1. Arayüz

```bash
sudo apt install -y can-utils
sudo modprobe slcan
sudo slcand -o -c -s6 /dev/ttyUSB0 can0 && sudo ip link set can0 up
ip -d -s link show can0
```
Beklenen: `state UP`, `can state ERROR-ACTIVE`. (`bitrate 0` normal.)

### 2. Dinleyici (terminal 1)

```bash
candump -td can0
```

### 3. Enkodere güç ver — LED'e bak

### 4. SYNC üreteci (terminal 2) — otomatik bit hızı için şart

```bash
cangen can0 -I 080 -L 0 -g 200
```
SYNC (0x080, 0 bayt) her 200 ms. Zararsız; hiçbir şey yazmaz.

Beklenen, terminal 1'de: `can0  77F  [1]  00`  → boot-up, düğüm 127.
Gelmezse: enkoderin gücünü kes-ver (boot-up yalnızca açılışta gelir).
Yine gelmezse `-s5` (250 k), sonra `-s4` (125 k) ile 1. adımı tekrarla:
```bash
sudo pkill slcand; sudo ip link set can0 down
```
Hâlâ yoksa: `ip -s link show can0` → TX `errors`/`dropped` artıyorsa
Waveshare slcan'de frame geçirmiyordur → plan B (Waveshare seri protokolü).

### 5. Çalıştır (pre-op → operational)

```bash
cansend can0 000#0100
```
Beklenen: `1FF [4] xx xx xx xx` akmaya başlar (TPDO1 = konum, 0x6004,
4 bayt, **little-endian**). LED yeşil sabit.

Çözme: baytlar `A B C D` ise konum = `0xDCBA`. Örnek `1FF [4] 3A 05 00 00`
→ 0x053A = 1338. 12 bit ise 0-4095 arasında döner.

**Tareti elle 10° çevir:** 12 bit × 1:3 → 4096·3/360·10 ≈ **341 sayım**
değişmeli. Yön: yaw + iken sayım artıyorsa `ENCODER_INVERT = False`,
azalıyorsa `True`. Bunu not al.

### 6. SDO ile kimlik ve ayarlar (düğüm 127: istek 0x67F, yanıt 0x5FF)

İstek formatı: `40 idx_lo idx_hi sub 00 00 00 00`. Yanıt `43/4B/4F ...`
+ değer little-endian; `80 ...` = hata.

| ne | komut | beklenen yanıt |
|---|---|---|
| cihaz tipi 0x1000 | `cansend can0 67F#4000100000000000` | `5FF [8] 43 00 10 00 96 01 01 00` → 0x0196 = CiA 406 |
| **çözünürlük 0x6501** | `cansend can0 67F#4001650000000000` | `... 00 10 00 00` = **4096** |
| **tur sayısı 0x6502** | `cansend can0 67F#4002650000000000` | `... 01 00 00 00` = **1** (multiturn yok) |
| konum 0x6004 | `cansend can0 67F#4004600000000000` | TPDO ile aynı değer |
| üretici 0x1018/1 | `cansend can0 67F#4018100100000000` | vendor id |

**16 bit denemesi** (isteğe bağlı, 2.5): 0x6001'e 65536 yaz:
```bash
cansend can0 67F#2301600000000100
```
Yanıt `60 01 60 00 ...` = kabul; `80 ...` = red. Kabulse 0x6501'i tekrar oku,
`0x6004` artık 0-65535 dönmeli. Kalıcı kaydet:
```bash
cansend can0 67F#2310100173617665
```
(`0x1010/1` = "save" ASCII.)

### 7. Ölçülenler (2026-09-08)

```
düğüm ID      : 127 (0x7F)        bit hızı : 250 k  (SABİT; 500k'da hata, otomatik algılama YOK)
LED           : 250k'da sabit yeşil = operational, NMT start beklemeden kendiliğinden başlıyor
TPDO1 (0x1FF) : her sayım değişiminde anında (olay tetiklemeli, inhibit yok) — çok yoğun
TPDO2 (0x2FF) : SYNC'e cevaben (bizim 20 ms SYNC → 50 Hz)  → KOD BUNU KULLANACAK
EMCY  (0x0FF) : açılışta 0x8100 haberleşme hatası (500k denemesinden), sonra temizlendi
konum aralığı : 1977–3635 gözlendi, 12 bit (0–4095) ile tutarlı; sarma henüz görülmedi
0x1000        : 0x10196 (CiA 406, tek tur)   0x1018/2: "WDGA"
0x6501        : 16384 = FIZIKSEL 14 BIT (siparis kodundaki 12, cikis olcegiymis)
0x6502        : 1 (multiturn yok)
0x6000        : 4 (olcekleme ACIK) ; 0x6001 = 0x6002 = 4096 (fabrika cikis olcegi)
TPDO1 0x1800  : tip 254 (her degisimde), inhibit YOK (abort 0x06090011), event timer 0
TPDO2 0x1801  : tip 1 (her SYNC)
yön           : yaw+ → sayım ARTIYOR  (ENCODER_INVERT = False)
ORAN          : enkoder/taret = 2 (kasnak caplari 1:2, triger kayis) -- 1:3 DEGIL
                21.8 sayim / komut derecesi @4096 (beklenen 22.75; %4 fark yaw'in
                komuttan az donmesi, HUNTER_DPP_YAW trimiyle tutarli)
                dis sayisi henuz sayilmadi (1.92 mi 2.00 mi -> kodda sabit)
+-90 taret    : = +-180 enkoder = TAM BIR TUR. Merkez preset 8192 (14 bit) ile
                sarma tam +-90'da; kullanici +-96'ya cikiyor -> sarma takibi kalir
```

### 7.1 Mekanik bulgular (2026-09-08) — MIMARIYI DEGISTIRDI

1. **Buyuk disli boslugu YOK.** 5 derecelik adimlarda yon donusundeki ilk adim
   kisa gelmiyor (-107 vs +108); +-96 derece gidip gelince 5 sayimla yerine donuyor.
2. **Elle bulunan "oynama" kutup atlamasi.** Step motor elektriksel cevrimi
   = 4 tam adim = 2.4 derece taret = **52.3 sayim**. Elle itince olculen 105
   (= 2 x 52.3) ve 158 (= 3 x 52.6) tam kat: rotor komsu kutba kayiyor, surucu
   acik dongu oldugu icin bilmiyor. Bu, kodun adim sayacinin (`_simulated_yaw`)
   sahada neden gercegi kaybettigini de acikliyor.
3. **Asil hata: surtunme altinda stepper yuk acisi histerezisi.** 1 derecelik
   adimlar: ileri 16,12,11,9 / geri 23,17,14,17, net -23 sayim (~1.2 derece).
   Mikro adimda rotor, surtunmeye karsi komutun bir tam adima (0.6 derece taret)
   kadar gerisinde kalir; yon donunce obur tarafa gecer. 5 derecelik adimlardaki
   100-118 dagilimi da ayni sey (surtunme konuma gore degisiyor).
   **Ileri beslemeyle telafi edilemez** (konuma ve surtunmeye bagli); enkoder
   goruyor, kapali dongu siler.

**KARAR: FAZ 5 (ileri besleme) ATLANIYOR, dogrudan FAZ 6 (kapali dongu).**
`YAW_BACKLASH_DEG` sabiti gereksiz. `HUNTER_DPP_YAW` trimi yine geri alinacak.

### 7.2 Enkoder kalici ayari (enk_ayar.py, tareti merkezde tut)

```
0x6001 = 16384   0x6002 = 16384   0x6003 = 8192 (merkez)
0x1800/1 = 0xC00001FF (TPDO1 KAPALI: 14 bitte 4000 cerceve/sn hatti bogardi)
0x1801/2 = 1 (TPDO2 her SYNC -> kod kendi SYNC'iyle 100 Hz okur)
0x1010/1 = "save"
Sonuc (R=2): 91.0 sayim / taret derecesi, 0.011 derece/sayim -> kameranin 0.0143'unden 1.3 kat ince.
(Onceki '136.5 / 0.0073' satiri R=3 varsayimiyla hesaplanmisti, yanlisti.)

UYGULANDI (2026-09-08): 0x6001/0x6002/0x6003/TPDO1 yazildi ve `save` OK.
Konum merkezde 8192. TPDO2 tip yazmasi 0x06070010 verdi (1 baytlik alana 4 bayt
yazildi) ama deger zaten 1. Guc kesme sonrasi kalicilik kontrolu: ___ (bekliyor).
5 derece adimlar 14 bitte: 486 / 491 / 467 (R=2 beklenen 455; +-%10 dagilim
stepper yuk acisindan, enkoderden degil).
```

### 7.3 Oran (R) nasil kesinlesecek

Komut edilen aciyla R hesaplanamaz: komutun tarette karsiligi +-%10 oynuyor
(stepper surtunme/yuk acisi). Iki yol:
- **Kamera (tercih):** pitch ekseni komut = gercek (direkt tahrik + planet
  reduktor, kalinti 0.9 px). Pikseller kare, yani pitch'ten olculen derece/piksel
  yaw icin GERCEK olcek. Yaw'i cevir, sabit hedefin piksel kaymasini ve enkoder
  sayim farkini oku -> R = sayim x 360 / (16384 x piksel x DPP_pitch).
  FAZ 3'te "Derece/Piksel Olc" aracina enkoder okumasi eklenince yapilacak.
- **Kumpas:** iki kasnagin dis capi (mm) + kayis dis araligi (GT2 = 2 mm).
  Dis sayisi = pi x (cap + 0.5) / aralik. Standart 20/40/60/80.
Koda `ENCODER_GEAR_RATIO = 2.0` ile baslanacak, kalibrasyonla duzeltilecek.

Not: TPDO1'in inhibit süresi 0 olduğu için taret 47°/s dönerken saniyede ~1600
çerçeve üretir. Kod tarafında ya TPDO1 kapatılacak (0x1800/1 bit 31) ya da
inhibit verilecek; konum SYNC-tetiklemeli TPDO2'den okunacak.
