# Changelog

## [0.4.3] — 2026-11-22

### Yeni Özellikler & Geliştirmeler
- **Bilgisayara Dışa Sürükle-Bırak (Native Drag-and-Drop to Explorer/Desktop):** Hearth içerisindeki dosya kartları veya satırları doğrudan masaüstüne, Windows Gezgini klasörlerine veya diğer uygulamalara (tarayıcı, mesajlaşma, ofis vb.) sürüklenip bırakılabilir. Birden fazla dosya seçiliyse tüm seçilen dosyalar birlikte taşınır/kopyalanır.
- **Daha Kompakt Dosya Kutuları (Refined Box Sizing):** Dosya grid kartları bir tık küçültüldü (150px yükseklikten 132px'e; simge ve metin oranları dengelendi). Ekranda daha fazla dosya net ve ferah bir şekilde görüntülenebiliyor.
- **Açılış Siyah Ekranının Düzeltilmesi (Instant Warm Splash & Performance):** Uygulama açılırken oluşan siyah ekranda bekleme sorunu giderildi. Başlangıç arka plan rengi `#101113` ile eşitlendi, HTML `<head>` içine anında render olan sıcak Hearth logolu animasyonlu karşılama ekranı (`app-splash`) eklendi ve kütüphane/durum yükleme işlemlerinde bağımlılık metadata okumaları önbelleğe alınarak açılış süresi hızlandırıldı.
- **Gelişmiş Animasyonlar & Efektler:**
  - Sürüklenen dosya kartı için sıcak altın ışıltılı yükselme efekti (`.dragging` aura).
  - Yenile butonu tıklandığında pürüzsüz 360° dönüş mikro-animasyonu (`spin-refresh`).
  - Açılış logosunda yumuşak köz nabzı (`splash-pulse`) ve lineer ilerleme çubuğu efekti.
  - Seçim noktası ve durum göstergesi için ince nefes alma animasyonu (`selection-dot-pulse`).
  - Bildirimler için yaylanmalı yumuşak açılış geçişi (`toast-in-spring`).
  - Tüm animasyonlar sistem erişilebilirlik tercihlerine (`reduced-motion`) tam uyumludur.
- **Gelişmiş Pano Desteği:** Dosya kopyalama işlemi Windows panosuyla entegre edilerek `Ctrl+V` ile Gezgin'e yapıştırma imkanı sağlandı.

### Teknik
- 19 birim testi — tamamı geçiyor.
- PyInstaller 6.22.3, Python 3.12.3 ile derlendi.
- Inno Setup 7.1.1 ile paketlendi (LZMA2 katı sıkıştırma).

## Çıktı Dosyaları
| Dosya | Boyut |
|-------|-------|
| `dist/Hearth-0.4.3-Portable.zip` | 25.4 MB |
| `dist/installer/Hearth-0.4.3-Setup.exe` | 20.9 MB |

## [0.4.2] — 2026-11-22

### Hata Düzeltmeleri
- **Tanıtım ekranı (intro) düzeltildi:** İlk kurulumda ve Portable sürümde açılmıyordu. `setDensity` fonksiyonu tanımlı olmadığından `loadState(true)` içinde `ReferenceError` fırlatılıyordu; `catch` bloğuna düşen hata `setTimeout(introDialog, 350)` satırının hiç çalışmamasına sebep oluyordu. Fonksiyon yazılarak düzeltildi.
- **Portable mod:** `portable.dat`, `data/` veya `.portable` dosyası varlığı ya da `HEARTH_PORTABLE=1` ortam değişkeni ile gerçek taşınabilir mod etkinleşiyor; uygulama verisi yürütülebilir dosyanın yanına yazılıyor.

### Yeni Özellikler
- **Günün Anıları (On This Day / Time Capsule):** Geçmiş yıllarda bugünün takvim gününde oluşturulan dosyaları listeler. Kenar çubuğunda ayrı kategori ve sayaç; `on:today` / `on:thisday` arama filtresi desteklenir.
- **Dosya Karşılaştırma (Side-by-Side Compare):** 2 dosya seçildiğinde araç çubuğunda ve sağ tık menüsünde "Karşılaştır" butonu aktifleşir. SHA-256 karma eşleşmesi, boyut, tarih ve metin snippet karşılaştırması ile yan yana görüntüleme.
- **QuickLook (Hızlı Bakış):** Dosyaya odaklanıp `Space` tuşuna basınca anlık önizleme modalı açılır. `← →` ile önceki/sonraki dosyaya geçilir, `Escape` veya tekrar `Space` ile kapatılır.

### Animasyonlar & Efektler
- Dosya kartı hover: `translateY(-2px)` yükselme + ısı gölgesi; `:active` ile hafif `scale(0.98)` geri bildirimi.
- QuickLook modal açılış animasyonu (`quicklook-pop` keyframe).
- Karşılaştırma grid: eşleşen / farklı içerik badge animasyonu.
- Carousel slide geçişi (`slide-in-smooth`) pürüzsüzleştirildi.

### Teknik
- 18 birim testi — tamamı geçiyor.
- PyInstaller 6.22.3, Python 3.12.3 ile derlendi.
- Inno Setup 7.1.1 ile paketlendi (LZMA2 sıkıştırma).

## Çıktı Dosyaları
| Dosya | Boyut |
|-------|-------|
| `dist/Hearth-0.4.2-Portable.zip` | 25.4 MB |
| `dist/installer/Hearth-0.4.2-Setup.exe` | 20.9 MB |
