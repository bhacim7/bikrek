# BUKREK — Görev Kabiliyet Gösterimi Videosu

**Şartname:** 2026 Savaşan İHA / Hava Savunma Sistemi, madde 2.4.4.1
**Süre hedefi:** 4 dk 30 sn (şartname sınırı: en az 2, en fazla 5 dakika)
**Çözünürlük:** en az 720p — 1080p önerilir, arayüz yazıları okunsun

---

## ÇEKİM KURALLARI (şartname 2.4.4.2)

| kural | ne yapılacak |
|---|---|
| Tek video | Tüm yetenekler kesintisiz tek dosyada, YouTube'a "Liste dışı" |
| Sıra | Yetenekler **1→7 sırasıyla ve eksiksiz** |
| Etiketleme | Her bölümün başında ekranda **"YETENEK N"** bindirmesi |
| Açıklama | Video açıklamasına zaman damgaları (aşağıda hazır) |
| Link | T3 KYS formuna eklenecek — link çalışmazsa **eleme** |

**Ekran bindirmesi zorunlu.** Şartname "videonun ilgili kısmında kaç numaralı yeteneğin gösterildiği belirtilmelidir" diyor. Sadece sesle söylemek yeterli değil.

---

## YOUTUBE AÇIKLAMASI (kopyala-yapıştır)

```
BUKREK Hava Savunma Sistemi — Görev Kabiliyet Gösterimi

00:00  Sistem tanıtımı
00:15  YETENEK 1 — Kullanıcı arayüzü ve tüm fonksiyonlar
01:25  YETENEK 2 — 15 metrede durağan atış, balon imhası
01:55  YETENEK 3 — Hareket sırasında Acil Durdur
02:15  YETENEK 4 — Ateş sırasında Acil Durdur
02:35  YETENEK 5 — Hareketli hedef takibi (yan + yükseliş)
03:05  YETENEK 6 — 5m / 10m / 15m hedef tespiti ve sınıflandırma
03:45  YETENEK 7 (OPSİYONEL) — Otonom dost/düşman ayrımı ve imha
04:40  Kapanış
```

---

# KONUŞMA METNİ

> Köşeli parantez içindekiler **çekim notu**, seslendirilmez.

---

## GİRİŞ — 00:00 → 00:15

[Görüntü: sistemin tamamı, taret + iki kamera + bilgisayar]

> Merhaba. BUKREK hava savunma sistemi.
>
> Sistem iki kameralı çalışıyor: gövdeye sabit **gözcü** kamera geniş açıyla ortamı tarıyor, taret üzerindeki **avcı** kamera ise sabit odaklı lensiyle hedefi doğruluyor ve nişan alıyor. Görüntü işleme bilgisayarda, motor ve tetik kontrolü Raspberry Pi 5 üzerinde yürüyor.
>
> Şimdi yetenekleri sırayla gösteriyoruz.

---

## YETENEK 1 — ARAYÜZ — 00:15 → 01:25

[Ekranda: **YETENEK 1**. Ekran kaydı, arayüz tam görünür. Konuşurken imleçle göster.]

> Yetenek 1: kullanıcı arayüzü ve tüm fonksiyonları.
>
> Solda avcı kameranın canlı görüntüsü var. Tespit edilen her hedef kutu içine alınıyor; kutunun üstünde sınıfı ve güven değeri yazıyor. Sağ üstte gözcü kameranın görüntüsü — burada renk analizinden geçen adaylar daire ile, elenen bölgeler ise elenme sebebiyle birlikte işaretleniyor.

[İmleci gözcü panelindeki bilgi satırına götür]

> Altındaki satır gözcünün o anki durumunu veriyor: kaç iz takip ediliyor, kaç renk bölgesi bulundu ve ilk adayın açısı.

[İmleci durum satırına götür]

> Bunun altında sistemin durumu ve nişan hatası piksel cinsinden yazıyor.

[GÖREVLER kutusunu göster, butonları tek tek]

> Görevler bölümünde dört mod var.
> **Aşama 1** manuel nişan modu.
> **Aşama 2** otonom imha — ortamdaki tüm hedefler düşman kabul edilir.
> **Aşama 3** dost-düşman ayrımlı otonom mod.
> **Hedef Takip** modu hedefe kilitlenir ve takip eder, ama **ateş etmez**; kilitlenme kalitesini ölçmek için kullanıyoruz.
> **Tam Manuel Kontrol** ise tareti ok tuşlarıyla sürmeyi sağlar.

[KONTROL kutusunu göster]

> Kontrol bölümünde Raspberry Pi bağlantısı, kamera başlat-durdur, görevi durdur, manuel **ATEŞ ET**, açıları sıfırlama ve derece-piksel kalibrasyonu var.

[Ateşsiz bölge alanını göster]

> Alt bölümde ateşsiz bölge tanımlanıyor. Girilen iki yaw açısı arasında sistem ateş kilidini açmıyor — güvenlik için seyirci veya hakem yönü buraya giriliyor.

[Fareyle görüntü üzerine tıkla, taret dönsün]

> Görüntü üzerine tıklandığında taret o noktaya yöneliyor; tıklanan piksel kamera açısına çevrilerek motor komutuna dönüştürülüyor.

---

## YETENEK 2 — 15 METREDE DURAĞAN ATIŞ — 01:25 → 01:55

[Ekranda: **YETENEK 2**. Önce mesafeyi göster — metre veya lazermetre ile 15 m]

> Yetenek 2: sistem durağan halde, 15 metredeki balonu imha edecek.

[Mesafe ölçümü görüntüsü, sonra sisteme dön]

> Hedef 15 metrede. Sistem sabit, taret hareket etmiyor.

[Aşama 2'ye bas veya manuel nişan al, ateş et]

> Hedef tespit edildi, balon kilitlendi ve ateş komutu verildi.

[Balonun patladığı an — yavaşlatılmış tekrar koymak iyi olur]

> Balon imha edildi.

---

## YETENEK 3 — HAREKET SIRASINDA ACİL DURDUR — 01:55 → 02:15

[Ekranda: **YETENEK 3**. Kadraja hem taret hem acil durdur butonu girsin]

> Yetenek 3: sistem yan ve yükseliş eksenlerinde hareket ederken acil durdurma.

[Manuel modda tareti çapraz sür — hem yaw hem pitch aynı anda dönsün]

> Taret şu anda her iki eksende de hareket ediyor.

[Butona bas — el hareketi net görünsün]

> Acil Durdur'a basıldı.

[Taretin anında durduğu görülsün, 2-3 saniye sabit kal]

> Motorlar anında durdu. Acil durdurma donanım seviyesinde çalışıyor: buton doğrudan Raspberry Pi'nin giriş pinine bağlı ve bilgisayardan bağımsız olarak motor sürücülerini devre dışı bırakıyor. Yazılım kilitlense bile durdurma çalışır.

---

## YETENEK 4 — ATEŞ SIRASINDA ACİL DURDUR — 02:15 → 02:35

[Ekranda: **YETENEK 4**. Kadrajda tetik mekanizması ve buton]

> Yetenek 4: sistem ateş ederken acil durdurma.

[Otonom modda veya sürekli ateş komutuyla sistemi ateş ederken yakala]

> Sistem hedefe kilitlendi ve ateş ediyor.

[Ateş sürerken butona bas]

> Acil Durdur'a basıldı.

[Ateşin kesildiği görülsün]

> Ateş kesildi. Tetiği çeken servo dinlenme konumuna döndü ve sinyal tamamen kesildi — sistem bu haldeyken yeni bir ateş komutu üretemez.

---

## YETENEK 5 — HAREKETLİ HEDEF TAKİBİ — 02:35 → 03:05

[Ekranda: **YETENEK 5**. Hedef ipe asılı veya elde taşınıyor; hem yatay hem dikey hareket etsin]

> Yetenek 5: yan ve yükseliş ekseninde hareket eden hedefin takibi.

[Hedef Takip moduna bas]

> Hedef Takip moduna alıyoruz. Bu modda sistem kilitlenir ve takip eder, ateş etmez.

[Hedefi yatay hareket ettir]

> Hedef yatayda hareket ediyor, taret yaw ekseninde takip ediyor.

[Hedefi dikey hareket ettir]

> Yükseliş ekseninde de aynı şekilde.

[Ekrandaki nişan hatası satırını göster]

> Ekranda anlık nişan hatası piksel ve derece cinsinden yazıyor. Sistem hedefin hızını da hesaba katıyor: görüntü işleme gecikmesi boyunca hedefin alacağı yol tahmin edilip nişan noktasına ekleniyor, böylece taret hedefin gerisinde kalmıyor.

---

## YETENEK 6 — MESAFEYE GÖRE TESPİT VE SINIFLANDIRMA — 03:05 → 03:45

[Ekranda: **YETENEK 6**. Her mesafede önce ölçümü göster]

> Yetenek 6: beş, on ve on beş metrede farklı hedef tiplerinin tespiti ve sınıflandırılması.

[5 metre — hedefleri diz, arayüz ekranı net görünsün]

> Beş metrede. Sistem hedefleri tespit etti ve sınıflandırdı: F16, helikopter, füze ve mini İHA.

[Arayüzde kutuların üstündeki etiketleri yakınlaştır]

> Her kutunun üstünde sınıf adı ve güven değeri görünüyor.

[10 metre]

> On metrede aynı hedefler.

[15 metre]

> On beş metrede.

> Sınıflandırmayı derin öğrenme modeli yapıyor; model Raspberry Pi'de değil, bilgisayarın ekran kartında TensorRT ile çalışıyor. Ayrıca her tespit iki süzgeçten geçiyor: hedefin sınıfına göre beklenen renk kutunun içinde gerçekten var mı, ve kutunun piksel boyutu bu mesafede fiziksel olarak mümkün mü. Bu iki kontrol yanlış tespitleri eliyor.

---

## YETENEK 7 (OPSİYONEL) — OTONOM DOST/DÜŞMAN — 03:45 → 04:40

[Ekranda: **YETENEK 7 (OPSİYONEL)**. Önce yerleşimi göster: 10 metrede 1 kırmızı + 2 mavi]

> Yetenek 7: otonom dost-düşman ayrımı.
>
> Sistemin yaklaşık on metre uzağında bir kırmızı düşman ve iki mavi dost hedef yerleştirildi. Her hedefin altında bir balon var.

[Aşama 3'e bas]

> Sistemi otonom moda alıyoruz.

[Sistem tararken durum satırını göster]

> Gözcü kamera adayları buluyor ve taret sırayla her adaya yöneliyor. Karar gözcüde verilmiyor — gözcü yalnızca sıralama yapıyor. Kimlik kararını avcı kamera veriyor.

[Dost hedefe yöneldiğinde durum satırında "DOST" yazısını göster]

> Bu hedef dost olarak doğrulandı, sistem ateş etmeden bir sonraki adaya geçiyor.

[Düşman hedefe kilitlendiğinde]

> Bu hedef düşman olarak doğrulandı ve balonuna kilitlenildi.

[Ateş ve patlama]

> Düşman hedef imha edildi.

> Sistem ateş etmeden önce dokuz koşulu birden arıyor: hedefin sınıfı düşman olmalı, kimlik en az dört ardışık karede aynı çıkmalı, balon o karede gerçekten görülmüş olmalı, nişan toleransı sağlanmalı ve yaw açısı ateşsiz bölgede olmamalı. Bu koşullardan biri bile sağlanmazsa ateş kilidi açılmıyor.

[Ateş sonrası 10 saniye bekle — sayaç göster veya kesme yapma]

> Şimdi on saniye bekliyoruz. Bu süre boyunca sistem dost hedeflere ateş etmiyor.

[10 saniye sonra Acil Durdur'a bas]

> Acil Durdur'a basıldı.

[10 saniye daha bekle]

> On saniye daha bekliyoruz.

[Sistemi kapat]

> Sistem kapatılıyor. Dost unsurlara hiçbir aşamada ateş edilmedi.

---

## KAPANIŞ — 04:40 → 04:50

[Görüntü: sistemin tamamı]

> BUKREK hava savunma sistemi. İzlediğiniz için teşekkür ederiz.

---

# ÇEKİM ÖNCESİ KONTROL LİSTESİ

## Sistem
- [ ] Servo tetik kalibrasyonu doğru (`FIRE_SERVO_MODE = 'konum'`, REST/PULL değerleri)
- [ ] Servo **ayrı besleme** ile çalışıyor, Pi'nin 5V pininden değil
- [ ] Acil durdurma butonu bağlı ve test edildi
- [ ] `Derece/Piksel Ölç` ile kalibrasyon yapıldı
- [ ] Kamera indeksleri doğru (ana görüntü = avcı, sağ üst = gözcü)
- [ ] Ateşsiz bölge kamera/seyirci yönüne göre ayarlandı

## Hedefler
- [ ] Balonlar şişirilmiş ve maketlerin altına takılı
- [ ] 5m / 10m / 15m mesafeler ölçülüp işaretlendi
- [ ] Yetenek 7 için 1 kırmızı + 2 mavi maket hazır
- [ ] Yedek balon (ıska ihtimaline karşı)

## Çekim
- [ ] Ekran kaydı 1080p, arayüz yazıları okunuyor
- [ ] Harici kamera taret + hedefi aynı kadrajda görüyor
- [ ] Acil durdur butonuna basan el kadrajda
- [ ] Ses kaydı temiz (motor gürültüsü konuşmayı bastırmıyor)
- [ ] Her bölüm başında **YETENEK N** bindirmesi eklendi

## Yükleme
- [ ] Tek dosya, YouTube, **Liste dışı**
- [ ] Açıklamaya zaman damgaları eklendi
- [ ] Link T3 KYS formuna girildi ve **açılıyor mu diye test edildi**

---

# NOTLAR

**Süre.** Metin 4:30–4:50 aralığında. Şartname sınırı 5 dakika — kurguda 10 saniyelik beklemeler (Yetenek 7) kesilirse süre rahatlar, ama **kesilmediğini gösteren bir sayaç** koymak daha güvenli olur; hakem beklemenin gerçekten yapıldığını görmek isteyecektir.

**Riskli bölüm Yetenek 7.** Sistem dost hedefe yönelip geçtiğini göstermeli — bu, dost/düşman ayrımının çalıştığının en güçlü kanıtı. Otonom tarama sırası her koşumda değişebileceği için birkaç tekrar çekip en net olanı kullanın.

**Ateş sırasında Acil Durdur (Yetenek 4)** zamanlaması zor: atış dizisi bir saniyeden kısa. Aşama 2'de sistemi hedefe kilitleyip ateş anını bekleyerek basmak en kolayı. Gerekirse `FIRE_MAX_ATTEMPTS` geçici olarak büyütülüp arka arkaya atış yaptırılabilir, buton basmak için daha geniş bir pencere oluşur.

**Yetenek 2 ve 6 aynı çekimde birleştirilmesin** — şartname sıralı ve eksiksiz gösterim istiyor.
