import json
import re
from collections import defaultdict


def load_rules():
    with open("data/rules.json", "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_text(text):
    """
    아주 간단한 정규화 함수.
    추후 형태소 분석기나 Gemini 보조 정규화로 확장 가능.
    """
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def analyze_text(text):
    rules = load_rules()
    text = normalize_text(text)

    scores = defaultdict(int)
    matched_keywords = []
    detected_groups = set()

    # 1. 키워드 그룹 탐지 및 점수 합산
    for group in rules["keyword_groups"]:
        group_id = group["group_id"]
        group_label = group["group_label"]

        for keyword in group["keywords"]:
            if keyword in text:
                detected_groups.add(group_id)

                matched_keywords.append({
                    "keyword": keyword,
                    "group_id": group_id,
                    "group_label": group_label
                })

                for case_type, score in group["scores"].items():
                    scores[case_type] += score

    # 2. 우선순위 규칙 적용
    forced_case_types = set()

    for rule in rules["priority_rules"]:
        if_group = rule["if_group_detected"]
        must_include = rule["must_include"]

        if if_group in detected_groups:
            forced_case_types.add(must_include)

    # 3. 출력할 사건 유형 결정
    display_threshold = rules["thresholds"]["display"]

    selected_case_types = []

    for case_type, score in scores.items():
        if score >= display_threshold or case_type in forced_case_types:
            selected_case_types.append({
                "case_type": case_type,
                "label": rules["case_types"][case_type]["label"],
                "description": rules["case_types"][case_type]["description"],
                "score": score,
                "forced": case_type in forced_case_types
            })

    # 4. 점수 높은 순으로 정렬
    selected_case_types.sort(key=lambda x: x["score"], reverse=True)

    # 5. 추천 기관 중복 제거
    agency_names = []

    if "digital_sexual_crime" in detected_groups:
        for agency in rules["support_agencies"].get("digital_sexual_crime", []):
            if agency not in agency_names:
                agency_names.append(agency)

    for item in selected_case_types:
        case_type = item["case_type"]
        for agency in rules["support_agencies"].get(case_type, []):
            if agency not in agency_names:
                agency_names.append(agency)

    school_context_pending = (
        has_school_age_context(text)
        and not any(item["case_type"] == "school_violence" for item in selected_case_types)
    )

    if school_context_pending:
        for agency in rules["support_agencies"].get("school_violence", []):
            if agency not in agency_names:
                agency_names.append(agency)

    agencies = []
    agency_info = rules.get("agency_info", {})

    for agency_name in agency_names:
        info = agency_info.get(agency_name, {})
        agencies.append({
            "name": info.get("name", agency_name),
            "phone": info.get("phone"),
            "url": info.get("url"),
            "description": info.get("description", "")
        })

    # 6. 추가 질문 생성 여부 판단
    follow_up_questions = get_follow_up_questions(text, selected_case_types, detected_groups)

    return {
        "input": text,
        "matched_keywords": matched_keywords,
        "scores": dict(scores),
        "detected_groups": list(detected_groups),
        "selected_case_types": selected_case_types,
        "recommended_agency_names": agency_names,
        "recommended_agencies": agencies,
        "follow_up_questions": follow_up_questions,
        "user_message": make_user_message(selected_case_types)
    }


def get_follow_up_questions(text, selected_case_types, detected_groups):
    """
    질문은 최대 2개만 반환.
    rules.json의 질문 은행에서 우선순위가 높은 질문을 선택.
    """
    rules = load_rules()
    question_policy = rules.get("follow_up_question_policy", {})
    question_bank = rules.get("follow_up_question_bank", {})
    max_questions = question_policy.get("max_questions", 2)

    candidates = []
    selected_type_ids = [item["case_type"] for item in selected_case_types]
    region_exists = has_region(text)
    school_age_context_exists = has_school_age_context(text)

    if "threat_danger" in detected_groups and "emergency_risk" not in selected_type_ids:
        selected_type_ids.insert(0, "emergency_risk")

    for type_index, case_type in enumerate(selected_type_ids):
        for question_item in question_bank.get(case_type, []):
            if question_item.get("condition") == "region" and region_exists:
                continue
            if question_item.get("condition") == "school_age_context" and not school_age_context_exists:
                continue

            candidates.append({
                "case_type": case_type,
                "type_index": type_index,
                **question_item
            })

    if not candidates:
        for question_item in question_bank.get("victim_support", []):
            if question_item.get("condition") == "region" and region_exists:
                continue
            if question_item.get("condition") == "school_age_context" and not school_age_context_exists:
                continue

            candidates.append({
                "case_type": "victim_support",
                "type_index": len(selected_type_ids),
                **question_item
            })

    candidates.sort(key=lambda item: (item.get("priority", 99), item["type_index"]))

    questions = []
    seen_questions = set()

    for candidate in candidates:
        question = candidate["question"]

        if question in seen_questions:
            continue

        questions.append(question)
        seen_questions.add(question)

        if len(questions) >= max_questions:
            break

    return questions


def has_school_age_context(text):
    school_context_keywords = [
        "학교", "초등학교", "중학교", "고등학교", "초등학생", "중학생", "고등학생",
        "같은 반", "반 친구", "반 애들", "담임", "교실", "급식실", "학년",
        "학교폭력", "학폭", "선배", "후배"
    ]

    return any(keyword in text for keyword in school_context_keywords)


def has_region(text):
    regions = [
        "서울", "인천", "부산", "대구", "광주", "대전", "울산", "세종",
        "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"
    ]

    return any(region in text for region in regions)


def make_user_message(selected_case_types):
    if not selected_case_types:
        return "입력하신 내용만으로는 상담 분야를 명확히 분류하기 어렵습니다."

    labels = [item["label"] for item in selected_case_types]

    return "입력하신 내용은 다음 상담 분야와 관련될 수 있습니다: " + ", ".join(labels)


if __name__ == "__main__":
    test_text = "주먹을 휘두르고 목을 졸랐어요 그러면서 몸을 밀착해서 제 몸을 더듬었어요"
    result = analyze_text(test_text)

    print(json.dumps(result, ensure_ascii=False, indent=2))
