# LinkedIn AI Poster

Gündəlik texnologiya xəbərlərini toplayıb, NVIDIA NIM (pulsuz) ilə ən məntiqli
olanı seçib LinkedIn postu + şəkil hazırlayan, sənin GitHub üzərindən
təsdiqini alıb yalnız ondan sonra LinkedIn-də paylaşan yarı-avtonom sistem.

Heç bir əlavə server və ya üçüncü tərəf servisi lazım deyil - hər şey GitHub
Actions + GitHub Issues daxilində baş verir.

## Necə işləyir

1. Hər gün planlaşdırılmış vaxtda `generate-draft.yml` işə düşür
2. RSS lentləri + Hacker News-dan son 48 saatın xəbərlərini toplayır
3. NVIDIA NIM ilə (yalnız yuxarıda toplanan real xəbərlər üzərində) ən məntiqli
   olanı seçib Azərbaycan dilində LinkedIn postu yazır
4. NVIDIA NIM ilə mövzuya uyğun, abstrakt bir şəkil generasiya edir
5. Repoda yeni bir GitHub Issue açır - post mətni + şəkil daxil
6. Sən mobil GitHub app-dan (push bildirişi gələcək) və ya browser-dan bu
   issue-nu görürsən
7. Bəyənsən: issue-ya `approved` etiketini əlavə et → `publish-on-approval.yml`
   avtomatik işə düşür və post LinkedIn-də paylaşılır
8. Bəyənməsən: issue-nu sadəcə bağla, heç nə paylaşılmır

## Qurulum

### 1. Repo yarat
Bu qovluğun içindəkiləri yeni (istəsən private) bir GitHub reposuna yüklə.

### 2. NVIDIA API açarı al
1. https://build.nvidia.com ünvanına get, pulsuz hesab aç (kredit kartı lazım deyil)
2. API açarı yarat
3. Repo → **Settings → Secrets and variables → Actions → New repository secret**:
   - `NVIDIA_API_KEY` = aldığın açar

### 3. LinkedIn Developer App yarat
1. https://www.linkedin.com/developers/apps → **Create app**
2. Bir Company Page-ə bağla (yoxdursa, boş bir page yarada bilərsən - bu addım məcburidir)
3. **Products** bölməsində əlavə et: *Sign In with LinkedIn using OpenID Connect* və *Share on LinkedIn*
4. **Auth** bölməsində Redirect URL kimi əlavə et: `http://localhost:8765/callback`
5. Client ID və Client Secret-i qeyd et (Auth bölməsində görünür)

### 4. Bir dəfəlik: refresh token al
Öz kompüterində (GitHub Actions-da yox):
```bash
pip install requests
python scripts/linkedin_auth.py
```
Brauzerdə LinkedIn-ə icazə ver. Terminal 3 dəyər çıxaracaq - bunları repo
secrets-ə əlavə et:
- `LINKEDIN_CLIENT_ID`
- `LINKEDIN_CLIENT_SECRET`
- `LINKEDIN_REFRESH_TOKEN`

*(Refresh token təxminən 365 gün etibarlıdır - bir ildən sonra bu addımı təkrarlamalısan.)*

### 5. Label-ları yarat
Repo → **Issues → Labels** bölməsində iki label yarat: `pending-approval` və `approved`.

### 6. Sına
**Actions** tabından `Generate LinkedIn draft` workflow-unu seç → **Run workflow**
ilə əl ilə işə sal. Uğurlu olsa, bir neçə dəqiqəyə yeni bir Issue görəcəksən.

## Fayl strukturu

```
scripts/generate_draft.py       xəbər toplama + AI ilə mətn/şəkil yaratma
scripts/publish_to_linkedin.py  təsdiqlənmiş draft-ı LinkedIn-ə paylaşır
scripts/linkedin_auth.py        bir dəfəlik OAuth qurulumu (yalnız lokal)
.github/workflows/generate-draft.yml       gündəlik trigger
.github/workflows/publish-on-approval.yml  `approved` etiketi ilə tetiklənir
pending/                        gündəlik draft-ların (json + şəkil) saxlandığı yer
```

## Fərdiləşdirmə

- **RSS mənbələri / açar sözlər**: `scripts/generate_draft.py` başındakı
  `RSS_FEEDS` və `HN_KEYWORDS` siyahılarını dəyiş.
- **Post üslubu / persona**: eyni fayldakı `PERSONA` dəyişəni və
  `choose_and_write()` funksiyasındakı prompt mətni.
- **Vaxt**: `generate-draft.yml`-dəki `cron` sətri (hazırda 05:00 UTC = 09:00 Baku).
- **Model adları**: `NVIDIA_TEXT_MODEL` / `NVIDIA_IMAGE_MODEL` - build.nvidia.com
  kataloqu yeniləndikcə dəyişə bilər, https://build.nvidia.com/models-də yoxla.

## Məlum məhdudiyyətlər

- Sadəlik üçün eyni anda bir neçə pending draft aça bilər (tarixə görə ayrıca
  saxlanılır), amma bir neçə gün təsdiq etməsən, açıq issue-lar yığıla bilər -
  vaxtaşırı köhnələri bağla və ya sil.
- NVIDIA-nın pulsuz səviyyəsi dəqiqədə ~40 sorğu ilə məhdudlaşır - gündə 1
  işə düşmə üçün bu tamamilə kifayətdir.
- `publish_to_linkedin.py`-dakı `LINKEDIN_VERSION` dəyişəni (YYYYMM formatı)
  LinkedIn-in tələb etdiyi cari versiyanı əks etdirməlidir - Developer
  Portal-da vaxtaşırı yoxla.
- Bu, şəxsi profilə (Company Page-ə yox) paylaşım üçün qurulub.
