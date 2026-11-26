# Kayıttan sonraki ilk arama

26 Kasım 2026’da aynı kayıt ve iki arama, aynı OpenClaw ve SDK sürümleriyle iki kez çalıştırıldı. Koşul `flush.execute-finalize.boundaries` açık. Son doğrulanmış puana katkı **+0**.

Notun ilk satırında “obsoletekiwi” vardı. Altına “freshmangosteen” yazıldı. Dosya içeriği, kaydın kaynağı, başarılı tamamlama işareti ve arama dizini güncellendikten sonraki sonuçlar iki sistemde de aynıydı. Fark, güncellemenin bittiği an ile iki arama arasındaki sıradaydı.

| Arama dizini ayrıca güncellenmeden önce | “obsoletekiwi” araması | “freshmangosteen” araması |
| --- | --- | --- |
| OpenClaw, birinci çalıştırma | Sonuç yok | Güncel not |
| OpenClaw, aynı örneğin ikinci çalıştırması | Notun eski hâli | Sonuç yok |
| SDK, örneğin kullandığı varsayılan HostKit, iki çalıştırma | Güncel not | Güncel not |

Ayrı bir küçük denemede SDK’nın arama sırasında güncellenen yönetilen HostKit'i kullanıldı. Gerçek arka plan güncellemesini iki sistemde de aramaların sonuna dek beklettik. İkisi de önce eski notu, güncelleme tamamlanınca yeni notu gösterdi. Karşılaştırılan yanıtın tüm alanları eşleşti. Bu deneme ayrı bir SDK çalışma ayarı kullanıyor. İlk tablodaki varsayılan davranış ve özgün karşılaştırma geçerliliğini koruyor.

[Özgün yanıtlar, işlem sırası ve doğrulama özetleri](flush-observations.json)
