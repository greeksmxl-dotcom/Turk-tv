# Hisense VIDAA için Türk TV M3U

## Kurulum
1. GitHub'da **public** yeni bir depo oluşturun (ör. `turk-tv`).
2. ZIP içindeki dosya ve `.github/workflows/kontrol.yml` klasörünü depoya yükleyin. Gizli `.github` klasörünün de yüklendiğinden emin olun.
3. Depo Settings → Actions → General → Workflow permissions: **Read and write permissions** seçin.
4. Actions sekmesinde **IPTV yayın kontrolü** → **Run workflow** ile ilk kontrolü başlatın.
5. SS IPTV → Harici Oynatma Listeleri → Kaynak alanına aşağıdaki URL'yi, USERNAME yerine GitHub kullanıcı adınızı yazarak girin:

`https://raw.githubusercontent.com/USERNAME/turk-tv/main/turk-tv.m3u`

## Çalışma şekli
- Her 12 saatte HLS listeleri kontrol edilir; sonuçlar `kontrol-raporu.md` dosyasına yazılır.
- Kanal sırası, adları ve logoları korunur.
- Hatalı yanıt alan kanallar **otomatik silinmez**; coğrafi kısıtlamalar ve geçici hatalar olabilir.
- Yayın adresi değiştiğinde `kaynak.m3u` dosyasındaki adresi güncelleyin. Sonraki çalışmada `turk-tv.m3u` güncellenir.
- Bu sürüm **otomatik bağlantı onarma** içermez; yalnızca kontrol ve yayınlama yapar.
- GitHub zamanlanmış işler gecikebilir veya uzun süre etkinlik olmayan public depolarda durdurulabilir.
