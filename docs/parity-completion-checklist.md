# OpenClaw bellek eşdeğerliği: bitiş ve ilerleme takibi

**Durum: tamamlanmadı. Son güncelleme: 26 Kasım 2026.**

Hedef, sabitlenmiş **OpenClaw v2026.9.9 bellek sözleşmesi** için eşdeğerliktir.
Bu sayfa mevcut [ana planın bitiş şartlarını](full-equivalence-checklist.md#5-completion-evidence-and-release-decision)
izler; yeni kabul koşulu veya puan eklemez. **128/128 tek başına bitiş değildir.**

## Şimdi neredeyiz?

**122/128 koşul doğrulandı. Bu çalışmada +3, kalan 6.** `bb40b5c` sürümünde önceki 119 koşulun tamamı yeniden geçti. Dört eski karşılaştırma farkı kapandı. [Genel karşılaştırma](https://github.com/DorukhanArslan/memory-core/actions/runs/45840190038) · [Bağımsız sayım](https://github.com/DorukhanArslan/memory-core/blob/45ac3284219ac82bcec99353c5d5b896bdbae5d7/independent-review/remaining-memory-conditions/README.md)

| Kapanan koşul | Kullanıcı ne görür? | Eşleşme |
| --- | --- | ---: |
| Başlangıç dosyaları · `prompt.bootstrap-discovery.boundaries` | Yeni sohbet varsayılan altı dosyayı kullanır. OpenClaw eski kurulumu onardığında SDK aynı tamamlanma tarihini okur. Ek tercih dosyası isteyenler `EXTENDED_WORKSPACE_LAYOUT` seçebilir. | 11/11 |
| Kalıcı belleğe aday notlar · `promotion.ranking-gates.boundaries` | Kaynağı bozuk bir not önizlemede görülebilir. Kalıcı belleğe yazmak için kaynak ayrıca doğrulanır. | 16/16 |
| Sohbet arşivleri · `sessions.transcript-filtering.boundaries` | OpenClaw uyumluluk modunda, sıkıştırılmış arşiv aynı boyutta ve aynı milisaniyede değiştirilirse eski metin okunur. Değişiklik zamanı ilerleyince yeni metin görünür. | 9/9 |

| Gösterge | Doğrulanmış durum | Bitiş hedefi |
| --- | --- | --- |
| Kabul koşulları | **122/128**, **6 açık** | 128/128 |
| Henüz karşılaştırmayla kapsanmayan koşullar | 6 | 0 |
| Karşılaştırması olan fakat kapanmayan koşullar | 0 | 0 |
| Başlıklar | 58 tamam, 6 kısmi, 0 bekliyor | 64 tamam |
| Son tam koşudaki örnekler | 1.659 eşleşti / 1.663 | Kapsamdaki tüm kayıtlı örnekler eşleşmeli |
| Kayıtlı karşılaştırma farkları | **4 açık** | 0 açık fark |
| Engellenen örnekler / koşu hataları | 0 / 0 | 0 / 0 |
| Tam eşdeğerlik kapısı | Geçmedi (`fullScopePassed: false`, çıkış kodu 1) | `fullScopePassed: true`, çıkış kodu 0 |

**23 Kasım’da 118 → 119 (+1).** Denemede bir nota yeni bir kelime eklendi ve arama listesi güncellenirken hata oluştu. Bu kelime hemen arandığında iki sistem de boş sonuç verdi ve listenin güncel olmayabileceğini bildirdi. Güncelleme bitince ikisi de notu buldu. `fc4aad3` sürümünde sekiz arama örneği ile takip notlarını taşıma ve saklamayı kapsayan 39 örneğin tamamı eşleşti. [Genel karşılaştırma](https://github.com/DorukhanArslan/memory-core/actions/runs/45153594838) · [PR #32](https://github.com/DorukhanArslan/memory-core/pull/32) · [Bağımsız sayım](https://github.com/DorukhanArslan/memory-core/blob/9430a2cb23a6660f281adbeadb0fb1b926687fa4/independent-review/search-retry/README.md)

**84 → 118, toplam +34 koşul.** Önceki 84 koşulun tamamı yeniden geçti ve yedi eski fark kapandı. Ölçülen ürün `160c7c2`, SDK dosyası sayısı 183. İlk değerlendirme bir dosya yolunda durdu. Arşiv incelemesi, açık kalan F14 örneğinde aynı zaman damgasının iki farklı sayı yazımıyla kaydedildiğini işaretledi. Bağımsız inceleme iki SDK sürümünün de boş aday listesi döndürdüğünü doğruladı. O ölçümde F14 açık kaldı. [118/128 kabul kaydı](https://github.com/DorukhanArslan/memory-core/blob/34b52d79f6082e061b8f1ce47a6ca27d407fb391/independent-review/README.md) · [Genel koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/44214324963) · [Arşiv incelemesi](https://github.com/DorukhanArslan/memory-core/actions/runs/44232754070/artifacts/14396301086)

**18 Kasım'daki ilk genel karşılaştırma puanı değiştirmedi.** Eksik araç
sonuçlarının onarılması 8/8, sayı sınırları 4/4, birleştirilen notların içeriği
ve kaynağı 7/7 örnekte eşleşti. Toplam 1.519 örneğin 1.495'i eşleşti, 14 eski
fark görüldü ve daha önce geçen 10 sohbet örneğinde kanıt doğrulaması durdu.
Koşu çıkış kodu 2 ile bitti. Sorun, yeni bir sohbet seçeneğinin eski
senaryolarda kapalı olduğunu denetleyen satırın eksik olmasıydı. O koşuda puan **84/128** olarak kaldı.
[Genel karşılaştırma](https://github.com/DorukhanArslan/memory-core/actions/runs/44189169478) · [PR #30](https://github.com/DorukhanArslan/memory-core/pull/30)

**18 Kasım tarihli önceki çalışma planı.** Yukarıdaki 19 örnek altı
koşulu kapsıyor. Aşağıdaki 73 örnek kendi karşılaştırmalarında geçti ve 18
koşulu kapsıyor. İkinci genel koşu bu hedefi ölçemeden durdu. [Koşu kaydı](https://github.com/DorukhanArslan/memory-core/actions/runs/44206756377)

| İş | İki sistemde denenen örnek | Eşleşme | Hedef artış |
| --- | --- | ---: | ---: |
| Günlük not seçimi | Aynı bilgiyi grupla ve silinen notu sonraki taramada ele | 7/7 | +2 |
| Rüya günlüğü | Yeniden tararken günlüğün kendi yorumlarını kaynak olarak alma | 8/8 | +2 |
| Günlükte alıntı ve kaynak | Kaynak ya da önceki alıntı yazım sırasında silinirse girdiyi yayımlama | 7/7 | +2 |
| Notların birlikte değerlendirilmesi | Kalıcı notu kaydet, günlük yazımı başarısız olursa iki sonucu ayrı bildir | 7/7 | +2 |
| Zamanlanmış görevin sınırları | Zamanı gelince güncel notu oku ve yeniden başlatınca aynı işi tekrarlama | 1/1, yedi adım | +1 |
| Zamanlanmış görevin sonucu | Başarısız denemeyi, yeniden deneme zamanını ve görevin geri yüklenmesini karşılaştır | 3/3 | +1 |
| Otomatik yoklama | Normal konuşma not yazabilir. Otomatik yoklama yazmaz ve sonradan anı diye listelenmez | 4/4 | +1 |
| Otomatik bildirimin teslimi | Aynı uyarıyı iki kez gönderme. Sessiz saatte bekle ve yeni uyarıyı izin verilen hedefe ilet | 4/4 | +1 |
| Ortak nota yazma | İkinci yazar beklesin ve kapanan yazarın kilidi süre dolunca devralınsın | 7/7 | +2 |
| Sohbeti yeniden açma | Son araç cevabı ve sohbet özeti, açılan sohbetin ilk model isteğine doğru sırayla girsin | 3/3 | +1 |
| Bozuk bellek kaydını onarma | Bozulmuş arama kaydını düzelt. İkinci onarımda sağlam kaydı koru | 9/9 | +2 |
| Notun kaydedileceği yeri seçme | Gün değiştiğinde doğru tarihli dosyayı seç. Hedef hazırlanamazsa modele istek gönderme | 13/13 | +1 |

## Kalan 6 iş

Her satır doğrulandığında **+1** getirir. Altı koşul için de kayıtlı örnekler puan vermeye yetmiyor. Ayrı denemeler aşağıdaki farkları gösterdi. Süreler, ilgili davranış üzerinde karar alındıktan sonraki tahmini uygulama ve doğrulama emeğidir. [64 başlığın durumu](full-equivalence-checklist.md#4-implement-and-verify-the-fixed-memory-behavior-contract)

| İş | Örnek ve kapanması için gereken | Tahmini emek |
| --- | --- | ---: |
| **Yeni notu hemen bulmak** · `flush.execute-finalize.boundaries` | Aynı notta ilk arama OpenClaw’ın iki çalıştırmasında farklı sonuç verdi. Varsayılan SDK hemen güncel metni buldu. İlk aramanın hangi güncellemeyi bekleyeceği ortak bir kurala bağlanmalı. | 2–4 gün |
| **Aynı adlı iki sohbet notu** · `sessions.reset-hook.outcomes` | Aynı dakikada kapanan iki sohbet için v2026.9.9 tek not bıraktı. SDK ikisini sakladı. Yeni sürümlerde doğrulanan çözüm aşağıda ayrı hedef olarak izleniyor. | Yeni sürüm araştırması tamamlandı. Sabit sürüm için süre verilemiyor. |
| **Günlük not dosyasını açmak** · `flush.plan-target.boundaries` | İki ad aynı fiziksel notu gösterdiğinde OpenClaw modeli çağırdı, SDK hazırlıkta durdu. Yazma güvenliğini koruyan ortak bir dosya açma kuralı gerekiyor. | 2–4 gün |
| **Aynı araç cevabındaki gizli bilgiyi temizlemek** · `trust.secret-redaction.outcomes` | Ekranda görünen metin aynı. OpenClaw aynı ham cevap için önceki temiz kopyayı geri veriyor. SDK yeni kopya üretiyor. Ham parolanın saklanma süresini uzatmadan aynı davranış sağlanmalı. | 2–5 gün |
| **Kesilen takip notu taşıması** · `heartbeat.scratch.boundaries` | Onarılan notun hangi çalışma alanından geldiği eski kayıttan belirlenemiyor. SDK’nın doğru depoyu tanıyıp o depoda çalışan onarımı önermesi gerekiyor. | 1–3 gün |
| **Kesintiden sonra sıradaki mesaj** · `recovery.failure-publication.boundaries` | Not yazıldıktan hemen sonra süreç kapandı. OpenClaw yeni isteği kabul etti. SDK mevcut dosya için onay istedi. Başarı kaydı eksikken hangi isteğin başlayabileceği belirlenmeli. | 3–6 gün |

[İlk arama denemeleri](https://github.com/DorukhanArslan/memory-core/blob/3a287e8725b016b5d15e14df38629fc6d9829b26/independent-review/remaining-memory-conditions/flush-review.md) · [Gizli bilgi denemesi](https://github.com/DorukhanArslan/memory-core/blob/3a287e8725b016b5d15e14df38629fc6d9829b26/independent-review/remaining-memory-conditions/redaction-input-identity.json) · [Diğer dört davranışın ölçümü](https://github.com/DorukhanArslan/memory-core/blob/3a287e8725b016b5d15e14df38629fc6d9829b26/independent-review/remaining-memory-conditions/four-point-review.md)

## Ayrı sürüm araştırması · Aynı anda kapanan iki sohbet

26 Kasım 2026’da iki farklı sohbeti aynı çalışma alanında aynı dakika içinde kapattık. İkisi de not için aynı dosya adını istedi. Sonunda diskte kalan dosyaları açıp her birinin hangi sohbetin metnini içerdiğini kontrol ettik.

| Sürüm | Diskte kalan not | İçerik kontrolü |
| --- | ---: | --- |
| OpenClaw v2026.9.9 · ana hedef | 1 | İki sohbetin metinlerinden yalnızca biri kaldı. |
| OpenClaw v2026.9.35 | 2 | Her iki metin de SDK’nın sakladığı karşılığıyla bayt bayt eşleşti. |
| OpenClaw v2026.11.10 | 2 | İkinci sohbet sonuna `-2` eklenen bir dosyaya yazıldı. Her iki metin de SDK ile eşleşti. |

Bu davranış için doğrulanmış güncel hedef **v2026.11.10**. Deneme iki OpenClaw sohbetinin aynı anda kapanmasını kapsıyor. Ana kontrol listesi v2026.9.9 sürümünü ölçüyor ve bu sürümde `sessions.reset-hook.outcomes` açık. [Ölçüm kaydı](https://github.com/DorukhanArslan/memory-core/blob/3a287e8725b016b5d15e14df38629fc6d9829b26/independent-review/remaining-memory-conditions/reset-release-research.md) · [v2026.11.10 dosya seçimi ve yazımı](https://github.com/openclaw/openclaw/blob/6ea542fd97e2876aa4c871ccc494ed5419a03c5c/src/hooks/bundled/session-memory/handler.ts#L338)

## “Tamamlandı” diyebilmek için

İşaretler, yanındaki kanıtla kapanır. Bu kutular ayrı bir yüzde veya puan değildir.

- [x] **B1 — Hedef sabit.** Sürüm, 64 başlık ve 128 koşul tanımlı.
  Referans: `bcfc88812a35243893585dbeca87ca41b48272ca`;
  [sabit kapsam](../equivalence/scope.json). Sonraki OpenClaw sürümleri bu iddiaya dahil değil.
- [ ] **B2 — 128 koşulun tamamı doğrulandı.** Şimdi 122/128.
  Kalan 6 koşul mevcut başlıkları altında kapanmalı; yalnızca kodun mevcut
  olması veya bir yardımcı fonksiyonun geçmesi yeterli değil.
- [ ] **B3 — Kayıtlı açık fark kalmadı.** Aşağıda 4 açık fark izleniyor.
  Puansız olması bir farkı çözülmüş yapmaz. Başarısız örnekler silinerek,
  çıktının alanları atılarak veya kurallar gevşetilerek bu kutu kapatılamaz.
- [ ] **B4 — Kapsam ve çalışma modları denetlendi.** Tüm 64 başlıktaki sınır
  notları, doğrulanan modlarla karşılaştırılmalı. İddianın içindeki ertelenmiş
  davranışlar kapanmalı; aşağıdaki bilinen açıklar bu denetimin başlangıcıdır.
- [ ] **B5 — Mevcut bütünleşik host senaryoları son sürümde doğrulandı.**
  Kaydetme, hemen hatırlama, güncelleme, yeni sohbet, yeniden başlatma,
  kullanıcı/çalışma alanı ayrımı ve gerçek hata akışları aynı son kaynakta geçmeli.
  Bunlar mevcut host sözleşmeleridir; yeni puan kalemleri değildir.
  26 Kasım ölçümünde önceki host kanıtları yeniden geçti. Nihai kaynak sürümü 128 koşul tamamlandığında belirlenecek.
- [ ] **B6 — Paket ve kullanım kontrolleri son sürümde geçti.** İddia edilen
  Python sürümleri, dağıtım paketleri ve temiz kurulumdan SDK kullanan örnekler
  için [mevcut yayın kontrolleri](release.md) tamamlanmalı.
  Ölçülen `160c7c2` paketini Linux x86-64 üzerinde temiz Python 3.11.16 ve 3.12.14 ortamlarına kurduk. İkisinde de Unicode dosya adıyla arama ve kullanıcı tanımlı gizleme kuralı çalıştı. Kaynak dağıtımı ve nihai yayın kontrolleri açık.
- [ ] **B7 — Tek, ortak nihai kanıt var.** Aynı referans, kapsam ve SDK kaynağı
  üzerinde 128/128, sıfır fark/engel/hata/atlanan zorunlu örnek ve gerçek
  depolama/yaşam döngüsü kanıtı birlikte bulunmalı. Tam kapı geçmeli;
  farklı sürümlerin iyi sonuçlarını birleştirmek yeterli değil.
- [ ] **B8 — Bağımsız son kontrol ve main doğrulaması yapıldı.** Raporun tamamı,
  kaynak kimlikleri ve kapsam sınırları bağımsızca kontrol edilmeli; main'deki
  SDK ölçülen SDK ile aynı olmalı. Komutlar, rapor ve kapanış notları yeniden
  üretilebilir olmalı. `bb40b5c` sürümünde 122/128 koşul bağımsızca doğrulandı.
  Nihai inceleme, 128 koşul tamamlandığında yapılacak.

## Puanın dışında kaybolmaması gereken bilinen sınırlar

B4 kapanmadan bu tablo eksiksiz bir kapsam envanteri sayılmaz. Her satırın
mevcut sözleşmeye, desteklenen çalışma moduna ve kanıtına bağlanması gerekir.
Sınırsız bütün platform/sağlayıcı/zamanlama olasılıkları için yeni bir vaat eklenmez.

| Takip | Basit örnek ve kapanacak konu | Mevcut kanıt / ilgili sözleşmeler |
| --- | --- | --- |
| K1 — Arama modları | Aynı not farklı arama altyapısında da doğru sırada bulunsun. CPU dışı hızlandırılmış arama, ICU/trigram ve Unicode dosya adı sırası için mevcut sınırlar denetlenecek. | [Arama koşulları](full-equivalence-checklist.md#retrieval-and-ranking); `retrieval.*`, `engine.unicode-collation` |
| K2 — Sağlayıcı ve indeks yayını | Bir not kaydedilirken değişirse hangi sürümün yayımlandığı ve aramada görüldüğü tutarlı olsun. Mevcut kanıtların bazıları sağlayıcısız veya kontrollü sağlayıcı profiline ait. Native'in yayımlayıp SDK'nın reddettiği gerçek akış açıkça kayıtlı. | [Cache sınırları](embedding_cache_lifecycle_closeout.md#compared-boundary); `indexing.*`, `tools.*`, `recovery.*` |
| K3 — Sıfırlama ve host modları | Arka arkaya ve eşzamanlı işlemler, otomatik sıfırlama, özel sohbet ve desteklenecek adlandırma/host akışları mevcut sınırlarıyla denetlensin. Sıralı manuel reset kanıtı hepsini tamamlamaz. | [Açık reset kapsamı](session_reset_boundaries_closeout.md#remaining-scope); `sessions.reset-hook`, `host.*`, `concurrency.*` |
| K4 — Diğer başlıkların sınırları | Gizleme kuralları, tarih/sayı sınırları, arşivler, başlangıç dosyaları ve bakım akışlarında “yalnızca şu profilde” notları mevcut 64 başlık üzerinden taransın. Runtime kanıtı sıralı, manuel ve özel olmayan sohbetlere, sağlayıcının verdiği `responseId` değerine ve 1–9999 takvim yıllarına bağlıdır; UUID fallback yolu ve modelin talimata uyma başarısı doğrulanmadı. İlgisiz persona ve araç kayıtları ham olarak tutuldu, karşılaştırılmadı. | [Runtime kapsam sınırları](prompt_runtime_context_closeout.md#remaining-scope), [ana plan](full-equivalence-checklist.md), [kaynak haritası](equivalence-source-map.md) ve ilgili kapanış notları |

## Karşılaştırma farkları (4 açık)

Her satır ancak aynı gerçek davranış tekrar karşılaştırılıp eşleştiğinde ve
kanıt bağlantısı eklendiğinde işaretlenir. Burada sadece son raporun kimlik ve
durum bilgisi listelenir; bekletilen eski rapor incelemeleri yeniden başlatılmadı.

- [x] **F01 — Unicode dosya adlarının sırası:** `hybrid-unicode-path-collation-diagnostic`. [Doğrulayan koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/44214324963)
- [x] **F02 — Yeniden yazılan sıkıştırılmış konuşmayı okuma:** `transcript-boundary-compressed-same-size-mtime-cache-diagnostic`. [Doğrulayan koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/45840190038)
- [ ] **F03 — Kayıttan sonraki ilk arama:** `flush-execution-warm-index-first-recall`.
- [x] **F04 — Karışık büyük/küçük i içeren gizleme kuralı:** `redaction-policy-letter-mixed-i-engine-diagnostic`. [Doğrulayan koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/44214324963)
- [x] **F05 — Tekrarlanan gruplu gizleme kuralı:** `redaction-policy-letter-repeated-capture-engine-diagnostic`. [Doğrulayan koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/44214324963)
- [x] **F06 — Gelişmiş karakter sınıflarıyla gizleme:** `redaction-policy-unsupported-valid-general-property`. [Doğrulayan koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/44214324963)
- [x] **F07 — Gelişmiş gizleme kuralının derlenmesi:** `redaction-policy-unsupported-valid-v-direct-compiler`. [Doğrulayan koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/44214324963)
- [ ] **F08 — Model aracının tam cevabı:** `model-tool-complete-tool-result`.
- [ ] **F09 — Gizleme ve metni kısaltma sırası:** `model-tool-utf16-redaction-truncation-order`.
- [x] **F10 — Sohbet içinde karışık i ile gizleme:** `model-session-configured-letter-mixed-i-engine-diagnostic`. [Doğrulayan koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/44214324963)
- [x] **F11 — Sohbet içinde gruplu gizleme:** `model-session-configured-letter-capture-reset-engine-diagnostic`. [Doğrulayan koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/44214324963)
- [x] **F12 — Başlangıçta bellek dosyalarını seçme:** `bootstrap-discovery-memory-core-layout-extension`. [Doğrulayan koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/45840190038)
- [x] **F13 — Eski çalışma alanında başlangıç seçimi:** `bootstrap-discovery-legacy-state-gate`. [Doğrulayan koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/45840190038)
- [x] **F14 — Kaynağın güven bilgisini değerlendirme:** `promotion-ranking-primitive-provenance-safety-diagnostic`. [Doğrulayan koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/45840190038)
- [ ] **F15 — Eski tarih yazımını okuma** `engine-datetime-unverified-legacy-grammar`.
  OpenClaw bir girdiyi tarih olarak okudu. SDK kaydın zamanını kullandı. [Ölçülen fark](https://github.com/DorukhanArslan/memory-core/actions/runs/44214324963)

- [x] **F16 — Arama hatasından sonra yeniden deneme** · `query-sync-boundaries-warm-failure-natural-retry`. Güncelleme arama sırasında tamamlansa da ilk yeniden deneme başladığı listedeki sonuçları ve o listenin uyarısını veriyor. Sonraki arama güncellenen notu buluyor. [Önceki fark](https://github.com/DorukhanArslan/memory-core/blob/5bd9ac41dfa66b7732a6898b6a4e02366dd836de/independent-review/heartbeat-home/query-retry-difference.json) · [Doğrulayan koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/45153594838)

Bir fark bilinçli SDK davranışı veya Python'a özel bir ek olabilir. Gerekçesi
açıkça kaydedilmeli. **“Kapsam dışı” demek onu eşleşmiş yapmaz.** İddianın
daraltılması kullanıcı onayı ve sürümlenmiş kapsam kararı gerektirir;
başarısız geçmiş kanıtlar korunur ve eski puanlar yeniden etiketlenmez.

## Nasıl güncellenecek?

Her uygulama paketi sonunda bu sayfa, ana checklist ve ilgili kapanış notu
aynı kanıta göre birlikte güncellenir:

1. Önce/sonra puan ve gerçek artış; eşleşen/farklı/engellenen örnek sayıları yazılır.
2. Kapanan **koşul kimlikleri** ve varsa **F/K/B kimlikleri** kanıtla bağlanır.
3. Eski puanların korunduğu ve main'deki SDK'nın ölçülen kaynakla aynı olduğu doğrulanır.
4. Sonraki iş basit bir örnek, hedef puan artışı ve süre tahminiyle sunulur;
   yeni uygulama kullanıcının onayından sonra başlar.

Yeni kanıt eski bir kapanışı geçersiz kılarsa ilgili durum yeniden açılır;
puan değişimi ve nedeni saklanmaz. Eski rapor kendi kaynak kimliğiyle korunur.

| Güncelleme | Puan değişimi | Kapanan konu | Kanıt |
| --- | --- | --- | --- |
| Başlangıç, aday notlar ve arşivler | 119 → 122, **+3** | F02, F12, F13 ve F14 kapandı. Önceki 119 koşul korundu. | [Genel karşılaştırma](https://github.com/DorukhanArslan/memory-core/actions/runs/45840190038) · [Bağımsız sayım](https://github.com/DorukhanArslan/memory-core/blob/45ac3284219ac82bcec99353c5d5b896bdbae5d7/independent-review/remaining-memory-conditions/README.md) |
| Hatadan sonra ilk arama | 118 → 119, **+1** | Arama yeniden denemesi (F16) kapandı. Taşıma ve saklama korundu (39/39). | [Özet](https://github.com/DorukhanArslan/memory-core/actions/runs/45153594838/artifacts/14820546579) · [Genel karşılaştırma](https://github.com/DorukhanArslan/memory-core/actions/runs/45153594838) · [Bağımsız sayım](https://github.com/DorukhanArslan/memory-core/blob/9430a2cb23a6660f281adbeadb0fb1b926687fa4/independent-review/search-retry/README.md) |
| Eski takip notunun taşınması | 118 → 118, **net 0** | Taşıma +1 (39/39), aramada yeniden deneme −1 | [Genel koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/44927413199) · [Özet](https://github.com/DorukhanArslan/memory-core/actions/runs/44927413199/artifacts/14721834715) · [Önceki bağımsız sayım](https://github.com/DorukhanArslan/memory-core/blob/5bd9ac41dfa66b7732a6898b6a4e02366dd836de/independent-review/heartbeat-home/README.md) |
| Genel bellek karşılaştırması | 84 → 118, **+34** | 1.623 örnek, 8 açık fark | [Genel koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/44214324963), [özet](https://github.com/DorukhanArslan/memory-core/actions/runs/44232754070/artifacts/14396301086) |
| Runtime bağlamının kapanışı | 82 → 84, **+2** | `prompt.runtime-context.outcomes`, `prompt.runtime-context.boundaries` | [PR #29](https://github.com/DorukhanArslan/memory-core/pull/29), [kapanış](prompt_runtime_context_closeout.md) |
| Reset sınırlarının kapanışı | 81 → 82, **+1** | `sessions.reset-hook.boundaries` | [PR #27](https://github.com/DorukhanArslan/memory-core/pull/27), [kapanış](session_reset_boundaries_closeout.md) |
| Bu takip sayfasının eklenmesi | 82 → 82, **+0** | İlerleme görünürlüğü; uygulama koşulu kapanmadı | [Tarihsel 82/128 ölçümü](session_reset_boundaries_closeout.md); yeni test koşusu yapılmadı |

**Korunan başarısız ilk koşu:** [İlk tam koşuda](https://github.com/DorukhanArslan/memory-core/actions/runs/44088814920)
yeni 10 örneğin tamamı eşleşti; eski bir unutma örneğinin kanıt dosyası
reddedildiği için genel doğrulama tamamlanmadı: 1.485 eşleşme, 14 fark,
bir engel ve gerçek çıkış kodu 2. O koşuda doğrulanmış puan **82/128** kaldı;
bu koşuya yeni puan verilmedi. [Kaydedilmiş dosya incelemesi](https://github.com/DorukhanArslan/memory-core/actions/runs/44114457990)
512 MiB sınırının 357.646 bayt aşıldığını doğruladı. Raporun yapısal
boşluklarını kaldıran tek satırlık düzeltme, aynı bilgileri ve aynı boyut
sınırını korudu. Başarısız ilk koşu ve ham kanıtı kendi kimlikleriyle saklanır.
Sonraki kabul edilen koşu yalnızca B2'nin iki koşulunu kapatır;
B2–B8 ve kayıtlı 14 fark açık kalır. Dört eski farkın değer incelemeleri
beklemede kalır; yeni kanıt bu incelemeleri yeniden başlatmadı.

Kalan 6 koşulun bağlı olduğu başlıklar ve doğrulanan koşullar [ana tabloda](full-equivalence-checklist.md#4-implement-and-verify-the-fixed-memory-behavior-contract) izleniyor.

## Bitişte kullanılabilecek ifade

B1–B8 tamamlandığında: **“Sabitlenmiş OpenClaw v2026.9.9 bellek sözleşmesi,
ilan edilen desteklenen çalışma modlarında doğrulandı; açık kapsam-içi fark yok.”**

Bu ifade tüm OpenClaw uygulaması, sonraki sürümler veya hariç tutulan platform
servisleri için garanti değildir. Python'a özel kolaylıklar, özel SQLite
dosyalarının birebir aynı olması ve resmi derlenmiş sürümün kaynak derlemesini
yeniden üretmek, davranış eşdeğerliğine ek puan veya gizli bitiş borcu değildir.
