# İki adla açılan günlük notunda sessiz bakım

**27 Kasım 2026 · 124/128 doğrulandı.** `flush.plan-target.boundaries` koşulu bir puan kazandırdı. Önceki 123 koşulun tamamı yeniden geçti. İki dosya adı aynı günlük notunu gösterdiğinde OpenClaw ve SDK bakım çağrısını tamamladı ve notun içeriğini korudu. [Bağımsız sayım](independent-46020719989.json) · [Genel koşu](https://github.com/DorukhanArslan/memory-core/actions/runs/46020719989)

| Günlük dosyasının durumu | İki sistemde gözlenen sonuç |
| --- | --- |
| `memory/2026-01-01.md` ve `memory/campus-notes.md` aynı notu açıyor | Model bir kez `NO_REPLY` verdi. Başlangıçta, model çağrısında ve bakım sonunda iki ad da aynı fiziksel dosyayı gösterdi. İki satırlık not korundu. |
| Not tek adla açılıyor | Model bir kez `NO_REPLY` verdi. Bakım başarılı olarak kaydedildi ve not korundu. |
| Günlük dosyasının yerinde `agenda.txt` içeren bir klasör var | İki sistem de model çağrısından önce durdu, başarısızlığı kaydetti ve ajandayı korudu. |

Her iki tam bakım talimatı ve model seçimi karşılaştırıldı. Bağlam boyutu 79.999’dan 80.000’e çıktığında ayrılan pay 19.999’dan 20.000’e yükseldi. Her iki durumda yumuşak eşik 30.000 kaldı. Kabul edilen işlem salt okunurdu. Bakım sırasında iki adlı nota yazma ve özel dosya türleri ayrı kapsamda kalıyor. SDK mevcut yazma korumalarını uyguluyor.

1.670 örneğin 1.666’sı eşleşti. Önceki 1.667 örneğin her biri önceki durumunu korudu. Önceki 92 yardımcı örneğin ve 13 otomatik bakım örneğinin iki taraftaki tam sonuçları ayrı ayrı karşılaştırıldı. Yardımcı örnekler doğrudan puan almıyor. Önceki 227 fiziksel doğrulama kaydı ve üç yeni kayıt doğrulandı.

60 başlık tamamlandı ve dört başlık kısmi kaldı. Engellenen örnek ve motor hatası sıfırdı. Dört eski fark nedeniyle genel karşılaştırma `mismatched` ve çıkış kodu `1` ile bitti. İlk aramada (`F03`) OpenClaw bu kez notun eski metnini döndürdü. Önceki koşuda aynı arama boş dönmüştü. SDK güncel metni döndürmeye devam etti. Diğer üç açık farkın iki taraftaki sonuçları önceki koşuyla aynıydı.

## Ölçüm kimlikleri

| Kaynak | Kimlik |
| --- | --- |
| Ürün | `44b4eb2a95dfab2daacf43bd08c9c9f12dc6074c` · 185 SDK kaynağının SHA-256 değeri `a9a9c030ef3c63428e540948e2dd47a3ce2f070facab5933ecb7c73addf2cdd9` |
| Ölçüm | `232aa039a89ee84075eeca8d713817e8b8f6517c` · SDK Git ağacı `3cff7b7f57c222f960ec162dd144bcb2695ad3f1` |
| OpenClaw | `v2026.9.9` · `bcfc88812a35243893585dbeca87ca41b48272ca` · Node `v24.16.0` |
| Kapsam ve katalog | 128 koşul `a8e066e63970dd0be734485d62a5932640894b8c0a42f47ac3eb67f784cbc7b9` · 1.670 örnek `468d7a01efc95c1c75cfb102e029f2b55a31c170fd41b08e42ff37f1a5ebde59` |
| Tam rapor | 1.921.734.814 bayt · `3237726cc9e37ceb4c8cff50830c9750857c8536899e59a017f8696d139c3c05` |
| Bu koşunun özet ZIP’i | GitHub `15222490229` · 381.755 bayt · `73339d91421c91cf78c82775560b16f2fd7dce8bb77ad7cb5117e3b39dc16e85` |
| Önceki koşunun özet ZIP’i | GitHub `15202883144` · 371.448 bayt · `900423902b6e82ed897e4a79d5d8a15156e9816a801614581818b040c62851bb` |

## Sayımı yeniden üretmek

Git, Python 3.12 ve `uv` bulunan bir ortamda bu dalın depo kökünden çalıştırın. Normal bir klonda uzak denetim dallarının geçmişi de bulunmalı. Sayım bu iki özetin özgün dosyalarını, mühürlenen kaynakları ve önceki bağımsız kararları okur. [Sayım betiği](review_flush_boundary.py) · [123 koşulun bağımsız kaydı](https://github.com/DorukhanArslan/memory-core/tree/95b108408409255cdf36c92ef627b50b0062440b/independent-review/interrupted-turn)

```bash
audit_dir="$PWD/independent-review/read-only-flush"
review_dir=$(mktemp -d)
measurement="$review_dir/measurement"
git worktree add --detach "$measurement" 232aa039a89ee84075eeca8d713817e8b8f6517c
for run in 45987128881 46020719989; do
  cp "$audit_dir/full-$run.zip" "$audit_dir/full-$run-envelope.json" "$review_dir/"
  python -m zipfile -e "$review_dir/full-$run.zip" "$review_dir/full-$run"
done
uv run --frozen --project "$measurement" --python 3.12 python "$audit_dir/review_flush_boundary.py" \
  --measurement "$measurement" --summary "$review_dir/full-46020719989" \
  --previous-summary "$review_dir/full-45987128881" --run 46020719989 \
  --head 232aa039a89ee84075eeca8d713817e8b8f6517c \
  --product 44b4eb2a95dfab2daacf43bd08c9c9f12dc6074c \
  --archive-sha256 73339d91421c91cf78c82775560b16f2fd7dce8bb77ad7cb5117e3b39dc16e85 \
  > "$review_dir/recount.json"
cmp "$review_dir/recount.json" "$audit_dir/independent-46020719989.json"
```

Sayım çıktısının SHA-256 değeri `0083ddf9c10484aae9e071deccf098912dee1c2085a561ebc3429365a53b9b40`. Önceki bağımsız doğrulayıcıları içeren Git commit’leri `95b10840`, `45ac3284`, `9430a2cb`, `5bd9ac41` ve `34b52d79`.
