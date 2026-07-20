"""
Təsdiqlənmiş draft-ı LinkedIn-ə paylaşır.

Bu skript GitHub Actions tərəfindən, sən bir issue-ya `approved` etiketini
əlavə etdiyin zaman avtomatik çağırılır (bax: .github/workflows/publish-on-approval.yml).
"""

import json
import os
import re
import sys

import requests

LINKEDIN_VERSION = "202601"


def get_person_urn(access_token):
    resp = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return f"urn:li:person:{resp.json()['sub']}"


def upload_image(access_token, person_urn, image_path):
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
    issue_body = os.environ.get("ISSUE_BODY", "")
    match = re.search(r"<!-- DRAFT_ID:\s*(.+?)\s*-->", issue_body)
    if not match:
        print("Issue mətnində DRAFT_ID markeri tapılmadı - bu issue bu skriptlə uyğun deyil.")
        sys.exit(1)
    draft_id = match.group(1)

    json_path, image_path = f"pending/{draft_id}.json", f"pending/{draft_id}.png"
    if not (os.path.exists(json_path) and os.path.exists(image_path)):
        print(f"Draft faylları tapılmadı: {json_path} / {image_path}")
        sys.exit(1)

    with open(json_path, encoding="utf-8") as f:
        draft = json.load(f)

    access_token = os.environ["LINKEDIN_ACCESS_TOKEN"]
    person_urn = get_person_urn(access_token)
    image_urn = upload_image(access_token, person_urn, image_path)
    post_id = create_post(access_token, person_urn, draft["post_text"], image_urn)

    print(f"Paylaşıldı. Post ID: {post_id}")


if __name__ == "__main__":
    main()