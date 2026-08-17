# -*- coding: utf-8 -*-
"""
Servo tetik kalibrasyon araci — RASPBERRY PI UZERINDE calisir.

    python3 servo_tani.py

Amac: tetigin GERCEKTEN cekildigi ve serbest kaldigi iki darbe genisligini
(mikrosaniye) bulmak. Bulunan iki deger motor_fire_module.py'ye yazilir:

    FIRE_SERVO_REST_US = <serbest>
    FIRE_SERVO_PULL_US = <cekili>

Kullanim: komut satirindan tek harf + Enter.
    a / d   : -10 / +10 us          (kaba)
    z / c   : -50 / +50 us          (cok kaba)
    s / w   : -2  / +2  us          (ince)
    r       : dinlenme adayini BU degere kaydet
    p       : cekili   adayini BU degere kaydet
    t       : kayitli iki deger arasinda git-gel DENE (gercek ates provasi)
    0       : darbeyi kes (servo gevser)
    q       : cik (cikista servo dinlenmeye gotorulup darbe kesilir)

GUVENLIK: kalibrasyon SILAH TAKILI DEGILKEN yapilmali. 500 us altina ve
2500 us ustune bilerek izin verilmiyor — cogu servo bu araligin disinda
mekanik sinira dayanir ve disli kirar.
"""
import sys
import time

try:
    import lgpio
except ImportError:
    print("HATA: lgpio yok. Bu arac Raspberry Pi uzerinde calisir:")
    print("  sudo apt install python3-lgpio")
    sys.exit(1)

# motor_fire_module ile ayni degerler — oradan okumuyoruz ki bu arac tek
# dosya halinde Pi'ye kopyalanabilsin.
SERVO_PIN = 12
FREQ = 50
ALT, UST = 500, 2500

# gpiochip bul (motor_fire_module._find_gpiochip ile ayni mantik, kisaltilmis)
_LABELS = ('pinctrl-rp1', 'pinctrl-bcm2712', 'pinctrl-bcm2711', 'pinctrl-bcm2835')
h = None
for n in range(32):
    try:
        aday = lgpio.gpiochip_open(n)
    except lgpio.error:
        continue
    try:
        bilgi = lgpio.gpio_get_chip_info(aday)
        if bilgi[2] in _LABELS:
            h = aday
            print("gpiochip%d acildi (%s)" % (n, bilgi[2]))
            break
    except lgpio.error:
        pass
    lgpio.gpiochip_close(aday)
if h is None:
    print("HATA: 40 pinli basliga ait gpiochip bulunamadi (gpiodetect ile bakin).")
    sys.exit(1)

lgpio.gpio_claim_output(h, SERVO_PIN, 0)


def darbe(us):
    lgpio.tx_servo(h, SERVO_PIN, int(us), FREQ, 0, 0)


deger = 1500
dinlenme = None
cekili = None
darbe(deger)
print()
print("Baslangic: %d us (merkez). Servo simdi bu konumda olmali." % deger)
print("Komutlar: a/d = -/+10, z/c = -/+50, s/w = -/+2, r = dinlenme kaydet,")
print("          p = cekili kaydet, t = git-gel dene, 0 = gevset, q = cik")
print()

try:
    while True:
        try:
            k = input("[%4d us | dinlenme=%s cekili=%s] > "
                      % (deger, dinlenme, cekili)).strip().lower()
        except EOFError:
            break
        if not k:
            continue
        if k == 'q':
            break
        elif k in ('a', 'd', 'z', 'c', 's', 'w'):
            adim = {'a': -10, 'd': 10, 'z': -50, 'c': 50, 's': -2, 'w': 2}[k]
            yeni = max(ALT, min(UST, deger + adim))
            if yeni == deger:
                print("  sinirda (%d-%d us)" % (ALT, UST))
            deger = yeni
            darbe(deger)
        elif k == 'r':
            dinlenme = deger
            print("  dinlenme = %d us" % dinlenme)
        elif k == 'p':
            cekili = deger
            print("  cekili = %d us" % cekili)
        elif k == '0':
            lgpio.tx_servo(h, SERVO_PIN, 0)
            print("  darbe kesildi (servo gevsek). Herhangi bir hareket komutu geri acar.")
        elif k == 't':
            if dinlenme is None or cekili is None:
                print("  once r ve p ile iki degeri kaydedin.")
                continue
            print("  prova: %d -> %d -> %d us" % (dinlenme, cekili, dinlenme))
            darbe(cekili)
            time.sleep(0.20)
            darbe(dinlenme)
            time.sleep(0.20)
            deger = dinlenme
        else:
            print("  bilinmeyen komut: %r" % k)
finally:
    # Cikista guvenli durum: dinlenmeye gotur (biliniyorsa), darbeyi kes.
    if dinlenme is not None:
        darbe(dinlenme)
        time.sleep(0.4)
    lgpio.tx_servo(h, SERVO_PIN, 0)
    lgpio.gpiochip_close(h)
    print()
    if dinlenme is not None and cekili is not None:
        print("motor_fire_module.py'ye yazilacak degerler:")
        print("    FIRE_SERVO_REST_US = %d" % dinlenme)
        print("    FIRE_SERVO_PULL_US = %d" % cekili)
        print("fark: %d us = ~%.0f derece" % (abs(cekili - dinlenme),
                                              abs(cekili - dinlenme) / 11.1))
    else:
        print("Kayit tamamlanmadi (r ve p ile iki deger de kaydedilmeliydi).")
