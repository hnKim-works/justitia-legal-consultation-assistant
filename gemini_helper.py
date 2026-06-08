import os
import json
from difflib import SequenceMatcher

from dotenv import load_dotenv


load_dotenv()

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def get_gemini_client():
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return None

    try:
        from google import genai
    except ImportError:
        return None

    return genai.Client(api_key=api_key)


def call_gemini(prompt):
    client = get_gemini_client()

    if client is None:
        return None

    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt
        )
    except Exception as error:
        print(f"Gemini API 호출 실패: {error}")
        return None

    print("Gemini API 호출 성공")
    return getattr(response, "text", None)


def load_guidance_templates():
    try:
        with open("data/rules.json", "r", encoding="utf-8") as file:
            rules = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}

    return rules.get("guidance_templates", {})


def selected_case_labels(analysis_result):
    return [
        item.get("label", item.get("case_type", ""))
        for item in analysis_result.get("selected_case_types", [])
    ]


def generate_follow_up_questions(user_input, analysis_result):
    """
    분류기가 고른 질문을 Gemini가 자연스럽게 다듬는다.
    Gemini를 사용할 수 없으면 원문 질문을 그대로 반환한다.
    """
    classifier_questions = analysis_result.get("follow_up_questions", [])

    if not classifier_questions:
        return [
            "현재 가장 도움이 필요한 부분은 무엇인가요?",
            "상담을 원하는 지역은 어디인가요?"
        ]

    questions = classifier_questions[:2]

    if os.getenv("GEMINI_REFINE_QUESTIONS", "false").lower() != "true":
        return questions

    prompt = f"""
다음은 법률상담 준비 서비스의 추가 질문 후보입니다.
질문 후보의 목적은 유지하되, 사용자 입력에 나온 관계나 상황 표현을 반영해 더 자연스럽게 다듬어 주세요.

사용자 입력:
{user_input}

분류 결과:
{analysis_result.get("selected_case_types", [])}

질문 후보:
{chr(10).join(f"{index + 1}. {question}" for index, question in enumerate(questions))}

규칙:
- 질문 개수는 반드시 {len(questions)}개입니다.
- 새 질문을 만들지 않습니다.
- 후보 질문의 의미를 바꾸지 않습니다.
- "상대방"처럼 일반적인 표현은 사용자 입력에 나온 관계 표현으로 바꿀 수 있습니다.
- 질문 문장은 후보와 완전히 똑같이 쓰지 말고, 더 부드러운 존댓말로 다듬습니다.
- 법률 판단이나 단정적인 표현을 하지 않습니다.
- 사용자를 탓하거나 책임을 묻는 표현을 쓰지 않습니다.
- 각 질문은 한 줄씩만 출력합니다.

예시:
- 후보: 현재 안전한 장소에 계신가요?
- 출력: 지금은 안전한 곳에 계신가요?
- 후보: 상대방의 접근, 연락, 협박이 지금도 이어지고 있나요?
- 출력: 전 남자친구의 연락이나 협박이 지금도 이어지고 있나요?
"""
    gemini_text = call_gemini(prompt)

    if not gemini_text:
        return questions

    refined_questions = [
        line.strip(" -0123456789.").strip()
        for line in gemini_text.splitlines()
        if line.strip()
    ]

    if len(refined_questions) != len(questions):
        return questions

    return refined_questions[:2]


def generate_guidance_response(
    user_input,
    follow_up_questions,
    follow_up_answers,
    incident_time,
    incident_region,
    analysis_result
):
    """
    사용자가 추가 질문에 답한 뒤 Gemini가 짧은 상담 준비 안내를 생성한다.
    이 단계는 PDF 생성 전 1회만 호출하는 것을 전제로 한다.
    """
    templates = load_guidance_templates()
    template_text = "\n".join(f"- {value}" for value in templates.values())

    prompt = f"""
아래 내용은 법률상담 준비 서비스에서 사용자가 추가 질문에 답한 내용입니다.
사용자에게 지금 할 수 있는 상담 준비 안내를 짧고 구체적으로 작성해 주세요.

초기 입력:
{user_input}

분류 결과:
{selected_case_labels(analysis_result)}

초기 추가 질문:
{chr(10).join(f"- {question}" for question in follow_up_questions)}

사용자의 추가 답변:
{follow_up_answers}

사건 발생 시간:
{incident_time or "미입력"}

사건 발생 지역:
{incident_region or "미입력"}

서비스 내부 안내 템플릿:
{template_text}

작성 규칙:
- 법률 판단, 죄명 단정, 신고 강요, 승소 가능성 판단은 하지 않습니다.
- 성폭력 피해로 보이고 증거가 없거나 증거 확보가 걱정된다고 답한 경우, 문자, 통화기록, CCTV 위치, 상처 사진, 진료기록, 사건 직후 메모 등이 상담 준비 자료가 될 수 있다고 안내합니다.
- 성폭력 피해 발생 후 시간이 얼마 지나지 않은 경우, 가능하면 씻거나 옷을 세탁하기 전에 해바라기센터 또는 성폭력전담의료기관에 연락해 의료지원과 증거채취 가능 여부를 확인하라고 안내합니다.
- 현재 위험하거나 집 밖으로 나가기 어려운 상황이면 112 또는 1366 등 긴급 지원기관에 먼저 연락할 수 있다고 안내합니다.
- 사용자를 탓하거나 책임을 묻는 표현을 쓰지 않습니다.
- 4문장 이내로 작성합니다.
- 마지막 문장은 "추가로 궁금한 점이 있다면 한 번만 더 질문할 수 있습니다."로 끝냅니다.
"""
    gemini_text = call_gemini(prompt)

    if gemini_text:
        return gemini_text.strip()

    return (
        "현재 답변을 보면 안전 확인과 상담 준비가 함께 필요한 상황일 수 있습니다. "
        "증거가 없다고 느껴져도 문자, 통화기록, CCTV 위치, 상처 사진, 진료기록, 사건 직후 메모 등이 상담 준비 자료가 될 수 있습니다. "
        "현재 위험하거나 혼자 이동하기 어렵다면 112 또는 1366에 먼저 연락할 수 있습니다. "
        "추가로 궁금한 점이 있다면 한 번만 더 질문할 수 있습니다."
    )


def answer_final_user_question(
    user_input,
    follow_up_answers,
    guidance_response,
    user_question,
    incident_time,
    incident_region,
    analysis_result
):
    """
    사용자의 선택적 추가 질문에 1회만 답변한다.
    이후에는 새 질문을 만들지 않고 PDF 단계로 넘어간다.
    """
    prompt = f"""
사용자가 상담 준비 안내를 본 뒤 마지막으로 한 가지 질문을 했습니다.
아래 정보를 바탕으로 짧고 안전하게 답변해 주세요.

초기 입력:
{user_input}

분류 결과:
{selected_case_labels(analysis_result)}

추가 답변:
{follow_up_answers}

이미 제공한 안내:
{guidance_response}

사용자의 마지막 질문:
{user_question}

사건 발생 시간:
{incident_time or "미입력"}

사건 발생 지역:
{incident_region or "미입력"}

작성 규칙:
- 새 질문을 만들지 않습니다.
- 이미 제공한 안내와 같은 문장을 반복하지 않습니다.
- 마지막 질문에 직접 답하고, 이전 안내에서 빠진 보충 내용만 작성합니다.
- 법률 판단, 죄명 단정, 신고 강요, 승소 가능성 판단은 하지 않습니다.
- 현재 위험하거나 긴급한 상황이면 112 또는 1366 등 긴급 지원기관에 연락할 수 있다고 안내합니다.
- 성폭력 피해 증거와 관련된 질문이면 해바라기센터 또는 성폭력전담의료기관에서 의료지원과 증거채취 가능 여부를 확인할 수 있다고 안내합니다.
- 4문장 이내로 답변합니다.
"""
    gemini_text = call_gemini(prompt)

    if gemini_text:
        final_text = gemini_text.strip()
        similarity = SequenceMatcher(None, guidance_response, final_text).ratio()

        if similarity < 0.7:
            return final_text

    return (
        "마지막 질문에 대해서는, 지금 당장 완벽한 증거를 만들려고 하기보다 남아 있는 자료를 훼손하지 않는 것이 먼저입니다. "
        "가능하다면 대화 내용은 삭제하지 말고 캡처와 원본을 함께 남기고, 상처나 주변 상황은 날짜가 보이게 기록해 두는 방식이 도움이 될 수 있습니다. "
        "혼자 이동하기 어렵거나 위협이 계속된다면 직접 움직이기 전에 112 또는 1366에 연락해 동행이나 긴급 보호 가능성을 확인하는 편이 안전합니다."
    )


def generate_case_summary(
    user_input,
    follow_up_answers,
    incident_time="",
    incident_region="",
    guidance_response="",
    final_answer=""
):
    """
    Gemini를 사용해 상담 준비용 사건 요약을 생성한다.
    Gemini를 사용할 수 없으면 기본 템플릿 요약을 반환한다.
    """
    if guidance_response or final_answer:
        summary = f"""
초기 입력과 추가 답변을 바탕으로 상담 준비용 사건 정리문을 작성하였습니다.

초기 입력:
{user_input}

추가 답변:
{follow_up_answers}

사건 발생 시간:
{incident_time or "미입력"}

사건 발생 지역:
{incident_region or "미입력"}

상담 시 확인하면 좋을 핵심 내용:
현재 안전 여부, 상대방의 연락이나 위협 지속 여부, 남아 있는 자료의 종류, 의료지원 또는 상담기관 방문 필요성을 중심으로 정리할 수 있습니다.
"""
        return summary.strip()

    prompt = f"""
아래 내용을 바탕으로 법률상담 전에 가져갈 사건 정리문을 작성해 주세요.

초기 입력:
{user_input}

추가 답변:
{follow_up_answers}

사건 발생 시간:
{incident_time or "미입력"}

사건 발생 지역:
{incident_region or "미입력"}

작성 규칙:
- 사용자가 상담기관에 보여줄 수 있는 중립적인 요약문으로 작성합니다.
- 법률 판단, 죄명 단정, 승소 가능성 판단은 하지 않습니다.
- 확인된 사실과 아직 확인이 필요한 내용을 구분합니다.
- 피해자에게 책임을 묻는 표현을 쓰지 않습니다.
- 5문장 이내로 간결하게 작성합니다.
"""
    gemini_summary = call_gemini(prompt)

    if gemini_summary:
        return gemini_summary.strip()

    summary = f"""
입력된 내용을 기반으로 상담 방향 정리를 진행하였습니다.

초기 입력:
{user_input}

추가 답변:
{follow_up_answers}

사건 발생 시간:
{incident_time or "미입력"}

사건 발생 지역:
{incident_region or "미입력"}

위 내용을 종합하면, 사건은 {incident_time or "확인된 시간 미상"}에 {incident_region or "확인된 지역 미상"}에서 발생한 것으로 정리할 수 있습니다.
현재 상황에 대해 피해자 보호, 안전 확인 및 관련 상담기관 연계가 필요할 수 있습니다.
"""

    return summary.strip()
