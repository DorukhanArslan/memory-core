# Kesinti sonrasında yeni bir mesajın işlenmesi

**27 Kasım 2026 · 123/128 doğrulandı, +1.** Önceki 122 koşulun tamamı tekrar geçti. Yeni koşul `recovery.failure-publication.boundaries`. SDK, açık OpenClaw uyumluluk seçeneğinde kesilmiş bir yazmayı tekrarlamadan yeni mesaja cevap verebildi. Varsayılan ayar hâlâ onay istiyor. [Bağımsız sayım](independent-45987128881.json) · [GitHub koşusu](https://github.com/DorukhanArslan/memory-core/actions/runs/45987128881)

| Süreç nerede kesildi? | Yeni isteğin ardından iki sistemde görülen sonuç |
| --- | --- |
| Tercih notu yazıldı, araç cevabı kaydedilmedi | Sohbet “2 + 2 kaç?” sorusuna yanıt verdi. Tercih notu korundu. |
| Aynı kesintiden sonra kullanıcı tercih notunu düzenledi | Sohbet yanıt verdi. Düzenlenen metin korundu. |
| Kullanıcı eski notu düzenledi ve başka bir tarihe yeni not istedi | Düzenleme korundu. Deneme saati 10 Kasım olduğu halde yeni not 27 Kasım dosyasına bir kez yazıldı. |
| İlk not henüz yazılmamıştı | Eski dosya oluşmadı. Açıkça istenen yeni not 27 Kasım dosyasına yazıldı. |

Dört örnekte de yazıcı gerçekten sonlandırıldı ve sohbet ayrı bir süreçte açıldı. Model ilk yanıtsız araç çağrısı için bir hata gördü. İlk çağrıya kalıcı bir başarı cevabı eklenmedi. İlk geliştirme denemesinde iki örnek farklıydı. SDK yeni notu 10 Kasım'a yazmıştı. Aynı dört girdi genel koşuda korundu. [İlk denemenin dosya sonuçları](interrupted-continued-turn-first-observations.json)

1.667 örneğin 1.663'ü eşleşti. Önceki 1.663 örneğin her birinin durumu korundu. Dört açık fark ilk arama (F03), gizli bilgiler temizlenirken aynı araç sonucunun yeniden kullanılması (F08, F09) ve eski tarih biçimleriyle (F15) ilgili. F03'te OpenClaw'ın ilk aramasında önceki koşuda gelen bir satır bu kez gelmedi. Engellenen örnek ve motor hatası sıfır. 64 başlığın 59'u tamamlandı ve beşi kısmi. Genel kapı `fullScopePassed: false` ve çıkış kodu 1 verdi.

Sayımda 128 koşul tek tek değerlendirildi. 34 grupta 227 karşılaştırmanın saklanan çalışma kayıtları yeniden okundu. Yeni koşul ayrıca yazma, indeks, bellek boşaltma, birleştirme, unutma ve günlük yayımlama yollarındaki 15 önceki örneğin geçmesini gerektiriyor. Beş açık koşul ve dört açık fark bağımsız sayımda ayrı kimliklerle yer alıyor.

| Kaynak | Kimlik |
| --- | --- |
| Ürün | `4a65fc22c5c8259f87fbfe8dfe73e1122891d777` |
| Ölçüm | `524a2603bf45d48f099cc319b8b55517963b68c4` |
| SDK | Git ağacı `f0ce0c93c3049d07eb1f015e6d77ad8d129c7620`, 185 Python dosyası |
| Karşılaştırılan sürüm | OpenClaw v2026.9.9, `bcfc88812a35243893585dbeca87ca41b48272ca`, Node v24.16.0 |
| Tam rapor | 1.915.320.935 bayt, SHA-256 `e2b2d2a1e1255e5977c271020e5dcb805fa9ea1931021bd9f160a1fcf8cdc1b0` |
| Bu koşunun özet ZIP'i | 371.448 bayt, SHA-256 `900423902b6e82ed897e4a79d5d8a15156e9816a801614581818b040c62851bb` |
| Önceki koşunun özet ZIP'i | 367.469 bayt, SHA-256 `e83f1927874b2388a18551c3dfbe704c933f6f3c9974054e2673becf734a7333` |

## Birleşme sonrası ana dal

PR #34 birleştirildikten sonra ana dalın `1b9055d7b3ca10a59626fb6969599cb5501ecf8e` commit'i yeniden alındı. Ölçüm ile bu commit'in `memory_core` Git ağacı aynı. `git diff --exit-code 524a260 1b9055d -- memory_core` fark bulmadan tamamlandı. [Ana daldaki takip listesi](https://github.com/DorukhanArslan/memory-core/blob/1b9055d7b3ca10a59626fb6969599cb5501ecf8e/docs/parity-completion-checklist.md) · [Birleşen PR](https://github.com/DorukhanArslan/memory-core/pull/34)

## Sayımı yeniden üretmek

Bu klasör iki özgün GitHub özetini, kimlik kayıtlarını ve sayım programını içerir. Aşağıdaki komutlar bu denetim dalının depo kökünde, Git geçmişi ve uzak denetim dalları alınmış bir klonda çalışır. Git nesneleri eksikse önce uzak dalları alın. Bağımlılıklar ölçümün kilitli Python ortamından yüklenir.

```bash
audit_dir="$PWD/independent-review/interrupted-turn"
review_dir=$(mktemp -d)
measurement="$review_dir/measurement"
git worktree add --detach "$measurement" 524a2603bf45d48f099cc319b8b55517963b68c4
for run in 45840190038 45987128881; do
  cp "$audit_dir/full-$run.zip" "$audit_dir/full-$run-envelope.json" "$review_dir/"
  python -m zipfile -e "$review_dir/full-$run.zip" "$review_dir/full-$run"
done
cd "$measurement"
uv sync --frozen
uv run --frozen python "$audit_dir/review_interrupted_turn.py" \
  --measurement "$measurement" --summary "$review_dir/full-45987128881" \
  --previous-summary "$review_dir/full-45840190038" --run 45987128881 \
  --head 524a2603bf45d48f099cc319b8b55517963b68c4 \
  --product 4a65fc22c5c8259f87fbfe8dfe73e1122891d777 \
  --archive-sha256 900423902b6e82ed897e4a79d5d8a15156e9816a801614581818b040c62851bb \
  > "$review_dir/recount.json"
cmp "$review_dir/recount.json" "$audit_dir/independent-45987128881.json"
```

Sayım çıktısının SHA-256 değeri `0dd1543d0b46f56080422bc945c22a2e1fff345040150a0d01694fbb7ee2121d`. Önceki bağımsız hesaplamalar için okunan Git commit'leri `45ac3284`, `9430a2cb`, `5bd9ac41` ve `34b52d79`. [Sayım programı](review_interrupted_turn.py)
