import json
import os
from datetime import datetime, timezone
from pathlib import Path
from curl_cffi import requests as cffi_requests
import requests

FEED_PATH = Path("neb-feed.json")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

MINERS = {
    "invminer": "getrigeos/INVminer-Release",
    "official": "SilasEigen/neb",
    "axehub": "dwespl/axehub-miner",
    "wildrig": "andru-kun/wildrig-ng",
    "nebx": "nurserypool/nebx-miner",
}

SAFETRADE_URLS = [
    "https://safetrade.com/api/v2/trade/public/markets/nebusdt/tickers",
    "https://safetrade.com/api/v2/peatio/public/markets/nebusdt/tickers",
    "https://safe.trade/api/v2/trade/public/markets/nebusdt/tickers",
    "https://safe.trade/api/v2/peatio/public/markets/nebusdt/tickers",
]


def load_previous():
    if FEED_PATH.exists():
        try:
            return json.loads(FEED_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def fetch_price(prev_price):
    for url in SAFETRADE_URLS:
        try:
            r = cffi_requests.get(url, impersonate="chrome", timeout=15)
            if r.status_code != 200:
                continue
            data = r.json()
            ticker = data.get("ticker", data) if isinstance(data, dict) else {}
            last = ticker.get("last")
            if last is not None and float(last) > 0:
                change = ticker.get("price_change_percent") or ticker.get("change_24h")
                vol = ticker.get("volume") or ticker.get("vol")
                return {
                    "usd": round(float(last), 4),
                    "change_24h": str(change) if change is not None else None,
                    "volume_24h": round(float(vol), 2) if vol is not None else None,
                    "source": "SafeTrade",
                    "live": True,
                }
        except Exception:
            continue

    # Если биржа временно не ответила — сохраняем последнюю валидную цену
    if prev_price and prev_price.get("usd"):
        return {**prev_price, "live": False}
    return {"usd": 1.10, "change_24h": None, "volume_24h": None, "source": "fallback", "live": False}


def fetch_miner_release(repo):
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        r = requests.get(
            f"https://api.github.com/repos/{repo}/releases?per_page=6",
            headers=headers,
            timeout=15,
        )
        if r.status_code == 200:
            rels = r.json()
            if isinstance(rels, list) and rels:
                latest = rels[0]
                info = {
                    "version": latest.get("tag_name") or latest.get("name") or "latest",
                    "published_at": latest.get("published_at"),
                    "url": latest.get("html_url") or f"https://github.com/{repo}/releases",
                    "assets": {},
                }

                # Для INVminer ищем прямые ссылки на HiveOS, Linux CUDA13/12 и самую свежую Windows-сборку
                if repo == "getrigeos/INVminer-Release":
                    for a in latest.get("assets", []):
                        name = a.get("name", "")
                        dl = a.get("browser_download_url", "")
                        if name.endswith("linux-x86_64-cuda13.tar.gz"):
                            info["assets"]["linux_cuda13"] = dl
                        elif name.endswith("linux-x86_64-cuda12.tar.gz"):
                            info["assets"]["linux_cuda12"] = dl
                        elif name.startswith("invminer-") and name.endswith(".tar.gz") and "linux" not in name:
                            info["assets"]["hiveos"] = dl

                    for rel in rels:
                        for a in rel.get("assets", []):
                            if a.get("name", "").endswith("windows-x86_64.zip"):
                                info["assets"]["windows"] = a.get("browser_download_url")
                                info["assets"]["windows_version"] = rel.get("tag_name")
                                break
                        if "windows" in info["assets"]:
                            break
                return info

        # Если у репозитория нет Releases — берём последний тег
        r_tags = requests.get(
            f"https://api.github.com/repos/{repo}/tags?per_page=1",
            headers=headers,
            timeout=15,
        )
        if r_tags.status_code == 200 and r_tags.json():
            tag = r_tags.json()[0].get("name")
            return {
                "version": tag,
                "published_at": None,
                "url": f"https://github.com/{repo}/releases/tag/{tag}",
                "assets": {},
            }
    except Exception:
        pass
    return None


def main():
    prev = load_previous()
    prev_miners = prev.get("miners", {})

    miners_out = {}
    for key, repo in MINERS.items():
        data = fetch_miner_release(repo)
        miners_out[key] = data if data else prev_miners.get(key, {
            "version": "latest",
            "published_at": None,
            "url": f"https://github.com/{repo}/releases",
            "assets": {},
        })

    payload = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "price": fetch_price(prev.get("price")),
        "miners": miners_out,
    }

    FEED_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Updated neb-feed.json:", payload["price"], {k: v["version"] for k, v in miners_out.items()})


if __name__ == "__main__":
    main()
