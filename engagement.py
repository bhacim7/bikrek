"""
Hedef çifti modeli ve angajman durum makinesi.

UI'dan ve donanımdan BAĞIMSIZ tutuldu — böylece simülasyonla test edilebilir.
Geçen fazda ekran kaydından çıkarılan yörüngeleri kapalı döngüde tekrar
oynatmak sorunları bulmanın en etkili yolu oldu; bu ayrıştırma o yeteneği
kalıcı hale getiriyor.

TEMEL DEĞİŞİKLİK: data.yaml'da tek bir 'balon' sınıfı var, yani balon
dost/düşman bilgisi TAŞIMIYOR. Karar zorunlu olarak üstündeki maketten
geliyor. Bu yüzden takip birimi artık tek nesne değil, bir ÇİFT:
maket (kim) + balon (nereye nişan alınacak).
"""

import time

import config

# --- Durumlar ---
BOSTA = 'BOSTA'
TARAMA = 'TARAMA'
YONELME = 'YONELME'
DOGRULAMA = 'DOGRULAMA'
KILIT = 'KILIT'
ATES = 'ATES'


def dusman_mi(sinif):
    return bool(sinif) and sinif.startswith(config.ENEMY_PREFIX)


def dost_mu(sinif):
    return bool(sinif) and sinif.startswith(config.FRIEND_PREFIX)


def maket_mi(sinif):
    return dost_mu(sinif) or dusman_mi(sinif)


def _merkez(bbox):
    x, y, w, h = bbox
    return x + w / 2.0, y + h / 2.0


class HedefCifti:
    """Bir maket ve onun altındaki balon."""

    def __init__(self, maket, balon, skor):
        self.maket = maket            # tespit sözlüğü veya None
        self.balon = balon            # tespit sözlüğü veya None
        self.skor = skor              # eşleşme kalitesi (0-1, büyük iyi)

    @property
    def sinif(self):
        return self.maket['class_name'] if self.maket else None

    @property
    def guven(self):
        return self.maket['score'] if self.maket else 0.0

    def nisan_noktasi(self):
        """
        Nişan alınacak piksel konumu ve o noktanın "yarıçapı".

        Balon varsa oraya nişan alınır. Balon 15 metrede avcıda yalnızca
        30 piksel — YOLO için küçük-nesne sınırı; tespit zayıflayabilir.
        O durumda nişan noktası maketten geometrik olarak türetilir
        (maket 96 piksel, çok daha güvenilir).
        """
        if self.balon is not None:
            cx, cy = _merkez(self.balon['bbox'])
            yaricap = max(self.balon['bbox'][2], self.balon['bbox'][3]) / 2.0
            return cx, cy, yaricap, True
        if self.maket is not None and config.PAIR_ALLOW_FALLBACK_AIM:
            mx, my = _merkez(self.maket['bbox'])
            mw = float(self.maket['bbox'][2])
            return mx, my + mw * config.PAIR_FALLBACK_AIM_OFFSET, mw * 0.15, False
        return None


def cift_eslestir(detections, tek_balonlara_izin=False):
    """
    Tespit listesinden hedef çiftleri kurar.

    `tek_balonlara_izin`: maketi olmayan balonlar da hedef sayılsın mı?
    Yarışmada her hedefin üstünde bir maket var, o yüzden OTONOM aşamalarda
    bu KAPALI kalmalı — tek başına duran bir kırmızı leke hedef değildir ve
    ateş kilidi zaten maket olmadan ateşe izin vermez.

    Ama getirme/kurulum ve KALİBRASYON sırasında elimizde yalnızca bir balon
    oluyor. Bu bayrak kapalıyken Aşama 1'de balon hiç kilitlenmiyordu ve
    "Derece/Piksel Ölç" kilitli hedef bulamadığı için hiç çalışmıyordu.

    Geometrik kural, maketin kutu GENİŞLİĞİNE normalize edildiği için
    mesafeden bağımsızdır: balon maketin altında, yatayda hizalı ve
    maketten küçük olmalı.

    Bu aynı zamanda hayalet eleyici olarak da çalışır — tek başına duran bir
    balon veya tek başına bir maket hedef çifti oluşturmaz.
    """
    maketler = [d for d in detections if maket_mi(d['class_name'])]
    balonlar = [d for d in detections if d['class_name'] == config.BALLOON_CLASS]

    ciftler = []
    kullanilan = set()
    # Büyük maketten küçüğe: yakın hedefler önce eşleşsin, küçük/uzak bir
    # maket yakındaki bir balonu kapmasın.
    for maket in sorted(maketler, key=lambda d: -d['bbox'][2]):
        mx, my = _merkez(maket['bbox'])
        mw = float(maket['bbox'][2])
        if mw <= 0:
            continue
        en_iyi, en_iyi_skor = None, 0.0
        for i, balon in enumerate(balonlar):
            if i in kullanilan:
                continue
            bx, by = _merkez(balon['bbox'])
            dx = abs(bx - mx) / mw
            dy = (by - my) / mw            # pozitif = balon aşağıda
            bw = float(balon['bbox'][2])
            if dx > config.PAIR_MAX_HORIZONTAL_OFFSET:
                continue
            alt, ust = config.PAIR_VERTICAL_RANGE
            if not (alt <= dy <= ust):
                continue
            if bw > mw * config.PAIR_MAX_BALLOON_RATIO:
                continue
            # Skor: yatayda ne kadar hizalı ve dikeyde ne kadar makul.
            yatay = 1.0 - dx / config.PAIR_MAX_HORIZONTAL_OFFSET
            dikey_orta = (alt + ust) / 2.0
            dikey = 1.0 - abs(dy - dikey_orta) / max(1e-6, (ust - alt) / 2.0)
            skor = 0.6 * yatay + 0.4 * max(0.0, dikey)
            if skor > en_iyi_skor:
                en_iyi, en_iyi_skor = i, skor
        if en_iyi is not None:
            kullanilan.add(en_iyi)
            ciftler.append(HedefCifti(maket, balonlar[en_iyi], en_iyi_skor))
        else:
            # Maket var, balonu görünmüyor. Yedek nişan yolu için tutulur.
            ciftler.append(HedefCifti(maket, None, 0.0))

    if tek_balonlara_izin:
        # Eşleşmemiş balonlar: maket alanı None kalır, dolayısıyla
        # `ates_serbest_mi` bunlara ateşe ASLA izin vermez (maket şartı).
        for i, balon in enumerate(balonlar):
            if i not in kullanilan:
                ciftler.append(HedefCifti(None, balon, 0.0))

    return ciftler


class KaraListe:
    """
    Angajman dışı bırakılan yönler.

    GÖVDE çerçevesinde mutlak açı olarak tutulur; piksel uzayında tutmak
    anlamsız olurdu çünkü taret döndükçe referans kayar.
    """

    def __init__(self):
        self._kayitlar = []   # (yaw, pitch, bitis_zamani, sebep)

    def ekle(self, yaw, pitch, ttl, sebep=''):
        self._kayitlar.append((yaw, pitch, time.time() + ttl, sebep))

    def icinde_mi(self, yaw, pitch, simdi=None):
        simdi = time.time() if simdi is None else simdi
        self._kayitlar = [k for k in self._kayitlar if k[2] > simdi]
        r = config.BLACKLIST_RADIUS_DEG
        for ky, kp, _, _ in self._kayitlar:
            if ((yaw - ky) ** 2 + (pitch - kp) ** 2) ** 0.5 <= r:
                return True
        return False

    def temizle(self):
        self._kayitlar = []


def aday_sirala(izler, kara_liste, asama):
    """
    Gözcü izlerini angajman önceliğine göre sıralar.

    Aşama 2: ortamda yalnızca düşman var; en büyük (= en yakın) hedef önce.
    Aşama 3: ortamda iki dost bir düşman var; gözcünün DÜŞMAN dediği izler
             önce, KARARSIZ olanlar sonra, DOST dedikleri hiç denenmez.

    Gözcünün kararı NİHAİ DEĞİL — yalnızca sıralama. Nihai karar avcının
    YOLO'sunda; gözcü yanılsa bile dost vurulmaz.
    """
    uygun = []
    for iz in izler:
        if kara_liste.icinde_mi(iz['yaw'], iz['pitch']):
            continue
        if iz['gorulme'] < 2:
            continue
        if asama == 'task3' and iz['sinif'] == 'dost':
            # Gözcü emin şekilde dost diyorsa sıraya bile alma. Yanılırsa
            # kaybettiğimiz tek şey zaman; dost vurmak ise diskalifiye.
            continue
        uygun.append(iz)

    def anahtar(iz):
        if asama == 'task3':
            oncelik = 0 if iz['sinif'] == 'dusman' else 1
        else:
            oncelik = 0
        return (oncelik, -iz['kirmizi_alan'])

    return sorted(uygun, key=anahtar)


class AngajmanMakinesi:
    """
    Gözcü -> taret -> avcı devir teslim akışını yöneten durum makinesi.

    Bu sınıf donanıma dokunmaz; yalnızca durum tutar ve "ne yapılmalı"
    kararını döndürür. Komutları çağıran taraf gönderir.
    """

    def __init__(self):
        self.durum = BOSTA
        self.durum_zamani = time.time()
        self.kara_liste = KaraListe()
        self.hedef_yaw = None          # gözcünün verdiği mutlak açı
        self.hedef_pitch = None
        self.aktif_iz_id = None
        self.asama = None

        self._sinif_gecmisi = []       # doğrulama için ardışık sınıflar
        self._nisan_ardisik = 0
        self.dogrulanan_sinif = None
        self.imha_sayisi = 0

    # ---- durum geçişleri ----

    def _gec(self, yeni):
        if yeni != self.durum:
            self.durum = yeni
            self.durum_zamani = time.time()
            if yeni in (TARAMA, YONELME):
                self._sinif_gecmisi = []
                self._nisan_ardisik = 0
                self.dogrulanan_sinif = None

    def gecen(self):
        return time.time() - self.durum_zamani

    def basla(self, asama):
        self.asama = asama
        self.kara_liste.temizle()
        self.imha_sayisi = 0
        self.aktif_iz_id = None
        self._gec(TARAMA)

    def durdur(self):
        self.asama = None
        self.aktif_iz_id = None
        self._gec(BOSTA)

    # ---- her karede çağrılır ----

    def tarama_adimi(self, izler):
        """
        Sıradaki adayı seçer ve YÖNELME'ye geçer.

        Taretin gideceği açı, izin ÖLÇÜLEN değil TAHMİN EDİLEN konumu:
        gözcü gecikmesi + yalpalama süresi toplamda ~0.5 saniye ve hedef bu
        sürede yol alır. Avcının yarı görüş açısı yaw'da ±11.4, pitch'te
        yalnızca ±6.65 derece — ölçülen açıya gitmek hedefi kaçırtabilir.
        """
        adaylar = aday_sirala(izler, self.kara_liste, self.asama)
        if not adaylar:
            return None
        iz = adaylar[0]
        ileri = config.SPOTTER_LATENCY + self._yalpalama_suresi(iz['yaw'])
        self.hedef_yaw = iz['yaw'] + iz['yaw_hiz'] * ileri
        self.hedef_pitch = iz['pitch'] + iz['pitch_hiz'] * ileri
        self.aktif_iz_id = iz['id']
        self._gec(YONELME)
        return self.hedef_yaw, self.hedef_pitch

    @staticmethod
    def _yalpalama_suresi(hedef_yaw, mevcut_yaw=0.0, tepe_hiz=89.0):
        """Kaba tahmin: taretin bu açıya dönmesi ne kadar sürer."""
        return min(1.0, abs(hedef_yaw - mevcut_yaw) / max(1e-6, tepe_hiz))

    def yonelme_adimi(self, mevcut_yaw, mevcut_pitch):
        """Taret hedefe oturdu mu? Oturduysa DOĞRULAMA'ya geç."""
        if self.hedef_yaw is None:
            self._gec(TARAMA)
            return False
        hata = ((mevcut_yaw - self.hedef_yaw) ** 2 +
                (mevcut_pitch - self.hedef_pitch) ** 2) ** 0.5
        if hata <= config.ENGAGE_SLEW_TOLERANCE_DEG:
            self._gec(DOGRULAMA)
            return True
        if self.gecen() > config.ENGAGE_SLEW_TIMEOUT:
            self._gec(TARAMA)
        return False

    def dogrulama_adimi(self, ciftler):
        """
        Avcının YOLO çıktısıyla dost/düşman kararı.

        DOST çıkarsa hedef kara listeye girer ve TARAMA'ya dönülür — bu,
        gözcü yanılsa bile dostun vurulmasını imkânsız kılan katman.
        """
        if not ciftler:
            if self.gecen() > config.ENGAGE_VERIFY_TIMEOUT:
                self._gec(TARAMA)
            return None

        # Merkeze en yakın çifti al: taret zaten adaya dönmüş durumda.
        cift = ciftler[0]
        if cift.maket is None or cift.guven < config.VERIFY_MIN_CONFIDENCE:
            if self.gecen() > config.ENGAGE_VERIFY_TIMEOUT:
                self._gec(TARAMA)
            return None

        self._sinif_gecmisi.append(cift.sinif)
        if len(self._sinif_gecmisi) > config.VERIFY_CONFIRM_FRAMES:
            self._sinif_gecmisi.pop(0)

        yeterli = len(self._sinif_gecmisi) >= config.VERIFY_CONFIRM_FRAMES
        tutarli = yeterli and len(set(self._sinif_gecmisi)) == 1
        if not tutarli:
            if self.gecen() > config.ENGAGE_VERIFY_TIMEOUT:
                self._gec(TARAMA)
            return None

        sinif = self._sinif_gecmisi[0]
        if dost_mu(sinif):
            self.kara_listeye_al(config.BLACKLIST_FRIEND_TTL_SEC, 'dost')
            self._gec(TARAMA)
            return sinif
        if dusman_mi(sinif):
            self.dogrulanan_sinif = sinif
            self._gec(KILIT)
            return sinif
        return None

    def kilit_adimi(self, nisan_hatasi_px, nisan_yaricap_px, balon_gorundu):
        """
        Nişan toleransı sağlandı mı?

        Tolerans balonun YARIÇAPININ oranı olarak tanımlı — hem mesafeden
        hem zoomdan bağımsız. Balon 15 metrede 30 piksel, 5 metrede 90;
        sabit piksel toleransı ikisinde farklı anlam taşırdı.
        """
        if self.gecen() > config.ENGAGE_LOCK_TIMEOUT:
            self._gec(TARAMA)
            return False

        tolerans = max(config.AIM_TOLERANCE_MIN_PIXELS,
                       nisan_yaricap_px * config.AIM_TOLERANCE_RATIO)
        if nisan_hatasi_px <= tolerans and balon_gorundu:
            self._nisan_ardisik += 1
        else:
            self._nisan_ardisik = 0

        if self._nisan_ardisik >= config.AIM_HOLD_FRAMES:
            self._gec(ATES)
            return True
        return False

    def kara_listeye_al(self, ttl, sebep=''):
        if self.hedef_yaw is not None:
            self.kara_liste.ekle(self.hedef_yaw, self.hedef_pitch, ttl, sebep)

    def imha_edildi(self):
        self.imha_sayisi += 1
        self.kara_listeye_al(config.BLACKLIST_TTL_SEC, 'imha')
        self.aktif_iz_id = None
        self._gec(TARAMA)


def ates_serbest_mi(cift, makine, balon_gorundu, nisan_tamam,
                    yaw, no_fire_start, no_fire_end):
    """
    Ateş kilidi — hepsi birden sağlanmalı.

    Aşama 3'te dost vurmak diskalifiye olduğu için burada cömert
    davranmıyoruz. Eski kodda Aşama 3'ün TAHMİN EDİLMİŞ (görülmemiş) hedefe
    ateş edebildiği bir açık vardı; 1. ve 5. koşullar onu kapatıyor.

    Döner: (izin_var, gerekce)
    """
    if makine.durum != ATES:
        return False, 'durum ATES degil'
    if cift is None or cift.maket is None:
        return False, 'maket bu karede tespit edilmedi'
    if not dusman_mi(cift.sinif):
        return False, f'sinif dusman degil: {cift.sinif}'
    if cift.guven < config.VERIFY_MIN_CONFIDENCE:
        return False, f'guven dusuk: {cift.guven:.2f}'
    if makine.dogrulanan_sinif != cift.sinif:
        return False, 'sinif dogrulanandan farkli'
    if not balon_gorundu:
        return False, 'balon bu karede tespit edilmedi'
    if not nisan_tamam:
        return False, 'nisan tolerans disinda'
    if _atesiz_bolgede(yaw, no_fire_start, no_fire_end):
        return False, 'atesiz bolge'
    return True, 'serbest'


def _atesiz_bolgede(yaw, baslangic, bitis):
    """
    Ateşsiz bölge kontrolü.

    Eski kodda varsayılan (0.0, 0.0) tam 0.0 derecede ateşi engelliyordu;
    başlangıç ile bitiş eşitse bölge TANIMSIZ kabul edilir.
    """
    if baslangic is None or bitis is None:
        return False
    if abs(bitis - baslangic) < 1e-9:
        return False
    alt, ust = min(baslangic, bitis), max(baslangic, bitis)
    return alt <= yaw <= ust
