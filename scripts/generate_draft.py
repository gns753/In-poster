"""
Gündəlik olaraq texnologiya xəbərlərini toplayır, NVIDIA NIM ilə ən məntiqli
xəbəri seçib Azərbaycan dilində LinkedIn postu yazır, mövzuya uyğun bir şəkil
generasiya edir və təsdiq üçün lazım olan faylları pending/ qovluğuna yazır.

Bu skript heç nəyi LinkedIn-ə paylaşmır - sadəcə draft hazırlayır.
Paylaşım yalnız publish_to_linkedin.py vasitəsilə, sən GitHub Issue-nu
`approved` etiketi ilə təsdiqlədikdən sonra baş verir.
"""

import base64
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests
from openai import OpenAI

# ---- Tənzimləmələr ------------------------------------------------------
# Bunları öz zövqünə/mənbələrinə görə dəyişə bilərsən.

RSS_FEEDS = [
    # AI News
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://openai.com/news/rss.xml",
    "https://www.anthropic.com/news/rss.xml",

    # Engineering & Product
    "https://www.producthunt.com/feed",
    "https://feeds.feedburner.com/MindTheProduct",
    "https://www.svpg.com/feed/",
    "https://martinfowler.com/feed.atom",
    "https://www.lennysnewsletter.com/feed",
    "https://www.producttalk.org/feed/",
    "https://medium.com/feed/product-coalition",

    # AI Research
    "https://huggingface.co/blog/feed.xml",
    "https://www.deeplearning.ai/the-batch/feed/",
    "https://www.marktechpost.com/feed/",

    # Startups & VC
    "https://a16z.com/feed/",
    "https://www.ycombinator.com/blog/feed",

    # Developer
    "https://stackoverflow.blog/feed/",
]

HN_KEYWORDS = [
    # AI
    "ai", "artificial intelligence", "generative ai", "llm", "foundation model",
    "multimodal", "reasoning model", "gpt", "claude", "gemini", "deepseek",
    "qwen", "mistral", "llama", "phi",
    # Agentic AI
    "agent", "ai agent", "agentic", "workflow", "automation", "copilot", "rag",
    "vector database", "mcp", "tool calling", "function calling",
    # Prompt Engineering
    "prompt", "prompt engineering", "system prompt", "evaluation", "guardrails",
    # Product
    "product", "product management", "product owner", "product manager",
    "roadmap", "customer discovery", "feature", "ux",
    # Startups
    "startup", "saas", "founder", "vc", "funding",
    # Companies
    "openai", "anthropic", "google ai", "microsoft ai", "meta ai", "nvidia",
]
HN_MIN_SCORE = 40  # aşağı upvote-lu, hələ sınanmamış elanları süzgəcdən keçirir - "product" geniş açar söz olduğu üçün bu, ikinci müdafiə xətti kimi qalır

# Bəzi mənbələr Product Owner peşəsi üçün İNTRİNSİK aiddir (Mind the Product,
# SVPG, Lenny's, Product Talk, Product Coalition), digərləri isə ümumi
# AI/texnologiya xəbəridir. Bu etiket seçim mərhələsində modelin mənbəyə görə
# çəki verə bilməsi üçündür.
RSS_FEED_CATEGORIES = {
    "https://feeds.feedburner.com/MindTheProduct": "MƏHSUL İDARƏETMƏSİ",
    "https://www.svpg.com/feed/": "MƏHSUL İDARƏETMƏSİ",
    "https://www.lennysnewsletter.com/feed": "MƏHSUL İDARƏETMƏSİ",
    "https://www.producttalk.org/feed/": "MƏHSUL İDARƏETMƏSİ",
    "https://medium.com/feed/product-coalition": "MƏHSUL İDARƏETMƏSİ",
    "https://martinfowler.com/feed.atom": "Mühəndislik təcrübəsi",
    "https://www.producthunt.com/feed": "Yeni məhsul elanı",
}
DEFAULT_FEED_CATEGORY = "Ümumi AI/texnologiya xəbəri"

PERSONA = """You are an experienced Product Owner specializing in AI-powered products.

Your audience:
- Product Owners
- Product Managers
- Startup founders
- Software Engineers
- AI enthusiasts
- CTOs

Your expertise:
- Product Management
- Agile & Scrum
- AI Product Strategy
- Prompt Engineering
- LLMs
- AI Agents
- Automation
- UX
- API integrations

Writing style:
- Professional but conversational
- Insightful, not sensational
- Focus on business impact rather than repeating news
- Explain why the news matters for product teams
- Add your own perspective
- Keep posts between 120-250 words
- Use clean formatting
- Avoid emojis unless they add value
- End with one engaging question to encourage discussion
- Never copy the original article
- Mention practical takeaways
"""

# build.nvidia.com kataloqu dəyişə bilər - hər ehtimala qarşı model adlarını
# https://build.nvidia.com/models səhifəsində yoxla.
# QEYD: nvidia/llama-3.3-nemotron-super-49b-v1.5 sınandı, amma Azərbaycan
# dilində uydurma sözlər yaradırdı (NAS-distillasiya reasoning/İngiliscə
# performansa optimallaşdırılıb, az yayılmış dil səlisliyini qurban verib).
# meta/llama-3.3-70b-instruct-a qayıdıldı - bu, sübut olunmuş yaxşı nəticə verirdi.
NVIDIA_TEXT_MODEL = "meta/llama-3.3-70b-instruct"
# NVIDIA-nın hosted kataloqunda şəkil modelləri OpenAI formatı ilə YOX, öz
# "invoke" formatı ilə çağırılır - bax https://build.nvidia.com/models,
# modelə klikləyib "Python" tabındaki nümunə koda.
NVIDIA_IMAGE_INVOKE_URL = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-dev"

ARTICLE_LOOKBACK_HOURS = 48
MAX_ARTICLES_TO_MODEL = 30

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.environ["NVIDIA_API_KEY"],
)


def collect_articles():
    """RSS lentləri və Hacker News-dan son N saatın xəbərlərini toplayır."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ARTICLE_LOOKBACK_HOURS)
    articles = []

    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"})
            for entry in feed.entries[:10]:
                published = entry.get("published_parsed")
                if published:
                    pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                articles.append({
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "summary": re.sub("<[^<]+?>", "", entry.get("summary", ""))[:600],
                    "category": RSS_FEED_CATEGORIES.get(url, DEFAULT_FEED_CATEGORY),
                })
        except Exception as e:
            print(f"RSS xətası ({url}): {e}")

    try:
        hn_ids = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10
        ).json()[:60]
        for item_id in hn_ids:
            try:
                item = requests.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json", timeout=10
                ).json()
            except Exception:
                continue
            if not item or "title" not in item:
                continue
            if item.get("score", 0) < HN_MIN_SCORE:
                continue
            if any(k in item["title"].lower() for k in HN_KEYWORDS):
                articles.append({
                    "title": item["title"],
                    "url": item.get("url", f"https://news.ycombinator.com/item?id={item_id}"),
                    "summary": "",
                    "category": "Hacker News müzakirəsi",
                })
    except Exception as e:
        print(f"Hacker News xətası: {e}")

    return articles[:MAX_ARTICLES_TO_MODEL]


def choose_and_write(articles):
    """NVIDIA NIM-ə göndərib ən məntiqli xəbəri seçdirir və postu yazdırır.
    Uyğun namizəd yoxdursa None qaytarır - main() bu halı zərərsiz keçir.
    """
    articles_text = "\n\n".join(
        f"[{i}] ({a['category']}) {a['title']}\n{a['url']}\n{a['summary']}" for i, a in enumerate(articles)
    )

    prompt = f"""{PERSONA}

VACIB: Yuxarıdakı təlimatlar ingiliscə olsa da, POST_TEXT və REASON FASİH,
qrammatik cəhətdən DÜZGÜN Azərbaycan dilində yazılmalıdır. Qondarma söz,
yanlış hərfi tərcümə, başqa dildən (məsələn türk dilindən) hərfi keçirmə
qəti qəbuledilməzdir - hər söz həqiqi, standart Azərbaycan sözü olmalıdır.
Yalnız IMAGE_CONCEPT və IMAGE_PROMPT ingiliscə olsun.

Aşağıda son {ARTICLE_LOOKBACK_HOURS} saatın texnologiya xəbərləri var (nömrələnmiş).

SEÇİM MEYARI: Yalnız BİRİNİ seç. ƏVVƏLLİKLƏ "MƏHSUL İDARƏETMƏSİ" etiketli
mənbələrdən uyğun bir xəbər seçməyə çalış - bunlar məhz Product Owner peşəsi
üçün yazılıb, intrinsik aiddir. Belə xəbər yoxdursa, digər mənbələrdən YALNIZ
məhsul strategiyasına, qiymətləndirməyə, istifadəçi təcrübəsinə, prompt
mühəndisliyi texnikasına və ya komanda prosesinə BİRBAŞA aid olanı seç.

RƏDD ET: bir şirkətin maliyyələşməsi, "stealth rejimindən çıxışı", yeni
məhsulunun sadəcə elanı, "hansı model daha güclüdür" müqayisəsi, kiçik bir
alətin "işə salındı" xəbəri - bunlar ÖZLƏRİ məhsul strategiyası/prosesi
müzakirə etmirsə, RƏDD ET, hətta AI ilə bağlı olsa və nə qədər "böyük" xəbər
sayılsa belə.

Sınaq sualı: "Bu xəbərin ÖZÜ artıq Product Owner təcrübəsi/qərarı haqqında
danışır, YOXSA mən sonradan zorla bir PO cümləsi ƏLAVƏ ETMƏLİYƏM?" Cavab
ikincidirsə, SEÇMƏ, başqa namizəd axtar.

ƏGƏR XƏBƏRLƏRİN HEÇ BİRİ bu meyarlara cavab vermirsə, zorla seçim ETMƏ.
Bu, PİS NƏTİCƏ DEYİL - süni, zorla calanmış əlaqə yaratmaqdan qat-qat
yaxşıdır. Belə halda YALNIZ bunu yaz, başqa heç nə yazma:
CHOSEN_INDEX: NONE

Xəbərlər:
{articles_text}

Cavabını DƏQİQ aşağıdakı formatda ver - başqa heç nə əlavə etmə, izah yazma,
markdown qalın (**) işarəsi və kod bloku (```) işarəsi qoyma:

CHOSEN_INDEX: <seçdiyin xəbərin nömrəsi, YA DA heç biri uyğun deyilsə "NONE">
REASON: <niyə seçdiyini bir cümlə ilə izah et, Azərbaycan dilində>
IMAGE_CONCEPT: <bir neçə sözlə (ingiliscə), bu KONKRET xəbərin əsas texniki/işgüzar
                konsepsiyası - xəbərin adından/mətnindən BİLAVASİTƏ çıxmalıdır
                (bunlar YALNIZ format nümunəsidir, mövzuya uyğun öz variantını
                tap: "model size comparison", "multi-camera tracking pipeline",
                "code generation workflow")>
IMAGE_PROMPT: <yuxarıdaki IMAGE_CONCEPT-i vizuallaşdıran İNGİLİSCƏ təsvir, bir sətirdə.
              ŞƏKİLDƏ HEÇ BİR MƏTN, RƏQƏM, HƏRF VƏ YA YAZI OLMASIN - şəkil generasiya
              modelləri mətni oxunaqlı göstərə bilmir, nəticə həmişə qarışmış simvollar
              olur. Fikri YALNIZ vizual obyektlər, formalar, ölçü və rənglə ifadə et.
              Əgər konsepsiya müqayisə/reytinqdirsə, MƏTNSİZ fərqli ÖLÇÜDƏ obyektlər/
              fiqurlar işlət (məsələn kiçik və böyük bloklar yanaşı, ƏDƏD/YAZI olmadan).
              Əgər proses/pipeline-dirsə, addımları göstərən sadə (yazısız) axın sxemi
              işlət. Əgər konkret alət/funksiyadırsa, onun funksiyasını göstər.
              BUNLARI İSTİFADƏ ETMƏ (klişedir, HEÇ BİR mövzu üçün işlətmə): robot
              insanla əl sıxışır, dövrə lövhəsindən/işıqlanan beyin, neyron şəbəkəsi
              kürəsi, futuristik hologram, monitor/kamera divarı və izləmə xətləri
              (YALNIZ mövzu HƏQİQƏTƏN kamera/video izləmə ilə bağlıdırsa istifadə et,
              başqa heç bir mövzu üçün YOX). Professional, minimal, flat-design,
              real loqo/brend adı olmadan.>
POST_TEXT_START
<Azərbaycan dilində, MƏQALƏ TƏRZİNDƏ LinkedIn postu, TAM 180-250 söz (bundan
AZ OLMASIN - qısa yazma). HEÇ BİR CÜMLƏ öz-özünə istinad edən, məzmunsuz formada
olmasın - "bu xəbər ... barədə məlumat verir", "bu vacibdir çünki ... etməlidirlər"
kimi dövrü, heç nə YENİ deməyən cümlələr QƏTİ QƏBULEDİLMƏZDİR. Hər cümlə YENİ,
konkret məlumat və ya iddia əlavə etməlidir. Bu quruluşu izlə:
(1) Diqqətçəkən ilk sətir - xəbərdəki KONKRET bir fakt, rəqəm və ya addan başla, ümumi giriş cümləsi yazma
(2) 3-4 cümlə - nə oldu, kim/nə edib, mənbədən ən azı 2 konkret detal istifadə et
(3) 3-4 cümlə - Bu xəbərin Product Owner/Product Manager üçün KONKRET nəticəsini
    YAZ - SUAL VERMƏ, İDDİA ET. Format nümunəsi (mövzu fərqli olacaq, bu YALNIZ
    struktur nümunəsidir, sözbəsöz köçürmə): "Bu, [konkret komanda/məhsul növü]
    üçün deməkdir ki, [konkret dəyişiklik] baş verə bilər, çünki [səbəb]." Sən bu
    xəbərə uyğun, öz KONKRET versiyanı yaz - "necə təsir edəcək?" kimi sual YAZMA,
    CAVABI ÖZÜN VER. "Təhlükəsizliyi təmin etməlidirlər" kimi ümumi, hər mövzuya
    tətbiq oluna bilən cümlə YAZMA - bu XƏBƏRƏ MƏXSUS bir nəticə olmalıdır.
(4) 1-2 cümlə - yuxarıdaki PERSONA-nın şəxsi mövqeyi/təcrübəsi
(5) Oxucuya yönəlmiş açıq, düşündürücü sual (SUAL YALNIZ BURADA olsun, (3)-də yox)
(6) 3-5 aidiyyəti hashtag
Yuxarıdaki "Writing style" bölməsindəki ton, emoji və format qaydalarına əməl et.>
POST_TEXT_END"""

    response = None
    last_error = None
    for attempt in range(1, 4):
        try:
            response = client.chat.completions.create(
                model=NVIDIA_TEXT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=1500,  # Azərbaycan hərfləri (ə,ş,ç,ğ) ingiliscədən daha çox token tutur - defolt limit 250 sözlük postu kəsə bilirdi
            )
            break
        except Exception as e:
            print(f"NVIDIA mətn API xətası (cəhd {attempt}/3): {e}")
            last_error = e
            if attempt < 3:
                time.sleep(attempt * 10)
    if response is None:
        raise last_error
    raw = response.choices[0].message.content.strip()

    def extract_line(pattern, text, default=""):
        m = re.search(pattern, text, re.IGNORECASE)
        return m.group(1).strip() if m else default

    def extract_block(pattern, text, default=""):
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else default

    chosen_raw = extract_line(r"CHOSEN_INDEX:\**\s*(\S+)", raw, "NONE")
    if chosen_raw.strip().upper() == "NONE" or not chosen_raw.strip().isdigit():
        print(f"Model bu gün üçün intrinsik uyğun bir PO xəbəri tapmadı (CHOSEN_INDEX: {chosen_raw}) - draft yaradılmır.")
        return None
    chosen_index = int(chosen_raw)
    reason = extract_line(r"REASON:\**\s*(.+)", raw)
    image_prompt = extract_line(r"IMAGE_PROMPT:\**\s*(.+)", raw)
    post_text = extract_block(r"POST_TEXT_START\**\s*(.*?)\s*\**POST_TEXT_END", raw)
    if not post_text:
        post_text = extract_block(r"POST_TEXT_START\**\s*(.*)", raw)
        if post_text:
            print("QEYD: POST_TEXT_END markeri tapılmadı, START-dan sona qədər olan mətn istifadə olundu.")

    if not post_text:
        raise ValueError(f"Modelin cavabı gözlənilən formatda deyil:\n{raw[:1500]}")

    return {
        "chosen_index": chosen_index,
        "reason": reason,
        "post_text": post_text,
        "image_prompt": image_prompt,
        "source": articles[chosen_index],
    }


def generate_image(image_prompt, out_path, max_retries=3):
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                NVIDIA_IMAGE_INVOKE_URL,
                headers={
                    "Authorization": f"Bearer {os.environ['NVIDIA_API_KEY']}",
                    "Accept": "application/json",
                },
                json={
                    "prompt": image_prompt,
                    "mode": "base",
                    "cfg_scale": 3.5,
                    "width": 1024,
                    "height": 1024,
                    "seed": 0,
                    "steps": 25,
                },
                timeout=90,
            )
            if resp.status_code == 200:
                img_bytes = base64.b64decode(resp.json()["artifacts"][0]["base64"])
                with open(out_path, "wb") as f:
                    f.write(img_bytes)
                return
            print(f"NVIDIA şəkil API cavabı (cəhd {attempt}/{max_retries}, {resp.status_code}): {resp.text[:400]}")
            last_error = requests.exceptions.HTTPError(f"{resp.status_code} Server Error", response=resp)
        except requests.exceptions.RequestException as e:
            print(f"Şəbəkə xətası (cəhd {attempt}/{max_retries}): {e}")
            last_error = e
        if attempt < max_retries:
            wait = attempt * 10
            print(f"{wait} saniyə gözləyib yenidən cəhd edilir...")
            time.sleep(wait)
    raise last_error


def build_issue_body(draft_id, draft, image_url):
    return f"""<!-- DRAFT_ID: {draft_id} -->
## Təklif olunan LinkedIn postu ({draft_id})

**Mənbə:** [{draft['source']['title']}]({draft['source']['url']})
**Niyə seçildi:** {draft['reason']}

---

{draft['post_text']}

---

![draft şəkli]({image_url})

---
Bəyənirsənsə, bu issue-ya **`approved`** etiketini əlavə et - avtomatik LinkedIn-də paylaşılacaq.
Bəyənməsən, sadəcə issue-nu bağla, heç nə paylaşılmayacaq."""


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    draft_id = f"{today}_{run_id}"
    os.makedirs("pending", exist_ok=True)

    articles = collect_articles()
    if not articles:
        print("Uyğun xəbər tapılmadı, bu gün draft yaradılmır.")
        return

    draft = choose_and_write(articles)
    if draft is None:
        print("Bu gün üçün draft yaradılmadı - sabah yenidən cəhd ediləcək.")
        return

    image_path = f"pending/{draft_id}.png"
    generate_image(draft["image_prompt"], image_path)

    json_path = f"pending/{draft_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)

    repo = os.environ.get("GITHUB_REPOSITORY", "OWNER/REPO")
    image_url = f"https://raw.githubusercontent.com/{repo}/main/{image_path}"

    with open("pending/issue_body.md", "w", encoding="utf-8") as f:
        f.write(build_issue_body(draft_id, draft, image_url))

    print(f"Draft hazırdır: {json_path}")
    print(f"Seçilən xəbər: {draft['source']['title']}")


if __name__ == "__main__":
    main()