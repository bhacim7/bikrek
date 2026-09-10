# Dataset ve Eğitim Analizi — HSS v16 (`HSS.v16-barishssdeneme8.yolo26`)

Tarih: 2026-09-03. Kaynak: dataset diskten tarandı (12 890 görüntü, etiketler
tek tek okundu), `yy2.py` eğitim betiği, Roboflow ekran görüntüleri, mevcut
`.pt`/`.onnx` modellerin içindeki eğitim argümanları ve `ultralytics 8.4.123`
kaynak kodu.

> **KARAR KAYDI (2026-09-08, kullanıcıyla konuşuldu):**
> - **§1 (sızıntı) DÜZELTİLDİ:** bölme kullanıcı tarafından videoya göre
>   yapılmış; train/test'te "aynı dosya adı" görünen kareler farklı arka planlı
>   (`masked-bg`) versiyonlar. Bu analiz yalnızca dosya adına bakmıştı, "birebir
>   aynı dosya" ifadesi **yanlıştır**. Kalan not: aynı karenin perdeli/perdesiz
>   halinde maket pikselleri aynıdır, valid skoru bir miktar iyimser kalır.
> - **`rect=True` korunuyor** (kullanıcı kararı). Bedeli §2'de; `mosaic` ve
>   `close_mosaic` satırları etkisizdir, bilerek bırakılmıştır.
> - Roboflow **x2**, test train'e katıldı (train 5 831 / valid 2 620 kaynak
>   kare). `Resize 1280x720 Stretch` ve motion blur 5 px yeni versiyonda.
> - `imgsz=1280` uygulandı. `cache='ram'` **kullanılmayacak** (12k kare
>   1280'de ~33 GB, PC kapandı); §8'deki öneri bu yüzden geçersiz.
> - `config.CLASSES`'a `dusman-Helikopter` eklenmesi (§7) hâlâ **bekliyor**.

**Kısa cevap: bu betikle bu dataset'i eğitmek "çalışır" ama ölçtüğün mAP
gerçek değil ve ayarların yarısı sessizce devre dışı.** Aşağıda önem sırasına
göre.

---

## 1. EN KRİTİK — Doğrulama seti eğitim setinin kopyası (sızıntı)

Roboflow bölmeyi **kare bazında rastgele** yapmış. Dataset ise **video
karelerinden** oluşuyor (`kayit3_0400`, `karekayit11_…`); ardışık kareler
neredeyse aynı görüntü. Sonuç: doğrulama ve test setinde, eğitimde görülen
videoların kareleri var.

| video | train | valid | test | durum |
|---|---|---|---|---|
| kayit1 | 1308 | – | – | temiz |
| kayit2 | 378 | **133** | – | valid sızıntı |
| kayit3 | 1626 | – | **234** | test sızıntı — **343 kare birebir aynı dosya** |
| kayit4 | 633 | **217** | – | valid sızıntı |
| kayit5 | 498 | – | **218** | test sızıntı |
| kayit6 | 267 | – | **200** | test sızıntı |
| kayit7 | – | 265 | 168 | **temiz** (eğitimde yok) |
| kayit8 | – | 444 | – | **temiz** |
| kayit9 | 690 | **233** | – | valid sızıntı |
| kayit10 | – | 466 | – | **temiz** |
| karekayit11 | 1467 | – | – | temiz |
| karekayit12 | 1347 | – | – | temiz |
| karekayit13 | 717 | **247** | – | valid sızıntı |

- **Test seti %100 kirli**: kayit3/5/6/7'den oluşuyor, kayit7 hariç hepsi
  eğitimde. Üstelik kayit3'ün **343 karesi train'de de test'te de birebir
  aynı dosya adıyla** duruyor.
- **Valid setinin %38'i kirli** (830 / 2192). Dürüst kısım yalnızca
  kayit7 + kayit8 + kayit10 = 1 175 kare.
- Eğitim sonunda gördüğün mAP bu yüzden **iyimser**. Sahada "model
  raporda iyiydi ama burada kaçırıyor" hissinin bir sebebi bu.

**Ayrıca kaynak israfı var:** train'de yalnızca **3 273 benzersiz kare**
var (9 819 / 3 Roboflow kopyası); valid+test'te 3 071. Yani elindeki
benzersiz karelerin **%48'i eğitime girmiyor**.

### Çözüm: videoya göre böl

Roboflow'un rastgele bölmesini kullanma. Ham export'u al, yerelde böl:

```
train : kayit1, kayit2, kayit3, kayit4, kayit5, kayit6, kayit9,
        karekayit11, karekayit12, karekayit13, tüm arka planlar
valid : kayit7, kayit8, kayit10        (3 video, ~1 340 kare, hiç görülmemiş)
test  : yok — ya da kayit6'yı da ayır
```

Bu bölmeyle train **4 459 benzersiz kareye** çıkar (şimdikinin %36 fazlası)
ve valid **gerçekten** genelleme ölçer. Bölme betiği: bkz. §8.

Yeni bir video kaydettiğinde de kural aynı: **bir video ya tamamen train'e
ya tamamen valid'e** girer.

---

## 2. KRİTİK — `rect=True` dört ayarı sessizce kapatıyor

`ultralytics 8.4.123` kaynak kodu:

```
data/dataset.py:314   hyp.mosaic = hyp.mosaic if self.augment and not self.rect else 0.0
data/dataset.py:315   hyp.mixup  = hyp.mixup  if self.augment and not self.rect else 0.0
detect/train.py:95    "'rect=True' is incompatible with DataLoader shuffle, setting shuffle=False"
```

Yani `rect=True` yazdığın anda:

| betikte yazan | gerçekte olan | kanıt |
|---|---|---|
| `mosaic=0.5` | **0.0** | `yeniDATA1280.pt` içindeki `train_args`: `mosaic: 0.0` |
| `close_mosaic=30` | anlamsız (kapatılacak mosaic yok) | |
| `mixup=0.0` | 0.0 (zaten) | |
| DataLoader shuffle | **KAPALI** | her epoch aynı sıra; aynı videonun ardışık kareleri aynı batch'e giriyor |

Mosaic, küçük nesne (balon) tespitinde en etkili augmentasyondur — görüntü
başına nesne sayısını dörde katlar ve ölçek çeşitliliği yaratır. Shuffle'ın
kapalı olması ise batch içi çeşitliliği öldürür: batch'teki 8 kare aynı
videodan, aynı sahneden.

**Çözüm:** `rect=False`. Kare 16:9 olduğu için letterbox'la 1280×1280'e
oturur; VRAM artar ama mosaic geri gelir. Deploy'da `rect` zaten
kullanılmıyor (ONNX girişi sabit 736×1280).

## 3. İki ayar daha hiçbir şey yapmıyor

| ayar | neden etkisiz | kaynak |
|---|---|---|
| `copy_paste=0.2` | **Yalnızca segmentasyon (poligon) etiketiyle çalışır**; dataset kutu etiketli | `augment.py:1919 if len(labels["instances"].segments) == 0 or self.p == 0: return` |
| `erasing=0.3` | **Yalnızca sınıflandırma** eğitiminde uygulanır | `cfg/default.yaml:134 "random erasing probability for classification"` |

Betikteki yorumlar ("şamandıra", "su yansımaları", "dalga köpüğü",
"siyah/yeşil sınıflar") **başka bir projeden** (RoboBoat) kopyalanmış —
`.pt` dosyasındaki eğitim yolu bunu doğruluyor:
`…\fofana\roboboat26\HSS.v12…`. Ayarlar bu dataset için düşünülmemiş.

---

## 4. Çözünürlük: balon 1056'da stride sınırının altında

Etiketlerden ölçülen kutu genişlikleri (1920 px kare):

| sınıf | p10 | medyan | p90 |
|---|---|---|---|
| **balon** | **21 px** | **32 px** | 68 px |
| dusman-Fuze | 30 | 52 | 136 |
| dost-F16 / dusman-F16 | 43–45 | 68–71 | 168–223 |
| dusman-Drone | 48 | 71 | 195 |
| dost-Helikopter | 57 | 92 | 238 |
| dusman-Helikopter | 59 | 99 | 296 |

Balon medyanının model girişindeki karşılığı:

| giriş | balon medyan | balon p10 | 24 px altı balon oranı (train) |
|---|---|---|---|
| 1056×608 | 17.6 px | **11.5 px** | %15.7 → ~%30 stride-8 sınırında |
| 1280×736 | 21.3 px | 14.0 px | daha az |

YOLO'nun en ince başı stride 8'dir; 12 px'in altı **güvenilir değil**.
1056'da balonların onda biri o bölgede. Sistemde balon **nişan noktası** —
kaçırılması doğrudan "ateş edilemedi" demek.

**Tutarsızlık:** `yy2.py` **1056** eğitiyor, `convert_to_*.py` ise
**736×1280** dışa aktarıyor, deploy'daki `yeniDATA1280` **1280**'de
eğitilmiş. Bu betikle eğitilecek v16 modeli 1056'da olur, sonra 1280'e
export edilir: nesneler eğitimde gördüğünden %21 büyük görünür. `scale=0.5`
bunu kısmen tolere eder ama küçük balonda kayıptır.

**Çözüm:** `imgsz=1280`. Bu makinede (RTX 5070 Laptop, **8 GB**) `batch=8`
sığmayabilir → `batch=4` (ultralytics `nbs=64` ile gradyanı zaten biriktirir,
etkin batch değişmez) veya `batch=-1` (otomatik).

---

## 5. Roboflow'daki 3× çevrimdışı augmentasyon gereksiz

`Outputs per training example: 3` → her kaynak kare 3 kopya. Ultralytics
zaten **her epoch'ta farklı** online augmentasyon uygular; Roboflow'un
sabit 3 kopyası yalnızca:

- epoch süresini **3 kat** uzatıyor (9 819 yerine 3 273 kare yeterdi),
- `rect=True` + shuffle kapalı ile aynı karenin 3 kopyasını **ardışık**
  batch'lere sokuyor.

Roboflow'un `Motion Blur 10 px` ayarı da 21 px'lik balonu yarı yarıya
bulanıklaştırıyor — hedef zaten küçük.

**Çözüm:** Roboflow'da `Outputs per training example = 1`, augmentasyon
**yok** (Auto-Orient kalsın). Bütün augmentasyon ultralytics'te.

---

## 6. Etiket ve içerik kalitesi

### 6.1 `masked-bg` (siyah perde) kareleri

Ekran görüntülerinde görülen: gerçek kare alınmış, **kutu dışı her şey
perde dokusuyla değiştirilmiş**, kutu içi olduğu gibi bırakılmış. Kutu
içinde sahneden parçalar kalıyor: **el, sandalye arkalığı, gümüş
reflektör, mavi gömlek** (kayit9_0099'daki dusman-Helikopter kutusu,
kayit3_0400'deki büyük pembe kutu).

Riski: model "**perde üstünde keskin kenarlı dikdörtgen yama = nesne**"
kestirmesini öğrenir. Sahada arka plan süreklidir, o kenar yoktur; model
tereddüt eder. Tersi de olur: sahadaki herhangi bir dikdörtgen yama
(tabela, pencere) tetikleyebilir.

Bu kareler valid'de de var (kayit8 tamamı `masked-bg`), yani doğrulama
kısmen bu yapay kolaylık üzerinden ölçülüyor.

**Öneri:**
- `masked-bg` payı eğitimin **%30'unu geçmesin**; oranı bilmiyorum,
  Roboflow'da tag ile filtreleyip say.
- Maskeleme yapılacaksa kutuyla değil **siluetle** (SAM vb.) ve kenar
  yumuşatarak (feather 3–5 px); arka plan tek perde değil **çeşitli gerçek
  arka planlar** (saha, gökyüzü, salon).
- Valid setinde `masked-bg` **olmasın** — valid gerçek kareyle ölçülmeli.

### 6.2 Eksik etiket

Roboflow raw-data ekran görüntüsünde (`kayıt5_0057`) **sol sandalyedeki
kırmızı jet kutusuz** görünüyor; altındaki balon kutulu. Eksik etiket,
modele "bu nesne arka plandır" der; kaçırmayı doğrudan öğretir. Tek bir kare
mi, sistematik mi bilmiyorum — **`dusman-Fuze` etiketli kareleri hızlıca
tara**: en küçük medyan (52 px) bu sınıfta ve etiketlenmesi en kolay
atlanan da bu.

### 6.3 Kutu gevşekliği

Rotasyon augmentasyonu (`degrees=10`) eksen hizalı kutuyu **büyütür**
(döndürülmüş kutunun çevreleyeni). Bu sistemde kutu merkezi = nişan
noktası ve kutu boyutu = açısal boyut kapısı (`DEGREES_PER_PIXEL`).
Kamera taret üstünde, yuvarlanma (roll) sıfır: **`degrees=0`** (en fazla 3).

### 6.4 Arka plan (negatif) görüntüleri

Train'in %9.9'u boş etiketli — oran doğru. **İçerik yanlış**: bunlar
internetten gelen **yaprak/bitki hastalığı fotoğrafları**
(`Bacterial-Spot`, `strawberry-leaf`) ve 640×480 rastgele kareler. Sahada
görülecek şey bunlar değil. Negatifler **avcı kamerasından** gelmeli:
boş salon, boş saha, hedefsiz gökyüzü, **insanların olduğu ama maketin
olmadığı** kareler (sahada insan var ve model "insan + kırmızı" görünce ne
yapacağını bilmeli).

### 6.5 Sınıf dengesi

Uçak sınıfları 3 869–4 948 arasında, dengeli. Balon 10 092 (kare başına
birden fazla, doğal). **Sorun yok.** Ancak 6 videoda (karekayit11-13,
kayit8, kayit9, kayit10) **hiç balon yok**; balon örneklerinin tamamı
kayit1-7'den geliyor. Videoya göre bölünce valid'deki balon yalnızca
kayit7'den (1 599 kutu) gelir — yeterli.

---

## 7. Deploy uyumu — yeni modelde 7. sınıf var

`data.yaml`: **7 sınıf**, sonuncusu `dusman-Helikopter` (index 6).
`config.py`'deki `CLASSES` listesi **6 sınıf**. `inference_module._postprocess`
index 6'yı `"Unknown"` yapar → **düşman helikopter sessizce düşer**, angajman
onu hiç görmez.

v16 modeli deploy edilmeden önce:

```python
CLASSES = ['balon', 'dost-F16', 'dost-Helikopter',
           'dusman-Drone', 'dusman-F16', 'dusman-Fuze', 'dusman-Helikopter']
```

Sıra `data.yaml` ile birebir. Engagement tarafı `dusman-` ön ekiyle karar
verdiği için başka değişiklik gerekmez.

ONNX çıkışı kontrol edildi: YOLO26'nın uçtan uca (NMS'siz) başı export'ta
**kullanılmıyor**, çıkış `[1, 10, N]` (one-to-many) ve `_postprocess` ile
uyumlu. Yeni modelde `[1, 11, N]` olacak; kod `4:` dilimlediği için
kendiliğinden uyar.

---

## 8. Önerilen eğitim betiği

```python
from ultralytics import YOLO

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()

    model = YOLO("yolo26m.pt")
    model.train(
        data="C:/.../HSS.v16-videoya-gore-bolunmus/data.yaml",  # §1'deki bölme
        device=0,
        epochs=150,
        patience=40,
        save_period=10,

        # --- Çözünürlük: deploy ile AYNI (736x1280 -> kare 1280) ---
        imgsz=1280,
        batch=4,            # 8 GB VRAM; nbs=64 gradyanı biriktirir, etkin batch değişmez
        rect=False,         # ZORUNLU: True mosaic'i ve shuffle'ı kapatıyordu
        workers=4,
        # cache: KULLANMA. 12k kare 1280'de ~33 GB RAM; PC kapandı. Gerekirse 'disk'.

        optimizer="AdamW",
        lr0=0.001,
        cos_lr=True,
        warmup_epochs=3,

        # --- Renk: HUE SIFIR KALMALI (kırmızı=düşman, mavi=dost) ---
        hsv_h=0.0,
        hsv_s=0.4,          # kapalı salon -> açık saha geçişi için doygunluk payı
        hsv_v=0.4,          # ışık farkı; balonun rengini değil parlaklığını oynatır

        # --- Geometri ---
        degrees=0.0,        # taret kamerasında roll yok; rotasyon kutuyu şişirir
        translate=0.1,
        scale=0.5,          # 5-15 m = 3x ölçek aralığı, 0.5 bunu kapsar
        perspective=0.0,
        flipud=0.0,
        fliplr=0.5,

        # --- Mosaic artık GERÇEKTEN açık ---
        mosaic=1.0,
        close_mosaic=15,
        mixup=0.0,
        copy_paste=0.0,     # kutu etiketiyle zaten çalışmıyordu
        # erasing: sınıflandırmaya özel, detect'te yok sayılır
    )
```

Değişen mantık: `rect` kapandı (mosaic/shuffle geri geldi), çözünürlük
deploy'a eşitlendi, ölü ayarlar silindi, renk augmentasyonu hue'ya
dokunmadan aydınlatma farkını kapsayacak kadar açıldı.

### Videoya göre bölme betiği

Roboflow'dan **augmentasyonsuz, tek bölmeli** (hepsi train) export al,
sonra:

```python
import os, re, shutil, glob
SRC = "C:/.../HSS.v16-ham"          # Roboflow export (tek 'train' klasörü)
DST = "C:/.../HSS.v16-videoya-gore-bolunmus"
VALID_VIDEOLAR = {"kayit7", "kayit8", "kayit10"}

def video(ad):
    m = re.match(r"(karekayit\d+|kayit\d+)", ad)
    return m.group(1) if m else "arka_plan"

for img in glob.glob(f"{SRC}/train/images/*"):
    stem = os.path.splitext(os.path.basename(img))[0]
    bolme = "valid" if video(stem) in VALID_VIDEOLAR else "train"
    for alt, uz in (("images", os.path.splitext(img)[1]), ("labels", ".txt")):
        kaynak = f"{SRC}/train/{alt}/{stem}{uz}"
        if os.path.exists(kaynak):
            os.makedirs(f"{DST}/{bolme}/{alt}", exist_ok=True)
            shutil.copy(kaynak, f"{DST}/{bolme}/{alt}/")
```

`data.yaml`'ı elle yaz (`train: ../train/images`, `val: ../valid/images`,
`nc: 7`, isimler aynı sırayla).

---

## 9. Neyi ölçmeli — mAP tek başına yetmez

Sistemin gerçek riskleri mAP'te görünmez. Valid (kayit7/8/10) üzerinde
ayrıca:

| ölçüm | neden | hedef |
|---|---|---|
| **balon recall, 24 px altı** | nişan noktası; kaçırılırsa ateş yok | > 0.85 |
| **dost ↔ düşman karışıklığı** (confusion matrix, F16↔F16, Heli↔Heli) | dost'a ateş = görev iptali | **0** |
| dusman-Fuze recall | en küçük maket, en çok atlanan etiket | ≥ diğerleri |
| `conf=0.4` ile FP/kare (negatif karelerde) | sahadaki yanlış yönelme | < 0.05 |

`model.val(data=..., conf=0.4, iou=0.4, imgsz=1280)` — deploy eşikleriyle
ölç, varsayılan `conf=0.001` ile değil.

---

## 10. Öncelik sırası

1. **Bölmeyi videoya göre yap** (§1) — bunsuz hiçbir ölçüm anlamlı değil.
2. **`rect=False`, `imgsz=1280`** (§2, §4).
3. Roboflow augmentasyonunu kapat, tek çıktı (§5).
4. `config.CLASSES`'a `dusman-Helikopter` ekle (§7) — yoksa model boşa.
5. Negatifleri avcı kamerasından topla, yaprak fotoğraflarını at (§6.4).
6. `dusman-Fuze` etiketlerini tara, eksikleri tamamla (§6.2).
7. `masked-bg` oranını ölç; valid'den çıkar (§6.1).
8. §9'daki ölçümleri her eğitimden sonra raporla.

Kod tarafında bu analiz için **hiçbir değişiklik yapılmadı**; yalnızca bu
belge yazıldı.
