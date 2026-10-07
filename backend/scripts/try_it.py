"""Quick check of your token and model, without the web app.
  python -m scripts.try_it --list     show model ids you can use
  python -m scripts.try_it            run a sample process through the real AI and save out.drawio"""
import argparse
import asyncio
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

SAMPLE = ("A customer submits a payment request. The maker prepares the supporting documents and sends them on. "
          "The approver reviews the request and checks whether the amount is within their limit. If details are missing, "
          "the request goes back to the maker. If it is within limit, compliance runs a sanctions check, and once it "
          "passes the payment is released.")


async def list_models():
    if os.getenv("PROVIDERS", "github_models").split(",")[0].strip() == "gemini":
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get("https://generativelanguage.googleapis.com/v1beta/models",
                            headers={"x-goog-api-key": os.getenv("GEMINI_API_KEY", "")}, params={"pageSize": 1000})
        r.raise_for_status()
        for m in r.json().get("models", []):
            if "generateContent" in m.get("supportedGenerationMethods", []):
                print(m["name"].removeprefix("models/"), "-", m.get("displayName", ""))
        return
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN', '')}",
               "X-GitHub-Api-Version": "2022-11-28"}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get("https://models.github.ai/catalog/models", headers=headers)
    r.raise_for_status()
    for m in r.json():
        print(m.get("id"), "-", m.get("name", ""))


async def run():
    from app.convert import to_drawio_xml
    from app.pipeline import generate_diagram
    from app.providers import build_providers_from_env
    diagram = await generate_diagram(SAMPLE, build_providers_from_env())
    print(diagram.model_dump_json(by_alias=True, indent=2))
    open("out.drawio", "w", encoding="utf-8").write(to_drawio_xml(diagram))
    print("\nSaved out.drawio. Open it at your draw.io site to see the diagram.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    asyncio.run(list_models() if ap.parse_args().list else run())
