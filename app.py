from flask import Flask, render_template, request, Response
import re
from gemini_helper import (
    answer_final_user_question,
    generate_case_summary,
    generate_follow_up_questions,
    generate_guidance_response
)
from weighted_classifier import analyze_text
from village_lawyer_api import find_lawyers_by_region
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)


REGION_HINTS = [
    "서울", "인천", "부산", "대구", "광주", "대전", "울산", "세종",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"
]


def has_region_hint(text):
    normalized = (text or "").replace(" ", "")

    if any(region in normalized for region in REGION_HINTS):
        return True

    return bool(re.search(r"[가-힣]+(시|군|구|읍|면|동)", normalized))


def get_lawyer_recommendations(user_text, region_text=""):
    search_text = f"{user_text} {region_text}".strip()

    try:
        return find_lawyers_by_region(search_text), None
    except Exception as error:
        print(f"마을변호사 API 조회 실패: {error}")
        return [], "마을변호사 공공데이터 조회가 일시적으로 실패했습니다. 잠시 후 다시 시도하거나 관할 행정복지센터에 문의해 주세요."


@app.route("/robots.txt", methods=["GET"])
def robots():
    return Response("User-agent: *\nDisallow: /\n", mimetype="text/plain")


@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")


@app.route("/result", methods=["POST"])
def result():
    user_text = request.form.get("user_text", "").strip()
    region_text = request.form.get("region_text", "").strip()

    if not user_text:
        return render_template("index.html", error="상황을 입력해주세요.")

    analysis_result = analyze_text(user_text)
    analysis_result["follow_up_questions"] = generate_follow_up_questions(
        user_text,
        analysis_result
    )
    lawyer_recommendations, lawyer_lookup_error = get_lawyer_recommendations(user_text, region_text)
    search_text = f"{user_text} {region_text}".strip()
    region_required = not lawyer_recommendations and not lawyer_lookup_error and not has_region_hint(search_text)
    region_no_match = not lawyer_recommendations and not lawyer_lookup_error and has_region_hint(search_text)

    return render_template(
        "result.html",
        user_text=user_text,
        result=analysis_result,
        follow_up_answers="",
        incident_time="",
        incident_region=region_text,
        region_text=region_text,
        region_required=region_required,
        region_no_match=region_no_match,
        lawyer_lookup_error=lawyer_lookup_error,
        lawyer_recommendations=lawyer_recommendations
    )


@app.route("/guidance", methods=["POST"])
def guidance():
    user_text = request.form.get("user_text", "").strip()
    follow_up_answers = request.form.get("follow_up_answers", "").strip()
    incident_time = request.form.get("incident_time", "").strip()
    incident_region = request.form.get("incident_region", "").strip()

    if not user_text:
        return render_template("index.html", error="상황을 입력해주세요.")

    analysis_result = analyze_text(user_text)
    analysis_result["follow_up_questions"] = generate_follow_up_questions(
        user_text,
        analysis_result
    )
    lawyer_recommendations, lawyer_lookup_error = get_lawyer_recommendations(user_text, incident_region)
    search_text = f"{user_text} {incident_region}".strip()
    region_required = not lawyer_recommendations and not lawyer_lookup_error and not has_region_hint(search_text)
    region_no_match = not lawyer_recommendations and not lawyer_lookup_error and has_region_hint(search_text)

    if not follow_up_answers or not incident_time or not incident_region:
        return render_template(
            "result.html",
            user_text=user_text,
            result=analysis_result,
            follow_up_answers=follow_up_answers,
            incident_time=incident_time,
            incident_region=incident_region,
            region_text=incident_region,
            region_required=region_required,
            region_no_match=region_no_match,
            lawyer_lookup_error=lawyer_lookup_error,
            lawyer_recommendations=lawyer_recommendations,
            answer_error="추가 답변, 사건 발생 시간, 사건 발생 지역을 모두 입력해주세요."
        )

    guidance_response = generate_guidance_response(
        user_text,
        analysis_result["follow_up_questions"],
        follow_up_answers,
        incident_time,
        incident_region,
        analysis_result
    )

    return render_template(
        "guidance.html",
        user_text=user_text,
        result=analysis_result,
        follow_up_answers=follow_up_answers,
        incident_time=incident_time,
        incident_region=incident_region,
        guidance_response=guidance_response
    )


@app.route("/case-summary", methods=["POST"])
def case_summary():
    user_text = request.form.get("user_text", "").strip()
    follow_up_answers = request.form.get("follow_up_answers", "").strip()
    incident_time = request.form.get("incident_time", "").strip()
    incident_region = request.form.get("incident_region", "").strip()
    guidance_response = request.form.get("guidance_response", "").strip()
    user_extra_question = request.form.get("user_extra_question", "").strip()

    if not user_text:
        return render_template("index.html", error="상황을 입력해주세요.")

    analysis_result = analyze_text(user_text)
    analysis_result["follow_up_questions"] = generate_follow_up_questions(
        user_text,
        analysis_result
    )

    final_answer = ""

    if user_extra_question:
        final_answer = answer_final_user_question(
            user_text,
            follow_up_answers,
            guidance_response,
            user_extra_question,
            incident_time,
            incident_region,
            analysis_result
        )

    return render_template(
        "case_summary.html",
        user_text=user_text,
        result=analysis_result,
        follow_up_questions=analysis_result["follow_up_questions"],
        follow_up_answers=follow_up_answers,
        incident_time=incident_time,
        incident_region=incident_region,
        guidance_response=guidance_response,
        user_extra_question=user_extra_question,
        final_answer=final_answer,
        case_summary=generate_case_summary(
            user_text,
            follow_up_answers,
            incident_time,
            incident_region,
            guidance_response,
            final_answer
        ),
        written_at=datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y년 %m월 %d일 %H:%M")
    )


if __name__ == "__main__":
    app.run(debug=True)
