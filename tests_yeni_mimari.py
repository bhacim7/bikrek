"""Yeni mimarinin birim testleri: eşleştirme, dost/düşman, durum makinesi."""
import sys, time
sys.path.insert(0, r"C:\Users\barış hacim\PycharmProjects\PythonProject\HSSmultipocess")

import numpy as np
import cv2
import config
import engagement
import spotter_module as sp

hata = 0


def kontrol(ad, kosul, ek=""):
    global hata
    if not kosul:
        hata += 1
    print(f"  [{'OK ' if kosul else 'HATA'}] {ad}{(' — ' + ek) if ek else ''}")


def det(sinif, x, y, w, h, skor=0.9):
    return {'class_name': sinif, 'bbox': (x, y, w, h), 'score': skor}


print("=" * 70)
print("1. HEDEF CIFTI ESLESTIRME (geometrik, mesafeden bagimsiz)")
print("=" * 70)

# 15 metre: maket 96 px, balon 30 px, balon maketin ~1.2 maket-genisligi altinda
uzak = [det('dusman-Drone', 600, 300, 96, 60), det('balon', 633, 415, 30, 30)]
c = engagement.cift_eslestir(uzak)
kontrol("uzak hedef eslesti", len(c) == 1 and c[0].balon is not None)
kontrol("sinif dusman", engagement.dusman_mi(c[0].sinif), c[0].sinif)

# 5 metre: her sey 3 kat buyuk. AYNI kural calismali (normalize edildigi icin)
yakin = [det('dusman-Drone', 400, 200, 288, 180), det('balon', 499, 545, 90, 90)]
c = engagement.cift_eslestir(yakin)
kontrol("yakin hedef eslesti (ayni kural)", len(c) == 1 and c[0].balon is not None)

# Balon maketin USTUNDE ise eslesmemeli
ters = [det('dusman-Drone', 600, 400, 96, 60), det('balon', 633, 300, 30, 30)]
c = engagement.cift_eslestir(ters)
kontrol("balon ustteyse eslesmez", c[0].balon is None)

# Balon yatayda cok uzaksa eslesmemeli
kaymis = [det('dusman-Drone', 600, 300, 96, 60), det('balon', 900, 415, 30, 30)]
c = engagement.cift_eslestir(kaymis)
kontrol("yatayda uzak balon eslesmez", c[0].balon is None)

# Iki hedef: her maket kendi balonuyla eslesmeli
ikili = [det('dusman-F16', 200, 300, 90, 55), det('balon', 230, 410, 28, 28),
         det('dost-Helikopter', 800, 300, 90, 55), det('balon', 830, 410, 28, 28)]
c = engagement.cift_eslestir(ikili)
kontrol("iki cift kuruldu", len(c) == 2)
dogru = all(x.balon is not None for x in c)
kontrol("her maket kendi balonunu aldi", dogru)
siniflar = sorted(x.sinif for x in c)
kontrol("dost ve dusman ayri", siniflar == ['dost-Helikopter', 'dusman-F16'], str(siniflar))

# Tek basina duran balon hedef cifti olusturmaz (hayalet eleyici)
c = engagement.cift_eslestir([det('balon', 600, 400, 30, 30)])
kontrol("yalniz balon cift olusturmaz", len(c) == 0)

print()
print("=" * 70)
print("2. NISAN NOKTASI ve YEDEK YOL")
print("=" * 70)
c = engagement.cift_eslestir(uzak)[0]
cx, cy, r, gercek = c.nisan_noktasi()
kontrol("balon varken balona nisan", gercek and abs(cx - 648) < 2 and abs(cy - 430) < 2,
        f"({cx:.0f},{cy:.0f}) r={r:.0f}")
c2 = engagement.HedefCifti(uzak[0], None, 0.0)
cx2, cy2, r2, gercek2 = c2.nisan_noktasi()
kontrol("balon yokken maketten turetiliyor", (not gercek2) and cy2 > uzak[0]['bbox'][1],
        f"({cx2:.0f},{cy2:.0f})")

print()
print("=" * 70)
print("3. GOZCU DOST/DUSMAN — mesafeden bagimsizlik")
print("=" * 70)


def sahne(gen, yuk, hedefler):
    """hedefler: [(cx, cy, balon_cap, maket_gen, maket_yuk, maket_rengi)]"""
    img = np.zeros((yuk, gen, 3), np.uint8)
    for cx, cy, cap, mg, my, renk in hedefler:
        cv2.circle(img, (cx, cy), cap // 2, (0, 0, 230), -1)          # kirmizi balon
        bgr = (230, 60, 0) if renk == 'mavi' else (0, 0, 230)
        ust = cy - int(cap * 1.6)
        cv2.rectangle(img, (cx - mg // 2, ust - my // 2),
                      (cx + mg // 2, ust + my // 2), bgr, -1)
    return img


# Kritik senaryo: YAKIN DOST + UZAK DUSMAN.
# "En buyuk kirmizi = dusman" kurali burada CUVALLIYOR; geometri kurali dogru
# cevabi vermeli.
img = sahne(1280, 720, [
    (300, 400, 120, 340, 110, 'mavi'),   # YAKIN DOST  (buyuk mavi maket)
    (1000, 380, 34, 90, 32, 'kirmizi'),  # UZAK DUSMAN (kucuk kirmizi maket)
])
yon = sp.IzYoneticisi()
izler, kirmizi, mavi = sp.kareyi_coz(img, yon, time.time())
izler, _, _ = sp.kareyi_coz(img, yon, time.time() + 0.04)   # gorulme >= 2 icin

bulunan = {}
for iz in izler:
    yan = 'sol' if iz.yaw < 0 else 'sag'
    bulunan[yan] = iz
print(f"  bulunan iz sayisi: {len(izler)}")
for iz in izler:
    print(f"    yaw {iz.yaw:+6.1f}  sinif={iz.sinif:9s} mavi_oran={iz.mavi_oran:.2f} "
          f"kirmizi_alan={iz.kirmizi_alan}")

kontrol("iki hedef de bulundu", len(izler) == 2)
if 'sol' in bulunan and 'sag' in bulunan:
    kontrol("yakin buyuk hedef DOST olarak isaretlendi",
            bulunan['sol'].sinif == sp.DOST, bulunan['sol'].sinif)
    kontrol("uzak kucuk hedef DUSMAN olarak isaretlendi",
            bulunan['sag'].sinif == sp.DUSMAN, bulunan['sag'].sinif)
    # ESKI kuralin cuvalladigini goster
    eski_kural = max(izler, key=lambda i: i.kirmizi_alan)
    print(f"  >>> ESKI kural ('en buyuk kirmizi') secerdi: yaw {eski_kural.yaw:+.1f} "
          f"({eski_kural.sinif})")
    kontrol("eski kural gercekten dostu secerdi (sorunun kaniti)",
            eski_kural.sinif == sp.DOST)

print()
print("=" * 70)
print("4. ADAY SIRALAMA — Asama 3'te dost hic siraya girmez")
print("=" * 70)
kl = engagement.KaraListe()
izl = [iz.sozluk() for iz in izler]
s3 = engagement.aday_sirala(izl, kl, 'task3')
kontrol("asama3: dost elendi", all(i['sinif'] != 'dost' for i in s3), str([i['sinif'] for i in s3]))
s2 = engagement.aday_sirala(izl, kl, 'task2')
kontrol("asama2: en buyuk kirmizi once", len(s2) >= 1 and s2[0]['kirmizi_alan'] >=
        (s2[1]['kirmizi_alan'] if len(s2) > 1 else 0))

print()
print("=" * 70)
print("5. DURUM MAKINESI — dost dogrulamasi angajmani iptal etmeli")
print("=" * 70)
m = engagement.AngajmanMakinesi()
m.basla('task3')
kontrol("baslangic TARAMA", m.durum == engagement.TARAMA, m.durum)

sahte_iz = [{'id': 1, 'yaw': 12.0, 'pitch': -2.0, 'yaw_hiz': 1.0, 'pitch_hiz': 0.0,
             'sinif': 'kararsiz', 'mavi_oran': 0.4, 'kirmizi_alan': 900,
             'cap': 20, 'gorulme': 5, 'kayip': 0}]
hedef = m.tarama_adimi(sahte_iz)
kontrol("YONELME'ye gecti", m.durum == engagement.YONELME, m.durum)
kontrol("hedef acisi ONGORULU (hiz x sure eklenmis)", hedef[0] > 12.0,
        f"{hedef[0]:.3f} > 12.0")

m.yonelme_adimi(hedef[0], hedef[1])
kontrol("taret oturunca DOGRULAMA", m.durum == engagement.DOGRULAMA, m.durum)

# DOST dogrulanirsa: kara listeye girmeli, TARAMA'ya donmeli
dost_cift = engagement.cift_eslestir(
    [det('dost-F16', 600, 300, 96, 60, 0.9), det('balon', 633, 415, 30, 30, 0.9)])
for _ in range(config.VERIFY_CONFIRM_FRAMES):
    m.dogrulama_adimi(dost_cift)
kontrol("dost -> TARAMA'ya donuldu", m.durum == engagement.TARAMA, m.durum)
kontrol("dost kara listeye alindi", m.kara_liste.icinde_mi(hedef[0], hedef[1]))
kontrol("kara listedeki aday bir daha secilmiyor",
        m.tarama_adimi([{**sahte_iz[0], 'yaw': hedef[0], 'pitch': hedef[1]}]) is None)

# DUSMAN dogrulanirsa: KILIT'e gecmeli
m2 = engagement.AngajmanMakinesi()
m2.basla('task2')
h = m2.tarama_adimi(sahte_iz)
m2.yonelme_adimi(h[0], h[1])
dusman_cift = engagement.cift_eslestir(uzak)
for _ in range(config.VERIFY_CONFIRM_FRAMES):
    m2.dogrulama_adimi(dusman_cift)
kontrol("dusman -> KILIT", m2.durum == engagement.KILIT, m2.durum)

# Nisan tutulunca ATES
for _ in range(config.AIM_HOLD_FRAMES):
    m2.kilit_adimi(2.0, 15.0, True)
kontrol("nisan tutulunca ATES", m2.durum == engagement.ATES, m2.durum)

print()
print("=" * 70)
print("6. ATES KILIDI")
print("=" * 70)
cift = dusman_cift[0]
izin, ger = engagement.ates_serbest_mi(cift, m2, True, True, 0.0, 0.0, 0.0)
kontrol("tum kosullar tamamsa serbest", izin, ger)

izin, ger = engagement.ates_serbest_mi(cift, m2, False, True, 0.0, 0.0, 0.0)
kontrol("balon GORULMEDIYSE engellenir (eski Asama3 acigi)", not izin, ger)

izin, ger = engagement.ates_serbest_mi(
    engagement.HedefCifti(None, cift.balon, 1.0), m2, True, True, 0.0, 0.0, 0.0)
kontrol("maket yoksa engellenir", not izin, ger)

dost = engagement.cift_eslestir(
    [det('dost-F16', 600, 300, 96, 60), det('balon', 633, 415, 30, 30)])[0]
izin, ger = engagement.ates_serbest_mi(dost, m2, True, True, 0.0, 0.0, 0.0)
kontrol("DOST'a ates engellenir", not izin, ger)

izin, ger = engagement.ates_serbest_mi(cift, m2, True, False, 0.0, 0.0, 0.0)
kontrol("nisan disindaysa engellenir", not izin, ger)

izin, ger = engagement.ates_serbest_mi(cift, m2, True, True, 5.0, -15.0, 15.0)
kontrol("atesiz bolgede engellenir", not izin, ger)

izin, ger = engagement.ates_serbest_mi(cift, m2, True, True, 0.0, 0.0, 0.0)
kontrol("atesiz bolge (0,0) tanimsiz sayilir — eski hata", izin, ger)

print()
print("=" * 70)
print("7. OLCEK KONTROLLERI (15 metre, gercek boyutlar)")
print("=" * 70)
balon_aci = 2 * np.degrees(np.arctan(0.07 / 15))
maket_aci = 2 * np.degrees(np.arctan(0.225 / 15))
b_avci = balon_aci / config.HUNTER_DPP_YAW
m_avci = maket_aci / config.HUNTER_DPP_YAW
b_gozcu = balon_aci / config.SPOTTER_DPP_YAW
print(f"  balon 14 cm @ 15 m: {balon_aci:.3f} derece -> avci {b_avci:.0f} px, gozcu {b_gozcu:.0f} px")
print(f"  maket 45 cm @ 15 m: {maket_aci:.3f} derece -> avci {m_avci:.0f} px")
kontrol("balon avcida YOLO icin yeterli (>=20 px)", b_avci >= 20, f"{b_avci:.0f} px")
kontrol("balon gozcude blob icin yeterli (>=8 px)", b_gozcu >= 8, f"{b_gozcu:.0f} px")
kontrol("gozcu min blob alani balonun altinda",
        config.SPOTTER_MIN_BLOB_AREA < 3.14 * (b_gozcu / 2) ** 2,
        f"{config.SPOTTER_MIN_BLOB_AREA} < {3.14*(b_gozcu/2)**2:.0f}")

# Hedef acisal hizi ve feedforward olu bandi
for mesafe in (15, 8, 5):
    b = 7.5
    x = mesafe
    w = np.degrees(b / (x * x + b * b) * 0.4)
    ff_var = w >= config.FEEDFORWARD_VELOCITY_DEADBAND
    kalan = w * config.FEEDFORWARD_LEAD_TIME / config.HUNTER_DPP_YAW
    print(f"  {mesafe:2d} m: hedef {w:.2f} derece/sn | ff {'ACIK' if ff_var else 'kapali'} "
          f"| ff'siz kalan hata {kalan:.0f} px")
kontrol("olu bant gercek hedef hizlarinin altinda",
        config.FEEDFORWARD_VELOCITY_DEADBAND < 2.6,
        f"{config.FEEDFORWARD_VELOCITY_DEADBAND} < 2.6")

# Hata kapisi acisal anlamini korumali
tam, sifir = config.FEEDFORWARD_ERROR_GATE_PIXELS
print(f"  hata kapisi: {tam:.0f}/{sifir:.0f} px = "
      f"{tam*config.HUNTER_DPP_YAW:.2f}/{sifir*config.HUNTER_DPP_YAW:.2f} derece")
kontrol("hata kapisi genis kameradaki aciyi koruyor (~1.6/6.4 derece)",
        abs(tam * config.HUNTER_DPP_YAW - 1.6) < 0.2 and
        abs(sifir * config.HUNTER_DPP_YAW - 6.4) < 0.4)

# Avci gorus acisi devir teslime yetiyor mu
fov_y = config.HUNTER_WIDTH * config.HUNTER_DPP_YAW
fov_p = config.HUNTER_HEIGHT * abs(config.HUNTER_DPP_PITCH)
print(f"  avci gorus acisi: {fov_y:.1f} x {fov_p:.1f} derece")
kontrol("devir teslim payi yeterli (yari-pitch > 5 derece)", fov_p / 2 > 5,
        f"{fov_p/2:.1f}")

print()
print("=" * 70)
print(f"SONUC: {'TUM TESTLER GECTI' if hata == 0 else str(hata) + ' TEST BASARISIZ'}")
print("=" * 70)
sys.exit(1 if hata else 0)
