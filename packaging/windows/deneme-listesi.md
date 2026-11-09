# Koç PDF Pro — Windows deneme listesi

Windows paketi Mac'te hazırlanıyor ve gerçek bir Windows bilgisayarda henüz baştan sona denenmedi. Yayımlamadan önce
bu listeyi bir Windows 10 ya da 11 (64 bit) bilgisayarda sırayla geçin. Her satırda önce **yapılacak**, okun ardından
**beklenen sonuç** yazıyor. Beklenen olmazsa satırın yanına ne olduğunu kısaca not edin; mümkünse ekran görüntüsü alın.

Başlamadan not edin:
- Windows sürümü (Başlat'a `winver` yazın): ……………
- Kullanıcı adında Türkçe harf var mı (ör. `C:\Users\Hüseyin`)? ……
- Masaüstü OneDrive'a mı bağlı (Dosya Gezgini'nde Masaüstü'ne sağ tık › Özellikler › Konum)? ……
- Microsoft Word / Excel kurulu mu? ……
- Ekran ölçeği (Ayarlar › Sistem › Ekran › Ölçek): ……

Bir şey ters giderse günlük dosyası: `%LOCALAPPDATA%\KocPDFPro\log.txt` (Dosya Gezgini adres çubuğuna yapıştırın).

## 1. İndirme ve kurulum

- [ ] Edge ile `KocPDFPro-Kurulum.exe` indirin → “genellikle indirilmez” uyarısı çıkabilir; **… › Sakla** (gerekirse
      **Daha fazla göster › Yine de sakla**) ile dosya iner.
- [ ] Dosyaya çift tıklayın → “Windows bilgisayarınızı korudu” çıkarsa **Ek bilgi › Yine de çalıştır** ile kurulum açılır.
- [ ] Kurulum yönetici parolası **sormaz**; **Kur** deyince biter. Son sayfada “Koç PDF Pro'yu şimdi aç” işaretliyken
      **Bitir** → uygulama açılır.
- [ ] Masaüstünde ve Başlat menüsünde **Koç PDF Pro** kısayolu var, simgesi doğru.
- [ ] **Ayarlar › Uygulamalar › Yüklü uygulamalar** listesinde “Koç PDF Pro” ve sürümü görünüyor.
- [ ] Microsoft Defender kurulum sırasında ya da sonra bir dosyayı karantinaya almadı (Windows Güvenliği › Koruma geçmişi).

## 2. Açılış ve pencere

- [ ] Kısayola çift tıklayın → logo animasyonlu açılış ekranı, ardından uygulama **kendi penceresinde** açılır
      (Edge sekmesi değil). Görev çubuğunda Koç PDF Pro simgesi görünür.
- [ ] **Açılış hızı:** bilgisayarı yeniden başlatın, Koç PDF Pro'yu açın → logo ekranı tıkladıktan sonra bir iki saniye
      içinde görünür (motor arkada yüklenirken boş ekran beklenmez). Günlük dosyasında her satırın başında
      `[+… sn]` yazar: “Pencere göründü”, “Motor yüklendi” ve “Uygulama yüklendi” satırlarındaki saniyeleri not edin.
      Aynısını ikinci açılışta da yapın.
- [ ] Kurulumdan (ya da güncellemeden) hemen sonraki ilk açılış da sonrakiler kadar hızlı: Python dosyaları hazır
      (derlenmiş) gelir. `%LOCALAPPDATA%\Programs\KocPDFPro\python\Lib\site-packages\flask\__pycache__` klasöründe
      `.pyc` dosyaları vardır.
- [ ] Windows karanlık temadaysa açılış ekranı ve uygulama gece görünümünde gelir.
- [ ] Ekran ölçeği %125 / %150 iken yazılar ve simgeler bulanık değil, taşma yok.
- [ ] **Ayarlar (⚙) › Görünüm › Arayüz büyüklüğü** değişince arayüz büyüyüp küçülür; kapatıp açınca hatırlanır.
- [ ] Uygulama açıkken kısayola yeniden çift tıklayın → ikinci pencere açılmaz, var olan öne gelir.
- [ ] **Hakkında**: sürüm numarası (ör. “Sürüm 1.0.0”) ve **Güncellemeleri denetle** var, “Demo” yazmıyor; telefon
      numarası yok; e-posta, “Sorun bildir” ve geliştirici bağlantısı var. Geliştirici bağlantısı
      varsayılan tarayıcıda açılır (uygulama penceresinde değil).

## 3. PDF açma ve sekmeler

- [ ] Dosya Gezgini'nde bir PDF'e sağ tık › **Birlikte aç › Koç PDF Pro** → okuyucuda açılır.
- [ ] Uygulama kapalıyken aynı yolla açın → uygulama açılır ve PDF gelir.
- [ ] Uygulama açıkken başka bir PDF'i aynı yolla açın → aynı pencerede yeni sekmede açılır.
- [ ] PDF'i pencereye sürükleyip bırakın → açılır.
- [ ] Bir `.udf` (UYAP) dosyasını açın → okunur.
- [ ] **Ayarlar › Belgeler › Varsayılan PDF uygulaması** → Windows'un varsayılan uygulamalar ayarı açılır; orada seçince
      PDF'ler çift tıklamayla Koç PDF Pro'da açılır.
- [ ] Ctrl+T yeni sekme, Ctrl+Tab / Ctrl+Shift+Tab sekmeler arası, Ctrl+W sekmeyi kapatır.
- [ ] Şifreli bir PDF açın → şifre sorulur, doğru şifreyle açılır.

## 4. Kaydetme ve kapatma

- [ ] Bir sayfayı döndürün → sekmede kırmızı nokta. **Ctrl+S** → dosyanın üzerine kaydedilir, nokta kaybolur.
- [ ] **Önceki sürümler** penceresinde eski hâl listelenir; geri yükleyince dosya o hâline döner.
- [ ] **Ctrl+Shift+S** (Farklı Kaydet) → Windows'un kaydetme penceresi açılır; Türkçe harfli adla
      (ör. `Dilekçe şık ğüı.pdf`) kaydedilir, Dosya Gezgini'nde ad doğru görünür.
- [ ] OneDrive'daki Masaüstü'ne kaydedin → kaydedilir, OneDrive eşitlemesi dosyayı bozmaz.
- [ ] Dosya başka bir programda açıkken (ör. Edge'de) Ctrl+S → anlaşılır bir hata mesajı; uygulama çökmez, değişiklikler
      kaybolmaz.
- [ ] Belge açıkken dosyayı başka bir programla değiştirip Ctrl+S → “Dosya siz çalışırken başka bir uygulamada
      değiştirilmiş” sorusu gelir.
- [ ] Kaydedilmemiş değişiklikle sekmeyi kapatın → **Kaydet / Farklı Kaydet… / Kaydetmeden kapat / Vazgeç** sorusu.
      Vazgeç → sekme açık kalır. Kaydet → kaydedip kapatır.
- [ ] Kaydedilmemiş değişiklikle pencereyi kapatın (sağ üst ×) → aynı soru her kaydedilmemiş sekme için gelir.
- [ ] Kaydedilmemiş değişiklik varken uygulamayı **Görev Yöneticisi**'nden sonlandırın, yeniden açın → belge
      kurtarılmak üzere önerilir ve değişiklikler geri gelir.

## 5. Düzenleme

- [ ] Metni düzenle: Türkçe harfli bir satırı değiştirin (ğ, ş, ı, İ) → doğru yazı tipiyle, kutu kutu değil.
- [ ] Metin ekle, beyaz kutu, vurgula, not ekle, yer imi ekle → hepsi çalışır; Geri al / Yinele (Ctrl+Z / Ctrl+Shift+Z).
- [ ] İmza ve kaşe: çizerek / resimden imza ekleyin; kapatıp açınca imza hatırlanır.
- [ ] Form alanı olan bir PDF'i doldurup kaydedin → başka bir PDF okuyucuda değerler görünür.
- [ ] KVKK karartma: kişisel verileri bul, karart, kaydet → karartılan yazı seçilemez / kopyalanamaz.
- [ ] E-imzalı bir PDF açın → araç çubuğunda yeşil “e-imzalı” rozeti. Not ekleyip kaydedin → e-imza doğrulaması
      (ör. e-imza programında) hâlâ geçerli. Karartma yapmadan önce imzanın geçersiz olacağı sorulur.

## 6. Araçlar ve dönüştürmeler

- [ ] Word → PDF (Word kuruluysa) → PDF oluşur; ilk seferde Word arka planda açılıp kapanabilir.
- [ ] PDF → Word → `.docx` Word'de düzgün açılır.
- [ ] Excel → PDF (Excel ya da LibreOffice varsa), PDF → Excel → tablolar sütunlarıyla gelir.
- [ ] PDF → UDF ve UDF → PDF → UYAP Doküman Editörü'nde açılır.
- [ ] Resimden PDF: JPG, PNG ve **iPhone fotoğrafı (HEIC)** → PDF oluşur.
- [ ] Metin tanıma (OCR): taranmış bir sayfada → Türkçe yazı tanınır, sonra aranabilir. Türkçe dil bileşeni yoksa
      uygulama nasıl yükleneceğini söyler.
- [ ] Birleştir, böl, sıkıştır, sayfa no / ek no, filigran, şifrele / şifre kaldır, karşılaştır → her biri sonuç verir.
- [ ] Birden çok çıktıyı bir klasöre kaydet → klasör seçme penceresi açılır, dosyalar oraya yazılır.

## 7. Yazdırma, paylaşma, sorun bildirme, kılavuz

- [ ] Yazdır (Ctrl+P) → PDF ayrı pencerede açılır, Windows'un yazdırma penceresi gelir.
- [ ] **Paylaş** → dosya panoya kopyalanır; Dosya Gezgini'ne, Outlook iletisine ya da UYAP'a Ctrl+V ile yapıştırılır.
- [ ] **Klasörde göster** → Dosya Gezgini'nde dosya seçili açılır.
- [ ] **Sorun bildir** → Outlook (ya da varsayılan e-posta programı) raporu ekli yeni ileti açar; yoksa e-posta adresi ve
      rapor dosyası gösterilir. İletiyi **göndermeyin**, yalnızca açıldığını görün.
- [ ] **Kullanım Kılavuzu › PDF olarak kaydet** → kılavuzda kısayollar Ctrl / Shift ile, “Finder” yerine
      “Dosya Gezgini” yazıyor; içindekiler bağlantıları çalışıyor.

## 8. Güncelleme

- [ ] **Ayarlar › Güncelleme**: yüklü sürüm görünüyor; **Denetle** → “güncel” ya da yeni sürüm bilgisi (internet gerekir).
- [ ] (İkinci bir sürüm yayımlandığında) sekme çubuğunda **Güncelleme hazır** → **İndir ve kur** → indirilir,
      doğrulanır, kurulum açılır; kurulum sonrası yeni sürüm açılır, ayarlar ve imzalar yerinde.
- [ ] Kaydedilmemiş değişiklik varken **İndir ve kur** → önce kaydetmeniz istenir.

## 9. Kaldırma

- [ ] **Ayarlar › Uygulamalar › Koç PDF Pro › Kaldır** → uygulama açıksa kapatılacağı sorulur; kaldırılınca kısayollar
      ve “Birlikte aç” seçeneği gider.
- [ ] `%LOCALAPPDATA%\KocPDFPro` klasörü (ayarlar, yedekler, günlük) kalır; yeniden kurulunca ayarlar geri gelir.

## Sonuç

- Denenen sürüm (Ayarlar › Güncelleme › Yüklü sürüm): ……………
- Sorunlu satırlar ve notlar:
