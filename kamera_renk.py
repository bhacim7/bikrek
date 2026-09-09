# -*- coding: utf-8 -*-
"""
Kamera renk / beyaz dengesi ayar aracı (avcı Arducam için, gözcüde de çalışır).

Neden var: avcı kamerası siyah perdeyi bordo, zemini pembe gösteriyordu.
config.KAMERA_KONTROLLERI avcıda beyaz dengesini OTOMATİK KAPALI ve
4600 K'ye sabitliyor ("tipik floresan"); salondaki LED panel ~5500-6500 K.
Kamera 4600'e kilitliyken soğuk ışık altında her şey kırmızıya kayar —
gözle görülen fark tam bu. Logitech aynı sahnede nötr çünkü otomatik
beyaz dengesiyle açılıyor.

Kullanım:
    python kamera_renk.py            -> config.HUNTER_CAMERA_INDICES[0]
    python kamera_renk.py 1          -> indeks 1
    python kamera_renk.py 1 spotter  -> gözcü ayarlarıyla

Pencerede tuşlar:
    a       otomatik beyaz dengesi AÇ/KAPA
    + / -   beyaz dengesi sıcaklığı ±200 K (otomatik kapalıyken)
    o       "tek atım": 3 sn otomatiğe bırak, oturan sıcaklığı oku, sonra KİLİTLE
    e       otomatik pozlama AÇ/KAPA        [ / ]  pozlama ±1 (log2 s)
    g / h   gain ±5                          t / y  doygunluk ±5
    r       sürücü varsayılanlarına dön (auto_wb=1, auto_exposure=0.75)
    k       yazılım beyaz dengesi: ortadaki kareyi GRİ kabul et, kanal
            kazançlarını hesapla (HUNTER_WB_GAINS) — sürücü sıcaklığı
            tutmuyorsa (TUTMADI) tek çare budur
    s       kareyi PNG kaydet      w  config'e yazılacak satırları bas
    q       çık

Ortadaki kare (yeşil) ölçüm bölgesi: ORAN satırı R/G ve B/G'yi verir. Nötr
gri/beyaz bir kâğıdı oraya tutunca ikisi de ~1.00 olmalı. R/G > 1.10 =
kırmızı kayma (sıcaklık düşük), B/G > 1.10 = mavi kayma (sıcaklık yüksek).
"""
import sys
import time

import cv2
import numpy as np

import config

OZELLIK = {
    "auto_wb": cv2.CAP_PROP_AUTO_WB, "wb": cv2.CAP_PROP_WB_TEMPERATURE,
    "auto_exp": cv2.CAP_PROP_AUTO_EXPOSURE, "exp": cv2.CAP_PROP_EXPOSURE,
    "gain": cv2.CAP_PROP_GAIN, "sat": cv2.CAP_PROP_SATURATION,
    "bright": cv2.CAP_PROP_BRIGHTNESS, "contrast": cv2.CAP_PROP_CONTRAST,
    "gamma": cv2.CAP_PROP_GAMMA,
}


def oku(cap):
    return {k: cap.get(v) for k, v in OZELLIK.items()}


def ayarla(cap, ad, deger):
    cap.set(OZELLIK[ad], float(deger))
    sonra = cap.get(OZELLIK[ad])
    tuttu = abs(sonra - float(deger)) < 1e-6
    print(f"  {ad}: istenen {deger:g} -> okunan {sonra:g}{'' if tuttu else '  << TUTMADI (sürücü desteklemiyor)'}")
    return tuttu


def gri_dunya(kare, kutu):
    x0, y0, x1, y1 = kutu
    p = kare[y0:y1, x0:x1].reshape(-1, 3).astype(np.float64)
    b, g, r = p.mean(axis=0)
    return b, g, r


def main():
    kamera_adi = "hunter"
    if len(sys.argv) > 2 and sys.argv[2] in ("spotter", "hunter"):
        kamera_adi = sys.argv[2]
    ayar = config.KAMERA_AYARLARI[kamera_adi]
    indeks = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else ayar["indices"][0]

    cap = cv2.VideoCapture(indeks, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"Kamera {indeks} açılamadı."); return 1
    if ayar["mjpg"]:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, ayar["width"])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ayar["height"])
    print(f"{kamera_adi}: indeks {indeks}, {int(cap.get(3))}x{int(cap.get(4))}")
    print("Açılıştaki sürücü değerleri:", {k: round(v, 3) for k, v in oku(cap).items()})
    print("(config.KAMERA_KONTROLLERI UYGULANMADI — sürücünün kendi durumu görülüyor; "
          "arayüz açılınca config'teki auto_wb=0 / 4600 uygulanıyor.)")

    kazanc = None          # yazılım beyaz dengesi (b, g, r)
    son_yazi = ""
    cv2.namedWindow("kamera_renk", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("kamera_renk", 1280, 800)
    while True:
        ok, kare = cap.read()
        if not ok:
            time.sleep(0.05); continue
        h, w = kare.shape[:2]
        kutu = (w // 2 - 60, h // 2 - 60, w // 2 + 60, h // 2 + 60)
        goster = kare
        if kazanc is not None:
            goster = np.clip(kare.astype(np.float32) * np.array(kazanc, np.float32), 0, 255).astype(np.uint8)
        b, g, r = gri_dunya(goster, kutu)
        d = oku(cap)
        satir1 = (f"auto_wb {d['auto_wb']:g}  wb {d['wb']:g}K  auto_exp {d['auto_exp']:g}  exp {d['exp']:g}  "
                  f"gain {d['gain']:g}  sat {d['sat']:g}")
        satir2 = (f"ORTA: B {b:5.1f} G {g:5.1f} R {r:5.1f}   R/G {r / max(g, 1):.2f}  B/G {b / max(g, 1):.2f}"
                  f"   yazilim WB {'AÇIK ' + str(tuple(round(k, 3) for k in kazanc)) if kazanc else 'kapali'}")
        ekran = goster.copy()
        cv2.rectangle(ekran, kutu[:2], kutu[2:], (0, 255, 0), 2)
        for i, s in enumerate((satir1, satir2, son_yazi)):
            cv2.putText(ekran, s, (10, 30 + 30 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 0), 4)
            cv2.putText(ekran, s, (10, 30 + 30 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 255), 2)
        cv2.imshow("kamera_renk", ekran)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        elif k == ord("a"):
            ayarla(cap, "auto_wb", 0 if d["auto_wb"] else 1)
        elif k in (ord("+"), ord("=")):
            ayarla(cap, "wb", d["wb"] + 200)
        elif k == ord("-"):
            ayarla(cap, "wb", d["wb"] - 200)
        elif k == ord("o"):
            print("tek atım: 3 sn otomatik beyaz dengesi...")
            ayarla(cap, "auto_wb", 1)
            t0 = time.time()
            while time.time() - t0 < 3.0:
                cap.read()
            oturan = cap.get(OZELLIK["wb"])
            ayarla(cap, "auto_wb", 0)
            ayarla(cap, "wb", oturan)
            son_yazi = f"otomatik {oturan:g} K'de oturdu ve kilitlendi -> config: wb_temperature={oturan:g}"
            print(son_yazi)
        elif k == ord("e"):
            ayarla(cap, "auto_exp", 0.25 if d["auto_exp"] > 0.5 else 0.75)
        elif k == ord("["):
            ayarla(cap, "exp", d["exp"] - 1)
        elif k == ord("]"):
            ayarla(cap, "exp", d["exp"] + 1)
        elif k == ord("g"):
            ayarla(cap, "gain", d["gain"] + 5)
        elif k == ord("h"):
            ayarla(cap, "gain", d["gain"] - 5)
        elif k == ord("t"):
            ayarla(cap, "sat", d["sat"] + 5)
        elif k == ord("y"):
            ayarla(cap, "sat", d["sat"] - 5)
        elif k == ord("r"):
            ayarla(cap, "auto_wb", 1); ayarla(cap, "auto_exp", 0.75); kazanc = None
        elif k == ord("k"):
            b0, g0, r0 = gri_dunya(kare, kutu)
            kazanc = (g0 / max(b0, 1), 1.0, g0 / max(r0, 1))
            son_yazi = f"yazilim WB kazanclari (B,G,R) = ({kazanc[0]:.3f}, 1.000, {kazanc[2]:.3f})"
            print(son_yazi)
        elif k == ord("s"):
            ad = time.strftime("kamera_renk_%H%M%S.png")
            cv2.imencode(".png", goster)[1].tofile(ad); print("kaydedildi:", ad)
        elif k == ord("w"):
            print("config.KAMERA_KONTROLLERI['%s'] icin:" % kamera_adi)
            print(f"    'auto_wb': {int(d['auto_wb'])},  'wb_temperature': {d['wb']:g},")
            print(f"    'auto_exposure': {d['auto_exp']:g},  'exposure': {d['exp']:g},  'gain': {d['gain']:g},  'saturation': {d['sat']:g},")
            if kazanc:
                print(f"config.HUNTER_WB_GAINS = ({kazanc[0]:.3f}, 1.000, {kazanc[2]:.3f})   # yazilim beyaz dengesi")
    cap.release(); cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
