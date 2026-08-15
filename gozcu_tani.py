"""
GÖZCÜ TANILAMA — "mavi neden tespit edilmiyor" sorusunu ölçerek cevaplar.

Gözcünün mavi maskesi ekranda HİÇ ÇİZİLMİYOR: izler yalnızca KIRMIZI
bloblardan doğuyor, mavi sadece "balonun üstünde ne var" sorusunun cevabında
bir ORAN olarak kullanılıyor. Yani mavi daire görmemek normaldir; ama
sınıflandırmanın doğru çalışıp çalışmadığı iz renginden anlaşılır:

    kırmızı daire  -> dusman
    MAVİ daire     -> dost
    sarı daire     -> kararsiz

İki dost bir düşman varken üç dairenin de kırmızı olması, mavi maskenin o
ortamda çalışmadığı anlamına gelir.

BU ARAÇ NE YAPAR
----------------
1. Gözcü kamerasını arayüzle AYNI ayarlarla açar.
2. Kırmızı ve mavi maskeleri hesaplar, diske yazar.
3. Her balon adayının üstündeki MAKET PENCERESİNİ çizer ve o pencerede
   kaç kırmızı / kaç mavi piksel olduğunu, mavi oranını ve çıkan sınıfı yazar.
4. Pencere içindeki gerçek HSV değerlerinin yüzdeliklerini basar — eşiğin
   neden tutmadığı buradan doğrudan görülür.
5. EŞİK TARAMASI yapar: farklı doygunluk/parlaklık eşikleriyle o pencerede
   kaç mavi piksel bulunacağını hesaplar, yani hangi eşiğin işe yarayacağını
   söyler.

KULLANIM
--------
    python gozcu_tani.py            # config'teki gözcü indekslerini dener
    python gozcu_tani.py 2          # doğrudan indeks 2
    python gozcu_tani.py 2 40       # 40 kare ortalayarak (gürültü azalır)

SAHNEYİ HAZIRLAYIN: dost (mavi maket + kırmızı balon) ve düşman (kırmızı
maket + kırmızı balon) gözcünün görüş alanında, yarışma mesafesinde ve
yarışma aydınlatmasında olsun.
"""
import os
import sys
import time

import cv2
import numpy as np

import config
import spotter_module as sp

CIKTI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gozcu_tani")


def kamera_ac(indeksler):
    for i in indeksler:
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            continue
        if config.SPOTTER_USE_MJPG:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.SPOTTER_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.SPOTTER_HEIGHT)
        ok, f = cap.read()
        if ok and f is not None:
            print(f"Gozcu kamerasi: indeks {i}, {f.shape[1]}x{f.shape[0]}")
            return cap, i
        cap.release()
    return None, None


def ortalama_kare(cap, n):
    """Gürültüyü azaltmak için n kareyi ortalar."""
    t = time.time() + 2.0
    while time.time() < t:
        cap.read()                       # otomatik pozlama otursun
    yigin = []
    while len(yigin) < n:
        ok, f = cap.read()
        if ok and f is not None and f.size:
            yigin.append(f.astype(np.float32))
    return np.clip(np.mean(yigin, axis=0), 0, 255).astype(np.uint8)


def hsv_ozet(hsv, maske=None):
    """Bölgedeki H/S/V yüzdelikleri."""
    if maske is not None:
        p = hsv[maske > 0]
    else:
        p = hsv.reshape(-1, 3)
    if len(p) == 0:
        return None
    out = {}
    for k, ad in enumerate("HSV"):
        d = p[:, k]
        out[ad] = (int(np.percentile(d, 10)), int(np.percentile(d, 50)),
                   int(np.percentile(d, 90)))
    return out


def main():
    argv = sys.argv[1:]
    indeksler = [int(argv[0])] if argv else list(config.SPOTTER_CAMERA_INDICES)
    kare_sayisi = int(argv[1]) if len(argv) > 1 else 20

    os.makedirs(CIKTI, exist_ok=True)
    cap, indeks = kamera_ac(indeksler)
    if cap is None:
        print(f"Gozcu kamerasi acilamadi. Denenen: {indeksler}")
        return 1

    kare = ortalama_kare(cap, kare_sayisi)
    cap.release()

    hsv = cv2.cvtColor(kare, cv2.COLOR_BGR2HSV)
    kirmizi = sp._temizle(sp._maske(hsv, config.SPOTTER_RED_RANGES))
    mavi = sp._temizle(sp._maske(hsv, config.SPOTTER_BLUE_RANGES))

    print()
    print("=" * 78)
    print("GENEL MASKE DURUMU")
    print("=" * 78)
    toplam = kare.shape[0] * kare.shape[1]
    print(f"  kirmizi piksel : {int(np.count_nonzero(kirmizi)):7d}  "
          f"(%{100*np.count_nonzero(kirmizi)/toplam:.3f})")
    print(f"  mavi piksel    : {int(np.count_nonzero(mavi)):7d}  "
          f"(%{100*np.count_nonzero(mavi)/toplam:.3f})")
    print(f"  esikler: kirmizi {config.SPOTTER_RED_RANGES}")
    print(f"          mavi    {config.SPOTTER_BLUE_RANGES}")
    if np.count_nonzero(mavi) == 0:
        print("  >>> MAVI MASKE TAMAMEN BOS. Esik bu ortam icin cok kati.")

    adaylar = sp.balon_adaylari(kirmizi)
    print()
    print("=" * 78)
    print(f"BALON ADAYLARI ve MAKET PENCERESI  ({len(adaylar)} aday)")
    print("=" * 78)

    isaretli = kare.copy()
    yuk, gen = kirmizi.shape[:2]
    for n, aday in enumerate(adaylar):
        sinif, oran, k, m = sp.dost_dusman(aday, kirmizi, mavi)
        yaw, pitch = sp.piksel_to_aci(aday['cx'], aday['cy'], gen, yuk)
        x0, y0, x1, y1 = sp.maket_penceresi(aday, gen, yuk)

        renk = {'dusman': (0, 0, 255), 'dost': (255, 120, 0)}.get(sinif, (0, 200, 255))
        cv2.circle(isaretli, (int(aday['cx']), int(aday['cy'])),
                   int(aday['cap'] / 2) + 4, renk, 2)
        cv2.rectangle(isaretli, (x0, y0), (x1, y1), renk, 2)
        cv2.putText(isaretli, f"#{n} {sinif} mavi={oran:.2f}", (x0, max(12, y0 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, renk, 1)

        print(f"\n  ADAY #{n}: yaw {yaw:+6.1f}  pitch {pitch:+6.1f}  "
              f"balon capi {aday['cap']:.0f} px, alan {aday['alan']} px2")
        print(f"    maket penceresi : x {x0}-{x1}, y {y0}-{y1} "
              f"({x1-x0}x{y1-y0} = {(x1-x0)*(y1-y0)} px2)")
        print(f"    pencerede       : kirmizi {k:5d} | mavi {m:5d} | "
              f"toplam {k+m:5d}")
        print(f"    mavi orani      : {oran:.3f}  -> SINIF: {sinif.upper()}")
        print(f"    esikler         : dost >= {config.SPOTTER_FRIEND_BLUE_RATIO}, "
              f"dusman <= {config.SPOTTER_ENEMY_BLUE_RATIO}, "
              f"min blob alani {config.SPOTTER_MIN_BLOB_AREA}")

        pencere_hsv = hsv[y0:y1, x0:x1]
        ozet = hsv_ozet(pencere_hsv)
        if ozet:
            print(f"    pencere HSV (%10/%50/%90): "
                  f"H {ozet['H']}  S {ozet['S']}  V {ozet['V']}")

        # --- ESIK TARAMASI: hangi (S,V) esigi bu pencerede mavi bulurdu? ---
        print("    mavi esik taramasi (H 90-135 sabit):")
        basliklar = "      S\\V  " + "".join(f"{v:>7d}" for v in (30, 40, 60, 80))
        print(basliklar)
        for s_esik in (40, 60, 80, 100, 120, 140):
            satir = f"      {s_esik:3d}  "
            for v_esik in (30, 40, 60, 80):
                mm = cv2.inRange(pencere_hsv,
                                 np.array((90, s_esik, v_esik), np.uint8),
                                 np.array((135, 255, 255), np.uint8))
                satir += f"{int(np.count_nonzero(mm)):7d}"
            print(satir)
        print("      (mevcut ayar: S>=140, V>=60 -> yukaridaki tabloda son satir)")

    for ad, gorsel in (("ham.png", kare),
                       ("kirmizi_maske.png", kirmizi),
                       ("mavi_maske.png", mavi),
                       ("isaretli.png", isaretli)):
        cv2.imwrite(os.path.join(CIKTI, ad), gorsel)

    print()
    print("=" * 78)
    print(f"Goruntuler: {CIKTI}")
    print("  ham.png           - kameranin gordugu")
    print("  kirmizi_maske.png - kirmizi maske (beyaz = gecti)")
    print("  mavi_maske.png    - MAVI maske; siyahsa esik cok kati")
    print("  isaretli.png      - adaylar, maket pencereleri ve siniflar")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
