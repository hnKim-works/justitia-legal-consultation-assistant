import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
import os
import time
from math import ceil
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

load_dotenv()

API_URL = os.getenv("API_URL")
SERVICE_KEY = os.getenv("SERVICE_KEY")


def mask_service_key(url):
    parts = urlsplit(url)
    query = []

    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "serviceKey":
            value = f"{value[:4]}...{value[-4:]}" if len(value) > 8 else "***"
        query.append((key, value))

    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def parse_lawyer_items(root):
    results = []

    for item in root.findall(".//item"):
        results.append({
            "state": item.findtext("State"),
            "city": item.findtext("City"),
            "village": item.findtext("Village"),
            "area_note": item.findtext("AreaNote"),
            "attorney": item.findtext("Attorney"),
            "attorney_note": item.findtext("AttorneyNote"),
            "city_public_servant": item.findtext("CityPublicServant"),
            "city_serv_duty": item.findtext("CityServDuty"),
            "village_public_servant": item.findtext("VillagePublicServant"),
            "village_serv_duty": item.findtext("VillageServDuty")
        })

    return results


def normalize_region_text(text):
    return (text or "").replace(" ", "").strip()


def make_region_label(lawyer):
    return " ".join(
        value for value in [
            lawyer.get("state"),
            lawyer.get("city"),
            lawyer.get("village")
        ]
        if value
    )


@lru_cache(maxsize=1)
def fetch_village_lawyers(page_no=1, num_of_rows=1000):
    if not API_URL:
        raise RuntimeError("API_URL이 설정되지 않았습니다. .env를 확인하세요.")
    if not SERVICE_KEY:
        raise RuntimeError("서비스키가 설정되지 않았습니다. .env를 확인하세요.")

    params = {
        "serviceKey": SERVICE_KEY,
        "pageNo": str(page_no),
        "numOfRows": str(num_of_rows)
    }

    def fetch_page(page):
        params["pageNo"] = str(page)

        last_error = None

        for attempt in range(3):
            try:
                response = requests.get(API_URL, params=params, timeout=15)
            except requests.RequestException as error:
                request = getattr(error, "request", None)
                request_url = mask_service_key(request.url) if request else API_URL
                last_error = RuntimeError(f"마을변호사 API 연결 실패: {request_url}")
            else:
                response.encoding = "utf-8"

                if response.status_code == 200 and response.text.strip().startswith("<"):
                    return ET.fromstring(response.text)

                if response.status_code != 200:
                    last_error = Exception(
                        f"API 요청 실패: status={response.status_code}, body={response.text[:200]}"
                    )
                else:
                    last_error = Exception("XML 응답이 아닙니다. API_URL 또는 serviceKey를 확인하세요.")

            time.sleep(0.4 * (attempt + 1))

        raise last_error

    first_root = fetch_page(page_no)
    total_count = int(first_root.findtext(".//totalCount") or 0)
    total_pages = ceil(total_count / num_of_rows)
    results = parse_lawyer_items(first_root)

    for page in range(page_no + 1, total_pages + 1):
        results.extend(parse_lawyer_items(fetch_page(page)))

    return results


def filter_by_region(region):
    lawyers = fetch_village_lawyers()

    filtered = []

    for lawyer in lawyers:
        state = lawyer.get("state") or ""
        city = lawyer.get("city") or ""

        if region in state or region in city:
            filtered.append(lawyer)

    return filtered


def find_lawyers_by_region(region_text, limit=3):
    normalized_text = normalize_region_text(region_text)
    if not normalized_text:
        return []

    matches = []

    for lawyer in fetch_village_lawyers():
        state = lawyer.get("state") or ""
        city = lawyer.get("city") or ""
        village = lawyer.get("village") or ""

        state_match = state and state in normalized_text
        city_match = city and normalize_region_text(city) in normalized_text
        village_match = village and normalize_region_text(village) in normalized_text

        # A province/city name alone is too broad for a useful village lawyer match.
        if not city_match and not village_match:
            continue

        score = 0
        if state_match:
            score += 2
        if city_match:
            score += 4
        if village_match:
            score += 8

        matches.append((score, lawyer))

    matches.sort(key=lambda item: item[0], reverse=True)

    recommendations = []
    seen = set()

    for _, lawyer in matches:
        key = (
            lawyer.get("state"),
            lawyer.get("city"),
            lawyer.get("village"),
            lawyer.get("attorney")
        )
        if key in seen:
            continue

        seen.add(key)
        recommendations.append({
            **lawyer,
            "region_label": make_region_label(lawyer)
        })

        if len(recommendations) >= limit:
            break

    return recommendations


if __name__ == "__main__":
    print(filter_by_region("인천"))
