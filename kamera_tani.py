"""
İki kamera tanılama aracı.

Arayüzden BAĞIMSIZ çalışır; "kameralar açılıyor ama görüntü gelmiyor" gibi
durumlarda sorunun kamerada mı, kuyrukta mı, arayüzde mi olduğunu ayırır.

Kullanım:
    python kamera_tani.py            -> indeksleri tara + ikili test
    python kamera_tani.py 1 2        -> gozcu=1, avci=2 ile ikili test
"""

import multiprocessing as mp
import sys
import time

import cv2

import config


def indeksleri_tara(en_fazla=8):
    """Hangi indekste kamera var, gerçekte hangi çözünürlüğü veriyor."""
    print("=" * 66)
    print("1. KAMERA INDEKSLERI")
    print("=" * 66)
    bulunan = []
    for i in range(en_fazla):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            continue
        ok, kare = cap.read()
        g = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        y = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        durum = "kare OK" if (ok and kare is not None) else "KARE GELMIYOR"
        print(f"  indeks {i}: acildi, {g}x{y} @ {fps:.0f} fps, {durum}")
        bulunan.append(i)
        cap.release()
        time.sleep(0.3)   # surucunun serbest birakmasi icin
    if not bulunan:
        print("  HICBIR INDEKSTE KAMERA YOK")
    print(f"\n  bulunan indeksler: {bulunan}")
    return bulunan


def _kamera_isci(ad, indeks, gen, yuk, mjpg, sonuc_q, sure=6.0):
    """Tek kamerayı açıp `sure` saniye boyunca kare sayar."""
    try:
        cap = cv2.VideoCapture(indeks, cv2.CAP_DSHOW)
        if not cap.isOpened():
            sonuc_q.put((ad, indeks, 'ACILAMADI', 0, 0, 0, 0.0))
            return
        if mjpg:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, gen)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, yuk)
        g = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        y = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        basla = time.time()
        kare, bos = 0, 0
        while time.time() - basla < sure:
            ok, img = cap.read()
            if ok and img is not None and img.size > 0:
                kare += 1
            else:
                bos += 1
        gecen = time.time() - basla
        cap.release()
        sonuc_q.put((ad, indeks, 'OK', g, y, kare, kare / gecen))
    except Exception as e:
        sonuc_q.put((ad, indeks, f'HATA: {e}', 0, 0, 0, 0.0))


def ikili_test(gozcu_idx, avci_idx, sure=6.0):
    """İkisini AYNI ANDA, ayrı süreçlerde açar — uygulamadaki durumun aynısı."""
    print()
    print("=" * 66)
    print(f"2. IKILI TEST  (gozcu={gozcu_idx}, avci={avci_idx}, {sure:.0f} sn)")
    print("=" * 66)
    q = mp.Queue()
    p1 = mp.Process(target=_kamera_isci,
                    args=('GOZCU', gozcu_idx, config.SPOTTER_WIDTH,
                          config.SPOTTER_HEIGHT, config.SPOTTER_USE_MJPG, q, sure))
    p2 = mp.Process(target=_kamera_isci,
                    args=('AVCI', avci_idx, config.HUNTER_WIDTH,
                          config.HUNTER_HEIGHT, config.HUNTER_USE_MJPG, q, sure))
    p1.start(); p2.start()
    p1.join(sure + 10); p2.join(sure + 10)

    sonuclar = []
    while not q.empty():
        sonuclar.append(q.get())
    for ad, idx, durum, g, y, kare, fps in sorted(sonuclar):
        print(f"  {ad:6s} (indeks {idx}): {durum:12s} {g}x{y}  {kare} kare  {fps:.1f} fps")

    if len(sonuclar) < 2:
        print("  UYARI: sureclerden biri yanit vermedi")
        return False
    hepsi_ok = all(s[2] == 'OK' and s[5] > 0 for s in sonuclar)
    dusuk = [s[0] for s in sonuclar if s[6] < 15]
    print()
    if not hepsi_ok:
        print("  SONUC: ikisi ayni anda calismiyor.")
        print("  -> farkli USB kok hub'larina takin (tercihen biri USB2, biri USB3)")
        print("  -> ya da config'de SPOTTER_WIDTH/HEIGHT degerlerini 640x480 yapin")
    elif dusuk:
        print(f"  SONUC: ikisi de calisiyor ama {', '.join(dusuk)} yavas (<15 fps).")
        print("  -> USB bant genisligi sinirda; gozcuyu 640x480'e dusurmeyi deneyin")
    else:
        print("  SONUC: ikisi de sorunsuz calisiyor. Sorun kamerada degil.")
    return hepsi_ok


def tekli_test(indeks, ad, gen, yuk, mjpg, sure=4.0):
    q = mp.Queue()
    p = mp.Process(target=_kamera_isci, args=(ad, indeks, gen, yuk, mjpg, q, sure))
    p.start(); p.join(sure + 10)
    return q.get() if not q.empty() else (ad, indeks, 'YANIT YOK', 0, 0, 0, 0.0)


if __name__ == '__main__':
    mp.freeze_support()
    print("ARAYUZU KAPATTIGINIZDAN EMIN OLUN — kameralari mesgul eder.\n")

    if len(sys.argv) >= 3:
        gozcu_idx, avci_idx = int(sys.argv[1]), int(sys.argv[2])
        bulunan = [gozcu_idx, avci_idx]
    else:
        bulunan = indeksleri_tara()
        if len(bulunan) < 2:
            print("\nIKI KAMERA BULUNAMADI. USB baglantilarini kontrol edin.")
            sys.exit(1)
        # config'in secmeye calisacagi indeksler
        gozcu_idx = next((i for i in config.SPOTTER_CAMERA_INDICES if i in bulunan),
                         bulunan[0])
        kalan = [i for i in bulunan if i != gozcu_idx]
        avci_idx = next((i for i in config.HUNTER_CAMERA_INDICES if i in kalan),
                        kalan[0] if kalan else gozcu_idx)
        print(f"  config'e gore secilecekler -> gozcu {gozcu_idx}, avci {avci_idx}")
        if gozcu_idx == avci_idx:
            print("  !!! IKISI AYNI INDEKSI SECIYOR — config duzeltilmeli !!!")

    # Once tek tek: kamera tek basina calisiyor mu
    print()
    print("=" * 66)
    print("1b. TEKLI TESTLER (her kamera tek basina)")
    print("=" * 66)
    for ad, idx, g, y, m in (('GOZCU', gozcu_idx, config.SPOTTER_WIDTH,
                              config.SPOTTER_HEIGHT, config.SPOTTER_USE_MJPG),
                             ('AVCI', avci_idx, config.HUNTER_WIDTH,
                              config.HUNTER_HEIGHT, config.HUNTER_USE_MJPG)):
        r = tekli_test(idx, ad, g, y, m)
        print(f"  {r[0]:6s} (indeks {r[1]}): {r[2]:12s} {r[3]}x{r[4]}  "
              f"{r[5]} kare  {r[6]:.1f} fps")
        time.sleep(0.5)

    ikili_test(gozcu_idx, avci_idx)
