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
    "ai",
    "artificial intelligence",
    "generative ai",
    "llm",
    "foundation model",
    "multimodal",
    "reasoning model",
    "gpt",
    "claude",
    "gemini",
    "deepseek",
    "qwen",
    "mistral",
    "llama",
    "phi",

    # Agentic AI
    "agent",
    "ai agent",
    "agentic",
    "workflow",
    "automation",
    "copilot",
    "rag",
    "vector database",
    "mcp",
    "tool calling",
    "function calling",

    # Prompt Engineering
    "prompt",
    "prompt engineering",
    "system prompt",
    "evaluation",
    "guardrails",

    # Product
    "product",
    "product management",
    "product owner",
    "product manager",
    "roadmap",
    "customer discovery",
    "feature",
    "ux",

    # Startups
    "startup",
    "saas",
    "founder",
    "vc",
    "funding",

    # Companies
    "openai",
    "anthropic",
    "google ai",
    "microsoft ai",
    "meta ai",
    "nvidia",
]
PERSONA = """
You are an experienced Product Owner specializing in AI-powered products.

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
NVIDIA_TEXT_MODEL = "meta/llama-3.3-70b-instruct"
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

    Diqqət: model yalnız BURADA verilən (real, çəkilmiş) xəbərlər üzərində
    işləyir - "bu gün nə oldu" deyə öz yaddaşından uydurmasının qarşısı
    məhz belə alınır.
    """
    articles_text = "\n\n".join(
        f"[{i}] {a['title']}\n{a['url']}\n{a['summary']}" for i, a in enumerate(articles)
    )

    prompt = f"""Sən {PERSONA} üçün LinkedIn məzmun strateqisən.

Aşağıda son {ARTICLE_LOOKBACK_HOURS} saatın texnologiya xəbərləri var (nömrələnmiş).
Bunlardan yalnız BİRİNİ seç - {PERSONA} auditoriyası üçün ən "məntiqli",
peşəkar müzakirəyə açıq olanı.

Xəbərlər:
{articles_text}

Yalnız aşağıdakı JSON formatında cavab ver, başqa heç nə yazma (kod bloku, izah və s. olmadan):
{{
  "chosen_index": <seçdiyin xəbərin nömrəsi, tam ədəd>,
  "reason": "<niyə seçdiyini bir cümlə ilə izah et>",
  "post_text": "<Azərbaycan dilində LinkedIn postu: ilk sətir diqqətçəkici olsun, qısa paraqraflar, bir əsas fikir, sonda oxucuya sual, sonda 3-5 aidiyyəti hashtag. 1300 simvoldan uzun olmasın>",
  "image_prompt": "<şəklin İNGİLİSCƏ təsviri: mövzuya uyğun abstrakt/konseptual vizual, real loqo/brend adı olmadan, professional, minimal, flat-design üslubda>"
}}"""

    response = client.chat.completions.create(
        model=NVIDIA_TEXT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```json|^```|```$", "", raw, flags=re.MULTILINE).strip()
    data = json.loads(raw)
    data["source"] = articles[int(data["chosen_index"])]
    return data


def generate_image(image_prompt, out_path):
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
    if resp.status_code != 200:
        print(f"NVIDIA şəkil API cavabı ({resp.status_code}): {resp.text[:800]}")
    resp.raise_for_status()
    img_bytes = base64.b64decode(resp.json()["artifacts"][0]["base64"])
    with open(out_path, "wb") as f:
        f.write(img_bytes)


def build_issue_body(today, draft, image_url):
    return f"""## Təklif olunan LinkedIn postu ({today})

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
    os.makedirs("pending", exist_ok=True)

    articles = collect_articles()
    if not articles:
        print("Uyğun xəbər tapılmadı, bu gün draft yaradılmır.")
        return

    draft = choose_and_write(articles)

    image_path = f"pending/{today}.png"
    generate_image(draft["image_prompt"], image_path)

    json_path = f"pending/{today}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)

    repo = os.environ.get("GITHUB_REPOSITORY", "OWNER/REPO")
    image_url = f"https://raw.githubusercontent.com/{repo}/main/{image_path}"

    with open("pending/issue_body.md", "w", encoding="utf-8") as f:
        f.write(build_issue_body(today, draft, image_url))

    print(f"Draft hazırdır: {json_path}")
    print(f"Seçilən xəbər: {draft['source']['title']}")


if __name__ == "__main__":
    main()
