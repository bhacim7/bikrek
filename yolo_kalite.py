"""
"Temiz görüntü ama YOLO'dan uzak" mı, "YOLO'ya yakın ama kirli görüntü" mü?

Bu soru göz kararı çözülemez. Çünkü tartışılan iki etki ZIT yönde çalışıyor:

  - Düşük çözünürlük model girişine daha yakın (az küçültme, az kayıp) AMA
    bu modülde 1280x720 sensörü satır atlayarak okuyor (gürültü + moire).
  - Yüksek çözünürlük temiz okuyor AMA 1.82 kat küçültmek gerekiyor.

Hangisinin kazandığı ancak GERÇEK MODELLE, GERÇEK SAHNEDE ölçülerek
bilinir. Bu araç tam olarak onu yapar: her kamera modunu ve her küçültme
süzgecini aynı sahnede çalıştırıp modelin çıktısını karşılaştırır.

ÖLÇÜLEN ŞEYLER
--------------
  tespit orani  : hedefin bulunduğu kare yüzdesi  (yüksek iyi)
  ort. guven    : bulunduğunda ortalama güven      (yüksek iyi)
  titreme       : kutu merkezinin DERECE cinsinden standart sapması
                  (düşük iyi) — PID'i doğrudan bu besliyor
  kutu boyutu   : derece cinsinden, modlar arası tutarlılık kontrolü

Titreme ve boyut DERECEYE çevriliyor; piksel cinsinden bırakılsaydı
farklı çözünürlükler haksız karşılaştırılırdı.

KULLANIM
--------
    python yolo_kalite.py                # config'teki avcı indeksleri
    python yolo_kalite.py 2              # doğrudan indeks 2
    python yolo_kalite.py 2 balon        # yalnızca 'balon' sınıfını ölç

SAHNEYİ HAZIRLAYIN: gerçek hedef (maket + balon) yarışma mesafesine yakın
bir uzaklıkta, SABİT dursun. Kamerayı ve ışığı ölçüm boyunca değiştirmeyin;
aksi halde modlar arasındaki fark sahneden gelir, kameradan değil.
"""
import os
import sys
import time

import cv2
import numpy as np

import config
from inference_module import YoloModel

KARE_SAYISI = 40
ISINMA_SN = 2.0
SENSOR_TAM_GENISLIK = 1920          # AR0234 dizi genişliği
SENSOR_DPP = 0.014324               # tam genişlikte derece/piksel

# (etiket, genislik, yukseklik)
MODLAR = [
    ("1280x720",  1280, 720),
    ("1920x1080", 1920, 1080),
    ("1920x1200", 1920, 1200),
]
SUZGECLER = ["LINEAR", "AREA"]


def kamera_ac(indeks, gen, yuk):
    cap = cv2.VideoCapture(indeks, cv2.CAP_DSHOW)
    if not cap.isOpened():
        return None
    if config.HUNTER_USE_MJPG:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, gen)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, yuk)
    return cap


def kareleri_al(cap, n):
    t_bitis = time.time() + ISINMA_SN
    while time.time() < t_bitis:
        cap.read()
    kareler = []
    while len(kareler) < n:
        ok, f = cap.read()
        if ok and f is not None and f.size > 0:
            kareler.append(f)
    return kareler


def en_iyi_tespit(detections, sinif_filtresi):
    uygun = [d for d in detections
             if sinif_filtresi is None or d["class_name"] == sinif_filtresi]
    if not uygun:
        return None
    return max(uygun, key=lambda d: d["score"])


def olc(model, kareler, suzgec, dpp, sinif_filtresi):
    model.interpolasyon = suzgec
    merkezler, guvenler, boyutlar = [], [], []
    sureler = []
    for kare in kareler:
        t0 = time.perf_counter()
        try:
            dets = model.infer(kare, config.CLASSES)
        except Exception as e:
            print(f"    cikarim hatasi: {e}")
            return None
        sureler.append(time.perf_counter() - t0)
        d = en_iyi_tespit(dets, sinif_filtresi)
        if d is None:
            continue
        x, y, w, h = d["bbox"]
        merkezler.append((x + w / 2.0, y + h / 2.0))
        guvenler.append(d["score"])
        boyutlar.append(max(w, h))

    n = len(kareler)
    oran = len(guvenler) / n if n else 0.0
    if len(merkezler) >= 2:
        m = np.array(merkezler)
        # Titreme: iki eksenin standart sapmasinin bilesikesi, DERECE olarak
        titreme = float(np.hypot(m[:, 0].std(), m[:, 1].std()) * dpp)
    else:
        titreme = float("nan")
    return {
        "oran": oran,
        "guven": float(np.mean(guvenler)) if guvenler else float("nan"),
        "titreme": titreme,
        "boyut": float(np.mean(boyutlar) * dpp) if boyutlar else float("nan"),
        "cikarim_ms": float(np.mean(sureler) * 1000) if sureler else float("nan"),
    }


def main():
    argv = sys.argv[1:]
    indeksler = [int(argv[0])] if argv else list(config.HUNTER_CAMERA_INDICES)
    sinif = argv[1] if len(argv) > 1 else None

    print("Model yukleniyor...")
    try:
        model = YoloModel(config.YOLO_MODEL_PATH, config.IMG_WIDTH, config.IMG_HEIGHT)
    except Exception as e:
        print(f"Model yuklenemedi: {e}")
        return 1
    if getattr(model, "model_type", None) is None:
        print("Model yuklenemedi (model_type None). best.engine mevcut mu?")
        return 1
    print(f"Model: {model.model_type}, giris {model.img_width}x{model.img_height}")
    print(f"Sinif filtresi: {sinif or 'hepsi'}\n")
    print("SAHNEYI VE KAMERAYI KIPIRDATMAYIN.\n")

    satirlar = []
    for etiket, gen, yuk in MODLAR:
        cap = None
        for i in indeksler:
            cap = kamera_ac(i, gen, yuk)
            if cap is not None:
                break
        if cap is None:
            print(f"[atlandi] {etiket}: kamera acilamadi")
            continue
        g = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        y = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (g, y) != (gen, yuk):
            print(f"[uyari]   {etiket}: kamera {g}x{y} verdi")
        kareler = kareleri_al(cap, KARE_SAYISI)
        cap.release()

        # Bu modun derece/piksel'i: gorus acisi sabit, piksel sayisi degisiyor
        dpp = SENSOR_DPP * SENSOR_TAM_GENISLIK / g
        kucultme = g / config.IMG_WIDTH
        print(f"--- {etiket} (gerceklesen {g}x{y}, {dpp:.6f} derece/px, "
              f"kucultme {kucultme:.2f}x) ---")

        for suzgec in SUZGECLER:
            s = olc(model, kareler, suzgec, dpp, sinif)
            if s is None:
                continue
            satirlar.append((f"{etiket} / {suzgec}", kucultme, s))
            print(f"    {suzgec:6s} tespit %{s['oran']*100:5.1f} | "
                  f"guven {s['guven']:.3f} | titreme {s['titreme']:.4f} derece | "
                  f"cikarim {s['cikarim_ms']:.1f} ms")
        print()

    if not satirlar:
        print("Hicbir olcum yapilamadi.")
        return 1

    print("=" * 92)
    print("KARSILASTIRMA   (tespit ve guven BUYUK iyi, titreme KUCUK iyi)")
    print("=" * 92)
    print(f"{'mod / suzgec':24s} {'kucultme':>9s} {'tespit':>8s} {'guven':>8s} "
          f"{'titreme(derece)':>16s} {'kutu(derece)':>13s} {'cikarim(ms)':>12s}")
    print("-" * 92)
    for ad, kc, s in satirlar:
        print(f"{ad:24s} {kc:8.2f}x {s['oran']*100:7.1f}% {s['guven']:8.3f} "
              f"{s['titreme']:16.4f} {s['boyut']:13.3f} {s['cikarim_ms']:12.1f}")
    print("-" * 92)

    gecerli = [s for s in satirlar if not np.isnan(s[2]["guven"])]
    if gecerli:
        en_iyi_oran = max(gecerli, key=lambda s: s[2]["oran"])
        en_iyi_guven = max(gecerli, key=lambda s: s[2]["guven"])
        kararli = [s for s in gecerli if not np.isnan(s[2]["titreme"])]
        print(f"En yuksek TESPIT ORANI : {en_iyi_oran[0]}  "
              f"(%{en_iyi_oran[2]['oran']*100:.1f})")
        print(f"En yuksek GUVEN        : {en_iyi_guven[0]}  "
              f"({en_iyi_guven[2]['guven']:.3f})")
        if kararli:
            en_kararli = min(kararli, key=lambda s: s[2]["titreme"])
            print(f"En az TITREME          : {en_kararli[0]}  "
                  f"({en_kararli[2]['titreme']:.4f} derece)")
    print("\nSecim sirasi: once TESPIT ORANI (hedefi kaybetmek en pahalisi),")
    print("esitse TITREME (PID'i dogrudan besler), sonra GUVEN.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
