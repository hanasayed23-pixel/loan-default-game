import csv
import os
import random
import uuid
from datetime import datetime

import requests
from flask import Flask, abort, redirect, render_template, request, session, url_for
from jinja2 import DictLoader

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "loan-default-game-dev-secret-key")

# On Render.com, set DATA_DIR to the mount path of an attached persistent disk
# (e.g. /var/data) so sessions.csv survives deploys/restarts. Defaults to the
# app folder for local development.
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(DATA_DIR, exist_ok=True)
CSV_PATH = os.path.join(DATA_DIR, "sessions.csv")

# Session-result email (Resend API, since Render's free tier blocks outbound
# SMTP but allows HTTPS). The API key is never hardcoded -- set the
# RESEND_API_KEY environment variable to enable sending.
RESEND_API_URL = "https://api.resend.com/emails"
EMAIL_SENDER = "onboarding@resend.dev"
EMAIL_RECIPIENT = "hannahmohamed.sayed23@gmail.com"
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")

# Admin results dashboard (/admin?key=...). Unset by default, which keeps the
# route 404ing -- set the ADMIN_KEY environment variable to enable it.
ADMIN_KEY = os.environ.get("ADMIN_KEY")

# ---------------------------------------------------------------------------
# Case data: 2 (credit score) x 5 (situation) factorial design = 10 cases.
# Loan amount, experience, income, guarantor, field investigation, literacy,
# and beneficiary are identical across every case by design -- only the
# credit score level and the situation narrative vary.
# ---------------------------------------------------------------------------

FIXED_FIELDS = {
    "loan_amount": 100000,
    "experience_years": 5,
    "monthly_income": {"en": "4,000 EGP", "ar": "٤,٠٠٠ جنيه"},
    "guarantor": {"en": "Brother", "ar": "الأخ"},
    "field_investigation": {
        "en": "Normal reputation, no negative remarks",
        "ar": "سمعة عادية، مفيش ملاحظات سلبية",
    },
    "literacy": {"en": "Can read and write", "ar": "يقرأ ويكتب"},
    "beneficiary": {"en": "No", "ar": "لا"},
}

# Hidden default probabilities per situation x credit score level. Never
# shown to the player -- only used to determine the post-decision outcome.
SITUATIONS = [
    {
        "type": "neutral",
        "en": "Grocery store owner, looking to restock inventory.",
        "ar": "صاحب محل بقالة، عايز يجدد المخزون بتاع المحل.",
        "default_high": 0.15,
        "default_low": 0.35,
    },
    {
        "type": "legal_judgment",
        "en": "Carpentry workshop owner. Has an outstanding court judgment for an unpaid debt to a wood supplier.",
        "ar": "صاحب ورشة نجارة. عليه حكم قضائي بسبب دين متأخر لمورد خشب.",
        "default_high": 0.40,
        "default_low": 0.60,
    },
    {
        "type": "sick_child",
        "en": "Clothing shop owner. Her son needs urgent surgery, and part of the loan will go toward his treatment.",
        "ar": "صاحبة محل ملابس. ابنها محتاج عملية عاجلة، وجزء من القرض هيتصرف على العلاج.",
        "default_high": 0.25,
        "default_low": 0.45,
    },
    {
        "type": "expansion",
        "en": "Bakery owner. The business has grown steadily over the past year, and he wants to open a second branch.",
        "ar": "صاحب مخبز. المشروع بينمو بثبات من سنة، وعايز يفتح فرع تاني.",
        "default_high": 0.05,
        "default_low": 0.25,
    },
    {
        "type": "family_obligation",
        "en": "Hair salon owner. She needs part of the loan to cover her daughter's upcoming wedding expenses next month.",
        "ar": "صاحبة صالون تصفيف شعر. محتاجة جزء من القرض عشان تجهيز جواز بنتها الشهر الجاي.",
        "default_high": 0.20,
        "default_low": 0.40,
    },
]

CASES = []
_case_id = 1
for _situation in SITUATIONS:
    for _level in ("high", "low"):
        _default_prob = _situation[f"default_{_level}"]
        CASES.append({
            **FIXED_FIELDS,
            "id": _case_id,
            "situation_type": _situation["type"],
            "situation": {"en": _situation["en"], "ar": _situation["ar"]},
            "credit_score_level": _level,
            "repay_probability": 1 - _default_prob,
        })
        _case_id += 1

# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------

TRANSLATIONS = {
    "en": {
        "title": "Loan Default Game",
        "case_label": "Case {n} of {total}",
        "loan_amount": "Loan Amount",
        "egp": "EGP",
        "credit_score": "Credit Score",
        "credit_score_high": "High",
        "credit_score_low": "Low",
        "experience": "Years of Experience",
        "years_suffix": "years",
        "monthly_income": "Monthly Income",
        "beneficiary": "Third-party Beneficiary",
        "field_investigation": "Field Investigation",
        "guarantor": "Guarantor",
        "literacy": "Literacy",
        "case_column": "Case",
        "approve": "Approve Loan",
        "reject": "Reject Loan",
        "score": "Score",
        "you_approved": "You approved this loan.",
        "you_rejected": "You rejected this loan.",
        "outcome_repay": "The client REPAID the loan.",
        "outcome_default": "The client DEFAULTED on the loan.",
        "outcome": "Result",
        "outcome_repay_short": "Repaid",
        "outcome_default_short": "Defaulted",
        "points": "Points this round",
        "continue": "Continue",
        "final_title": "Game Over",
        "summary": "Summary",
        "play_again": "Play Again",
        "total_earned": "Total earned",
        "won": "KRW",
        "out_of": "out of",
        "reason_question": "What was the single most important factor in your decision?",
        "glossary_title": "What do these mean?",
        "glossary_credit_score": "Credit score: A simple High/Low rating of the applicant's past repayment reliability — High means lower default risk, Low means higher default risk.",
        "glossary_experience": "How long the applicant has run their business.",
        "glossary_monthly_income": "The applicant's reported monthly earnings.",
        "glossary_guarantor": "How close/trusted the person backing the loan is to the applicant.",
        "glossary_field_investigation": "What the bank's own visit found about the applicant's reputation and business location.",
        "glossary_beneficiary": "Whether someone else benefits from the loan besides the applicant.",
        "glossary_literacy": "Whether the applicant can read and write.",
    },
    "ar": {
        "title": "لعبة تعثر السداد",
        "case_label": "الحالة {n} من {total}",
        "loan_amount": "مبلغ القرض",
        "egp": "جنيه",
        "credit_score": "الدرجة الائتمانية",
        "credit_score_high": "مرتفعة",
        "credit_score_low": "منخفضة",
        "experience": "سنوات الخبرة",
        "years_suffix": "سنين",
        "monthly_income": "الدخل الشهري",
        "beneficiary": "مستفيد من الغير",
        "field_investigation": "تقرير المعاينة الميدانية",
        "guarantor": "الضامن",
        "literacy": "محو الأمية",
        "case_column": "الحالة",
        "approve": "موافقة على القرض",
        "reject": "رفض القرض",
        "score": "النقط",
        "you_approved": "انت وافقت على القرض ده.",
        "you_rejected": "انت رفضت القرض ده.",
        "outcome_repay": "العميل سدد القرض.",
        "outcome_default": "العميل اتعثر ومسددش القرض.",
        "outcome": "النتيجة",
        "outcome_repay_short": "سدد",
        "outcome_default_short": "اتعثر",
        "points": "نقط الجولة دي",
        "continue": "كمل",
        "final_title": "خلصت اللعبة",
        "summary": "ملخص",
        "play_again": "العب تاني",
        "total_earned": "إجمالي المكسب",
        "won": "وون",
        "out_of": "من أصل",
        "reason_question": "إيه أهم عامل أثر في قرارك؟",
        "glossary_title": "الكلمات دي معناها إيه؟",
        "glossary_credit_score": "الدرجة الائتمانية: تقييم بسيط (مرتفعة/منخفضة) لموثوقية سداد العميل في الماضي — مرتفعة تعني احتمال تعثر أقل، منخفضة تعني احتمال تعثر أعلى.",
        "glossary_experience": "من إمتى وهو شغال في مشروعه.",
        "glossary_monthly_income": "دخل العميل المُصرَّح بيه شهريًا.",
        "glossary_guarantor": "مدى قرب/ثقة الشخص الضامن للقرض من العميل.",
        "glossary_field_investigation": "اللي البنك لقاه بنفسه من زيارة سمعة العميل ومكان مشروعه.",
        "glossary_beneficiary": "هل فيه حد تاني بيستفيد من القرض غير العميل نفسه.",
        "glossary_literacy": "هل العميل يعرف يقرأ ويكتب.",
    },
}

CASES_BY_ID = {c["id"]: c for c in CASES}

SCORE_MATRIX = {
    ("approve", "repay"): 100,
    ("approve", "default"): -100,
    ("reject", "repay"): -50,
    ("reject", "default"): 50,
}

# Reason options shown after each decision, before the outcome is revealed.
REASON_OPTIONS = [
    {"id": "credit_score", "en": "Credit score", "ar": "التصنيف الائتماني"},
    {"id": "experience", "en": "Years of business experience", "ar": "سنين الخبرة في النشاط"},
    {"id": "monthly_income", "en": "Monthly income", "ar": "الدخل الشهري"},
    {"id": "guarantor", "en": "Guarantor relationship", "ar": "علاقة الضامن"},
    {
        "id": "field_investigation",
        "en": "Field investigation notes (reputation/location)",
        "ar": "تقرير المعاينة الميدانية (السمعة/الموقع)",
    },
    {"id": "beneficiary", "en": "Existence of a third-party beneficiary", "ar": "وجود مستفيد من الغير"},
    {"id": "literacy", "en": "Literacy", "ar": "محو الأمية"},
    {
        "id": "credit_limit",
        "en": "Credit utilization and existing loan installments",
        "ar": "نسبة استخدام الائتمان وقسط القروض التانية",
    },
]
REASON_IDS = {opt["id"] for opt in REASON_OPTIONS}


def points_to_krw(points):
    # Maps -100 -> 0 KRW and +100 -> 1000 KRW, so 10 max-score cases total 10,000 KRW.
    return round(1000 * (points + 100) / 200)


def total_krw_earned(decisions):
    return sum(d.get("krw", 0) for d in decisions)


def t(key):
    lang = session.get("lang", "en")
    return TRANSLATIONS.get(lang, TRANSLATIONS["en"]).get(key, key)


app.jinja_env.globals["t"] = t

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

BASE_HTML = """
<!doctype html>
<html lang="{{ 'ar' if lang == 'ar' else 'en' }}" dir="{{ 'rtl' if lang == 'ar' else 'ltr' }}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ t('title') }}</title>
<style>
  :root {
    --bg: #0f172a;
    --card: #1e293b;
    --card-border: #334155;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --green: #22c55e;
    --red: #ef4444;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; background: var(--bg); color: var(--text);
    font-family: 'Segoe UI', Tahoma, Arial, sans-serif;
    display: flex; flex-direction: column; align-items: center; padding: 24px 16px;
  }
  .topbar { width: 100%; max-width: 720px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
  .title { font-size: 1.3rem; font-weight: 700; }
  .score-badge { background: var(--card); border: 1px solid var(--card-border); padding: 8px 16px; border-radius: 999px; font-weight: 600; }
  .card { background: var(--card); border: 1px solid var(--card-border); border-radius: 16px; padding: 28px; max-width: 720px; width: 100%; box-shadow: 0 8px 24px rgba(0,0,0,.3); }
  .progress { width: 100%; max-width: 720px; height: 8px; background: var(--card-border); border-radius: 999px; margin-bottom: 20px; overflow: hidden; }
  .progress-fill { height: 100%; background: var(--accent); transition: width .3s; }
  h1, h2 { margin-top: 0; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 24px; margin: 20px 0; }
  @media (max-width: 600px) { .grid { grid-template-columns: 1fr; } }
  .field-label { color: var(--muted); font-size: .8rem; text-transform: uppercase; letter-spacing: .03em; }
  .field-value { font-size: 1.02rem; font-weight: 500; }
  .actions { display: flex; gap: 16px; margin-top: 24px; }
  button, .btn { flex: 1; padding: 14px; border: none; border-radius: 10px; font-size: 1.05rem; font-weight: 700; cursor: pointer; color: #fff; text-align: center; text-decoration: none; display: inline-block; }
  .btn-approve { background: var(--green); }
  .btn-reject { background: var(--red); }
  .btn-continue { background: var(--accent); color: #0f172a; }
  .btn-lang { background: var(--card); border: 1px solid var(--card-border); color: var(--text); }
  .outcome-repay { color: var(--green); font-weight: 700; }
  .outcome-default { color: var(--red); font-weight: 700; }
  .delta-pos { color: var(--green); }
  .delta-neg { color: var(--red); }
  table { width: 100%; border-collapse: collapse; margin-top: 16px; }
  th, td { padding: 8px 10px; border-bottom: 1px solid var(--card-border); text-align: {{ 'right' if lang == 'ar' else 'left' }}; font-size: .92rem; }
  .lang-row { display: flex; gap: 16px; margin-top: 24px; }
  .final-score { font-size: 2.6rem; font-weight: 800; text-align: center; margin: 16px 0; }
  .final-out-of { text-align: center; margin-top: -10px; }
  .muted { color: var(--muted); }
  .score-line { font-size: .85rem; }
  .reason-options { display: flex; flex-direction: column; gap: 10px; margin-top: 20px; }
  .reason-option { display: flex; align-items: center; gap: 10px; background: var(--bg); border: 1px solid var(--card-border); border-radius: 10px; padding: 12px 14px; cursor: pointer; }
  .reason-option input { width: 18px; height: 18px; accent-color: var(--accent); }
  .reason-option span { font-size: 1rem; }
  .glossary { margin: 4px 0 20px; }
  .glossary summary { cursor: pointer; color: var(--accent); font-weight: 600; font-size: .92rem; user-select: none; }
  .glossary ul { margin: 10px 0 0; padding-inline-start: 18px; }
  .glossary li { margin-bottom: 6px; font-size: .88rem; color: var(--muted); }
  .glossary li strong { color: var(--text); }
</style>
{% block head_extra %}{% endblock %}
</head>
<body>
{% block body %}{% endblock %}
</body>
</html>
"""

LANGUAGE_HTML = """
{% extends 'base.html' %}
{% block body %}
<div class="topbar">
  <div class="title">Loan Default Game / لعبة تعثر السداد</div>
</div>
<div class="card">
  <h1>Select Language / اختار اللغة</h1>
  <p class="muted">
    Review 10 loan applications and decide whether to approve or reject each one.<br>
    راجع ١٠ طلبات قروض وقرر توافق ولا ترفض كل واحد فيهم.
  </p>
  <div class="lang-row">
    <a class="btn btn-lang" href="{{ url_for('set_language', lang='en') }}">English</a>
    <a class="btn btn-lang" href="{{ url_for('set_language', lang='ar') }}">المصري</a>
  </div>
</div>
{% endblock %}
"""

CASE_HTML = """
{% extends 'base.html' %}
{% block body %}
<div class="topbar">
  <div class="title">{{ t('title') }}</div>
  <div class="score-badge">{{ t('score') }}: {{ score }}<div class="score-line muted">{{ t('total_earned') }}: {{ total_krw }} {{ t('won') }}</div></div>
</div>
<div class="progress"><div class="progress-fill" style="width: {{ (index / total * 100) | round(1) }}%;"></div></div>
<div class="card">
  <h2 class="muted">{{ t('case_label').format(n=index + 1, total=total) }}</h2>
  <h1>{{ case.situation[lang] }}</h1>
  <details class="glossary">
    <summary>{{ t('glossary_title') }}</summary>
    <ul>
      <li><strong>{{ t('credit_score') }}:</strong> {{ t('glossary_credit_score') }}</li>
      <li><strong>{{ t('experience') }}:</strong> {{ t('glossary_experience') }}</li>
      <li><strong>{{ t('monthly_income') }}:</strong> {{ t('glossary_monthly_income') }}</li>
      <li><strong>{{ t('guarantor') }}:</strong> {{ t('glossary_guarantor') }}</li>
      <li><strong>{{ t('field_investigation') }}:</strong> {{ t('glossary_field_investigation') }}</li>
      <li><strong>{{ t('beneficiary') }}:</strong> {{ t('glossary_beneficiary') }}</li>
      <li><strong>{{ t('literacy') }}:</strong> {{ t('glossary_literacy') }}</li>
    </ul>
  </details>
  <div class="grid">
    <div>
      <div class="field-label">{{ t('loan_amount') }}</div>
      <div class="field-value">{{ '{:,}'.format(case.loan_amount) }} {{ t('egp') }}</div>
    </div>
    <div>
      <div class="field-label">{{ t('credit_score') }}</div>
      <div class="field-value">{{ t('credit_score_high') if case.credit_score_level == 'high' else t('credit_score_low') }}</div>
    </div>
    <div>
      <div class="field-label">{{ t('experience') }}</div>
      <div class="field-value">{{ case.experience_years }} {{ t('years_suffix') }}</div>
    </div>
    <div>
      <div class="field-label">{{ t('monthly_income') }}</div>
      <div class="field-value">{{ case.monthly_income[lang] }}</div>
    </div>
    <div>
      <div class="field-label">{{ t('beneficiary') }}</div>
      <div class="field-value">{{ case.beneficiary[lang] }}</div>
    </div>
    <div>
      <div class="field-label">{{ t('field_investigation') }}</div>
      <div class="field-value">{{ case.field_investigation[lang] }}</div>
    </div>
    <div>
      <div class="field-label">{{ t('guarantor') }}</div>
      <div class="field-value">{{ case.guarantor[lang] }}</div>
    </div>
    <div>
      <div class="field-label">{{ t('literacy') }}</div>
      <div class="field-value">{{ case.literacy[lang] }}</div>
    </div>
  </div>
  <form method="post" action="{{ url_for('decide') }}" class="actions">
    <button type="submit" name="decision" value="approve" class="btn-approve">{{ t('approve') }}</button>
    <button type="submit" name="decision" value="reject" class="btn-reject">{{ t('reject') }}</button>
  </form>
</div>
{% endblock %}
"""

REASON_HTML = """
{% extends 'base.html' %}
{% block body %}
<div class="topbar">
  <div class="title">{{ t('title') }}</div>
  <div class="score-badge">{{ t('score') }}: {{ score }}<div class="score-line muted">{{ t('total_earned') }}: {{ total_krw }} {{ t('won') }}</div></div>
</div>
<div class="card">
  <h2 class="muted">{{ t('case_label').format(n=index + 1, total=total) }} &mdash; {{ case_desc }}</h2>
  <h1>{{ t('reason_question') }}</h1>
  <form method="post" action="{{ url_for('submit_reason') }}">
    <div class="reason-options">
      {% for opt in reason_options %}
      <label class="reason-option">
        <input type="radio" name="reason" value="{{ opt.id }}" required>
        <span>{{ opt.label }}</span>
      </label>
      {% endfor %}
    </div>
    <button type="submit" class="btn-continue" style="width: 100%; margin-top: 20px;">{{ t('continue') }}</button>
  </form>
</div>
{% endblock %}
"""

OUTCOME_HTML = """
{% extends 'base.html' %}
{% block body %}
<div class="topbar">
  <div class="title">{{ t('title') }}</div>
  <div class="score-badge">{{ t('score') }}: {{ score }}<div class="score-line muted">{{ t('total_earned') }}: {{ total_krw }} {{ t('won') }}</div></div>
</div>
<div class="card">
  <h2 class="muted">{{ t('case_label').format(n=result.index + 1, total=total) }} &mdash; {{ case_desc }}</h2>
  <p>{{ t('you_approved') if result.decision == 'approve' else t('you_rejected') }}</p>
  <p class="{{ 'outcome-repay' if result.outcome == 'repay' else 'outcome-default' }}">
    {{ t('outcome_repay') if result.outcome == 'repay' else t('outcome_default') }}
  </p>
  <p>{{ t('points') }}: <strong class="{{ 'delta-pos' if result.delta > 0 else 'delta-neg' }}">{{ '+' if result.delta > 0 else '' }}{{ result.delta }}</strong></p>
  <form method="post" action="{{ url_for('next_case') }}">
    <button type="submit" class="btn-continue" style="width: 100%;">{{ t('continue') }}</button>
  </form>
</div>
{% endblock %}
"""

FINAL_HTML = """
{% extends 'base.html' %}
{% block body %}
<div class="topbar">
  <div class="title">{{ t('title') }}</div>
</div>
<div class="card">
  <h1>{{ t('final_title') }}</h1>
  <div class="final-score">{{ total_krw }} {{ t('won') }}</div>
  <p class="muted final-out-of">{{ t('out_of') }} 10,000 {{ t('won') }}</p>
  <h2>{{ t('summary') }}</h2>
  <table>
    <tr>
      <th>#</th>
      <th>{{ t('case_column') }}</th>
      <th>{{ t('approve') }}/{{ t('reject') }}</th>
      <th>{{ t('outcome') }}</th>
      <th>{{ t('points') }}</th>
    </tr>
    {% for d in decisions %}
    <tr>
      <td>{{ loop.index }}</td>
      <td>{{ d.situation }}</td>
      <td>{{ t('approve') if d.decision == 'approve' else t('reject') }}</td>
      <td class="{{ 'outcome-repay' if d.outcome == 'repay' else 'outcome-default' }}">
        {{ t('outcome_repay_short') if d.outcome == 'repay' else t('outcome_default_short') }}
      </td>
      <td class="{{ 'delta-pos' if d.delta > 0 else 'delta-neg' }}">{{ '+' if d.delta > 0 else '' }}{{ d.delta }}</td>
    </tr>
    {% endfor %}
  </table>
  <form method="post" action="{{ url_for('restart') }}" style="margin-top: 24px;">
    <button type="submit" class="btn-continue" style="width: 100%;">{{ t('play_again') }}</button>
  </form>
</div>
{% endblock %}
"""

ADMIN_HTML = """
{% extends 'base.html' %}
{% block head_extra %}
<meta http-equiv="refresh" content="30">
{% endblock %}
{% block body %}
<div class="topbar">
  <div class="title">Loan Default Game &mdash; Admin Dashboard</div>
</div>
<div class="card" style="max-width: 1000px;">
  <p class="muted">Auto-refreshes every 30 seconds.</p>

  <h2>Summary</h2>
  <div class="grid">
    <div>
      <div class="field-label">Total sessions completed</div>
      <div class="field-value">{{ total_sessions }}</div>
    </div>
    <div>
      <div class="field-label">Average KRW earned</div>
      <div class="field-value">{{ avg_krw }}</div>
    </div>
    <div>
      <div class="field-label">Average total score</div>
      <div class="field-value">{{ avg_score }}</div>
    </div>
  </div>

  <h2>Approval rate: credit score &times; situation</h2>
  <div style="overflow-x: auto;">
  <table>
    <tr>
      <th>Credit score</th>
      {% for stype in situation_types %}<th>{{ stype }}</th>{% endfor %}
    </tr>
    {% for row in crosstab_rows %}
    <tr>
      <td>{{ 'High' if row.level == 'high' else 'Low' }}</td>
      {% for cell in row.cells %}
      <td>
        {% if cell.pct is not none %}{{ cell.pct }}%{% else %}&mdash;{% endif %}
        <span class="muted">(n={{ cell.n }})</span>
      </td>
      {% endfor %}
    </tr>
    {% endfor %}
  </table>
  </div>

  <h2>Reason selected (all decisions, all sessions)</h2>
  <table>
    <tr><th>Reason</th><th>Times selected</th></tr>
    {% for r in reason_table %}
    <tr><td>{{ r.label }}</td><td>{{ r.count }}</td></tr>
    {% endfor %}
  </table>

  <h2>All completed sessions ({{ total_sessions }})</h2>
  <div style="overflow-x: auto;">
  <table>
    <tr>
      <th>Timestamp</th>
      <th>Session ID</th>
      <th>Total KRW</th>
      <th>Total score</th>
    </tr>
    {% for s in sessions_table %}
    <tr>
      <td>{{ s.timestamp }}</td>
      <td>{{ s.session_id }}</td>
      <td>{{ s.total_krw }}</td>
      <td>{{ s.total_score }}</td>
    </tr>
    {% endfor %}
  </table>
  </div>
</div>
{% endblock %}
"""

app.jinja_env.loader = DictLoader({
    "base.html": BASE_HTML,
    "language.html": LANGUAGE_HTML,
    "case.html": CASE_HTML,
    "reason.html": REASON_HTML,
    "outcome.html": OUTCOME_HTML,
    "final.html": FINAL_HTML,
    "admin.html": ADMIN_HTML,
})

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def resolve_decisions(decisions, lang):
    return [
        {
            "situation": CASES_BY_ID[d["case_id"]]["situation"][lang],
            "situation_type": CASES_BY_ID[d["case_id"]]["situation_type"],
            "credit_score_level": CASES_BY_ID[d["case_id"]]["credit_score_level"],
            "decision": d["decision"],
            "outcome": d["outcome"],
            "delta": d["delta"],
            "krw": d.get("krw", 0),
            "reason": d.get("reason", ""),
        }
        for d in decisions
    ]


# ---------------------------------------------------------------------------
# CSV logging
# ---------------------------------------------------------------------------


def save_session_to_csv():
    lang = session.get("lang", "en")
    resolved = resolve_decisions(session.get("decisions", []), lang)
    fieldnames = ["timestamp", "session_id", "language", "total_score", "total_krw"]
    for i in range(1, len(CASES) + 1):
        fieldnames += [
            f"case{i}_situation_type",
            f"case{i}_credit_score_level",
            f"case{i}_situation",
            f"case{i}_decision",
            f"case{i}_outcome",
            f"case{i}_points",
            f"case{i}_krw",
            f"case{i}_reason",
        ]

    file_exists = os.path.isfile(CSV_PATH)
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "session_id": session.get("session_id", ""),
        "language": lang,
        "total_score": session.get("score", 0),
        "total_krw": total_krw_earned(session.get("decisions", [])),
    }
    for i, d in enumerate(resolved, start=1):
        row[f"case{i}_situation_type"] = d["situation_type"]
        row[f"case{i}_credit_score_level"] = d["credit_score_level"]
        row[f"case{i}_situation"] = d["situation"]
        row[f"case{i}_decision"] = d["decision"]
        row[f"case{i}_outcome"] = d["outcome"]
        row[f"case{i}_points"] = d["delta"]
        row[f"case{i}_krw"] = d["krw"]
        row[f"case{i}_reason"] = d["reason"]

    with open(CSV_PATH, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def read_sessions_csv():
    if not os.path.isfile(CSV_PATH):
        return []
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Email notification
# ---------------------------------------------------------------------------


def send_session_email(lang, score, total_krw, session_id, resolved_decisions):
    if not RESEND_API_KEY:
        app.logger.warning("RESEND_API_KEY not set; skipping session result email.")
        return

    lines = [
        f"Language: {lang}",
        f"Session ID: {session_id}",
        f"Total score: {score}",
        f"Total KRW earned: {total_krw} / 10000",
        "",
        "Decisions:",
    ]
    for i, d in enumerate(resolved_decisions, start=1):
        lines.append(
            f"{i}. [{d['situation_type']}/{d['credit_score_level']}] {d['situation']} - "
            f"{d['decision']} - {d['outcome']} - {d['delta']:+d} "
            f"({d['krw']} KRW) - reason: {d['reason']}"
        )

    try:
        response = requests.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": EMAIL_SENDER,
                "to": [EMAIL_RECIPIENT],
                "subject": f"Loan Default Game session result - {total_krw} KRW (score {score})",
                "text": "\n".join(lines),
            },
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException:
        app.logger.exception("Failed to send session result email")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    session.clear()
    return render_template("language.html", lang="en")


@app.route("/set-language/<lang>")
def set_language(lang):
    if lang not in ("en", "ar"):
        lang = "en"
    session.clear()
    session["lang"] = lang
    session["session_id"] = str(uuid.uuid4())
    session["score"] = 0
    session["index"] = 0
    session["decisions"] = []
    session["outcomes"] = [
        "repay" if random.random() < c["repay_probability"] else "default" for c in CASES
    ]
    case_order = list(range(len(CASES)))
    random.shuffle(case_order)
    session["case_order"] = case_order
    return redirect(url_for("show_case"))


@app.route("/case")
def show_case():
    lang = session.get("lang")
    if not lang:
        return redirect(url_for("index"))
    index = session.get("index", 0)
    if index >= len(CASES):
        return redirect(url_for("final"))
    case_idx = session["case_order"][index]
    return render_template(
        "case.html",
        lang=lang,
        case=CASES[case_idx],
        index=index,
        total=len(CASES),
        score=session.get("score", 0),
        total_krw=total_krw_earned(session.get("decisions", [])),
    )


@app.route("/decide", methods=["POST"])
def decide():
    lang = session.get("lang")
    if not lang:
        return redirect(url_for("index"))
    index = session.get("index", 0)
    if index >= len(CASES):
        return redirect(url_for("final"))

    decision = request.form.get("decision")
    if decision not in ("approve", "reject"):
        return redirect(url_for("show_case"))

    case_idx = session["case_order"][index]
    case = CASES[case_idx]
    outcome = session["outcomes"][case_idx]
    delta = SCORE_MATRIX[(decision, outcome)]
    krw = points_to_krw(delta)

    session["score"] = session.get("score", 0) + delta

    decisions = session.get("decisions", [])
    entry = {
        "case_id": case["id"],
        "decision": decision,
        "outcome": outcome,
        "delta": delta,
        "krw": krw,
        "reason": None,
    }
    decisions.append(entry)
    session["decisions"] = decisions

    result = dict(entry)
    result["index"] = index
    session["last_result"] = result

    return redirect(url_for("show_reason"))


@app.route("/reason")
def show_reason():
    lang = session.get("lang")
    result = session.get("last_result")
    if not lang or not result:
        return redirect(url_for("index"))
    case_desc = CASES_BY_ID[result["case_id"]]["situation"][lang]
    reason_options = [{"id": opt["id"], "label": opt[lang]} for opt in REASON_OPTIONS]
    return render_template(
        "reason.html",
        lang=lang,
        index=result["index"],
        case_desc=case_desc,
        total=len(CASES),
        score=session.get("score", 0),
        total_krw=total_krw_earned(session.get("decisions", [])),
        reason_options=reason_options,
    )


@app.route("/reason", methods=["POST"])
def submit_reason():
    lang = session.get("lang")
    result = session.get("last_result")
    if not lang or not result:
        return redirect(url_for("index"))

    reason = request.form.get("reason")
    if reason not in REASON_IDS:
        return redirect(url_for("show_reason"))

    decisions = session.get("decisions", [])
    if decisions:
        decisions[-1]["reason"] = reason
        session["decisions"] = decisions

    result["reason"] = reason
    session["last_result"] = result

    return redirect(url_for("show_outcome"))


@app.route("/outcome")
def show_outcome():
    lang = session.get("lang")
    result = session.get("last_result")
    if not lang or not result:
        return redirect(url_for("index"))
    if not result.get("reason"):
        return redirect(url_for("show_reason"))
    case_desc = CASES_BY_ID[result["case_id"]]["situation"][lang]
    return render_template(
        "outcome.html",
        lang=lang,
        result=result,
        case_desc=case_desc,
        total=len(CASES),
        score=session.get("score", 0),
        total_krw=total_krw_earned(session.get("decisions", [])),
    )


@app.route("/next", methods=["POST"])
def next_case():
    lang = session.get("lang")
    if not lang:
        return redirect(url_for("index"))
    session["index"] = session.get("index", 0) + 1
    if session["index"] >= len(CASES):
        save_session_to_csv()
        send_session_email(
            lang,
            session.get("score", 0),
            total_krw_earned(session.get("decisions", [])),
            session.get("session_id", ""),
            resolve_decisions(session.get("decisions", []), lang),
        )
        return redirect(url_for("final"))
    return redirect(url_for("show_case"))


@app.route("/final")
def final():
    lang = session.get("lang")
    if not lang:
        return redirect(url_for("index"))
    decisions = session.get("decisions", [])
    if len(decisions) < len(CASES):
        return redirect(url_for("show_case"))
    return render_template(
        "final.html",
        lang=lang,
        decisions=resolve_decisions(decisions, lang),
        score=session.get("score", 0),
        total_krw=total_krw_earned(decisions),
    )


@app.route("/restart", methods=["POST"])
def restart():
    session.clear()
    return redirect(url_for("index"))


@app.route("/admin")
def admin_dashboard():
    # Wrong/missing key looks identical to a route that doesn't exist.
    if not ADMIN_KEY or request.args.get("key") != ADMIN_KEY:
        abort(404)

    rows = read_sessions_csv()

    def to_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    total_sessions = len(rows)
    avg_krw = round(sum(to_float(r.get("total_krw")) for r in rows) / total_sessions, 1) if total_sessions else 0
    avg_score = round(sum(to_float(r.get("total_score")) for r in rows) / total_sessions, 1) if total_sessions else 0

    sessions_table = sorted(
        (
            {
                "timestamp": r.get("timestamp", ""),
                "session_id": r.get("session_id", ""),
                "total_krw": r.get("total_krw", ""),
                "total_score": r.get("total_score", ""),
            }
            for r in rows
        ),
        key=lambda r: r["timestamp"],
        reverse=True,
    )

    situation_types = [s["type"] for s in SITUATIONS]
    credit_levels = ["high", "low"]
    crosstab = {
        level: {stype: {"approve": 0, "total": 0} for stype in situation_types}
        for level in credit_levels
    }
    reason_counts = {opt["id"]: 0 for opt in REASON_OPTIONS}

    for r in rows:
        for i in range(1, len(CASES) + 1):
            level = r.get(f"case{i}_credit_score_level")
            stype = r.get(f"case{i}_situation_type")
            decision = r.get(f"case{i}_decision")
            reason = r.get(f"case{i}_reason")
            if level in crosstab and stype in crosstab[level]:
                crosstab[level][stype]["total"] += 1
                if decision == "approve":
                    crosstab[level][stype]["approve"] += 1
            if reason in reason_counts:
                reason_counts[reason] += 1

    crosstab_rows = []
    for level in credit_levels:
        cells = []
        for stype in situation_types:
            cell = crosstab[level][stype]
            pct = round(100 * cell["approve"] / cell["total"], 1) if cell["total"] else None
            cells.append({"pct": pct, "n": cell["total"]})
        crosstab_rows.append({"level": level, "cells": cells})

    reason_table = [
        {"id": opt["id"], "label": opt["en"], "count": reason_counts[opt["id"]]}
        for opt in REASON_OPTIONS
    ]

    return render_template(
        "admin.html",
        lang="en",
        total_sessions=total_sessions,
        avg_krw=avg_krw,
        avg_score=avg_score,
        sessions_table=sessions_table,
        situation_types=situation_types,
        crosstab_rows=crosstab_rows,
        reason_table=reason_table,
    )


if __name__ == "__main__":
    app.run(debug=True)
