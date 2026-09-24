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

import math
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

    def olculen_ofset(self):
        """
        Balonun maket kutusuna göre ÖLÇÜLEN bağıl konumu.

        Döner: (dx/mw, dy/mw, yaricap/mw) veya None.

        Maket genişliğine normalize edildiği için mesafeden bağımsız —
        `PAIR_FALLBACK_AIM_OFFSET` sabitinin ölçümle öğrenilmiş hali.
        """
        if self.maket is None or self.balon is None:
            return None
        mx, my = _merkez(self.maket['bbox'])
        mw = float(self.maket['bbox'][2])
        if mw <= 0:
            return None
        bx, by = _merkez(self.balon['bbox'])
        yaricap = max(self.balon['bbox'][2], self.balon['bbox'][3]) / 2.0
        return ((bx - mx) / mw, (by - my) / mw, yaricap / mw)

    def nisan_noktasi(self, ogrenilen_ofset=None, maket_merkezine=False):
        """
        Nişan alınacak piksel konumu ve o noktanın "yarıçapı".

        Döner: (cx, cy, yaricap, balon_gercekten_gorundu) veya None.

        Balon varsa oraya nişan alınır. Balon 15 metrede avcıda yalnızca
        30 piksel — YOLO için küçük-nesne sınırı; tespit zayıflayabilir.

        BALON GÖRÜNMEDİĞİNDE nişan noktası maketten türetilir, AMA nasıl
        türetildiği kritik. Sahada ölçüldü (asama2-3-hedefTakip.mp4): sabit
        `PAIR_FALLBACK_AIM_OFFSET` (0.75) formülüyle üretilen nokta, gerçek
        balon merkezinin 25-34 piksel YUKARISINA düşüyordu. İki kaynak aynı
        x'te ama farklı y'de olduğu için her kaynak değişimi SAF BİR PITCH
        SIÇRAMASI üretiyordu — ölçülen ardışık hatalar: yaw -5 px'te sabit
        dururken pitch -52 ile +22 arasında zıplıyordu. Kilit salınımının
        kök nedeni buydu.

        `ogrenilen_ofset`: balon en son görüldüğünde ÖLÇÜLEN bağıl konum
        (`olculen_ofset` çıktısı). Verilirse sabit formül yerine bu kullanılır
        ve kaynak değişimindeki sıçrama sıfıra iner — türetilen nokta tam
        olarak balonun en son bulunduğu yeri gösterir.

        `maket_merkezine`: balon yokken maketin TAM MERKEZİNE nişan al.
        Hedef Takip modu için: o mod bir ölçüm aracı, görülmeyen bir balonun
        yerini tahmin etmemeli — kullanıcı kutunun ortasını bekliyor.
        """
        if self.balon is not None:
            cx, cy = _merkez(self.balon['bbox'])
            yaricap = max(self.balon['bbox'][2], self.balon['bbox'][3]) / 2.0
            return cx, _nisan_yuksekligi(cy, yaricap), yaricap, True

        if self.maket is None:
            return None

        mx, my = _merkez(self.maket['bbox'])
        mw = float(self.maket['bbox'][2])

        if maket_merkezine:
            yaricap = max(4.0, min(mw, float(self.maket['bbox'][3])) / 2.0)
            return mx, my, yaricap, False

        if not config.PAIR_ALLOW_FALLBACK_AIM:
            return None

        if ogrenilen_ofset is not None:
            dx, dy, dr = ogrenilen_ofset
            yaricap = max(4.0, dr * mw)
            return (mx + dx * mw, _nisan_yuksekligi(my + dy * mw, yaricap),
                    yaricap, False)

        yaricap = mw * 0.15
        merkez_y = my + mw * config.PAIR_FALLBACK_AIM_OFFSET
        return mx, _nisan_yuksekligi(merkez_y, yaricap), yaricap, False


def _nisan_yuksekligi(merkez_y, yaricap):
    """
    Balonun MERKEZİ yerine kutunun ÜST tarafına kaydırılmış nişan noktası.

    Avcı kamera namlunun 5.5 cm ÜSTÜNDE ve eksenler PARALEL. Paralel oldukları
    için mermi HER MESAFEDE kamera ekseninin 5.5 cm altından geçer — yani
    nişangahı balonun merkezine oturtursak mermi merkezin 5.5 cm altına gider
    (balon yarıçapı 7 cm, payı yalnızca 1.5 cm).

    Düzeltme MESAFEDEN BAĞIMSIZ: gereken ofset ile balonun yarıçapı aynı
    mesafedeki iki fiziksel uzunluk, oranları sabittir. Bu yüzden düzeltme
    yarıçapın bir katsayısı olarak yazılabiliyor ve mesafe bilgisine hiç
    ihtiyaç duyulmuyor.

    `AIM_POINT_HEIGHT_RATIO` kutunun ALTINDAN ölçülen yükseklik oranıdır:
    0.5 = merkez, 1.0 = üst kenar. Görüntüde yukarı = küçük y.
    """
    oran = config.AIM_POINT_HEIGHT_RATIO
    return merkez_y - (oran - 0.5) * 2.0 * yaricap


def _en_yakin_maket(balon, maketler):
    """Bu balona merkez mesafesi en kucuk olan maket."""
    bx, by = _merkez(balon['bbox'])
    en_iyi, en_kisa = None, float('inf')
    for m in maketler:
        mx, my = _merkez(m['bbox'])
        d = ((bx - mx) ** 2 + (by - my) ** 2) ** 0.5
        if d < en_kisa:
            en_iyi, en_kisa = m, d
    return en_iyi


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
            # CAPRAZ ESLESME KORUMASI: balon, kendisine EN YAKIN maketten
            # baskasiyla eslesemez. Bu olmadan dusmanin maketi dostun
            # balonuyla cift kurabiliyor, ciftin sinifi maketten geldigi
            # icin 'dusman-' okunuyor ve ates kilidinin dokuz kosulu birden
            # geciyordu -> DOSTUN BALONUNA ATES.
            if (config.PAIR_REQUIRE_NEAREST_MAKET
                    and _en_yakin_maket(balon, maketler) is not maket):
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
        self._kayitlar = []   # (yaw, pitch, bitis_zamani, sebep, yaricap)

    def ekle(self, yaw, pitch, ttl, sebep='', yaricap=None):
        """
        Bir yönü geçici olarak angajman dışı bırakır.

        `yaricap` KAYIT BAŞINA veriliyor, çünkü sebebe göre ne kadar geniş
        bir bölge kapatılacağı değişiyor. Kara liste hedef değil AÇI
        tuttuğundan, geniş bir yarıçap komşu hedefi de kapatabilir:
            16 metrede 1.0 m yanal ayrım = 3.58 derece
        yani varsayılan 4.0 ile bir hedefi elemek yanındakini de eler.
        Balonsuz hedef için dar bir yarıçap kullanılıyor
        (`BLACKLIST_NO_BALLOON_RADIUS_DEG`), imha/dost için geniş.
        """
        r = config.BLACKLIST_RADIUS_DEG if yaricap is None else yaricap
        self._kayitlar.append((yaw, pitch, time.time() + ttl, sebep, r))

    def icinde_mi(self, yaw, pitch, simdi=None):
        simdi = time.time() if simdi is None else simdi
        self._kayitlar = [k for k in self._kayitlar if k[2] > simdi]
        for ky, kp, _, _, r in self._kayitlar:
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
        uygun.append(iz)

    def anahtar(iz):
        if asama == 'task3':
            # ESKİDEN gözcünün 'dost' dediği izler LİSTEDEN SİLİNİYORDU.
            # Risk asimetrik olduğu için bu yanlıştı: gözcü düşmanı yanlışlıkla
            # dost sayarsa o hedef bir daha HİÇ denenmez ve görev başarısız
            # olur. Oysa sona sıralamanın maliyeti yalnızca zamandır — dostun
            # vurulması zaten `ates_serbest_mi` tarafından imkânsız kılınmış
            # durumda (sınıf `dusman-` olmadan ateş serbest kalmıyor).
            # Bu, sınıfın kendi ilkesiyle de tutarlı: "Gözcünün kararı NİHAİ
            # DEĞİL — yalnızca sıralama."
            oncelik = {'dusman': 0, 'kararsiz': 1}.get(iz['sinif'], 2)
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

        # KILIT koprusu: maket bir kare gorunmedigi icin kilidi birakmamak
        # uzere, dogrulanmis hedefin balonunun son bilinen DUNYA acisi.
        self.kilit_aci = None
        self.kopru_kare = 0
        # Kilit acisinda BASKA siniftan maket kac karedir goruluyor.
        self.yabanci_maket_ardisik = 0
        # BALON CAPASI (config.LOCK_BALLOON_ANCHOR): capadaki maket kac
        # ardisik karede guvenle DOST gorundu; capaya yakin balon kac
        # ardisik karedir bulunamiyor (arama yaricapi buna gore buyur).
        self.dost_ardisik = 0
        self.capa_kayip = 0

        self._sinif_gecmisi = []       # doğrulama için ardışık sınıflar
        self._dogrulama_balon = 0      # doğrulamada balon kaç karede görüldü
        self._nisan_ardisik = 0
        self.dogrulanan_sinif = None
        self.imha_sayisi = 0

        # IMHA DOGRULAMA penceresi
        self.ates_sayisi = 0           # bu hedefe yapılan ardışık atış
        self.son_ates_zamani = 0.0
        self._ates_balon_gorulme = 0   # pencerede balon kaç karede görüldü
        self.ates_engel_ardisik = 0    # "tekrar" istendi ama ateş edilemedi
        # ATESTEN ONCE balonun ne siklikta goruldugu (29.16 B50). "Balon
        # kayboldu" ancak balon ONCESINDE guvenilir goruluyorduysa imha
        # kanitidir; zaten yarisinda gorunmuyorsa hicbir sey kanitlamaz.
        self._balon_gecmisi = []
        self._ates_oncesi_balon_orani = None
        self.dogrulama_notu = ''       # imha dogrulanamadiysa sebebi
        # KILIT'te balonun hic gorulmedigi surenin baslangici (29.18 B55)
        self._balonsuz_baslangic = None

        # Balon en son görüldüğünde ölçülen bağıl konumu (nişan sürekliliği).
        self.nisan_ofseti = None

    # ---- durum geçişleri ----

    def _gec(self, yeni):
        if yeni != self.durum:
            self.durum = yeni
            self.durum_zamani = time.time()
            if yeni in (TARAMA, YONELME):
                self._sinif_gecmisi = []
                self._dogrulama_balon = 0
                self._nisan_ardisik = 0
                self.dogrulanan_sinif = None
                self.kilit_aci = None
                self.kopru_kare = 0
                self.yabanci_maket_ardisik = 0
                self.dost_ardisik = 0
                self.capa_kayip = 0
                # Yeni hedefe geçiliyor: atış bütçesi ve öğrenilen nişan
                # ofseti sıfırlanmalı. Ofset maket genişliğine normalize
                # olsa da başka bir hedefin geometrisini taşımamalı.
                self.ates_sayisi = 0
                self._ates_balon_gorulme = 0
                self.ates_engel_ardisik = 0
                self.nisan_ofseti = None
                self._balon_gecmisi = []
                self._ates_oncesi_balon_orani = None
                self.dogrulama_notu = ''
                self._balonsuz_baslangic = None

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

    def avcida_hazir_hedef_var(self, ciftler, acilar):
        """
        Avcının BU KAREDE gördüğü, merkeze en yakın çift doğrudan angaje
        edilebilir mi?

        `ciftler[0]` bakılıyor çünkü `dogrulama_adimi` de onu kullanıyor;
        başka bir çift seçmek ikisini birbirinden ayırırdı.

        `acilar[0]` çiftin nişan noktasının GÖVDE çerçevesindeki dünya açısı.
        Kara liste bu çerçevede tutulduğu için şart: açı bilinmiyorsa
        angaje etmiyoruz, yoksa az önce reddedilmiş bir dostu tekrar tekrar
        doğrulamaya alıp sonsuz döngüye gireriz.
        """
        if not ciftler or not acilar:
            return False
        # Maketsiz kayıtlar (yalnız balon) angaje edilemez: kimlik yok.
        secim = next(((c, a) for c, a in zip(ciftler, acilar)
                      if c.maket is not None and a is not None), None)
        if secim is None:
            return False
        cift, (yaw, pitch) = secim
        if cift.guven < config.VERIFY_MIN_CONFIDENCE:
            return False
        if self.kara_liste.icinde_mi(yaw, pitch):
            return False
        return True

    def tarama_adimi(self, izler, ciftler=(), acilar=()):
        """
        Sıradaki adayı seçer ve YÖNELME'ye geçer.

        ÖNCE AVCIYA BAKILIR. İster açıkça şöyle: "eğer baktığı yerde imha
        etmesi gereken balon-hedef ikilisi YOKSA gözcüden gelen açıyla döner."
        Eskiden bu adım yalnızca gözcü izlerine bakıyordu ve iki yanlış
        davranış üretiyordu:
          - avcı hedefi merkezde görürken taret gözcünün başka adayına
            savruluyordu (sahada kayıtlı: kare 658'de düşman çifti 0.82/0.83
            güvenle çerçevelendi, sistem yanından geçip boş duvara baktı),
          - gözcü iz üretemediğinde (balon blobu çıkmadıysa) avcı hedefi tam
            merkezde tutsa bile sistem TARAMA'da bekliyor, hiç angaje olmuyordu.

        Gözcüye gidilecekse taretin gideceği açı, izin ÖLÇÜLEN değil TAHMİN
        EDİLEN konumu: gözcü gecikmesi + yalpalama süresi toplamda ~0.5 saniye
        ve hedef bu sürede yol alır. Avcının yarı görüş açısı yaw'da ±13.75,
        pitch'te yalnızca ±7.7 derece — ölçülen açıya gitmek hedefi kaçırtabilir.
        """
        if self.avcida_hazir_hedef_var(ciftler, acilar):
            # Taret zaten doğru yöne bakıyor: açı komutu YOK, doğrudan
            # doğrulamaya geç. hedef_yaw/pitch çiftin gerçek açısına
            # ayarlanıyor ki dost çıkarsa kara liste doğru yere düşsün.
            self.hedef_yaw, self.hedef_pitch = acilar[0]
            self.aktif_iz_id = None
            self._gec(DOGRULAMA)
            return None

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

    def _dost_ttl(self):
        """
        Doğrulamada DOST çıkan hedefin kara liste ömrü — AŞAMAYA GÖRE.

        Aşama 3'te ortamda gerçekten iki dost var; onları pratikte kalıcı
        elemek doğru (600 sn).

        Aşama 2'de ise ortamda dost YOK — "dost" verdicti tanımı gereği bir
        YOLO hatasıdır. Ona 600 saniyelik ceza vermek, gerçek bir düşman
        hedefini turdan tamamen silmek demekti. Doğrulama zaman aşımıyla
        aynı kısa ömür veriliyor ki hedef birkaç saniye sonra tekrar denensin.
        """
        if self.asama == 'task3':
            return config.BLACKLIST_FRIEND_TTL_SEC
        return config.BLACKLIST_VERIFY_TTL_SEC

    def _dogrulama_zaman_asimi(self):
        """
        Doğrulama süresi doldu: adayı KISA süreliğine kara listeye alıp
        TARAMA'ya dön.

        Kara listeye almadan dönmek sonsuz döngü demekti: TARAMA aynı izi
        (en büyük kırmızı alan) yine ilk sıraya koyuyor, aynı açı gönderiliyor,
        avcı yine bir şey göremiyor. Sahada taret 4 saniye boyunca boş bir
        duvara bakıp kaldı. TTL kısa olduğu için aday kalıcı olarak elenmez.
        """
        if self.gecen() <= config.ENGAGE_VERIFY_TIMEOUT:
            return False
        self.kara_listeye_al(config.BLACKLIST_VERIFY_TTL_SEC, 'dogrulanamadi')
        self._gec(TARAMA)
        return True

    def dogrulama_adimi(self, ciftler):
        """
        Avcının YOLO çıktısıyla dost/düşman kararı.

        DOST çıkarsa hedef kara listeye girer ve TARAMA'ya dönülür — bu,
        gözcü yanılsa bile dostun vurulmasını imkânsız kılan katman.
        """
        if not ciftler:
            self._dogrulama_zaman_asimi()
            return None

        # Merkeze en yakın MAKETLİ çifti al: taret zaten adaya dönmüş
        # durumda. Maketsiz (yalnız balon) kayıtlar doğrulanamaz — kimlik
        # bilgisini yalnızca maket taşıyor.
        cift = next((c for c in ciftler if c.maket is not None), None)
        if cift is None or cift.guven < config.VERIFY_MIN_CONFIDENCE:
            self._dogrulama_zaman_asimi()
            return None

        # BALON SAYACI: doğrulama penceresi boyunca balonun kaç karede
        # görüldüğü. Aşağıda düşman kararı verilirken şart koşuluyor.
        if cift.balon is not None:
            self._dogrulama_balon += 1

        # ERKEN ÇIKIŞ. Balonun yokluğu, sınıfın ne olduğundan BAĞIMSIZ bir
        # bilgi: balon yoksa hedef ateşlenemez, sınıfını öğrenmenin değeri
        # yok. Aşağıdaki sınıf tutarlılığını beklemek kararı gereksiz yere
        # geciktiriyordu — maket aralıklı görülüyorsa `ENGAGE_VERIFY_TIMEOUT`
        # sınırına kadar (en kötü 1.5 sn) sarkıyordu.
        if (self._dogrulama_balon == 0
                and self.gecen() >= config.VERIFY_NO_BALLOON_GIVEUP_SEC):
            self.kara_listeye_al(
                config.BLACKLIST_NO_BALLOON_TTL_SEC, 'balon yok (erken)',
                yaricap=config.BLACKLIST_NO_BALLOON_RADIUS_DEG)
            self._gec(TARAMA)
            return None

        self._sinif_gecmisi.append(cift.sinif)
        pencere = max(config.VERIFY_CONFIRM_FRAMES,
                      getattr(config, 'VERIFY_WINDOW_FRAMES', config.VERIFY_CONFIRM_FRAMES))
        if len(self._sinif_gecmisi) > pencere:
            self._sinif_gecmisi.pop(0)

        # TARAF COGUNLUGU (config.VERIFY_WINDOW_FRAMES): dusman tipleri
        # birbirine karisabilir, dost/dusman ayrimi karismaz. Eski "4 kare
        # birebir ayni etiket" kurali sahada dogrulamayi 2.7 saniyeye
        # uzatiyordu.
        sinif = _taraf_cogunlugu(self._sinif_gecmisi, config.VERIFY_CONFIRM_FRAMES)
        if sinif is None:
            self._dogrulama_zaman_asimi()
            return None
        if dost_mu(sinif):
            self.kara_listeye_al(self._dost_ttl(), 'dost')
            self._gec(TARAMA)
            return sinif
        if dusman_mi(sinif):
            # BALON ŞARTI. Sınıf doğru olabilir ama balonu görülmeyen hedef
            # ATEŞLENEMEZ — ona kilitlenmek taretin boşuna oyalanmasıdır.
            #
            # Sahada ölçüldü (analizaşama3.mp4): gözcü gerçek balonu eledi ve
            # sistemi balonsuz bir `dusman-F16`ya yönlendirdi. Doğrulama
            # yalnızca sınıfa baktığı için geçti, KİLİT'e girildi ve 42 saniye
            # boyunca oradan çıkılamadı — aynı karede avcı, balonu görünen
            # başka bir düşman hedefi de görüyordu.
            #
            # Kara liste DAR ve KISA: amaç elemek değil, sıradakine
            # geçebilmek. Süre dolunca hedef yeniden denenir.
            if self._dogrulama_balon < config.VERIFY_MIN_BALLOON_FRAMES:
                # BALONA SÜRE TANI. Sınıf tutarlılığı 4 karede (0.13 sn)
                # sağlanabiliyor; balon ise YOLO için küçük nesne ve ilk
                # karelerde kaçırılabiliyor. Süre tanımadan elemek, balonu
                # GERÇEKTEN olan bir hedefi yanlışlıkla listeden düşürürdü.
                # Ölçüm: balon karelerin %19-40'ında görülüyor; 0.4 saniye
                # (12 kare) en kötü oranla bile %92 yakalama demek.
                if self.gecen() < config.VERIFY_NO_BALLOON_GIVEUP_SEC:
                    return None
                self.kara_listeye_al(
                    config.BLACKLIST_NO_BALLOON_TTL_SEC, 'balon yok',
                    yaricap=config.BLACKLIST_NO_BALLOON_RADIUS_DEG)
                self._gec(TARAMA)
                return None
            self.dogrulanan_sinif = sinif
            self._gec(KILIT)
            return sinif
        return None

    def kilit_hedefi_sec(self, ciftler, acilar):
        """
        KİLİT/ATEŞ'te bu karede nişan alınacak çifti seçer.

        Döner: (cift, kopruden_mi). `cift` None ise bu karede hedef yok.

        Üç kademe:
          1. Doğrulanan sınıfla eşleşen MAKETLİ çift  -> normal takip
          2. Maketsiz ama son kilit açısına çok yakın balon -> KÖPRÜ
          3. Kilit açısında BAŞKA SINIFTAN maket belirdi -> kilidi bırak

        3. madde emniyet ağıdır: köprü sırasında yandaki hedefin balonuna
        kaymışsak, maket geri geldiğinde sınıfı tutmaz ve kilit düşer.
        Ateş zaten `ates_serbest_mi` ile ayrıca korunuyor; bu katman
        taretin yanlış hedefte oyalanmasını da engelliyor.

        BALON CAPASI (config.LOCK_BALLOON_ANCHOR, 2026-09-16 gece):
        yukaridaki uc kademe, maketin HER KAREDE dogrulanan sinifla
        etiketlenmesini sart kosuyordu. Sahada maket kare kare
        dusman-Fuze / -Helikopter / -Drone / balon arasinda kayiyor
        (HedefSıkmaDeneme.mp4); her kayma kilidi dusuruyordu. Kimlik
        DOGRULAMA'da bir kez karara baglandigina gore takip edilmesi
        gereken sey BALON'dur — o zaten her karede var. Yeni siralama:
          1. Dogrulanan sinifla eslesen maketli cift -> capa guncellenir
          2. Capaya (son kilit acisi) en yakin BALONLU cift, maketin bu
             karedeki etiketi ne olursa olsun -> takip surer
          3. Capadaki maket ARDISIK karelerde guvenle DOST ise -> kilidi
             birak, aciyi kara listeye al (emniyet agi)
        """
        acilar = list(acilar) + [None] * max(0, len(ciftler) - len(acilar))
        if not getattr(config, 'LOCK_BALLOON_ANCHOR', True):
            return self._kilit_hedefi_sec_eski(ciftler, acilar)

        # Capa yaricapi: kacirilan her karede buyur (hedef gorulmezken
        # hareket etmis olabilir), ust sinirli.
        yaricap = min(config.LOCK_ANCHOR_MAX_TOTAL_DEG,
                      config.LOCK_ANCHOR_MAX_DEG
                      + config.LOCK_ANCHOR_GROW_DEG * self.capa_kayip)

        # 1) Dogrulanan sinifla eslesen maketli cift: capa guncellenir.
        #    CAPA VARSA MESAFE SARTI BURADA DA GECERLI: ayni siniftan ama
        #    uzaktaki bir cift BASKA bir hedeftir (yarismada 3 hedef ayni
        #    anda; ikisi ayni tip olabilir). Eski kod sinif tutunca aciya
        #    bakmadan aliyordu.
        for c, a in zip(ciftler, acilar):
            if c.maket is not None and c.sinif == self.dogrulanan_sinif:
                if (self.kilit_aci is not None and a is not None
                        and _aci_uzakligi(a, self.kilit_aci) > yaricap):
                    continue
                if a is not None:
                    self._capayi_guncelle(a)
                self.kopru_kare = 0
                self.capa_kayip = 0
                self.dost_ardisik = 0
                self.yabanci_maket_ardisik = 0
                return c, False

        if self.kilit_aci is None:
            return None, False

        # 2) Capaya en yakin BALONLU cift (maket etiketi onemsiz)
        aday, aday_aci, aday_uzaklik = None, None, None
        for c, a in zip(ciftler, acilar):
            if c.balon is None or a is None:
                continue
            u = _aci_uzakligi(a, self.kilit_aci)
            if u <= yaricap and (aday is None or u < aday_uzaklik):
                aday, aday_aci, aday_uzaklik = c, a, u
        if aday is None:
            self.capa_kayip += 1
            self.kopru_kare += 1
            return None, False

        # 3) EMNIYET: capadaki maket israrla ve guvenle DOST ise birak
        if (aday.maket is not None and dost_mu(aday.sinif)
                and aday.guven >= config.LOCK_FRIEND_ABORT_CONF):
            self.dost_ardisik += 1
            if self.dost_ardisik >= config.LOCK_FRIEND_ABORT_FRAMES:
                self.hedef_yaw, self.hedef_pitch = self.kilit_aci
                self.kara_listeye_al(self._dost_ttl(), 'kilitte dost gorundu')
                self._gec(TARAMA)
                return None, False
        else:
            self.dost_ardisik = 0

        self._capayi_guncelle(aday_aci)
        self.capa_kayip = 0
        self.kopru_kare += 1          # istatistik: kac kare capayla gidildi
        return aday, True

    def _capayi_guncelle(self, aci):
        """
        Kilit capasini ve KARA LISTE MERKEZINI birlikte gunceller (29.19 B57).

        `hedef_yaw/hedef_pitch` eskiden YALNIZCA TARAMA'da (gozcunun verdigi
        aciyla) yaziliyordu ve KILIT boyunca hic guncellenmiyordu. Kara
        liste ise merkez olarak bu alanlari kullanir. Hedef yaklastikca
        gercek acisi gozcunun ilk tahmininden uzaklastigi icin imha /
        vazgecme / balonsuz cikis kayitlari YANLIS ACIYA dusuyordu.
        Sahada olculdu (aşama2son7.mp4): t=10.5'te F16 icin atis butcesi
        doldu ve hedef "birakildi", ama kara liste kaydi yanlis yere
        dustugu icin sistem 0.5 SANIYE sonra ayni hedefe geri kilitlendi;
        o tek hedef turun 12.5 saniyesini yedi.
        """
        if aci is None:
            return
        self.kilit_aci = aci
        self.hedef_yaw, self.hedef_pitch = aci

    def _kilit_hedefi_sec_eski(self, ciftler, acilar):
        """config.LOCK_BALLOON_ANCHOR = False iken eski uc kademeli secim."""
        # 1) Doğrulanan sınıfla eşleşen maketli çift
        for c, a in zip(ciftler, acilar):
            if c.maket is not None and c.sinif == self.dogrulanan_sinif:
                if a is not None:
                    self._capayi_guncelle(a)
                self.kopru_kare = 0
                self.yabanci_maket_ardisik = 0
                return c, False

        # 3) Kilit açısında BAŞKA sınıftan maket belirdiyse kilidi bırak
        yabanci_var = False
        if self.kilit_aci is not None:
            for c, a in zip(ciftler, acilar):
                if c.maket is None or a is None:
                    continue
                if _aci_uzakligi(a, self.kilit_aci) <= config.LOCK_BRIDGE_MAX_DEG:
                    yabanci_var = True
                    break
        if yabanci_var:
            # ZAMANSAL ONAY: sahada 0.1-0.2 saniye suren (1-3 kare) sahte
            # etiketler goruldu, guvenleri 0.6'ya kadar cikiyor. Onay olmadan
            # tek karelik bir hayalet iyi bir kilidi dusurup TARAMA'ya
            # gonderebiliyordu.
            self.yabanci_maket_ardisik += 1
            if self.yabanci_maket_ardisik >= config.LOCK_ABORT_CONFIRM_FRAMES:
                self._gec(TARAMA)
                return None, False
        else:
            self.yabanci_maket_ardisik = 0

        # 2) Köprü: maketsiz ama son kilit açısına çok yakın balon
        if self.kilit_aci is not None and self.kopru_kare < config.LOCK_BRIDGE_MAX_FRAMES:
            for c, a in zip(ciftler, acilar):
                if c.maket is not None or c.balon is None or a is None:
                    continue
                if _aci_uzakligi(a, self.kilit_aci) <= config.LOCK_BRIDGE_MAX_DEG:
                    self.kopru_kare += 1
                    return c, True

        # Köprü bütçesi doldu: kilidi bırak
        if self.kopru_kare >= config.LOCK_BRIDGE_MAX_FRAMES:
            self._gec(TARAMA)
        return None, False

    def kilit_adimi(self, nisan_hatasi_px, nisan_yaricap_px, balon_gorundu):
        """
        Nişan toleransı sağlandı mı?

        Tolerans balonun YARIÇAPININ oranı olarak tanımlı — hem mesafeden
        hem zoomdan bağımsız. Balon 15 metrede 30 piksel, 5 metrede 90;
        sabit piksel toleransı ikisinde farklı anlam taşırdı.
        """
        if self.gecen() > config.ENGAGE_LOCK_TIMEOUT:
            # EMNIYET AGI: kilit suresi doldu ama ates edilemedi. Kara
            # listeye ALINMADAN TARAMA'ya donmek kisir dongu uretiyordu --
            # `avcida_hazir_hedef_var` ayni hedefi aninda geri seciyor ve
            # sistem hicbir zaman siradaki adaya gecemiyordu (sahada 42
            # saniye boyunca ayni balonsuz hedefte kalindi).
            # Yaricap DAR: komsu hedefi kapatmasin.
            self.kara_listeye_al(
                config.BLACKLIST_NO_BALLOON_TTL_SEC, 'kilit zaman asimi',
                yaricap=config.BLACKLIST_NO_BALLOON_RADIUS_DEG)
            self._gec(TARAMA)
            return False

        # Balonun kare kare gorulup gorulmedigi KILIT boyunca kaydediliyor;
        # imha dogrulamasinin taban orani bu (29.16 B50).
        self.balon_gozlemi(balon_gorundu)

        # BALONSUZ KILIT HIZLI ELENIR (2026-09-23 gece, 29.18 B55).
        # Sahada olculdu (aşama2son6.mp4): imha edilen F16'nin karkasina
        # kilitlenildi, balon hic gorulmedi ve sistem `ENGAGE_LOCK_TIMEOUT`
        # (8 sn) dolana kadar orada bekledi — 29.4 saniyelik turun 8.75
        # saniyesi tek bir olu kilitte gecti. Nisan MUKEMMELDI (kayma 1-5
        # px, "nisan TAMAM") ama balon olmadigi icin ATES'e hic gecilemedi:
        # `_nisan_ardisik` yalnizca balon goruluyorsa artiyor. Yani hicbir
        # ilerleme olmadan bekleniyordu. Balonsuz gecen sure esigi asinca
        # DAR yaricapla (komsu hedefi kapatmasin) kara listeye alinip
        # TARAMA'ya donuluyor.
        _bsuz = getattr(config, 'LOCK_NO_BALLOON_GIVEUP_SEC', 0.0) or 0.0
        if balon_gorundu:
            self._balonsuz_baslangic = None
        elif _bsuz > 0:
            if self._balonsuz_baslangic is None:
                self._balonsuz_baslangic = time.time()
            elif time.time() - self._balonsuz_baslangic > _bsuz:
                self.kara_listeye_al(
                    config.BLACKLIST_NO_BALLOON_TTL_SEC, 'kilitte balon yok',
                    yaricap=config.BLACKLIST_NO_BALLOON_RADIUS_DEG)
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

    def kara_liste_disinda(self, ciftler, acilar):
        """
        Kara listedeki acilarda duran ciftleri eler (29.18 B54).

        KARA LISTE ESKIDEN YALNIZCA TARAMA'DA BAKILIYORDU. Sahada olculdu
        (aşama2son6.mp4): +2.9 derecedeki F16 imha edilip 12 saniyeligine
        kara listeye alindi, TARAMA dogru sekilde baska bir adaya
        (+6.8 derece) yoneldi, ama DOGRULAMA ve KILIT kara listeye hic
        bakmadigi icin sistem taret oraya varinca ayni olu F16'ya
        (+1.6 derece, kara listenin TAM ICINDE) kilitlendi ve 8.75 saniye
        orada kaldi. Filtre artik angajmanin her asamasinda uygulaniyor.
        """
        if not getattr(config, 'LOCK_SKIP_BLACKLISTED', True):
            return list(ciftler), list(acilar)
        acilar = list(acilar) + [None] * max(0, len(ciftler) - len(acilar))
        yeni_c, yeni_a = [], []
        for c, a in zip(ciftler, acilar):
            if a is not None and self.kara_liste.icinde_mi(a[0], a[1]):
                continue
            yeni_c.append(c)
            yeni_a.append(a)
        return yeni_c, yeni_a

    def balon_gozlemi(self, goruldu):
        """
        Balonun bu karede GERCEKTEN gorulup gorulmedigini kaydeder.

        Imha dogrulamasinin taban orani (29.16 B50): "ates sonrasi balon
        gorunmuyor" ancak balon ATESTEN ONCE guvenilir goruluyorduysa imha
        kanitidir. Sahada olculdu (aşama2son4.mp4): uzaktaki hedefte balon
        karelerin ~%100'unde, yakindaki (en one gecmis) hedefte yalnizca
        ~%35'inde goruluyor — o hedefte "balon kayboldu" testi hicbir sey
        kanitlamiyor ve sistem patlamamis balonu imha sandi.
        """
        self._balon_gecmisi.append(bool(goruldu))
        _n = max(4, getattr(config, 'FIRE_CONFIRM_BASELINE_FRAMES', 20))
        if len(self._balon_gecmisi) > _n:
            del self._balon_gecmisi[:-_n]

    def balon_gorulme_orani(self):
        """Son pencerede balonun gorulme orani (0-1), olcum yoksa None."""
        if len(self._balon_gecmisi) < 4:
            return None
        return sum(self._balon_gecmisi) / float(len(self._balon_gecmisi))

    def nisan_ofsetini_ogren(self, cift):
        """Balon görülüyorken bağıl konumunu sakla (nişan sürekliliği)."""
        olcum = cift.olculen_ofset() if cift is not None else None
        if olcum is not None:
            self.nisan_ofseti = olcum

    def ates_kaydet(self):
        """
        Ateş komutu gönderildi: imha doğrulama penceresini aç.

        ESKİDEN burada doğrudan `imha_edildi()` çağrılıyordu, yani ateş
        etmek imha saymaya yetiyordu. Ölçülen sonuç: balon patlamasa bile
        hedef 12 saniye kara listeye giriyor ve sistem onu görmezden
        geliyordu (bkz. `config.FIRE_CONFIRM_SEC` yorumu).
        """
        self.ates_sayisi += 1
        self.son_ates_zamani = time.time()
        self._ates_balon_gorulme = 0
        self.ates_engel_ardisik = 0
        # Atis anindaki taban oran donduruluyor: dogrulama bununla
        # karsilastirilacak (29.16 B50).
        self._ates_oncesi_balon_orani = self.balon_gorulme_orani()

    def ates_dogrulama_adimi(self, balon_gorundu):
        """
        Ateş sonrası imha doğrulama penceresini bir adım ilerletir.

        HER KAREDE çağrılır. Döner:
          'bekle'     — pencere sürüyor, karar yok
          'onaylandi' — balon kayboldu, imha doğrulandı
          'tekrar'    — balon hâlâ orada, yeniden ateş edilmeli
          'pes'       — balon duruyor ama atış bütçesi doldu

        SAYIM GECİKMELİ BAŞLAR (`FIRE_CONFIRM_DELAY_SEC`). Sahada ölçüldü:
        ateşten sonra patlamış balon 0.5 saniye daha görünmeye devam ediyor
        (mermi uçuş süresi + patlama + YOLO'nun kutuyu bırakması). Gecikme
        olmadan bu kareler "balon hâlâ orada" sayılıyor ve patlamış hedefe
        tekrar ateş edilmeye çalışılıyordu.

        Balonun tek kare kaçırılması "imha" sanılmasın diye pencere boyunca
        görülme SAYILIYOR; karar pencerenin sonunda veriliyor.
        """
        if self.ates_sayisi <= 0:
            return 'bekle'
        gecen = time.time() - self.son_ates_zamani
        # Patlama penceresi: bu süre boyunca görülen balon SAYILMAZ.
        if gecen >= config.FIRE_CONFIRM_DELAY_SEC and balon_gorundu:
            self._ates_balon_gorulme += 1
        if gecen < config.FIRE_CONFIRM_DELAY_SEC + config.FIRE_CONFIRM_SEC:
            return 'bekle'
        if self._ates_balon_gorulme <= config.FIRE_CONFIRM_MAX_SEEN:
            # IMHA KANITI ICIN TABAN ORAN SARTI (2026-09-23 gece, 29.16 B50).
            # "Balon artik gorunmuyor" ancak balon ATESTEN ONCE guvenilir
            # goruluyorduysa imha kanitidir. Yakin mesafede balon buyuyup
            # egitim dagiliminin disina ciktigi icin tespit orani %35'e
            # dusuyor; o hedefte bu test her zaman "imha" der ve sistem
            # patlamamis balonu vurulmus sanip siradaki hedefe gecer.
            # Sahada tam olarak bu oldu: ilk hedef (en yakin, ortadaki)
            # imha sayildi, 12 saniye sonra kara listesi dolunca ayni
            # hedef balonuyla birlikte yeniden karsimiza cikti.
            _taban = getattr(config, 'FIRE_CONFIRM_MIN_BEFORE_RATE', 0.0) or 0.0
            _onceki = self._ates_oncesi_balon_orani
            if _taban > 0 and _onceki is not None and _onceki < _taban:
                self.dogrulama_notu = (
                    f'imha dogrulanamadi: balon atistan once de yalnizca '
                    f'%{_onceki * 100:.0f} goruluyordu')
                if self.ates_sayisi >= config.FIRE_MAX_ATTEMPTS:
                    return 'pes'
                return 'tekrar'
            self.dogrulama_notu = ''
            return 'onaylandi'
        if self.ates_sayisi >= config.FIRE_MAX_ATTEMPTS:
            return 'pes'
        return 'tekrar'

    def ates_engellendi(self):
        """
        'tekrar' istendi ama ateş kilidi izin vermedi.

        Döner: True ise hedef bırakılmalı.

        BU KİLİDİ KIRAN KONTROL. Sahada ölçüldü (18. bölüm): Aşama 3'te
        7.6 saniyede ateş edildi, balon 8.10'da patladı, ama pencere
        'tekrar' dediği için sistem yeniden ateş etmeye çalıştı; balon
        artık görünmediğinden ateş kilidi her karede engelledi. `ates_kaydet`
        çağrılmadığı için sayaç artmadı, `'pes'` asla tetiklenmedi ve
        `ates_sayisi > 0` olduğu için KİLİT'e de dönülmedi — sistem ATEŞ
        durumunda 20 saniye takılı kaldı.

        Artık engellenen her kare sayılıyor; eşiği aşınca hedef bırakılıyor,
        yani çıkış her durumda garanti.
        """
        self.ates_engel_ardisik += 1
        return self.ates_engel_ardisik >= config.FIRE_RETRY_GIVEUP_FRAMES

    def kara_listeye_al(self, ttl, sebep='', yaricap=None):
        if self.hedef_yaw is not None:
            self.kara_liste.ekle(self.hedef_yaw, self.hedef_pitch, ttl,
                                 sebep, yaricap)

    def imha_edildi(self):
        self.imha_sayisi += 1
        self.kara_listeye_al(config.BLACKLIST_TTL_SEC, 'imha',
                             yaricap=getattr(config, 'BLACKLIST_KILL_RADIUS_DEG',
                                             None))
        self.aktif_iz_id = None
        self._gec(TARAMA)

    def imha_edilemedi(self):
        """
        Atış bütçesi doldu, balon hâlâ duruyor: hedefi geçici olarak bırak.

        TTL 1.5 -> `BLACKLIST_GIVEUP_TTL_SEC` (29.16). 1.5 saniye, sistemin
        siradaki hedefe yonelip donmesine bile yetmiyordu: ayni hedefe
        hemen geri donup ayni sonucu aliyordu. Vurulamayan hedef, diger
        hedeflere servis verilecek kadar bir sure birakilmali.
        """
        self.kara_listeye_al(
            getattr(config, 'BLACKLIST_GIVEUP_TTL_SEC',
                    config.BLACKLIST_VERIFY_TTL_SEC),
            'imha edilemedi',
            yaricap=getattr(config, 'BLACKLIST_KILL_RADIUS_DEG', None))
        self.aktif_iz_id = None
        self._gec(TARAMA)


def ates_serbest_mi(cift, makine, balon_gorundu, nisan_tamam,
                    yaw, no_fire_start, no_fire_end, taret_hizi=None,
                    hedef_hizi=None, hata_hizi=None, balon_yakin=False,
                    yon_kararli=True):
    """
    Ateş kilidi — hepsi birden sağlanmalı.

    Aşama 3'te dost vurmak diskalifiye olduğu için burada cömert
    davranmıyoruz. Eski kodda Aşama 3'ün TAHMİN EDİLMİŞ (görülmemiş) hedefe
    ateş edebildiği bir açık vardı; 1. ve 5. koşullar onu kapatıyor.

    Döner: (izin_var, gerekce)
    """
    if makine.durum != ATES:
        return False, 'durum ATES degil'
    if cift is None:
        return False, 'hedef yok'
    if getattr(config, 'LOCK_BALLOON_ANCHOR', True):
        # BALON CAPASI: kimlik DOGRULAMA'da bir kez karara baglandi. Bu
        # karede maketin etiketi/guveni/varligi sart DEGIL — balon
        # capaya baglilikla takip ediliyor (bkz. kilit_hedefi_sec).
        # Sahada (HedefSıkmaDeneme.mp4) uc kosulun her biri ayri ayri
        # atesi kesiyordu: "maket bu karede tespit edilmedi", "sinif
        # dogrulanandan farkli", "guven dusuk 0.36"; balon o karelerde
        # 0.80+ ile duruyordu.
        if not dusman_mi(makine.dogrulanan_sinif):
            return False, f'dogrulanan sinif dusman degil: {makine.dogrulanan_sinif}'
        # Tek karelik bile olsa GUVENLE dost gorunen makete ates yok.
        if (cift.maket is not None and dost_mu(cift.sinif)
                and cift.guven >= config.LOCK_FRIEND_ABORT_CONF):
            return False, f'bu karede dost gorunumu: {cift.sinif} {cift.guven:.2f}'
    else:
        if cift.maket is None:
            return False, 'maket bu karede tespit edilmedi'
        if not dusman_mi(cift.sinif):
            return False, f'sinif dusman degil: {cift.sinif}'
        if cift.guven < config.VERIFY_MIN_CONFIDENCE:
            return False, f'guven dusuk: {cift.guven:.2f}'
        if makine.dogrulanan_sinif != cift.sinif:
            return False, 'sinif dogrulanandan farkli'
    # İKİ AYRI KONTROL, BİLEREK.
    # `balon_gorundu` ÇAĞIRANDAN gelen bir bayrak; çağıran onu yanlış
    # hesaplarsa bu koşul sessizce geçilir. Elimizdeki çifti de doğrudan
    # kontrol ediyoruz: balonu eşleşmemiş bir çifte ateş, "maketin altında
    # balon var" varsayımının çöktüğü anlamına gelir ve o an nişan alınan
    # nokta maketten TÜRETİLMİŞ bir tahmindir — yani görülmemiş bir yere ateş.
    #
    # KISA SUREL GRACE (2026-09-23, 29.13 B45): balonun TESPITI kare kare
    # titriyor (sahada F16 kilidinde karelerin ~yarisinda "BALON YOK";
    # balon 15 metrede yalnizca ~30 piksel). Balon fiziksel olarak 0.2
    # saniyede kacamaz, o yuzden SON BIRKAC KAREDE gercekten gorulmus
    # olmasi yeterli sayiliyor; nisan noktasi o sirada `nisan_ofseti` ile
    # balonun en son OLCULEN yerinden turetiliyor. `balon_yakin` bu grace'i
    # cagirandan alir; False ise eski kati davranis gecerli.
    if cift.balon is None and not balon_yakin:
        return False, 'cifte balon eslesmemis (nisan noktasi tahmini)'
    if not balon_gorundu and not balon_yakin:
        return False, 'balon bu karede tespit edilmedi'
    if not nisan_tamam:
        return False, 'nisan tolerans disinda'
    # NISAN HATASININ DEGISIM HIZI — asil isabet kapisi (29.13 B44).
    # Mermi FIRE_SHOT_LATENCY_SEC sonra variyor; o sure icinde nisan
    # noktasinin hedefe gore kayacagi miktar toleransi asmamali. Taret
    # hedefle birlikte duzgun gidiyorsa hata degismez ve mutlak hizlar
    # buyuk olsa bile atis serbesttir — istenen davranis tam olarak budur.
    _gec = getattr(config, 'FIRE_SHOT_LATENCY_SEC', 0.0) or 0.0
    _kayma_siniri = getattr(config, 'FIRE_MAX_ERROR_DRIFT_PIXELS', 0.0) or 0.0
    if hata_hizi is not None and _gec > 0 and _kayma_siniri > 0:
        _kayma = abs(hata_hizi) * _gec
        if _kayma > _kayma_siniri:
            return False, f'nisan kayiyor: atisa kadar {_kayma:.0f} px'
    # HEDEF YON DEGISTIRIRKEN ATES ETME (29.23).
    # Olculdu: isabet eden uc angajmanda hedefin hiz isareti hic
    # degismemisti (0 yon degisimi, 1.11-1.75 derece/sn); iskalayan
    # angajmanda ise 4.5 saniyede 4 kez yon degistirdi (ort 0.78 derece/sn).
    # Yani belirleyici olan hiz degil, donus ani. `yon_kararli` cagirandan
    # gelir; varsayilan True oldugu icin bayrak verilmezse eski davranis.
    if not yon_kararli:
        return False, 'hedef yon degistiriyor'
    # TARET HAREKET HALINDEYKEN ATES ETME. `taret_hizi` enkoderden olculen
    # mutlak yaw hizi (derece/sn); None ise enkoder yok/saglıksiz demektir ve
    # kapi uygulanmaz. Gerekce config.FIRE_MAX_TURRET_RATE_DEG_S yaninda.
    _sinir = getattr(config, 'FIRE_MAX_TURRET_RATE_DEG_S', 0) or 0
    if taret_hizi is not None and _sinir > 0 and taret_hizi > _sinir:
        return False, f'taret hareketli: {taret_hizi:.1f} derece/sn'
    # HEDEF SALLANIRKEN ATES ETME: balon direkte sarkac gibi salinir, tepe
    # hizi ~7 derece/sn; 0.25 sn'lik atis gecikmesinde 1.75 derece kayar.
    # Sarkac uclarda durur; ates oraya tasinir. Gerekce config'te.
    _hs = getattr(config, 'FIRE_MAX_TARGET_RATE_DEG_S', 0) or 0
    if hedef_hizi is not None and _hs > 0 and hedef_hizi > _hs:
        return False, f'hedef hareketli: {hedef_hizi:.1f} derece/sn'
    if _atesiz_bolgede(yaw, no_fire_start, no_fire_end):
        return False, 'atesiz bolge'
    return True, 'serbest'


def nisan_kayma_hizi(gecmis, en_az=4):
    """
    Nisan hatasinin KAYMA hizi (px/sn): (zaman, hata_yaw_px, hata_pitch_px)
    dizisine EKSEN BASINA en kucuk kareler dogrusu uydurup egimlerin
    bileskesini dondurur. Ornek sayisi yetmezse None (kapi uygulanmaz).

    NEDEN EGIM, NEDEN ARDISIK FARK DEGIL (2026-09-23, 29.14 B46):
    ilk surum ardisik karelerin farkinin BUYUKLUGUNU (hypot, daima pozitif)
    EMA'liyordu. Sifir ortalamali tespit gurultusu bile pozitif bir
    ortalamaya yakinsadigi icin kapi neredeyse hep kapali kaldi — sahada
    "takip iyi ama silah hic atesleme yapmiyor". Olculdu (3 px gurultu,
    GERCEK kayma yok): eski kestirici 74-79 px/sn, egim kestiricisi
    6-13 px/sn. Gercek 60 px/sn kayma varken egim 60 px/sn okuyor.
    """
    n = len(gecmis)
    if n < en_az:
        return None
    t0 = gecmis[0][0]
    ts = [k[0] - t0 for k in gecmis]
    t_ort = sum(ts) / n
    payda = sum((t - t_ort) ** 2 for t in ts)
    if payda <= 1e-9:
        return None
    egimler = []
    for eksen in (1, 2):
        v = [k[eksen] for k in gecmis]
        v_ort = sum(v) / n
        egimler.append(sum((t - t_ort) * (x - v_ort)
                           for t, x in zip(ts, v)) / payda)
    return math.hypot(egimler[0], egimler[1])


def _taraf_cogunlugu(gecmis, gerekli):
    """
    Pencerede ayni TARAF (dost-/dusman-) en az `gerekli` kez ve digerinden
    cok gorulduyse o tarafin en sik sinifini dondurur, yoksa None.
    """
    dusman = [s for s in gecmis if dusman_mi(s)]
    dost = [s for s in gecmis if dost_mu(s)]
    if len(dusman) >= gerekli and len(dusman) > len(dost):
        return max(set(dusman), key=dusman.count)
    if len(dost) >= gerekli and len(dost) > len(dusman):
        return max(set(dost), key=dost.count)
    return None


def _aci_uzakligi(a, b):
    """İki (yaw, pitch) açısı arasındaki mesafe (derece)."""
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


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
