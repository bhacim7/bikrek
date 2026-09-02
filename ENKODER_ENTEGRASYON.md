# Yaw Enkoder Entegrasyonu — Sıralı Yapılacaklar

> **GÜNCEL DURUM (2026-09-02):** enkodere henüz **güç verilmedi**, montaj yapılmadı.
> USB dönüştürücü Pi'ye takıldı, `/dev/ttyUSB0` göründü ve `slcand` ile `can0`
> arayüzü **oluştu** (`ERROR-ACTIVE`) — ama hat üzerinde **gerçek CAN trafiği
> henüz doğrulanmadı**. Sıradaki adım: **0.1**.

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

- [x] **1.1** `can0` arayüzünü kur: **YAPILDI**, arayüz `UP` ve `ERROR-ACTIVE`.
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

- [ ] **3.1** `encoder_module.py` yaz (Pi tarafı, yeni dosya):
      - `baslat()` / `kapat()`
      - `_ham_oku()` — CAN'dan ham adım
      - `_sarma_takibi()` — 360° sarmasını çöz (eşik 180°, pay 48 kat)
      - `taret_acisi()` — ham → tur → **/3 dişli** → ofset → derece
      - `sifirla()` — mevcut açıyı sıfır kabul et
      - `saglikli_mi()` — son veri yaşı; **kopukluk sessizce yutulmamalı**
- [ ] **3.2** `motor_fire_module.py` sabitleri ekle:
      `ENCODER_ENABLED`, `ENCODER_BITS`, `ENCODER_GEAR_RATIO = 3.0`,
      `ENCODER_OFFSET_DEG`, `ENCODER_INVERT`
- [ ] **3.3** `rpi_motor_server.py`: başlatmada `encoder_module.baslat()`,
      kapanışta `kapat()`
- [ ] **3.4** `angle_sender_loop` yanıtına iki alan ekle: `encoder_yaw`, `encoder_ok`
      (mevcut `current_yaw` **DEĞİŞMEYECEK** — hâlâ adım sayımından)
- [ ] **3.5** PC tarafı `bukrek_main.py`: bilgi paneline enkoder açısını ve **farkı** yaz:
      `Yaw 12.3° (enk 12.1°, Δ0.2°)`
- [ ] **3.6** Enkoder düşerse durum çubuğunda uyar
- [ ] **3.7** **Sahada doğrula:** tareti elle sağa-sola sür, iki açı birlikte hareket
      ediyor mu, yön doğru mu (`ENCODER_INVERT` gerekebilir), ölçek doğru mu

## FAZ 4 — BOŞLUĞU ÖLÇ (hâlâ kontrol değişmiyor)

- [ ] **4.1** Ölçüm koşumu: tareti bir yöne sür, durdur, ters yöne sür.
      Motor komutu ile enkoder açısı arasındaki **gecikme farkı** = boşluk
- [ ] **4.2** Sağ→sol ve sol→sağ **ayrı ayrı** ölç — simetrik olmayabilir
- [ ] **4.3** Farklı hızlarda tekrarla (yavaş/hızlı) — boşluk hıza bağlı değişmemeli,
      değişiyorsa kayma (adım kaçırma) var demektir
- [ ] **4.4** Ölçüm sonucunu `config.py`'ye yaz: `YAW_BACKLASH_DEG = ___`
- [ ] **4.5** Kayıt al: video + sayısal log. Karşılaştırma için gerekecek

## FAZ 5 — TELAFİ (ilk gerçek kontrol değişikliği)

- [ ] **5.1** `HUNTER_DPP_YAW = 0.01430` **GERİ ALINACAK** → pitch ile aynı ölçeğe.
      Bu değer şu an boşluğu telafi için kasten kaydırılmış; enkoder gerçek açıyı
      verince **çifte düzeltme** yapar. **Bu adım unutulursa sistem bozulur.**
- [ ] **5.2** Yön değişiminde `YAW_BACKLASH_DEG` kadar fazladan adım at
      (ileri besleme telafisi — basit, düşük riskli)
- [ ] **5.3** Sahada ölç: kilit salınımı azaldı mı, yaw kalıntısı (10.7 px) düştü mü
- [ ] **5.4** `Derece/Piksel Ölç` kalibrasyonunu enkoderle tekrarla — artık komut
      edilen değil **gerçek** açı farkı kullanılabilir, ölçüm çok daha doğru olur

## FAZ 6 — KAPALI DÖNGÜ (opsiyonel, riskli)

> **Bu faza geçmeden önce Faz 5'in sonucunu ölç.** Telafi yeterliyse buraya
> hiç gerek olmayabilir.

- [ ] **6.1** `get_current_angles()` yaw'ı enkoderden döndürsün
      (sağlıksızsa adım sayımına geri düş + uyar)
- [ ] **6.2** PID geri beslemesini gerçek açıya bağla
- [ ] **6.3** **Gecikme kontrolü:** sistemde zaten ~185 ms ölü zaman var ve
      2.2–3.2 Hz'de rezonans ölçüldü. Enkoder gecikmesi eklenince kararlılık
      bozulabilir — `PID_OUTPUT_SMOOTHING` yeniden ayarlanması gerekebilir
- [ ] **6.4** Hedefe varış kontrolü: `perform_servo_step` enkoderden doğrulasın
- [ ] **6.5** Salınım frekansını yeniden ölç (FFT), rezonans bandı kaymış mı bak

## FAZ 7 — SAĞLAMLAŞTIRMA

- [ ] **7.1** Testlere yeni bölüm: sarma takibi, dişli dönüşümü, ofset, sağlıksızlıkta
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
