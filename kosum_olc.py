# -*- coding: utf-8 -*-
"""
Saha koşumu ölçüm aracı — `enkoder_kayit/*.csv` dosyasından takip kalitesini
sayıya döker. Sisteme dokunmaz, sadece okur.

NİYE VAR: "daha iyi oldu mu" sorusunu gözle yanıtlamak mümkün değil.
2026-09-16'da iki koşum gözle "aynı" göründü; ölçünce biri diğerinden 2.9 kat
daha çok titriyordu (PROJE_DURUMU 29.6). Bir ayarı değiştirip koşum yaptıktan
sonra bu araç çalıştırılır ve önceki koşumla karşılaştırılır.

KULLANIM:
    python kosum_olc.py                 -> en yeni kayıt dosyası
    python kosum_olc.py dosya.csv       -> belirli dosya
    python kosum_olc.py a.csv b.csv     -> iki koşumu yan yana karşılaştır
    python kosum_olc.py dosya.csv 12 34 -> yalnızca 12.-34. saniye arası

ZAMAN PENCERESİ: kayıt, arayüz açılır açılmaz başlar; taretin beklediği ölü
zamanlar ölçümü sulandırır. Araç varsayılan olarak taretin GERÇEKTEN hareket
ettiği bölümü kendisi bulur (ilk ve son hareketin arası). Videoyla birebir
hizalamak isterseniz saniye aralığını elle verin.

ÇIKTIDAKİ SATIRLAR:
  titreşim RMS      : yavaş yönelme çıkarıldıktan sonra kalan salınım. Küçük
                      olmalı. 0.12 derece = iyi (süzgeç açık), 0.35 = kötü.
  titreşim frekansı : 2-4 Hz ise yapısal rezonans (denetleyici kaynaklı),
                      0.5-1 Hz ise hedefin kendi salınımını takip ediyordur.
  nişan bandı dışı  : zamanın yüzde kaçında hata nişan toleransından büyük.
                      Düşük olmalı; ateş ancak bu bandın içindeyken açılır.
  yön değişimi      : 55 saniyeye normalize. Yüksekse taret gürültü kovalıyor.
  en büyük komut    : tek karede istenen en büyük açı değişimi (aşım göstergesi).
  sayaç-enkoder     : adım sayacı ile gerçek açı farkı; boşluk + rapor gecikmesi.
"""
import csv
import glob
import os
import sys

import numpy as np

import config

# Nişan toleransının derece karşılığı (14 piksel x derece/piksel).
NISAN_BANDI = config.AIM_TOLERANCE_MIN_PIXELS * abs(config.HUNTER_DPP_YAW)


def yukle(yol):
    with open(yol, newline='') as f:
        satirlar = list(csv.DictReader(f))
    if not satirlar:
        raise SystemExit(f"{yol}: kayıt boş.")
    t = np.array([float(x['t']) for x in satirlar])
    return (t - t[0],
            np.array([float(x['sayac_yaw']) for x in satirlar]),
            np.array([float(x['enk_yaw']) for x in satirlar]),
            np.array([int(x['enk_ok']) for x in satirlar]))


def hareket_penceresi(t, sy, uzunluk=15.0):
    """
    Otonom koşumun geçtiği bölümü bul.

    Kayıt, arayüz açıldığı andan itibaren HER ŞEYİ tutar: manuel sürüş, boş
    bekleme, birden çok deneme. Tamamını ölçmek sayıları sulandırır — sahada
    ölçüldü: aynı koşumun otonom bölümünde titreşim RMS 0.345 iken tüm kayıt
    üzerinden 0.269 çıkıyor, çünkü taretin hiç kımıldamadığı dakikalar
    ortalamayı aşağı çekiyor.

    Bu yüzden komut yoğunluğu EN YÜKSEK olan `uzunluk` saniyelik pencere
    seçilir: otonom takip, saniyede onlarca küçük düzeltme gönderir; manuel
    sürüş ve bekleme göndermez.
    """
    hareketli = np.abs(np.diff(sy)) > 0.02
    if hareketli.sum() < 10 or t[-1] - t[0] <= uzunluk:
        return t[0], t[-1]
    orta = t[:-1][hareketli]
    # kayan pencere: her başlangıç için içindeki hareketli örnek sayısı
    baslangiclar = np.arange(t[0], t[-1] - uzunluk, 0.5)
    sayimlar = np.array([np.sum((orta >= b) & (orta < b + uzunluk))
                         for b in baslangiclar])
    b = baslangiclar[int(np.argmax(sayimlar))]
    return b, b + uzunluk


def titresim(t, e, fs=50.0):
    """Yavaş yönelmeyi çıkar, kalan salınımın genliğini ve frekansını ver."""
    if t[-1] - t[0] < 1.0:
        return None
    ti = np.arange(t[0], t[-1], 1 / fs)
    ei = np.interp(ti, t, e)
    n = max(3, int(0.4 * fs))                  # 0.4 sn kayan ortalama = yavaş bileşen
    yavas = np.convolve(ei, np.ones(n) / n, mode='same')
    kalan = (ei - yavas)[n:-n]
    if len(kalan) < 16:
        return None
    pencere = np.hanning(len(kalan))
    gucler = np.abs(np.fft.rfft(kalan * pencere))
    frekanslar = np.fft.rfftfreq(len(kalan), 1 / fs)
    bant = (frekanslar > 0.4) & (frekanslar < 8.0)
    tepe = float(frekanslar[bant][np.argmax(gucler[bant])]) if bant.any() else float('nan')
    return {
        'rms': float(kalan.std()),
        'tepeden_tepeye': float(np.percentile(kalan, 97) - np.percentile(kalan, 3)),
        'frekans': tepe,
        'bant_disi': 100.0 * float(np.mean(np.abs(kalan) > NISAN_BANDI)),
    }


def olc(yol, baslangic=None, bitis=None):
    t, sy, ey, ok = yukle(yol)
    a, b = hareket_penceresi(t, sy)
    if baslangic is not None:
        a = baslangic
    if bitis is not None:
        b = bitis
    m = (t >= a) & (t <= b)
    if m.sum() < 20:
        raise SystemExit(f"{yol}: {a:.1f}-{b:.1f} sn aralığında yeterli örnek yok.")
    tt, s, e = t[m], sy[m], ey[m]
    sure = tt[-1] - tt[0]

    ds = np.diff(s)
    dt = np.maximum(np.diff(tt), 1e-3)
    buyuk = np.abs(ds) > 0.02
    isaret = np.sign(ds[buyuk])
    yon = int(np.sum(isaret[1:] * isaret[:-1] < 0)) if len(isaret) > 1 else 0

    adimlar = np.abs(ds[np.abs(ds) > 1e-6])
    hiz = np.abs(np.diff(e) / dt)
    fark = s - e
    ti = titresim(tt, e)

    kendi_secti = baslangic is None and bitis is None
    print(f"\n=== {os.path.basename(yol)}   ({a:.1f} - {b:.1f} sn, {sure:.1f} saniye"
          f"{', en yoğun bölüm' if kendi_secti else ''}) ===")
    print(f"  enkoder sağlıklı           : %{100 * ok[m].mean():.1f}")
    if ti:
        print(f"  titreşim RMS               : {ti['rms']:.3f} derece"
              f"   (tepeden tepeye {ti['tepeden_tepeye']:.2f})")
        print(f"  titreşim frekansı          : {ti['frekans']:.2f} Hz")
        print(f"  nişan bandı ({NISAN_BANDI:.3f} der.) dışı : %{ti['bant_disi']:.1f}")
    print(f"  yaw yön değişimi           : {yon}  ({yon / sure * 55:.1f} / 55 saniye)")
    if len(adimlar):
        print(f"  tek karede en büyük komut  : {adimlar.max():.2f} derece"
              f"   (p90 {np.percentile(adimlar, 90):.2f})")
    print(f"  tepe dönüş hızı            : {hiz.max():.0f} derece/sn"
          f"   (p99 {np.percentile(hiz, 99):.0f})")
    print(f"  |sayaç - enkoder|          : ortalama {np.mean(np.abs(fark)):.2f},"
          f" en büyük {np.abs(fark).max():.2f} derece   (boşluk göstergesi)")
    return ti


def main():
    args = [x for x in sys.argv[1:]]
    sayilar = [x for x in args if x.replace('.', '', 1).isdigit()]
    dosyalar = [x for x in args if x not in sayilar]
    if not dosyalar:
        hepsi = sorted(glob.glob(os.path.join(config.ENCODER_LOG_DIR, '*.csv')),
                       key=os.path.getmtime)
        if not hepsi:
            raise SystemExit(f"{config.ENCODER_LOG_DIR} içinde kayıt yok. "
                             "config.ENCODER_LOG açık mı?")
        dosyalar = [hepsi[-1]]
        print(f"(dosya verilmedi, en yeni kayıt alındı: {os.path.basename(dosyalar[0])})")
    bas = float(sayilar[0]) if len(sayilar) > 0 else None
    bit = float(sayilar[1]) if len(sayilar) > 1 else None

    sonuclar = [(d, olc(d, bas, bit)) for d in dosyalar]

    if len(sonuclar) > 1 and all(s for _, s in sonuclar):
        print("\n=== karşılaştırma (titreşim) ===")
        ilk = sonuclar[0][1]
        for d, s in sonuclar:
            k = s['rms'] / ilk['rms'] if ilk['rms'] else float('nan')
            print(f"  {os.path.basename(d):34s} RMS {s['rms']:.3f} ({k:4.2f}x)"
                  f"   {s['frekans']:5.2f} Hz   bant dışı %{s['bant_disi']:.1f}")
    print("\nDeğerlendirme: titreşim RMS 0.15 derecenin altı iyi, 0.30 üstü kötü."
          " Frekans 2-4 Hz ise denetleyici kaynaklı rezonans (PROJE_DURUMU 29.6).")


if __name__ == '__main__':
    main()
