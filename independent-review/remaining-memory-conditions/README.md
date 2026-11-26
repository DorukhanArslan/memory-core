# OpenClaw v2026.9.9 bellek karşılaştırması

**122/128 koşul doğrulandı.** Önceki 119 koşul yeniden geçti. Üç kazanım, oturum arşivindeki iletilerin seçimi, çalışma alanı açılırken seçilen dosyalar ve bir notun kalıcı belleğe alınması için gereken kurallardı. Bağımsız sayım, 1.663 örneğin 1.659’unda iki sistemin aynı sonucu verdiğini gösterdi. Dört örnek farklı sonuç verdi. 64 sözleşmenin 58’i tam, altısı kısmi. [Bağımsız sayım](independent-45840190038.json) · [GitHub Actions ölçümü](https://github.com/DorukhanArslan/memory-core/actions/runs/45840190038)

Tam karşılaştırma süreci **çıkış kodu 1** ve `mismatched` durumuyla sonlandı. `fullScopePassed` değeri `false`, engellenen örnek ve motor hatası sayısı sıfırdı. Dört fark ilk arama, iki araç çıktısı ve bir tarih-saat örneğindeydi. Altı açık koşulun her biri ölçümde kayıtlı karşılaştırma kapsamı bekliyor. Koşul puanının kapsamı sabit bellek listesi ve belirtilen OpenClaw sürümüyle sınırlı. [Açık koşullar ve gözlemleri](open-decisions-45840190038.json)

## Ölçüm kaynakları

| Kaynak | Kimlik | SHA-256 |
|---|---|---|
| Ürün | `bb40b5c532ae4dabf5504806922fba4fa414adf4`, 184 Python dosyası | `da7eea7d8aa960f5e86018fe2bafe47ddce8a22ec7c6df60945d8216dec8356d` |
| Ölçüm | `c7ac7cd757d510c047fcd9b5d24b9e4b5b9ec2d6`, 1.663 örneğin kataloğu | `f95caff97657df1f3365228fa7353589ce9b025bc78aadf5e7790200e4247a59` |
| Karşılaştırılan OpenClaw | `v2026.9.9`, `bcfc88812a35243893585dbeca87ca41b48272ca`, Node `v24.16.0` | `09f313df5a3b93723c7f408bba1887e9978156bbcfd4fa0b3c3bccb61c4779c8` (npm paketi) |
| Güncel özet ZIP | Actions `45840190038`, artifact `15138598570`, 367.469 bayt | `e83f1927874b2388a18551c3dfbe704c933f6f3c9974054e2673becf734a7333` |
| Önceki özet ZIP | Actions `45153594838`, artifact `14820546579`, 354.903 bayt | `68590697b56a6fed14c3d3b49d62714fb3c4cc2f34332a2d9177b79b58c09a4a` |
| Güncel koşunun `source-seal.json` dosyası | Başlatma ve çıkış kaydındaki kaynak kimliği | `a296c03d0cc50e400caabb4e2057cff4293cc9859c074e03529dccdf6a9e46c6` |
| Tam rapor | `full.json`, 1.913.419.824 bayt | `0f7cc3ba8239cd0e2e241f4d18c7b02ab981954c79d2fd329739d82d30a1ede2` |

Kaynakları mühürleyen `run_merged_comparison.py` dosyasının SHA-256 değeri `458aade4a4010ea9245a5a3f61d771452c00232190be57cf6c0b51d4630c331f`. Bu program ölçüm commit’indeki `followup_seal.py` sabitlerini kullandı. Bu ikinci dosyanın SHA-256 değeri `22b57ccb17563f783858fe211f877034281f3770c70a7b3b38caaab6b0903000`. Önceki ölçüm commit’i `8a8b447bf539c4f270c5d319da9ca84d5879530d`. GitHub her iki küçük ZIP’i `memory-contract-remainder-summary` adıyla yayımladı. [Kaynak mührünü üreten dosya](https://github.com/DorukhanArslan/memory-core/blob/c7ac7cd757d510c047fcd9b5d24b9e4b5b9ec2d6/.github/scripts/run_merged_comparison.py) · [Sabitler](https://github.com/DorukhanArslan/memory-core/blob/c7ac7cd757d510c047fcd9b5d24b9e4b5b9ec2d6/.github/scripts/followup_seal.py) · [Güncel GitHub artifact kaydı](full-45840190038-envelope.json) · [Güncel ZIP](https://github.com/DorukhanArslan/memory-core/actions/runs/45840190038/artifacts/15138598570) · [Önceki ZIP](https://github.com/DorukhanArslan/memory-core/actions/runs/45153594838/artifacts/14820546579)

## Küçük ZIP’lerle sonucu yeniden hesaplama

Bu README’nin bulunduğu depo kopyasında, GitHub’a giriş yapılmış `gh`, `jq`, `unzip`, `uv` ve Python 3.12 ile aşağıdaki iki bloğu aynı Bash oturumunda çalıştırın. İlk blok ölçüm kodunu ve inceleme sırasında Git nesnelerinden okunan önceki üç kararı hazırlar.

```bash
repo_root=$(git rev-parse --show-toplevel)
review="$repo_root/independent-review/remaining-memory-conditions"
evidence_dir=$(mktemp -d)
measurement="$evidence_dir/measurement"
head_sha=c7ac7cd757d510c047fcd9b5d24b9e4b5b9ec2d6
for rev in "$head_sha" 9430a2cb23a6660f281adbeadb0fb1b926687fa4 \
           5bd9ac41dfa66b7732a6898b6a4e02366dd836de 34b52d79f6082e061b8f1ce47a6ca27d407fb391
do
  git -C "$repo_root" cat-file -e "$rev^{commit}" 2>/dev/null || git -C "$repo_root" fetch origin "$rev"
done
git -C "$repo_root" worktree add --detach "$measurement" "$head_sha"
uv sync --project "$measurement" --python 3.12 --frozen
```

İkinci blok, GitHub’ın artifact bilgilerini ve özgün ZIP baytlarını alır. İnceleyici her ZIP’in özetini, çalıştırma ve commit kimliklerini ve çıkarılan dokuz dosyayı doğrular. Ardından sabit koşulların sonuçlarını yeniden sayar. Son komut, hesaplanan çıktıyı bu dizindeki bağımsız kararla bayt düzeyinde karşılaştırır.

```bash
cd "$evidence_dir"
for pair in '45840190038 15138598570' '45153594838 14820546579'; do
  read -r run_id artifact_id <<< "$pair"
  endpoint="repos/DorukhanArslan/memory-core/actions/artifacts/$artifact_id"
  gh api "$endpoint" | jq '{artifact: .}' > "full-$run_id-envelope.json"
  gh api "$endpoint/zip" > "full-$run_id.zip"
  unzip -q "full-$run_id.zip" -d "full-$run_id"
done
"$measurement/.venv/bin/python" "$review/review_remaining.py" \
  --measurement "$measurement" --summary full-45840190038 --previous-summary full-45153594838 \
  --head "$head_sha" --product bb40b5c532ae4dabf5504806922fba4fa414adf4 \
  --archive-sha256 e83f1927874b2388a18551c3dfbe704c933f6f3c9974054e2673becf734a7333 \
  --run 45840190038 > reproduced.json
cmp reproduced.json "$review/independent-45840190038.json"
```

## Altı açık davranışın kanıtları

Oturum kapanışında aynı dakikadaki iki notun korunması, günlük not hedefinin hazırlanması, yarım kalmış takip kaydının sahibinin bulunması ve yazma sırasında kesintiden sonraki ilk istek için dört yerel gözlem saklandı. [Dört gözlemin açıklaması](four-point-review.md) · [Fiziksel sonuçlar](four-point-review.json)

Bir kayıt biter bitmez yapılan ilk arama, arama dizininin hangi anda güncellendiğine bağlıydı. Hassas metni gizleme örneği ise döndürülen içerikle birlikte girdi nesnesinin yeniden kullanılıp kullanılmadığını ölçtü. [İlk arama gözlemleri](flush-review.md) · [Arama çıktıları](flush-observations.json) · [Gizleme ve nesne kimliği kaydı](redaction-input-identity.json)

Ayrı sürüm denemesinde aynı dakikada kapanan iki oturumdan **v2026.9.9’da bir not, v2026.9.35 ve v2026.11.10’da iki not** kaldı. Bu deneme sadece eşzamanlı iki kapanışta iki konuşmanın saklanmasını doğruladı. Yeni sürümlerin genel bellek eşdeğerliği ayrı ölçüm gerektirir. [İki not denemesi](reset-release-research.md) · [Üç sürümün gözlemleri](reset-release-comparison.json) · [28 sürüm etiketinin kaynak taraması](reset-release-source-inventory.json)

Yukarıdaki artışta kullanılan açılış ve oturum arşivi karşılaştırmalarının küçük fiziksel kayıtları da bu dizinde bulunuyor. [Çalışma alanı açılışı](bootstrap-receipt.json) · [Oturum arşivleri](transcript-receipt.json)
