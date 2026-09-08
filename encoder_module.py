# -*- coding: utf-8 -*-
"""
Yaw enkoderi: Wachendorff WDGA 36A CANopen, Raspberry Pi'ye Waveshare
USB-CAN-A ile bağlı.

FAZ 3 — YALNIZCA OKU ve GÖSTER. Kontrol döngüsü hâlâ adım sayacını
(motor_fire_module._simulated_yaw) kullanır. Bu modül gerçek açıyı ölçüp
sunucu yanıtına `encoder_yaw` / `encoder_ok` olarak ekler; PC ekranda adım
sayacıyla yan yana gösterir. Veriye güvenmeden önce onu izlemek için.

NEDEN SocketCAN DEĞİL (2026-09-08 saha ölçümü):
  * Waveshare USB-CAN-A slcan konuşmuyor. `slcand` arayüzü kurar ama tele
    hiçbir şey çıkmaz; candump'taki kendi çerçevelerimiz çekirdek yankısıydı.
  * python-can'in `seeedstudio` sürücüsü de tele çıkmadı.
  * Çalışan tek yol cihazın KENDİ seri protokolü (aşağıda). Bu yüzden
    burada pyserial + elle çerçeveleme var; kütüphane yok.

WAVESHARE PROTOKOLÜ (seri 2 000 000 baud, 8N1):
  ayar : AA 55 12 <hız> <tip=01 std> <filtre×4> <maske×4> <mod> <tekrar> 00 00 00 00 <ck>
         ck = 2..18 arası baytların toplamının düşük baytı
  veri : AA <C0|dlc> <id düşük> <id yüksek> <veri…> 55        (standart 11-bit ID)
  hız  : 1=1M 2=800k 3=500k 4=400k 5=250k 6=200k 7=125k 8=100k 9=50k

CANopen (düğüm 127, sahada okundu ve enkodere `save` edildi):
  0x080  SYNC   — BİZ gönderiyoruz (ENCODER_SYNC_MS'de bir)
  0x2FF  TPDO2  — SYNC'e cevaben konum, UNSIGNED32 little-endian   ← OKUNAN
  0x1FF  TPDO1  — her değişimde; KAPATILDI (0x1800/1 bit 31), hattı boğuyordu
  0x0FF  EMCY   — sayılır, açıya karışmaz
  0x77F  boot-up
  0x6001 = 0x6002 = 16384 (14 bit), 0x6003 preset = 8192 → mekanik merkez 8192.

AÇI HESABI:
  toplam = tur × CPR + ham            (sarma çözümü, eşik CPR/2)
  derece = (toplam − merkez − ofset) / (CPR × oran / 360)
  R = 2 için 91.0 sayım/derece, 0.011°/sayım. Bir enkoder turu = 180° taret;
  taret ±90°'de ham 0↔16383 sarar, sarma çözümü bunu takip eder.

AÇILIŞ KURALI: güç gelince tur sayacı bilinmez; ham değer merkeze EN YAKIN
tura yerleştirilir. Yani sunucu, taret merkezden ±90° içindeyken başlamalı
(pratikte her zaman böyle; taret ±80-90° gidebiliyor). Tam ±90'da belirsizlik
var, oradan başlatma.

Bu dosya PC'de de import edilebilir (testler için): pyserial yalnızca
`baslat()` içinde yüklenir.
"""
import sys
import time
import threading

import motor_fire_module as mfm

HIZ_KODU = {1000000: 1, 800000: 2, 500000: 3, 400000: 4, 250000: 5,
            200000: 6, 125000: 7, 100000: 8, 50000: 9}

SYNC_ID = 0x080
NMT_ID = 0x000


# ---------------------------------------------------------------------------
#  Saf fonksiyonlar (donanımsız test edilir)
# ---------------------------------------------------------------------------

def ayar_cercevesi(bitrate, mod=0):
    """Waveshare ayar çerçevesi (20 bayt). mod: 0 normal, 1 loopback, 2 sessiz."""
    kod = HIZ_KODU[bitrate]
    f = [0xAA, 0x55, 0x12, kod, 0x01] + [0] * 8 + [mod, 0x00] + [0] * 4
    f.append(sum(f[2:19]) & 0xFF)
    return bytes(f)


def veri_cercevesi(aid, data):
    """Standart 11-bit ID'li veri çerçevesi."""
    data = list(data)
    if len(data) > 8:
        raise ValueError("CAN verisi en fazla 8 bayt")
    return bytes([0xAA, 0xC0 | len(data), aid & 0xFF, (aid >> 8) & 0xFF]
                 + data + [0x55])


def cozumle(buf):
    """
    `buf` (bytearray) içindeki tam çerçeveleri (id, veri) listesi olarak
    döndürür ve tüketir; yarım çerçeve tamponda kalır. 20 baytlık ayar
    yankıları (AA 55 …) atlanır.
    """
    out = []
    while True:
        i = buf.find(b'\xAA')
        if i < 0:
            buf.clear()
            return out
        if len(buf) < i + 2:
            del buf[:i]
            return out
        t = buf[i + 1]
        if t == 0x55:                      # ayar/durum yankısı, 20 bayt
            if len(buf) < i + 20:
                del buf[:i]
                return out
            del buf[:i + 20]
            continue
        if t & 0xC0 != 0xC0:               # çerçeve başı değil, atla
            del buf[:i + 1]
            continue
        dlc = t & 0x0F
        nid = 4 if t & 0x20 else 2
        n = 2 + nid + dlc + 1
        if dlc > 8:
            del buf[:i + 1]
            continue
        if len(buf) < i + n:
            del buf[:i]
            return out
        fr = buf[i:i + n]
        if fr[-1] == 0x55:
            aid = int.from_bytes(fr[2:2 + nid], 'little')
            out.append((aid, bytes(fr[2 + nid:-1])))
            del buf[:i + n]
        else:
            del buf[:i + 1]


def sarma_coz(ham, onceki_ham, tur, cpr):
    """Tek turlu enkoderin 0↔CPR sarmasını çözer. (tur, toplam) döner."""
    fark = ham - onceki_ham
    if fark > cpr / 2:
        tur -= 1
    elif fark < -cpr / 2:
        tur += 1
    return tur, tur * cpr + ham


def baslangic_toplam(ham, merkez, cpr):
    """Açılışta ham değeri merkeze en yakın tura yerleştir: (merkez−CPR/2, merkez+CPR/2]."""
    toplam = ham
    while toplam - merkez > cpr / 2:
        toplam -= cpr
    while toplam - merkez <= -cpr / 2:
        toplam += cpr
    return toplam


def sayim_per_derece(cpr, oran):
    return cpr * oran / 360.0


def sayim_to_derece(toplam, cpr, oran, merkez, ters=False, ofset=0):
    d = (toplam - merkez - ofset) / sayim_per_derece(cpr, oran)
    return -d if ters else d


# ---------------------------------------------------------------------------
#  Enkoder nesnesi
# ---------------------------------------------------------------------------

class Enkoder:
    def __init__(self, port=None, bitrate=None, cpr=None, oran=None, merkez=None,
                 ters=None, sync_ms=None, zaman_asimi=None, node_id=None):
        self.port = port or mfm.ENCODER_PORT
        self.bitrate = bitrate or mfm.ENCODER_BITRATE
        self.cpr = cpr or mfm.ENCODER_CPR
        self.oran = oran or mfm.ENCODER_GEAR_RATIO
        self.merkez = mfm.ENCODER_CENTER if merkez is None else merkez
        self.ters = mfm.ENCODER_INVERT if ters is None else ters
        self.sync_ms = sync_ms or mfm.ENCODER_SYNC_MS
        self.zaman_asimi = zaman_asimi or mfm.ENCODER_TIMEOUT_SEC
        self.node_id = node_id or mfm.ENCODER_NODE_ID
        self.tpdo_id = 0x280 + self.node_id      # TPDO2
        self.emcy_id = 0x080 + self.node_id

        self._kilit = threading.Lock()
        self._ham = None
        self._tur = 0
        self._toplam = None
        self._ofset = 0
        self._son_zaman = 0.0
        self._emcy = 0
        self._cerceve = 0
        self._hata = None
        self._seri = None
        self._is = None
        self._calisiyor = False

    # --- veri işleme (donanımsız çağrılabilir) ---
    def _isle(self, aid, d, simdi=None):
        simdi = time.monotonic() if simdi is None else simdi
        if aid == self.tpdo_id and len(d) >= 4:
            ham = int.from_bytes(d[:4], 'little') % self.cpr
            with self._kilit:
                if self._ham is None:
                    self._tur = 0
                    self._toplam = baslangic_toplam(ham, self.merkez, self.cpr)
                    self._tur = (self._toplam - ham) // self.cpr
                else:
                    self._tur, self._toplam = sarma_coz(ham, self._ham, self._tur, self.cpr)
                self._ham = ham
                self._son_zaman = simdi
                self._cerceve += 1
        elif aid == self.emcy_id:
            with self._kilit:
                self._emcy += 1

    def saglikli_mi(self, simdi=None):
        simdi = time.monotonic() if simdi is None else simdi
        with self._kilit:
            return self._toplam is not None and (simdi - self._son_zaman) < self.zaman_asimi

    def taret_acisi(self, simdi=None):
        """Derece; sağlıksızsa None."""
        if not self.saglikli_mi(simdi):
            return None
        with self._kilit:
            return sayim_to_derece(self._toplam, self.cpr, self.oran, self.merkez,
                                   self.ters, self._ofset)

    def ham(self):
        with self._kilit:
            return self._ham

    def sifirla(self):
        """Mevcut konumu 0° kabul et (arayüzdeki 'Açıları Sıfırla' ile aynı anlam)."""
        with self._kilit:
            if self._toplam is not None:
                self._ofset = self._toplam - self.merkez

    def rapor(self, simdi=None):
        """Sunucu yanıtına eklenecek alanlar."""
        aci = self.taret_acisi(simdi)
        with self._kilit:
            return {"encoder_ok": aci is not None,
                    "encoder_yaw": None if aci is None else round(aci, 3),
                    "encoder_raw": self._ham}

    def durum(self):
        with self._kilit:
            return {"port": self.port, "calisiyor": self._calisiyor, "hata": self._hata,
                    "ham": self._ham, "tur": self._tur, "toplam": self._toplam,
                    "ofset": self._ofset, "emcy": self._emcy, "cerceve": self._cerceve}

    # --- donanım ---
    def _ac(self):
        import serial  # yalnızca burada: PC'de pyserial olmadan da import edilebilsin
        self._seri = serial.Serial(self.port, 2000000, timeout=0)
        self._seri.write(ayar_cercevesi(self.bitrate))
        time.sleep(0.3)
        self._seri.reset_input_buffer()
        self._seri.write(veri_cercevesi(NMT_ID, [0x01, 0x00]))   # NMT start all
        self._hata = None

    def baslat(self):
        if self._calisiyor:
            return True
        try:
            self._ac()
        except Exception as e:
            self._hata = str(e)
            print(f"HATA (encoder_module): enkoder açılamadı ({self.port}): {e}")
            sys.stdout.flush()
            return False
        self._calisiyor = True
        self._is = threading.Thread(target=self._dongu, daemon=True)
        self._is.start()
        print(f"DEBUG (encoder_module): enkoder başlatıldı: {self.port}, "
              f"{self.bitrate // 1000} kbit/s, CPR {self.cpr}, oran {self.oran}, SYNC {self.sync_ms} ms")
        sys.stdout.flush()
        return True

    def kapat(self):
        self._calisiyor = False
        if self._is is not None:
            self._is.join(timeout=1.0)
        if self._seri is not None:
            try:
                self._seri.close()
            except Exception:
                pass
            self._seri = None

    def _dongu(self):
        buf = bytearray()
        son_sync = 0.0
        son_uyari = 0.0
        while self._calisiyor:
            try:
                simdi = time.monotonic()
                if simdi - son_sync >= self.sync_ms / 1000.0:
                    self._seri.write(veri_cercevesi(SYNC_ID, []))
                    son_sync = simdi
                veri = self._seri.read(4096)
                if veri:
                    buf.extend(veri)
                    for aid, d in cozumle(buf):
                        self._isle(aid, d, simdi)
                if not self.saglikli_mi(simdi) and simdi - son_uyari > 5.0:
                    son_uyari = simdi
                    print("UYARI (encoder_module): enkoderden veri gelmiyor (kablo? güç? bit hızı?)")
                    sys.stdout.flush()
                time.sleep(0.001)
            except Exception as e:
                # Kablo çekildi / USB resetlendi: sağlıksız kal, yeniden açmayı dene.
                self._hata = str(e)
                print(f"HATA (encoder_module): seri hata: {e} — 2 sn sonra yeniden denenecek")
                sys.stdout.flush()
                try:
                    self._seri.close()
                except Exception:
                    pass
                time.sleep(2.0)
                if not self._calisiyor:
                    break
                try:
                    self._ac()
                    buf.clear()
                except Exception as e2:
                    self._hata = str(e2)


# ---------------------------------------------------------------------------
#  Modül düzeyi tekil nesne (rpi_motor_server bunu kullanır)
# ---------------------------------------------------------------------------

_enkoder = None


def baslat():
    global _enkoder
    if not getattr(mfm, "ENCODER_ENABLED", False):
        print("DEBUG (encoder_module): ENCODER_ENABLED = False, enkoder devre dışı.")
        sys.stdout.flush()
        return False
    if _enkoder is None:
        _enkoder = Enkoder()
    return _enkoder.baslat()


def kapat():
    if _enkoder is not None:
        _enkoder.kapat()


def sifirla():
    if _enkoder is not None:
        _enkoder.sifirla()


def taret_acisi():
    return None if _enkoder is None else _enkoder.taret_acisi()


def saglikli_mi():
    return _enkoder is not None and _enkoder.saglikli_mi()


def rapor():
    if _enkoder is None:
        return {"encoder_ok": False, "encoder_yaw": None, "encoder_raw": None}
    return _enkoder.rapor()


def durum():
    return None if _enkoder is None else _enkoder.durum()


if __name__ == "__main__":
    # Tek başına tanı: python3 encoder_module.py
    if not baslat():
        sys.exit(1)
    try:
        while True:
            d = durum()
            print(f"aci {taret_acisi()}  ham {d['ham']}  tur {d['tur']}  "
                  f"cerceve {d['cerceve']}  emcy {d['emcy']}  hata {d['hata']}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        kapat()
