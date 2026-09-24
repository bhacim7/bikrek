"""
AYARLAR PENCERESI — arayuzun tek ayar noktasi (2026-09-24, 29.20).

Bu dosya SISTEMIN DAVRANISINA HICBIR SEY EKLEMEZ. Yaptigi tek sey:
  - `config` icindeki sabitleri canli degistirmek (`config.ayar_uygula`),
  - kamera surecine UVC komutu gondermek,
  - ana pencerenin zaten sahip oldugu ates/kisitli bolge alanlarini
    ayri bir sekmede toplamak.

Tasarim kurali: ana pencere bu dosya olmadan da calisabilmeli. `bukrek_main`
import'u try/except icinde yapar; pencere acilamazsa sistem aynen devam eder.

Sekmeler:
  Avci Kamera / Gozcu Kamera : UVC denetimleri (kaydirici + "dokunma" kutusu)
  Ates Kontrolu              : atessiz bolge (ana penceredeki alanlar tasindi)
  Kisitli Bolge              : Asama 3 hareket kisitlama dilimi
  Harekete Yasak Alan        : taretin CIKAMAYACAGI aci araligi
  Takip / Tanima / Ates      : config sabitleri, aciklamalariyla
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox, QDialog, QDoubleSpinBox, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QTabWidget,
    QVBoxLayout, QWidget)

import config
import config_yazici


class _TekerleksizSlider(QSlider):
    """
    Fare tekerlegini YOK SAYAN kaydirici (2026-09-24, 29.21).

    Ayar sekmeleri uzun ve kaydirilabilir. Varsayilan QSlider, uzerinden
    gecerken tekerlek olayini yakalayip DEGERI degistiriyordu: kullanici
    sayfayi asagi kaydirmak isterken farkinda olmadan ayarlari bozuyordu.
    `ignore()` demek olayi ebeveyne birakir, yani kaydirma alanina gider
    ve sayfa normal sekilde kayar.
    """

    def wheelEvent(self, olay):
        olay.ignore()


class _TekerleksizKutu(QDoubleSpinBox):
    """Fare tekerlegini yok sayan sayi kutusu (ayni gerekce)."""

    def wheelEvent(self, olay):
        olay.ignore()

# Logitech arayuzundeki gibi koyu tema.
_ARKA = "#1c1c1e"
_PANEL = "#2a2a2e"
_VURGU = "#0a84ff"

_PENCERE_STILI = f"""
QDialog, QWidget {{ background-color: {_ARKA}; color: #f2f2f7; }}
QTabWidget::pane {{ border: 1px solid #3a3a3e; background: {_ARKA}; }}
QTabBar::tab {{
    background: {_ARKA}; color: #9a9aa0; padding: 9px 16px;
    font-size: 13px; font-weight: bold; border: none;
}}
QTabBar::tab:selected {{ color: {_VURGU}; border-bottom: 2px solid {_VURGU}; }}
QGroupBox {{
    background: {_PANEL}; border: 1px solid #3a3a3e; border-radius: 8px;
    margin-top: 14px; padding: 10px; font-size: 13px; font-weight: bold;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 5px; }}
QLabel {{ font-size: 12px; }}
QSlider::groove:horizontal {{ height: 4px; background: #4a4a4e; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {_VURGU}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: #ffffff; width: 16px; height: 16px;
    margin: -6px 0; border-radius: 8px;
}}
QDoubleSpinBox {{
    background: {_ARKA}; border: 1px solid #4a4a4e; border-radius: 6px;
    padding: 4px; color: #f2f2f7; font-size: 12px; min-width: 76px;
}}
QCheckBox {{ font-size: 12px; }}
QPushButton {{
    background: {_VURGU}; border: none; border-radius: 6px;
    padding: 8px 14px; font-size: 13px; font-weight: bold; color: white;
}}
QPushButton:hover {{ background: #0a6fd8; }}
QPushButton#ikincil {{ background: #48484c; }}
QPushButton#ikincil:hover {{ background: #5a5a5e; }}
QPushButton#kaydet {{ background: #30a14e; }}
QPushButton#kaydet:hover {{ background: #278442; }}
QScrollArea {{ border: none; }}
"""


def _aciklama(metin):
    """Parantez ici aciklama etiketi: ne ise yaradigini ekranda yazar."""
    e = QLabel(f"({metin})")
    e.setWordWrap(True)
    e.setStyleSheet("color: #8e8e93; font-size: 11px;")
    return e


class _KaydiriciSatir(QWidget):
    """
    Bir kaydirici + sayi kutusu + (istege bagli) "dokunma" kutusu.

    Kaydirici tamsayi calisir; ondalikli degerler `adim` ile olceklenir.
    Sayi kutusu ile kaydirici birbirini gunceller, geri besleme dongusu
    `_kilit` ile kesilir.
    """

    def __init__(self, etiket, en_az, en_cok, adim, ondalik, aciklama,
                 dokunma_kutusu=False, parent=None):
        super().__init__(parent)
        self._adim = float(adim) if adim else 1.0
        self._en_az = float(en_az)
        self._kilit = False
        self._geri_cagir = None

        duzen = QVBoxLayout(self)
        duzen.setContentsMargins(0, 6, 0, 6)
        duzen.setSpacing(3)

        ust = QHBoxLayout()
        self.baslik = QLabel(etiket)
        self.baslik.setStyleSheet("font-size: 13px; font-weight: bold;")
        ust.addWidget(self.baslik)
        ust.addStretch()
        if dokunma_kutusu:
            self.dokunma = QCheckBox("dokunma")
            self.dokunma.setToolTip(
                "Isaretliyse bu denetim kameraya HIC gonderilmez "
                "(surucunun kendi degeri kalir).")
            self.dokunma.stateChanged.connect(self._dokunma_degisti)
            ust.addWidget(self.dokunma)
        else:
            self.dokunma = None
        duzen.addLayout(ust)

        alt = QHBoxLayout()
        self.kaydirici = _TekerleksizSlider(Qt.Horizontal)
        self.kaydirici.setMinimum(0)
        self.kaydirici.setMaximum(max(1, int(round((en_cok - en_az) / self._adim))))
        self.kaydirici.valueChanged.connect(self._kaydiriciDegisti)
        alt.addWidget(self.kaydirici, 1)

        self.kutu = _TekerleksizKutu()
        self.kutu.setDecimals(int(ondalik))
        self.kutu.setMinimum(float(en_az))
        self.kutu.setMaximum(float(en_cok))
        self.kutu.setSingleStep(self._adim)
        self.kutu.valueChanged.connect(self._kutuDegisti)
        alt.addWidget(self.kutu)
        duzen.addLayout(alt)

        if aciklama:
            duzen.addWidget(_aciklama(aciklama))

    # --- degerler ---
    def deger(self):
        if self.dokunma is not None and self.dokunma.isChecked():
            return None
        return self.kutu.value()

    def degeri_yaz(self, deger):
        self._kilit = True
        try:
            if deger is None:
                if self.dokunma is not None:
                    self.dokunma.setChecked(True)
            else:
                if self.dokunma is not None:
                    self.dokunma.setChecked(False)
                d = max(self.kutu.minimum(), min(self.kutu.maximum(), float(deger)))
                self.kutu.setValue(d)
                self.kaydirici.setValue(int(round((d - self._en_az) / self._adim)))
        finally:
            self._kilit = False
        self._etkinligi_guncelle()

    def geri_cagir_ayarla(self, fn):
        self._geri_cagir = fn

    # --- ic olaylar ---
    def _etkinligi_guncelle(self):
        pasif = self.dokunma is not None and self.dokunma.isChecked()
        self.kaydirici.setEnabled(not pasif)
        self.kutu.setEnabled(not pasif)

    def _bildir(self):
        if not self._kilit and self._geri_cagir:
            self._geri_cagir(self.deger())

    def _kaydiriciDegisti(self, v):
        if self._kilit:
            return
        self._kilit = True
        self.kutu.setValue(self._en_az + v * self._adim)
        self._kilit = False
        self._bildir()

    def _kutuDegisti(self, v):
        if self._kilit:
            return
        self._kilit = True
        self.kaydirici.setValue(int(round((v - self._en_az) / self._adim)))
        self._kilit = False
        self._bildir()

    def _dokunma_degisti(self, _):
        self._etkinligi_guncelle()
        self._bildir()


def _kaydirilabilir(ic_widget):
    alan = QScrollArea()
    alan.setWidgetResizable(True)
    alan.setWidget(ic_widget)
    return alan


class AyarlarPenceresi(QDialog):
    """
    Ana pencereden bagimsiz, modelsiz (non-modal) ayar penceresi.

    `arayuz` ana pencere nesnesi. Bu sinif ondan YALNIZCA sunlari kullanir:
      - `camera_cmd_q` / `spotter_cmd_q` (UVC komutu)
      - atessiz bolge ve kisitli bolge alanlari (tasinir, yeniden yaratilmaz)
      - `_update_status_label` (varsa)
    Baska hicbir seye dokunmaz.
    """

    def __init__(self, arayuz, parent=None):
        super().__init__(parent)
        self.arayuz = arayuz
        self.setWindowTitle("Ayarlar")
        self.setStyleSheet(_PENCERE_STILI)
        self.resize(760, 900)
        # Modelsiz: ayar yaparken goruntu akmaya devam etsin.
        self.setModal(False)

        self._kamera_satirlari = {"hunter": {}, "spotter": {}}
        self._param_satirlari = {}

        ana = QVBoxLayout(self)
        self.sekmeler = QTabWidget()
        self.sekmeler.addTab(self._kamera_sekmesi("hunter"), "Avcı Kamera")
        self.sekmeler.addTab(self._kamera_sekmesi("spotter"), "Gözcü Kamera")
        self.sekmeler.addTab(self._ates_sekmesi(), "Ateş Kontrolü")
        self.sekmeler.addTab(self._kisitli_bolge_sekmesi(), "Kısıtlı Bölge")
        self.sekmeler.addTab(self._hareket_sekmesi(), "Harekete Yasak Alan")
        self.sekmeler.addTab(self._parametre_sekmesi(), "Takip / Tanıma / Ateş")
        ana.addWidget(self.sekmeler)

        self.durum = QLabel("")
        self.durum.setStyleSheet("color: #8e8e93; font-size: 11px;")
        ana.addWidget(self.durum)

        self.degerleri_yukle()

    # ------------------------------------------------------------------
    # Kamera sekmeleri
    # ------------------------------------------------------------------
    def _kamera_sekmesi(self, kamera_adi):
        ic = QWidget()
        duzen = QVBoxLayout(ic)

        bilgi = QLabel(
            "Kaydırıcılar kamerayı KAPATMADAN uygulanır; görüntü akmaya "
            "devam eder. \"dokunma\" işaretliyse o denetim kameraya hiç "
            "gönderilmez, sürücünün kendi değeri kalır.\n"
            "Çözünürlük, format ve kare hızı buradan DEĞİŞMEZ.")
        bilgi.setWordWrap(True)
        bilgi.setStyleSheet("color: #8e8e93; font-size: 11px;")
        duzen.addWidget(bilgi)

        kutu = QGroupBox("UVC Denetimleri")
        kutu_duzen = QVBoxLayout(kutu)
        for ad, etiket, en_az, en_cok, adim, aciklama in config.KAMERA_UVC_ARALIKLARI:
            ondalik = 2 if isinstance(adim, float) and adim < 1 else 0
            satir = _KaydiriciSatir(etiket, en_az, en_cok, adim, ondalik,
                                    aciklama, dokunma_kutusu=True)
            satir.geri_cagir_ayarla(
                lambda _d, k=kamera_adi: self._kamerayi_gonder(k))
            self._kamera_satirlari[kamera_adi][ad] = satir
            kutu_duzen.addWidget(satir)
            cizgi = QFrame()
            cizgi.setFrameShape(QFrame.HLine)
            cizgi.setStyleSheet("color: #3a3a3e;")
            kutu_duzen.addWidget(cizgi)
        duzen.addWidget(kutu)

        dugmeler = QHBoxLayout()
        yeniden = QPushButton("Kameraya Yeniden Uygula")
        yeniden.clicked.connect(lambda: self._kamerayi_gonder(kamera_adi))
        dugmeler.addWidget(yeniden)
        kaydet = QPushButton("config.py'ye Kaydet")
        kaydet.setObjectName("kaydet")
        kaydet.setToolTip("Bu kameranın denetimlerini config.py'ye yazar; "
                          "bir sonraki açılışta bu değerlerle başlanır.")
        kaydet.clicked.connect(lambda: self._kamerayi_kaydet(kamera_adi))
        dugmeler.addWidget(kaydet)
        geri = QPushButton("Açılıştaki Değerlere Dön")
        geri.setObjectName("ikincil")
        geri.setToolTip("Bu oturum açıldığındaki değerlere döner. "
                        "Kaydetmiş olsanız bile çalışır.")
        geri.clicked.connect(lambda: self._kamera_varsayilana(kamera_adi))
        dugmeler.addWidget(geri)
        dugmeler.addStretch()
        duzen.addLayout(dugmeler)
        duzen.addStretch()
        return _kaydirilabilir(ic)

    def _kamerayi_kaydet(self, kamera_adi):
        degerler = {ad: s.deger()
                    for ad, s in self._kamera_satirlari[kamera_adi].items()}
        ok, mesaj = config_yazici.kaydet(kamera={kamera_adi: degerler})
        self._bildir(("Kaydedildi — " if ok else "KAYDEDİLEMEDİ — ") + mesaj)

    def _kamerayi_gonder(self, kamera_adi):
        degerler = {ad: s.deger()
                    for ad, s in self._kamera_satirlari[kamera_adi].items()}
        # Once yerel config, sonra kamera sureci: surec kapaliysa bile
        # degerler kalir ve kamera acilinca uygulanir.
        config.KAMERA_KONTROLLERI.setdefault(kamera_adi, {}).update(degerler)
        kuyruk = (self.arayuz.camera_cmd_q if kamera_adi == "hunter"
                  else getattr(self.arayuz, 'spotter_cmd_q', None))
        if kuyruk is None:
            self._bildir(f"{kamera_adi}: kuyruk yok, yalnızca kaydedildi.")
            return
        try:
            kuyruk.put({"action": "UVC", "degerler": degerler})
            self._bildir(f"{kamera_adi}: {len(degerler)} denetim gönderildi.")
        except Exception as e:
            self._bildir(f"{kamera_adi}: gönderilemedi ({e}).")

    def _kamera_varsayilana(self, kamera_adi):
        """
        Bu OTURUM acildigindaki degerlere doner.

        `config` modulu yeniden YUKLENMEZ: calisan sistem config nesnelerine
        referans tutuyor, yeniden yukleme onlari kopariridi. Bunun yerine ana
        pencerenin aciliста aldigi kopya kullanilir. Bu sayede "kaydettim
        ama yine de onceki degere donmek istiyorum" mumkun olur.
        """
        kaynak = getattr(self.arayuz, '_kamera_kontrol_yedegi', {}).get(kamera_adi)
        if not kaynak:
            self._bildir("Açılıştaki değerler bulunamadı.")
            return
        for ad, satir in self._kamera_satirlari[kamera_adi].items():
            satir.degeri_yaz(kaynak.get(ad))
        self._kamerayi_gonder(kamera_adi)

    # ------------------------------------------------------------------
    # Ates / kisitli bolge / hareket sekmeleri
    # ------------------------------------------------------------------
    def _ates_sekmesi(self):
        ic = QWidget()
        duzen = QVBoxLayout(ic)
        kutu = QGroupBox("Ateşsiz Bölge")
        kutu_duzen = QVBoxLayout(kutu)
        kutu_duzen.addWidget(_aciklama(
            "Taret bu yaw aralığının içindeyken ateş açılmaz. "
            "Otonom ve manuel ateşin ikisini de kapsar. "
            "Başlangıç ve bitiş aynı (0) ise kısıtlama yoktur."))
        # Ana penceredeki alanlar TASINIR; yeniden yaratilmaz ki mevcut
        # `apply_no_fire_zone` / `clear_no_fire_zone` yollari aynen calissin.
        for isim, etiket in (("no_fire_start_input", "Başlangıç Yaw (°)"),
                             ("no_fire_end_input", "Bitiş Yaw (°)")):
            alan = getattr(self.arayuz, isim, None)
            if alan is None:
                continue
            satir = QHBoxLayout()
            satir.addWidget(QLabel(etiket))
            alan.setStyleSheet(
                "color: #f2f2f7; background-color: #1c1c1e; "
                "border: 1px solid #4a4a4e; border-radius: 6px; padding: 5px;")
            satir.addWidget(alan, 1)
            kutu_duzen.addLayout(satir)
        dugme_satiri = QHBoxLayout()
        for isim in ("apply_no_fire_zone_button", "clear_no_fire_zone_button"):
            dugme = getattr(self.arayuz, isim, None)
            if dugme is not None:
                dugme.setStyleSheet("")
                if isim.startswith("clear"):
                    dugme.setObjectName("ikincil")
                dugme_satiri.addWidget(dugme)
        kutu_duzen.addLayout(dugme_satiri)
        duzen.addWidget(kutu)
        duzen.addStretch()
        return _kaydirilabilir(ic)

    def _kisitli_bolge_sekmesi(self):
        ic = QWidget()
        duzen = QVBoxLayout(ic)
        kutu = QGroupBox("Kısıtlı Hareket Bölgesi (Aşama 3)")
        k = QVBoxLayout(kutu)
        k.addWidget(_aciklama(
            "Aşama 3'te taret bu yaw dilimine GİRMEZ; PID o yönde komut "
            "üretmez. Başlangıç ve bitiş aynı (0) ise kısıtlama yoktur. "
            "Ateşsiz bölgeden farkı: bu, hareketi engeller."))
        self.kisitli_bas = _KaydiriciSatir(
            "Kısıtlı Bölge Başlangıç Yaw (°)", -180, 180, 1, 0,
            "Dilimin başladığı açı.")
        self.kisitli_bit = _KaydiriciSatir(
            "Kısıtlı Bölge Bitiş Yaw (°)", -180, 180, 1, 0,
            "Dilimin bittiği açı.")
        k.addWidget(self.kisitli_bas)
        k.addWidget(self.kisitli_bit)
        d = QHBoxLayout()
        uygula = QPushButton("Uygula")
        uygula.clicked.connect(self._kisitli_uygula)
        d.addWidget(uygula)
        temizle = QPushButton("Temizle (kısıtlama yok)")
        temizle.setObjectName("ikincil")
        temizle.clicked.connect(self._kisitli_temizle)
        d.addWidget(temizle)
        d.addStretch()
        k.addLayout(d)
        duzen.addWidget(kutu)
        duzen.addStretch()
        return _kaydirilabilir(ic)

    def _kisitli_uygula(self):
        self.arayuz.movement_restricted_yaw_start = self.kisitli_bas.deger()
        self.arayuz.movement_restricted_yaw_end = self.kisitli_bit.deger()
        self._bildir(f"Kısıtlı bölge: {self.kisitli_bas.deger():.0f}° .. "
                     f"{self.kisitli_bit.deger():.0f}°")

    def _kisitli_temizle(self):
        self.arayuz.movement_restricted_yaw_start = 0
        self.arayuz.movement_restricted_yaw_end = 0
        self.kisitli_bas.degeri_yaz(0)
        self.kisitli_bit.degeri_yaz(0)
        self._bildir("Kısıtlı bölge temizlendi.")

    def _hareket_sekmesi(self):
        ic = QWidget()
        duzen = QVBoxLayout(ic)
        kutu = QGroupBox("Harekete Yasak Alan (çalışma sınırları)")
        k = QVBoxLayout(kutu)
        k.addWidget(_aciklama(
            "Taret bu aralığın DIŞINA çıkmaz. Kısıtlı bölge bir dilimi "
            "yasaklar; bu ise çalışılabilecek tüm aralığı sınırlar "
            "(mekanik emniyet, kablo koruma). Gönderilen her açı komutu "
            "bu aralığa kırpılır. VARSAYILAN KAPALI: kapalıyken sistem "
            "bugünkü gibi davranır, hiçbir sınır uygulanmaz."))
        self.hareket_aktif = QCheckBox("Hareket sınırını uygula")
        self.hareket_aktif.stateChanged.connect(self._hareket_uygula)
        k.addWidget(self.hareket_aktif)
        self.hareket_yaw_min = _KaydiriciSatir(
            "En küçük Yaw (°)", -180, 180, 1, 0, "Sola dönüş sınırı.")
        self.hareket_yaw_max = _KaydiriciSatir(
            "En büyük Yaw (°)", -180, 180, 1, 0, "Sağa dönüş sınırı.")
        self.hareket_pitch_min = _KaydiriciSatir(
            "En küçük Pitch (°)", -90, 90, 1, 0, "Aşağı bakış sınırı.")
        self.hareket_pitch_max = _KaydiriciSatir(
            "En büyük Pitch (°)", -90, 90, 1, 0, "Yukarı bakış sınırı.")
        for s in (self.hareket_yaw_min, self.hareket_yaw_max,
                  self.hareket_pitch_min, self.hareket_pitch_max):
            s.geri_cagir_ayarla(lambda _d: self._hareket_uygula())
            k.addWidget(s)
        d = QHBoxLayout()
        kaydet = QPushButton("config.py'ye Kaydet")
        kaydet.setObjectName("kaydet")
        kaydet.clicked.connect(self._hareket_kaydet)
        d.addWidget(kaydet)
        d.addStretch()
        k.addLayout(d)
        duzen.addWidget(kutu)
        duzen.addStretch()
        return _kaydirilabilir(ic)

    def _hareket_kaydet(self):
        ok, mesaj = config_yazici.kaydet(sabitler={
            'HAREKET_SINIRI_AKTIF': bool(self.hareket_aktif.isChecked()),
            'HAREKET_YAW_MIN': float(self.hareket_yaw_min.deger()),
            'HAREKET_YAW_MAX': float(self.hareket_yaw_max.deger()),
            'HAREKET_PITCH_MIN': float(self.hareket_pitch_min.deger()),
            'HAREKET_PITCH_MAX': float(self.hareket_pitch_max.deger()),
        })
        self._bildir(("Kaydedildi — " if ok else "KAYDEDİLEMEDİ — ") + mesaj)

    def _hareket_uygula(self):
        config.HAREKET_SINIRI_AKTIF = bool(self.hareket_aktif.isChecked())
        config.HAREKET_YAW_MIN = self.hareket_yaw_min.deger()
        config.HAREKET_YAW_MAX = self.hareket_yaw_max.deger()
        config.HAREKET_PITCH_MIN = self.hareket_pitch_min.deger()
        config.HAREKET_PITCH_MAX = self.hareket_pitch_max.deger()
        if config.HAREKET_SINIRI_AKTIF:
            self._bildir(
                f"Hareket sınırı AÇIK: yaw {config.HAREKET_YAW_MIN:.0f}.."
                f"{config.HAREKET_YAW_MAX:.0f}°, pitch "
                f"{config.HAREKET_PITCH_MIN:.0f}..{config.HAREKET_PITCH_MAX:.0f}°")
        else:
            self._bildir("Hareket sınırı kapalı (sınırsız).")

    # ------------------------------------------------------------------
    # Parametre sekmesi
    # ------------------------------------------------------------------
    def _parametre_sekmesi(self):
        ic = QWidget()
        duzen = QVBoxLayout(ic)
        duzen.addWidget(_aciklama(
            "Buradaki değerler anında geçerli olur; kod her karede config "
            "üzerinden okur. Değişiklikler dosyaya YAZILMAZ, program "
            "kapanınca dosyadaki değerlere dönülür."))
        aktif_kutu = None
        aktif_duzen = None
        for satir in config.AYARLANABILIR_PARAMETRELER:
            ad, etiket, en_az, en_cok, adim, ondalik, aciklama = satir
            if etiket is None:
                aktif_kutu = QGroupBox(aciklama)
                aktif_duzen = QVBoxLayout(aktif_kutu)
                duzen.addWidget(aktif_kutu)
                continue
            if aktif_duzen is None:
                aktif_kutu = QGroupBox("Parametreler")
                aktif_duzen = QVBoxLayout(aktif_kutu)
                duzen.addWidget(aktif_kutu)
            s = _KaydiriciSatir(etiket, en_az, en_cok, adim, ondalik, aciklama)
            s.geri_cagir_ayarla(lambda d, a=ad: self._parametre_yaz(a, d))
            self._param_satirlari[ad] = s
            aktif_duzen.addWidget(s)
        d = QHBoxLayout()
        kaydet = QPushButton("config.py'ye Kaydet")
        kaydet.setObjectName("kaydet")
        kaydet.setToolTip(
            "Ekrandaki tüm parametreleri config.py'ye yazar; bir sonraki "
            "açılışta bu değerlerle başlanır. Dosya yazılmadan önce "
            "derlenip doğrulanır, config.py.yedek olarak yedeklenir.")
        kaydet.clicked.connect(self._parametreleri_kaydet)
        d.addWidget(kaydet)
        geri = QPushButton("Açılıştaki Değerlere Dön")
        geri.setObjectName("ikincil")
        geri.setToolTip("Bu oturum açıldığındaki değerlere döner. "
                        "Kaydetmiş olsanız bile çalışır (dosya değişmez).")
        geri.clicked.connect(self._parametre_varsayilana)
        d.addWidget(geri)
        d.addStretch()
        duzen.addLayout(d)
        duzen.addStretch()
        return _kaydirilabilir(ic)

    def _parametreleri_kaydet(self):
        sabitler = {}
        for ad, s in self._param_satirlari.items():
            deger = s.deger()
            for _a, _e, _mn, _mx, _ad, ondalik, _ac in config.AYARLANABILIR_PARAMETRELER:
                if _a == ad:
                    deger = int(round(deger)) if ondalik == 0 else float(deger)
                    break
            sabitler[ad] = deger
        ok, mesaj = config_yazici.kaydet(sabitler=sabitler)
        self._bildir(("Kaydedildi — " if ok else "KAYDEDİLEMEDİ — ") + mesaj)

    def _parametre_yaz(self, ad, deger):
        for _a, _e, _mn, _mx, _ad, ondalik, _ac in config.AYARLANABILIR_PARAMETRELER:
            if _a == ad:
                deger = int(round(deger)) if ondalik == 0 else float(deger)
                break
        if config.ayar_uygula(ad, deger):
            self._bildir(f"{ad} = {deger}")
        else:
            self._bildir(f"{ad} uygulanamadı (config'de yok).")

    def _parametre_varsayilana(self):
        yedek = getattr(self.arayuz, '_parametre_yedegi', {})
        for ad, s in self._param_satirlari.items():
            if ad in yedek:
                s.degeri_yaz(yedek[ad])
                config.ayar_uygula(ad, yedek[ad])
        self._bildir("Parametreler açılıştaki değerlere döndü.")

    # ------------------------------------------------------------------
    def degerleri_yukle(self):
        """Pencere her acildiginda mevcut degerleri kutulara yazar."""
        for kamera_adi, satirlar in self._kamera_satirlari.items():
            mevcut = config.KAMERA_KONTROLLERI.get(kamera_adi, {})
            for ad, s in satirlar.items():
                s.degeri_yaz(mevcut.get(ad))
        for ad, s in self._param_satirlari.items():
            s.degeri_yaz(config.ayar_oku(ad, s.kutu.value()))
        self.kisitli_bas.degeri_yaz(
            getattr(self.arayuz, 'movement_restricted_yaw_start', 0))
        self.kisitli_bit.degeri_yaz(
            getattr(self.arayuz, 'movement_restricted_yaw_end', 0))
        self.hareket_aktif.setChecked(bool(config.HAREKET_SINIRI_AKTIF))
        self.hareket_yaw_min.degeri_yaz(config.HAREKET_YAW_MIN)
        self.hareket_yaw_max.degeri_yaz(config.HAREKET_YAW_MAX)
        self.hareket_pitch_min.degeri_yaz(config.HAREKET_PITCH_MIN)
        self.hareket_pitch_max.degeri_yaz(config.HAREKET_PITCH_MAX)

    def _bildir(self, metin):
        self.durum.setText(metin)
        yaz = getattr(self.arayuz, '_update_status_label', None)
        if callable(yaz):
            try:
                yaz(f"Ayarlar: {metin}")
            except Exception:
                pass
