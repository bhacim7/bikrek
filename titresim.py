# -*- coding: utf-8 -*-
"""Titremenin frekansi ve genligi: enkoder sinyalini yavas bilesenden ayir."""
import csv
import numpy as np


def yukle(yol):
    r = list(csv.DictReader(open(yol)))
    t = np.array([float(x['t']) for x in r])
    return t - t[0], np.array([float(x['sayac_yaw']) for x in r]), np.array([float(x['enk_yaw']) for x in r])


def analiz(ad, yol, a, b):
    t, s, e = yukle(yol)
    m = (t >= a) & (t <= b)
    tt, ee, ss = t[m], e[m], s[m]
    # esit araliga getir (21 ms -> 50 Hz)
    fs = 50.0
    ti = np.arange(tt[0], tt[-1], 1 / fs)
    ei = np.interp(ti, tt, ee)
    # yavas bilesen: 0.4 sn'lik kayan ortalama
    n = int(0.4 * fs)
    cek = np.convolve(ei, np.ones(n) / n, mode='same')
    kalan = (ei - cek)[n:-n]
    # FFT
    w = np.hanning(len(kalan))
    sp = np.abs(np.fft.rfft(kalan * w))
    fr = np.fft.rfftfreq(len(kalan), 1 / fs)
    band = (fr > 0.5) & (fr < 8)
    tepe = fr[band][np.argmax(sp[band])]
    # sifir gecisleri -> frekans
    gec = np.sum(np.diff(np.sign(kalan)) != 0)
    f_gec = gec / 2 / (len(kalan) / fs)
    print(f"{ad:24s} titresim RMS {kalan.std():.3f} deg, tepeden tepeye {np.percentile(kalan, 97) - np.percentile(kalan, 3):.2f} deg, "
          f"FFT tepe {tepe:.2f} Hz, sifir-gecis frekansi {f_gec:.2f} Hz")
    # nisan toleransi karsiligi: 14 px = 0.198 deg
    print(f"{'':24s} 0.198 derece bandinin disinda gecen zaman: %{100 * np.mean(np.abs(kalan) > 0.198):.1f}")


print("Titreme (yavas yonelme cikarildiktan sonra kalan bilesen):")
analiz("ONCE  (asama3Denem)", r"enkoder_kayit/enkoder_20260916_142911.csv", 61.507 - 3.2 + 9.0, 61.507 - 3.2 + 22.0)
analiz("SONRA (asama3Deneme2)", r"enkoder_kayit/enkoder_20260916_152053.csv", 229.03 - 3.75 + 4.0, 229.03 - 3.75 + 17.0)
