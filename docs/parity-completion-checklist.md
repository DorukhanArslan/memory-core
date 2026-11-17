# OpenClaw bellek eşdeğerliği: bitiş ve ilerleme takibi

**Durum: tamamlanmadı. Son güncelleme: 18 Kasım 2026.**

Hedef, sabitlenmiş **OpenClaw v2026.9.9 bellek sözleşmesi** için eşdeğerliktir.
Bu sayfa mevcut [ana planın bitiş şartlarını](full-equivalence-checklist.md#5-completion-evidence-and-release-decision)
izler; yeni kabul koşulu veya puan eklemez. **128/128 tek başına bitiş değildir.**

## Şimdi neredeyiz?

| Gösterge | Doğrulanmış durum | Bitiş hedefi |
| --- | --- | --- |
| Kabul koşulları | **84/128**; **44 açık** | 128/128 |
| Henüz karşılaştırmayla kapsanmayan koşullar | 42 | 0 |
| Karşılaştırması olan fakat kapanmayan koşullar | 2 | 0 |
| Başlıklar | 39 tamam, 6 kısmi, 19 bekliyor | 64 tamam |
| Son tam koşudaki örnekler | 1.486 eşleşti / 1.500 | Kapsamdaki tüm kayıtlı örnekler eşleşmeli |
| Kayıtlı karşılaştırma farkları | **14 açık** | 0 açık fark |
| Engellenen örnekler / koşu hataları | 0 / 0 | 0 / 0 |
| Tam eşdeğerlik kapısı | Geçmedi; gerçek çıkış kodu 1 | `fullScopePassed: true`, çıkış kodu 0 |

**Devam eden paket (18 Kasım).** Eksik araç sonuçlarının sohbeti bozmadan
onarılması 8/8, sayı sınırları 4/4, birleşen notların önceki içeriği ve
kaynağının korunması 7/7 örnekte eşleşti. **84 → 90** hedefi için bu 19
örnek önceki 1.500 örnekle birlikte çalıştırılıyor.
[Genel karşılaştırma](https://github.com/DorukhanArslan/memory-core/actions/runs/44189169478) · [PR #30](https://github.com/DorukhanArslan/memory-core/pull/30)

**Sonraki paketin hedefi +12 koşul.** Aşağıdaki 40 örnek kendi
karşılaştırmalarında geçti. İki günlük yazma grubunun 14 örneği, değişiklikler
birleştirildikten sonra da birlikte geçti. İlk paket 90'a ulaşırsa bu paketin
hedefi **102/128**. Resmî puan genel karşılaştırmayla güncellenir.

| İş | İki sistemde denenen örnek | Eşleşme | Hedef artış |
| --- | --- | ---: | ---: |
| Günlük not seçimi | Aynı bilgiyi grupla ve silinen notu sonraki taramada ele | 7/7 | +2 |
| Rüya günlüğü | Yeniden tararken günlüğün kendi yorumlarını kaynak olarak alma | 8/8 | +2 |
| Günlükte alıntı ve kaynak | Kaynak ya da önceki alıntı yazım sırasında silinirse girdiyi yayımlama | 7/7 | +2 |
| Notların birlikte değerlendirilmesi | Kalıcı notu kaydet, günlük yazımı başarısız olursa iki sonucu ayrı bildir | 7/7 | +2 |
| Zamanlanmış görevin sınırları | Zamanı gelince güncel notu oku ve yeniden başlatınca aynı işi tekrarlama | 1/1, yedi adım | +1 |
| Zamanlanmış görevin sonucu | Başarısız denemeyi, yeniden deneme zamanını ve görevin geri yüklenmesini karşılaştır | 3/3 | +1 |
| Ortak nota yazma | İkinci yazar beklesin ve kapanan yazarın kilidi süre dolunca devralınsın | 7/7 | +2 |

84/128, kabul koşullarının %65,6'sıdır; harcanan işin veya genel parity'nin
%65,6'sı anlamına gelmez. **44 koşul ve 14 fark toplanmaz:** farklı ölçülerdir.
14 farkın 11'i puana bağlanmamış teşhis örnekleridir (`covers: []`);
kalan üç örnek iki açık koşula bağlıdır. Bu yüzden yalnızca puana bakamayız.

Kanıt: [son tam koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/44137396647),
[84/128 kapanış notu](prompt_runtime_context_closeout.md) ve
[uygulama PR'ı #29](https://github.com/DorukhanArslan/memory-core/pull/29).
Ölçülen ürün kaynağı `907944e`, karşılaştırma kaynağı `a27ec47`;
PR #29 ölçülen 164 dosyalık SDK ağacını içerir. Bağımsız denetimler önceki
82 koşulun korunduğunu ve yalnızca iki özgün runtime-context koşulunun
kapandığını doğruladı. Ayrıntılı 64 başlığın durumu
[ana checklist'te](full-equivalence-checklist.md#4-implement-and-verify-the-fixed-memory-behavior-contract).

## “Tamamlandı” diyebilmek için

İşaretler, yanındaki kanıtla kapanır. Bu kutular ayrı bir yüzde veya puan değildir.

- [x] **B1 — Hedef sabit.** Sürüm, 64 başlık ve 128 koşul tanımlı.
  Referans: `bcfc88812a35243893585dbeca87ca41b48272ca`;
  [sabit kapsam](../equivalence/scope.json). Sonraki OpenClaw sürümleri bu iddiaya dahil değil.
- [ ] **B2 — 128 koşulun tamamı doğrulandı.** Şimdi 84/128.
  Kalan 44 koşul mevcut başlıkları altında kapanmalı; yalnızca kodun mevcut
  olması veya bir yardımcı fonksiyonun geçmesi yeterli değil.
- [ ] **B3 — Kayıtlı açık fark kalmadı.** Şimdi 14 fark var; aşağıda tek tek izleniyor.
  Puansız olması bir farkı çözülmüş yapmaz. Başarısız örnekler silinerek,
  çıktının alanları atılarak veya kurallar gevşetilerek bu kutu kapatılamaz.
- [ ] **B4 — Kapsam ve çalışma modları denetlendi.** Tüm 64 başlıktaki sınır
  notları, doğrulanan modlarla karşılaştırılmalı. İddianın içindeki ertelenmiş
  davranışlar kapanmalı; aşağıdaki bilinen açıklar bu denetimin başlangıcıdır.
- [ ] **B5 — Mevcut bütünleşik host senaryoları son sürümde doğrulandı.**
  Kaydetme, hemen hatırlama, güncelleme, yeni sohbet, yeniden başlatma,
  kullanıcı/çalışma alanı ayrımı ve gerçek hata akışları aynı son kaynakta geçmeli.
  Bunlar mevcut host sözleşmeleridir; yeni puan kalemleri değildir.
  Son 84/128 ölçümünde ilgili host kanıtları geçti; nihai kaynak temeli henüz yok.
- [ ] **B6 — Paket ve kullanım kontrolleri son sürümde geçti.** İddia edilen
  Python sürümleri, dağıtım paketleri ve temiz kurulumdan SDK kullanan örnekler
  için [mevcut yayın kontrolleri](release.md) tamamlanmalı.
  Eski sürümdeki sonuçlar son sürüme aktarılmış sayılmaz.
- [ ] **B7 — Tek, ortak nihai kanıt var.** Aynı referans, kapsam ve SDK kaynağı
  üzerinde 128/128, sıfır fark/engel/hata/atlanan zorunlu örnek ve gerçek
  depolama/yaşam döngüsü kanıtı birlikte bulunmalı. Tam kapı geçmeli;
  farklı sürümlerin iyi sonuçlarını birleştirmek yeterli değil.
- [ ] **B8 — Bağımsız son kontrol ve main doğrulaması yapıldı.** Raporun tamamı,
  kaynak kimlikleri ve kapsam sınırları bağımsızca kontrol edilmeli; main'deki
  SDK ölçülen SDK ile aynı olmalı. Komutlar, rapor ve kapanış notları yeniden
  üretilebilir olmalı. Mevcut 84/128 paketi kendi sınırları için bağımsızca incelendi;
  nihai eşdeğerlik paketi henüz tamamlanmadı.

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

## Açık 14 karşılaştırma farkı

Her satır ancak aynı gerçek davranış tekrar karşılaştırılıp eşleştiğinde ve
kanıt bağlantısı eklendiğinde işaretlenir. Burada sadece son raporun kimlik ve
durum bilgisi listelenir; bekletilen eski rapor incelemeleri yeniden başlatılmadı.

- [ ] **F01 — Unicode dosya adlarının sırası:** `hybrid-unicode-path-collation-diagnostic`.
- [ ] **F02 — Yeniden yazılan sıkıştırılmış konuşmayı okuma:** `transcript-boundary-compressed-same-size-mtime-cache-diagnostic`.
- [ ] **F03 — Kayıttan sonraki ilk arama:** `flush-execution-warm-index-first-recall`.
- [ ] **F04 — Karışık büyük/küçük i içeren gizleme kuralı:** `redaction-policy-letter-mixed-i-engine-diagnostic`.
- [ ] **F05 — Tekrarlanan gruplu gizleme kuralı:** `redaction-policy-letter-repeated-capture-engine-diagnostic`.
- [ ] **F06 — Gelişmiş karakter sınıflarıyla gizleme:** `redaction-policy-unsupported-valid-general-property`.
- [ ] **F07 — Gelişmiş gizleme kuralının derlenmesi:** `redaction-policy-unsupported-valid-v-direct-compiler`.
- [ ] **F08 — Model aracının tam cevabı:** `model-tool-complete-tool-result`.
- [ ] **F09 — Gizleme ve metni kısaltma sırası:** `model-tool-utf16-redaction-truncation-order`.
- [ ] **F10 — Sohbet içinde karışık i ile gizleme:** `model-session-configured-letter-mixed-i-engine-diagnostic`.
- [ ] **F11 — Sohbet içinde gruplu gizleme:** `model-session-configured-letter-capture-reset-engine-diagnostic`.
- [ ] **F12 — Başlangıçta bellek dosyalarını seçme:** `bootstrap-discovery-memory-core-layout-extension`.
- [ ] **F13 — Eski çalışma alanında başlangıç seçimi:** `bootstrap-discovery-legacy-state-gate`.
- [ ] **F14 — Kaynağın güven bilgisini değerlendirme:** `promotion-ranking-primitive-provenance-safety-diagnostic`.

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

Kullanıcı 128 koşula doğru ilerlemeyi onayladı. Sıradaki işler arasında,
zamanı gelen bir bellek görevinin tek kez çalışması ve gün sonu bakımında
güncel bilgilerin seçilmesi var. Puanlar tamamlanan genel karşılaştırmaya
göre işlenir.

## Bitişte kullanılabilecek ifade

B1–B8 tamamlandığında: **“Sabitlenmiş OpenClaw v2026.9.9 bellek sözleşmesi,
ilan edilen desteklenen çalışma modlarında doğrulandı; açık kapsam-içi fark yok.”**

Bu ifade tüm OpenClaw uygulaması, sonraki sürümler veya hariç tutulan platform
servisleri için garanti değildir. Python'a özel kolaylıklar, özel SQLite
dosyalarının birebir aynı olması ve resmi derlenmiş sürümün kaynak derlemesini
yeniden üretmek, davranış eşdeğerliğine ek puan veya gizli bitiş borcu değildir.
