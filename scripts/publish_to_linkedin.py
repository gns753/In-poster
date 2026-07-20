"""
Təsdiqlənmiş draft-ı LinkedIn-ə paylaşır.

Bu skript GitHub Actions tərəfindən, sən bir issue-ya `approved` etiketini
əlavə etdiyin zaman avtomatik çağırılır (bax: .github/workflows/publish-on-approval.yml).
Əl ilə də çalışdıra bilərsən, amma ISSUE_TITLE mühit dəyişənini özün verməlisən:

    ISSUE_TITLE="LinkedIn draft - 2026-07-20" python scripts/publish_to_linkedin.py
"""

import json
import os
import re
import sys

import requests

# LinkedIn Developer Portal-da tələb olunan cari versiyanı (YYYYMM formatında)
# vaxtaşırı yoxla - LinkedIn bunu zaman-zaman yeniləyir.
LINKEDIN_VERSION = "202601"


def get_access_token():
    resp = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "refresh_token",
            "refresh_token": os.environ["LINKEDIN_REFRESH_TOKEN"],
            "client_id": os.environ["LINKEDIN_CLIENT_ID"],
            "client_secret": os.environ["LINKEDIN_CLIENT_SECRET"],
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_person_urn(access_token):
    resp = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return f"urn:li:person:{resp.json()['sub']}"


def upload_image(access_token, person_urn, image_path):
    """3 addımlı LinkedIn Images API axını: init -> binary upload -> URN."""
    init = requests.post(
        "https://api.linkedin.com/rest/images?action=initializeUpload",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "LinkedIn-Version": LINKEDIN_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json={"initializeUploadRequest": {"owner": person_urn}},
        timeout=15,
    )
    init.raise_for_status()
    value = init.json()["value"]
    upload_url, image_urn = value["uploadUrl"], value["image"]

    with open(image_path, "rb") as f:
        put = requests.put(
            upload_url,
            headers={"Authorization": f"Bearer {access_token}"},
            data=f.read(),
            timeout=30,
        )
    put.raise_for_status()
    return image_urn


def create_post(access_token, person_urn, text, image_urn):
    resp = requests.post(
        "https://api.linkedin.com/rest/posts",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "LinkedIn-Version": LINKEDIN_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
        },
        json={
            "author": person_urn,
            "commentary": text,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "content": {"media": {"altText": "LinkedIn post şəkli", "id": image_urn}},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.headers.get("x-restli-id", "(post id başlıqda tapılmadı)")


def main():
    issue_title = os.environ.get("ISSUE_TITLE", "")
    match = re.search(r"\d{4}-\d{2}-\d{2}", issue_title)
    if not match:
        print(f"Issue başlığında tarix (YYYY-MM-DD) tapılmadı: '{issue_title}'")
        sys.exit(1)
    date = match.group(0)

    json_path, image_path = f"pending/{date}.json", f"pending/{date}.png"
    if not (os.path.exists(json_path) and os.path.exists(image_path)):
        print(f"Draft faylları tapılmadı: {json_path} / {image_path}")
        sys.exit(1)

    with open(json_path, encoding="utf-8") as f:
        draft = json.load(f)

    access_token = get_access_token()
    person_urn = get_person_urn(access_token)
    image_urn = upload_image(access_token, person_urn, image_path)
    post_id = create_post(access_token, person_urn, draft["post_text"], image_urn)

    print(f"Paylaşıldı. Post ID: {post_id}")


if __name__ == "__main__":
    main()
