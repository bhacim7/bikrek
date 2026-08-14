"""
Avcı kamerası için mod seçimi aracı — TAHMİNLE DEĞİL ÖLÇEREK.

Sorun: "1280x720 mi 1920x1080 mi, MJPG mi sıkıştırmasız mı" sorusu kâğıt
üstünde çözülemiyor. Modül düşük çözünürlüğü sensörü ÖLÇEKLEYEREK de
üretebilir (temiz), satır ATLAYARAK da (gürültülü + renk moiresi). Hangisi
olduğu ancak ölçülerek bilinir.

YÖNTEM
------
Gürültü ZAMANSAL ölçülüyor: sahne SABİTken N kare alınıp her pikselin
zaman içindeki standart sapması hesaplanıyor. Bu ölçüm sahnedeki detaydan
tamamen bağımsızdır — tek kareden "gürültü" ölçmeye çalışmak detayı
gürültü sanma hatasına düşer.

Netlik ise zamansal ORTALAMA kare üzerinden ölçülüyor (ortalama gürültüyü
söndürür, geriye gerçek detay kalır) ve karşılaştırma MODEL GİRİŞ
BOYUTUNDA (1056x608) yapılıyor — çünkü YOLO'nun gördüğü budur. Farklı
çözünürlükleri kendi boyutlarında karşılaştırmak haksızlık olurdu.

KULLANIM
--------
    python kamera_kalite.py            # config'teki avcı indekslerini dener
    python kamera_kalite.py 2          # doğrudan indeks 2

KAMERAYI VE SAHNEYİ KIPIRDATMAYIN. Ölçüm boyunca sahne sabit olmalı,
yoksa hareket gürültü olarak sayılır. Işığı da değiştirmeyin.

Çıktı: kamera_kalite/ klasörüne her modun ortalama karesi PNG olarak
yazılır; konsola karşılaştırma tablosu basılır.
"""
import os
import sys
import time

import cv2
import numpy as np

import config

CIKTI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kamera_kalite")
KARE_SAYISI = 20        # zamansal gürültü için
ISINMA_SN = 2.0         # otomatik pozlama/kazanç otursun

# Denenecek kombinasyonlar: (etiket, backend, genislik, yukseklik, fourcc)
# fourcc None -> sürücünün varsayılanı (FOURCC'ye hiç dokunulmaz)
DENEMELER = [
    ("1280x720  varsayilan", cv2.CAP_DSHOW, 1280, 720, None),
    ("1280x720  MJPG",       cv2.CAP_DSHOW, 1280, 720, "MJPG"),
    ("1280x720  YUY2",       cv2.CAP_DSHOW, 1280, 720, "YUY2"),
    ("1920x1080 varsayilan", cv2.CAP_DSHOW, 1920, 1080, None),
    ("1920x1080 MJPG",       cv2.CAP_DSHOW, 1920, 1080, "MJPG"),
    ("1920x1200 varsayilan", cv2.CAP_DSHOW, 1920, 1200, None),
    ("1280x720  MSMF",       cv2.CAP_MSMF,  1280, 720, None),
    ("1920x1080 MSMF",       cv2.CAP_MSMF,  1920, 1080, None),
]


def fourcc_metni(cap):
    ham = int(cap.get(cv2.CAP_PROP_FOURCC))
    if not ham:
        return "?"
    m = "".join(chr((ham >> (8 * i)) & 0xFF) for i in range(4))
    return m if m.isprintable() else f"0x{ham:08X}"


def kareleri_topla(cap, n):
    """Isınmadan sonra n kare toplar; gerçek kare hızını da ölçer."""
    t_bitis = time.time() + ISINMA_SN
    while time.time() < t_bitis:
        cap.read()
    kareler = []
    t0 = time.time()
    while len(kareler) < n:
        ok, f = cap.read()
        if not ok or f is None or f.size == 0:
            continue
        kareler.append(f.astype(np.float32))
    sure = time.time() - t0
    return kareler, (len(kareler) / sure if sure > 0 else 0.0)


def olc(kareler):
    """
    Döner: (parlaklik_gurultusu, renk_gurultusu, netlik, ortalama_kare)

    Gürültü zamansal standart sapmanın ortalamasıdır (0-255 biriminde).
    Renk gürültüsü Lab uzayının a,b kanallarında ölçülür — ekranda
    "renkli benek" olarak görünen tam olarak budur.
    Netlik, model giriş boyutuna küçültülmüş ORTALAMA karenin Laplace
    varyansıdır.
    """
    yigin = np.stack(kareler, axis=0)          # (N, H, W, 3)
    ortalama = yigin.mean(axis=0)

    # Parlaklık gürültüsü: gri kanalda zamansal std
    gri = yigin.mean(axis=3)                   # (N, H, W)
    parlaklik_gurultusu = float(gri.std(axis=0).mean())

    # Renk gürültüsü: her kareyi Lab'e çevirip a,b kanallarında zamansal std
    ab = []
    for f in kareler:
        lab = cv2.cvtColor(np.clip(f, 0, 255).astype(np.uint8), cv2.COLOR_BGR2Lab)
        ab.append(lab[:, :, 1:].astype(np.float32))
    ab = np.stack(ab, axis=0)
    renk_gurultusu = float(ab.std(axis=0).mean())

    # Netlik: model giriş boyutunda, ortalama kare üzerinde
    ort8 = np.clip(ortalama, 0, 255).astype(np.uint8)
    model_boy = cv2.resize(ort8, (config.IMG_WIDTH, config.IMG_HEIGHT),
                           interpolation=cv2.INTER_LINEAR)
    netlik = float(cv2.Laplacian(cv2.cvtColor(model_boy, cv2.COLOR_BGR2GRAY),
                                 cv2.CV_64F).var())
    return parlaklik_gurultusu, renk_gurultusu, netlik, ort8


def indeksleri_bul(argv):
    if len(argv) > 1:
        return [int(argv[1])]
    return list(config.HUNTER_CAMERA_INDICES)


def main():
    os.makedirs(CIKTI, exist_ok=True)
    indeksler = indeksleri_bul(sys.argv)

    # Çalışan bir indeks bul
    indeks = None
    for i in indeksler:
        c = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if c.isOpened():
            ok, f = c.read()
            c.release()
            if ok and f is not None:
                indeks = i
                break
        c.release()
    if indeks is None:
        print(f"Hicbir kamera acilamadi. Denenen indeksler: {indeksler}")
        print("`python kamera_tani.py` ile dogru indeksi bulun.")
        return 1

    print(f"Kamera indeksi {indeks} kullaniliyor.")
    print("SAHNEYI VE KAMERAYI KIPIRDATMAYIN; isigi degistirmeyin.\n")

    sonuclar = []
    for etiket, backend, gen, yuk, fcc in DENEMELER:
        cap = cv2.VideoCapture(indeks, backend)
        if not cap.isOpened():
            print(f"[atlandi] {etiket}: acilamadi")
            cap.release()
            continue
        if fcc:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, gen)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, yuk)

        g = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        y = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        f_gercek = fourcc_metni(cap)

        try:
            kareler, olculen_fps = kareleri_topla(cap, KARE_SAYISI)
        except Exception as e:
            print(f"[atlandi] {etiket}: kare alinamadi ({e})")
            cap.release()
            continue
        finally:
            pass
        cap.release()

        if len(kareler) < 2:
            print(f"[atlandi] {etiket}: yeterli kare yok")
            continue

        pg, rg, netlik, ort = olc(kareler)
        dosya = os.path.join(CIKTI, etiket.replace(" ", "_") + f"_{g}x{y}_{f_gercek}.png")
        cv2.imwrite(dosya, ort)
        sonuclar.append((etiket, g, y, f_gercek, olculen_fps, pg, rg, netlik))
        print(f"[bitti]   {etiket}  -> gerceklesen {g}x{y} {f_gercek} "
              f"{olculen_fps:.1f} fps")

    if not sonuclar:
        print("Hicbir mod olculemedi.")
        return 1

    print("\n" + "=" * 100)
    print("KARSILASTIRMA  (gurultu KUCUK iyi, netlik BUYUK iyi)")
    print("=" * 100)
    print(f"{'mod':22s} {'gerceklesen':16s} {'fps':>6s} "
          f"{'parlaklik gur.':>15s} {'renk gur.':>10s} {'netlik':>9s}")
    print("-" * 100)
    for etiket, g, y, f, fps, pg, rg, nt in sonuclar:
        print(f"{etiket:22s} {f'{g}x{y} {f}':16s} {fps:6.1f} "
              f"{pg:15.3f} {rg:10.3f} {nt:9.1f}")
    print("-" * 100)

    en_temiz = min(sonuclar, key=lambda s: s[6])
    en_net = max(sonuclar, key=lambda s: s[7])
    print(f"En az RENK GURULTUSU : {en_temiz[0]}  ({en_temiz[6]:.3f})")
    print(f"En NET (model boyunda): {en_net[0]}  ({en_net[7]:.1f})")
    print(f"\nOrtalama kareler: {CIKTI}")
    print("Bu klasoru ve yukaridaki tabloyu paylasin; secim buna gore yapilir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
