"""
config.py'ye GERI YAZMA (2026-09-24, PROJE_DURUMU 29.21).

Arayuzdeki "Kaydet" dugmesi burayi cagirir. Amac: sahada kaydiriciyla
bulunan bir degeri kalici hale getirmek, boylece bir sonraki aciliste
zaten o degerle baslanir.

TASARIM KURALI — DOSYAYI BOZMAMAK:
  1. Yalnizca `AD = deger` bicimindeki MODUL SEVIYESI atamalar ve
     `KAMERA_KONTROLLERI` icindeki `"anahtar": deger` satirlari degisir.
  2. Satirdaki yorum, girinti ve dosyanin geri kalani harfi harfine korunur.
  3. Yazmadan ONCE yeni metin `compile()` ile derlenir; derlenmezse hicbir
     sey yazilmaz.
  4. Yazmadan once `config.py.yedek` olusturulur.
  5. Yazdiktan sonra dosya AYRI BIR SURECTE import edilip degerlerin
     gercekten okundugu dogrulanir; dogrulanmazsa yedekten geri alinir.
Bu adimlarin hepsi, calisan bir yarisma sisteminin ayar dosyasini tek bir
hatali regex ile kaybetmemek icin.
"""

import io
import os
import re
import shutil
import subprocess
import sys

_KAMERA_BASLIK = re.compile(r'^\s*"(spotter|hunter)"\s*:\s*\{\s*$')
_KAMERA_ANAHTAR = re.compile(
    r'^(?P<on>\s*"(?P<ad>[a-z_]+)"\s*:\s*)(?P<deger>[^,#]*?)(?P<virgul>,?)(?P<yorum>\s*#.*)?$')


def deger_metni(deger):
    """Python kaynagina yazilacak literal metin."""
    if deger is None:
        return "None"
    if isinstance(deger, bool):
        return "True" if deger else "False"
    if isinstance(deger, int):
        return str(deger)
    if isinstance(deger, float):
        if deger == int(deger) and abs(deger) < 1e15:
            return f"{deger:.1f}"
        return repr(round(deger, 6))
    return repr(deger)


def sabitleri_degistir(kaynak, degisiklikler):
    """
    Modul seviyesi `AD = deger` satirlarini degistirir.

    Ayni ad birden cok kez atanmissa SONUNCUSU gecerli oldugu icin hepsi
    guncellenir. Doner: (yeni_kaynak, bulunanlar, bulunamayanlar)
    """
    if not degisiklikler:
        return kaynak, set(), set()
    satirlar = kaynak.split('\n')
    bulunan = set()
    for i, satir in enumerate(satirlar):
        m = re.match(r'^([A-Z_][A-Z0-9_]*)(\s*=\s*)([^#]*?)(\s*#.*)?$', satir)
        if not m:
            continue
        ad = m.group(1)
        if ad not in degisiklikler:
            continue
        yorum = m.group(4) or ''
        satirlar[i] = f"{ad}{m.group(2)}{deger_metni(degisiklikler[ad])}{yorum}"
        bulunan.add(ad)
    return '\n'.join(satirlar), bulunan, set(degisiklikler) - bulunan


def kamera_degerlerini_degistir(kaynak, kamera_degisiklikleri):
    """
    `KAMERA_KONTROLLERI` sozlugu icindeki kamera bloklarini gunceller.

    kamera_degisiklikleri: {"hunter": {"gain": 168, ...}, "spotter": {...}}
    Doner: (yeni_kaynak, yazilan_sayisi)
    """
    if not kamera_degisiklikleri:
        return kaynak, 0
    satirlar = kaynak.split('\n')
    aktif = None
    yazilan = 0
    for i, satir in enumerate(satirlar):
        bas = _KAMERA_BASLIK.match(satir)
        if bas:
            aktif = bas.group(1)
            continue
        if aktif is None:
            continue
        # Blok sonu: girintisi 4 olan kapanis
        if re.match(r'^\s{0,8}\},?\s*$', satir):
            aktif = None
            continue
        m = _KAMERA_ANAHTAR.match(satir)
        if not m:
            continue
        ad = m.group('ad')
        istek = kamera_degisiklikleri.get(aktif, {})
        if ad not in istek:
            continue
        satirlar[i] = (f"{m.group('on')}{deger_metni(istek[ad])}"
                       f"{m.group('virgul')}{m.group('yorum') or ''}")
        yazilan += 1
    return '\n'.join(satirlar), yazilan


def kaydet(sabitler=None, kamera=None, yol=None):
    """
    Degisiklikleri config.py'ye yazar.

    Doner: (basarili_mi, mesaj)
    Basarisizlikta dosya HIC degismemis olur (ya da yedekten geri alinir).
    """
    yol = yol or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'config.py')
    try:
        with io.open(yol, encoding='utf-8') as f:
            orijinal = f.read()
    except Exception as e:
        return False, f"config.py okunamadi: {e}"

    yeni, bulunan, eksik = sabitleri_degistir(orijinal, sabitler or {})
    yeni, kamera_sayisi = kamera_degerlerini_degistir(yeni, kamera or {})

    if yeni == orijinal:
        return True, "Degisiklik yok (dosya zaten guncel)."

    # 3. adim: derlenmiyorsa dokunma.
    try:
        compile(yeni, yol, 'exec')
    except SyntaxError as e:
        return False, f"Yeni icerik derlenmedi, yazilmadi: {e}"

    # 4. adim: yedek.
    yedek = yol + '.yedek'
    try:
        shutil.copy2(yol, yedek)
    except Exception as e:
        return False, f"Yedek alinamadi, yazilmadi: {e}"

    try:
        with io.open(yol, 'w', encoding='utf-8', newline='') as f:
            f.write(yeni)
    except Exception as e:
        shutil.copy2(yedek, yol)
        return False, f"Yazilamadi, geri alindi: {e}"

    # 5. adim: ayri surecte import edip degerleri dogrula.
    ok, ayrinti = _dogrula(yol, sabitler or {}, kamera or {})
    if not ok:
        shutil.copy2(yedek, yol)
        return False, f"Dogrulama basarisiz, geri alindi: {ayrinti}"

    mesaj = f"{len(bulunan)} sabit"
    if kamera_sayisi:
        mesaj += f" + {kamera_sayisi} kamera denetimi"
    mesaj += " config.py'ye kaydedildi."
    if eksik:
        mesaj += f" (bulunamadi: {', '.join(sorted(eksik))})"
    return True, mesaj


def _dogrula(yol, sabitler, kamera):
    """Yazilan dosyayi AYRI BIR SURECTE import edip degerleri karsilastirir."""
    klasor = os.path.dirname(yol)
    kod = (
        "import json,sys\n"
        "sys.path.insert(0,%r)\n"
        "import config\n"
        "print(json.dumps({'sabit':{a:getattr(config,a,None) for a in %r},"
        "'kamera':{k:{x:config.KAMERA_KONTROLLERI.get(k,{}).get(x) for x in v}"
        " for k,v in %r.items()}}))\n"
        % (klasor, list(sabitler), {k: list(v) for k, v in kamera.items()})
    )
    try:
        sonuc = subprocess.run([sys.executable, '-c', kod], capture_output=True,
                               text=True, timeout=60, cwd=klasor)
    except Exception as e:
        return False, f"dogrulama sureci calismadi: {e}"
    if sonuc.returncode != 0:
        return False, (sonuc.stderr or '').strip().splitlines()[-1:] or 'import hatasi'
    import json
    try:
        okunan = json.loads(sonuc.stdout.strip().splitlines()[-1])
    except Exception as e:
        return False, f"dogrulama ciktisi okunamadi: {e}"
    for ad, beklenen in sabitler.items():
        varolan = okunan['sabit'].get(ad)
        if varolan is None and beklenen is None:
            continue
        if varolan is None or abs(float(varolan) - float(beklenen)) > 1e-6:
            return False, f"{ad}: beklenen {beklenen}, okunan {varolan}"
    for kam, istek in kamera.items():
        for ad, beklenen in istek.items():
            varolan = okunan['kamera'].get(kam, {}).get(ad)
            if beklenen is None:
                if varolan is not None:
                    return False, f"{kam}.{ad}: None bekleniyordu, {varolan} okundu"
                continue
            if varolan is None or abs(float(varolan) - float(beklenen)) > 1e-6:
                return False, f"{kam}.{ad}: beklenen {beklenen}, okunan {varolan}"
    return True, "tamam"
