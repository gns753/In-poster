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
                    "summary": re.sub("<[^<]+?>", "", entry.get("summary", ""))[:400],
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
                })
    except Exception as e:
        print(f"Hacker News xətası: {e}")

    return articles[:MAX_ARTICLES_TO_MODEL]


def choose_and_write(articles):
    """NVIDIA NIM-ə göndərib ən məntiqli xəbəri seçdirir və postu yazdırır.

    Diqqət 1: model yalnız BURADA verilən (real, çəkilmiş) xəbərlər üzərində
    işləyir - "bu gün nə oldu" deyə öz yaddaşından uydurmasının qarşısı
    məhz belə alınır.

    Diqqət 2: JSON YOX, açar-sözlü mətn markerləri istifadə olunur. Uzun,
    çoxparaqraflı post mətnini JSON string-i için-də istəsək, kiçik modellər
    tez-tez sətir sonu simvollarını düzgün "escape" etmir və JSON sınır.
    Marker-based format bu problemi tamamilə aradan qaldırır.
    """
    articles_text = "\n\n".join(
        f"[{i}] {a['title']}\n{a['url']}\n{a['summary']}" for i, a in enumerate(articles)
    )

    prompt = f"""{PERSONA}

VACIB: Yuxarıdakı təlimatlar ingiliscə olsa da, POST_TEXT və REASON FASİH,
qrammatik cəhətdən DÜZGÜN Azərbaycan dilində yazılmalıdır. Qondarma söz,
yanlış hərfi tərcümə, başqa dildən (məsələn türk dilindən) hərfi keçirmə
qəti qəbuledilməzdir - hər söz həqiqi, standart Azərbaycan sözü olmalıdır.
Yalnız IMAGE_PROMPT ingiliscə olsun.

Aşağıda son {ARTICLE_LOOKBACK_HOURS} saatın texnologiya xəbərləri var (nömrələnmiş).

SEÇİM MEYARI: Yalnız BİRİNİ seç. Kiçik, tək bir alətin sadə "işə salındı" elanını
və ya məzmunca kasıb, dərinliyi olmayan xəbərləri SEÇMƏ. Əvəzinə, arxasında real
substansiya olan və yuxarıdaki auditoriya üçün maraqlı, konkret fikir yazmaq
mümkün olan bir xəbər seç.

Xəbərlər:
{articles_text}

Cavabını DƏQİQ aşağıdakı formatda ver - başqa heç nə əlavə etmə, izah yazma,
markdown qalın (**) işarəsi və kod bloku (```) işarəsi qoyma:

CHOSEN_INDEX: <seçdiyin xəbərin nömrəsi>
REASON: <niyə seçdiyini bir cümlə ilə izah et, Azərbaycan dilində>
IMAGE_PROMPT: <şəklin İNGİLİSCƏ təsviri, bir sətirdə. KONKRET, gözlə görünə bilən 2-3 əşya/element təsvir et ki, xəbərin mövzusundan bilavasitə çıxsın (məsələn "a grid of small monitor screens showing different camera angles connected by glowing lines to a central dashboard" kimi konkret bir səhnə). BUNU YAZMA: tək bir mücərrəd 3D forma və ya aydın mövzusu olmayan həndəsi fiqur - bu, şəkil modelinin "təhlükəsiz" defolt seçimidir və mövzuya heç bağlı olmur. BUNLARI da İSTİFADƏ ETMƏ: robot insanla əl sıxışır, dövrə lövhəsindən/işıqlanan beyin, neyron şəbəkəsi kürəsi, futuristik hologram. Professional, minimal, flat-design, real loqo/brend adı olmadan.>
POST_TEXT_START
<Azərbaycan dilində, MƏQALƏ TƏRZİNDƏ LinkedIn postu, TAM 180-250 söz (bundan
AZ OLMASIN - qısa yazma). Bu quruluşu izlə:
(1) Diqqətçəkən ilk sətir - xəbərdəki KONKRET bir fakt, rəqəm və ya addan başla, ümumi giriş cümləsi yazma
(2) 3-4 cümlə - nə oldu, kim/nə edib, mənbədən ən azı 2 konkret detal istifadə et
(3) 3-4 cümlə - MƏHZ Product Owner/Product Manager auditoriyası üçün bunun praktiki mənası: hansı qərara, prioritetə, riskə və ya imkana təsir edir - ümumi "AI gələcəyi dəyişəcək" tipli cümlə YOX, konkret iş nəticəsi
(4) 1-2 cümlə - yuxarıdaki PERSONA-nın şəxsi mövqeyi/təcrübəsi
(5) Oxucuya yönəlmiş açıq, düşündürücü sual
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

    chosen_index = int(extract_line(r"CHOSEN_INDEX:\**\s*(\d+)", raw, "0"))
    reason = extract_line(r"REASON:\**\s*(.+)", raw)
    image_prompt = extract_line(r"IMAGE_PROMPT:\**\s*(.+)", raw)
    post_text = extract_block(r"POST_TEXT_START\**\s*(.*?)\s*\**POST_TEXT_END", raw)

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
                    "steps": 50,
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
    # Hər run-a unikal ID veririk (tarix + GitHub run ID). Bu, eyni gündə
    # bir neçə dəfə test edərkən köhnə issue-ların faylının üzərinə yazılıb
    # şəkil/mətnin qarışmasının qarşısını alır.
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    draft_id = f"{today}_{run_id}"
    os.makedirs("pending", exist_ok=True)

    articles = collect_articles()
    if not articles:
        print("Uyğun xəbər tapılmadı, bu gün draft yaradılmır.")
        return

    draft = choose_and_write(articles)

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