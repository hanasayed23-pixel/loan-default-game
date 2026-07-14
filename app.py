import csv
import os
import random
import smtplib
import uuid
from datetime import datetime
from email.message import EmailMessage

from flask import Flask, redirect, render_template, request, session, url_for
from jinja2 import DictLoader

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "loan-default-game-dev-secret-key")

# On Render.com, set DATA_DIR to the mount path of an attached persistent disk
# (e.g. /var/data) so sessions.csv survives deploys/restarts. Defaults to the
# app folder for local development.
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(DATA_DIR, exist_ok=True)
CSV_PATH = os.path.join(DATA_DIR, "sessions.csv")

# Session-result email (Gmail SMTP). The app password is never hardcoded --
# set the EMAIL_APP_PASSWORD environment variable to enable sending.
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_SENDER = "hannahmohamed.sayed23@gmail.com"
EMAIL_RECIPIENT = "hannahmohamed.sayed23@gmail.com"
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")

# ---------------------------------------------------------------------------
# Case data (real cases supplied by the user)
# ---------------------------------------------------------------------------

CASES = [
    {
        "id": 1,
        "business_type": {"en": "Hair salon", "ar": "صالون حلاقة"},
        "loan_amount": 100000,
        "credit_limit_pct": 25,
        "credit_limit_note": {
            "en": "Has another 5,000 EGP loan, paying 450 EGP/month, current",
            "ar": "عنده قرض تاني ٥,٠٠٠ جنيه، بيسدد ٤٥٠ جنيه في الشهر ومنتظم في السداد",
        },
        "risk_grade": {"en": "Excellent", "ar": "ممتاز"},
        "experience_years": 6,
        "monthly_income": {"en": "5,000 EGP", "ar": "٥,٠٠٠ جنيه"},
        "beneficiary": {"en": "No third-party beneficiary", "ar": "مفيش مستفيد من الغير"},
        "field_investigation": {
            "en": "Good reputation, easy-to-reach location",
            "ar": "سمعته كويسة والمكان سهل الوصول له",
        },
        "guarantor": {"en": "Distant relation", "ar": "قريب بعيد"},
        "literacy": {"en": "Literate", "ar": "يعرف يقرا ويكتب"},
        "repay_probability": 0.90,
    },
    {
        "id": 2,
        "business_type": {"en": "Grocery store", "ar": "بقالة"},
        "loan_amount": 100000,
        "credit_limit_pct": 20,
        "credit_limit_note": {
            "en": "No other loans",
            "ar": "مفيش قروض تانية",
        },
        "risk_grade": {"en": "Excellent", "ar": "ممتاز"},
        "experience_years": 8,
        "monthly_income": {"en": "7,000 EGP", "ar": "٧,٠٠٠ جنيه"},
        "beneficiary": {"en": "No third-party beneficiary", "ar": "مفيش مستفيد من الغير"},
        "field_investigation": {
            "en": "Excellent reputation, main street location",
            "ar": "سمعة ممتازة والمحل على شارع رئيسي",
        },
        "guarantor": {"en": "Sister", "ar": "أخته"},
        "literacy": {"en": "Literate", "ar": "يعرف يقرا ويكتب"},
        "repay_probability": 0.95,
    },
    {
        "id": 3,
        "business_type": {"en": "New clothing shop", "ar": "محل ملابس جديد"},
        "loan_amount": 100000,
        "credit_limit_pct": 28,
        "credit_limit_note": {
            "en": "No other loans",
            "ar": "مفيش قروض تانية",
        },
        "risk_grade": {"en": "Excellent", "ar": "ممتاز"},
        "experience_years": 0,
        "monthly_income": {"en": "Not established (new business)", "ar": "مش محدد لسه (نشاط جديد)"},
        "beneficiary": {
            "en": "Has third-party beneficiary (brother manages the capital)",
            "ar": "فيه مستفيد من الغير (أخوه هو اللي بيدير رأس المال)",
        },
        "field_investigation": {
            "en": "Unknown reputation, remote area",
            "ar": "سمعته مش معروفة والمنطقة بعيدة",
        },
        "guarantor": {"en": "No guarantor", "ar": "مفيش ضامن"},
        "literacy": {"en": "Literate", "ar": "يعرف يقرا ويكتب"},
        "repay_probability": 0.30,
    },
    {
        "id": 4,
        "business_type": {"en": "Tailoring workshop", "ar": "ورشة خياطة"},
        "loan_amount": 100000,
        "credit_limit_pct": 90,
        "credit_limit_note": {
            "en": "Has a 5,000 EGP loan, 450 EGP/month, multiple late payments",
            "ar": "عنده قرض ٥,٠٠٠ جنيه بيسدد ٤٥٠ جنيه شهريًا لكن اتأخر في السداد أكتر من مرة",
        },
        "risk_grade": {"en": "Poor", "ar": "ضعيف"},
        "experience_years": 9,
        "monthly_income": {"en": "6,000 EGP", "ar": "٦,٠٠٠ جنيه"},
        "beneficiary": {"en": "No third-party beneficiary", "ar": "مفيش مستفيد من الغير"},
        "field_investigation": {
            "en": "Very good reputation, known for seasonal work, easy to reach",
            "ar": "سمعة كويسة جدًا ومعروف بشغل موسمي والمكان سهل الوصول له",
        },
        "guarantor": {"en": "Wife", "ar": "مراته"},
        "literacy": {"en": "Literate", "ar": "يعرف يقرا ويكتب"},
        "repay_probability": 0.55,
    },
    {
        "id": 5,
        "business_type": {"en": "Cigarette kiosk", "ar": "كشك سجاير"},
        "loan_amount": 100000,
        "credit_limit_pct": 95,
        "credit_limit_note": {
            "en": "Has a 5,000 EGP loan, multiple late payments",
            "ar": "عنده قرض ٥,٠٠٠ جنيه واتأخر في السداد أكتر من مرة",
        },
        "risk_grade": {"en": "Poor", "ar": "ضعيف"},
        "experience_years": 0,
        "monthly_income": {"en": "Not established (new business)", "ar": "مش محدد لسه (نشاط جديد)"},
        "beneficiary": {
            "en": "Has third-party beneficiary (a relative asked him to take the loan to pay off a personal debt)",
            "ar": "فيه مستفيد من الغير (قريبه طلب منه ياخد القرض عشان يسدد بيه دين شخصي)",
        },
        "field_investigation": {
            "en": "Unknown reputation, unsafe remote area",
            "ar": "سمعته مش معروفة والمنطقة بعيدة وغير آمنة",
        },
        "guarantor": {"en": "No guarantor", "ar": "مفيش ضامن"},
        "literacy": {
            "en": "Illiterate (uses a stamp instead of a signature)",
            "ar": "أُمّي (بيستخدم ختم بدل الإمضاء)",
        },
        "repay_probability": 0.10,
    },
    {
        "id": 6,
        "business_type": {"en": "Gas station", "ar": "محطة بنزين"},
        "loan_amount": 100000,
        "credit_limit_pct": 20,
        "credit_limit_note": {
            "en": "No other loans",
            "ar": "مفيش قروض تانية",
        },
        "risk_grade": {"en": "Excellent", "ar": "ممتاز"},
        "experience_years": 10,
        "monthly_income": {"en": "9,000 EGP", "ar": "٩,٠٠٠ جنيه"},
        "beneficiary": {"en": "No third-party beneficiary", "ar": "مفيش مستفيد من الغير"},
        "field_investigation": {
            "en": "Excellent reputation, main road location",
            "ar": "سمعة ممتازة والمحل على طريق رئيسي",
        },
        "guarantor": {"en": "Distant relation", "ar": "قريب بعيد"},
        "literacy": {"en": "Literate", "ar": "يعرف يقرا ويكتب"},
        "repay_probability": 0.95,
    },
    {
        "id": 7,
        "business_type": {"en": "Women's clothing / abaya shop", "ar": "محل عبايات وملابس حريمي"},
        "loan_amount": 100000,
        "credit_limit_pct": 30,
        "credit_limit_note": {
            "en": "No other loans",
            "ar": "مفيش قروض تانية",
        },
        "risk_grade": {"en": "Excellent", "ar": "ممتاز"},
        "experience_years": 0,
        "monthly_income": {"en": "Not established (new business)", "ar": "مش محدد لسه (نشاط جديد)"},
        "beneficiary": {
            "en": "Has third-party beneficiary (husband manages the money)",
            "ar": "فيه مستفيد من الغير (جوزها هو اللي بيدير الفلوس)",
        },
        "field_investigation": {
            "en": "Unknown reputation, remote area",
            "ar": "سمعته مش معروفة والمنطقة بعيدة",
        },
        "guarantor": {"en": "No guarantor", "ar": "مفيش ضامن"},
        "literacy": {"en": "Literate", "ar": "يعرف يقرا ويكتب"},
        "repay_probability": 0.30,
    },
    {
        "id": 8,
        "business_type": {"en": "Auto repair workshop", "ar": "ورشة تصليح عربيات"},
        "loan_amount": 100000,
        "credit_limit_pct": 85,
        "credit_limit_note": {
            "en": "Has a 5,000 EGP loan, 450 EGP/month, current with minor delays",
            "ar": "عنده قرض ٥,٠٠٠ جنيه بيسدد ٤٥٠ جنيه شهريًا ومنتظم مع تأخير بسيط أحيانًا",
        },
        "risk_grade": {"en": "Poor", "ar": "ضعيف"},
        "experience_years": 12,
        "monthly_income": {"en": "8,000 EGP", "ar": "٨,٠٠٠ جنيه"},
        "beneficiary": {"en": "No third-party beneficiary", "ar": "مفيش مستفيد من الغير"},
        "field_investigation": {
            "en": "Very strong reputation, established clientele, busy area",
            "ar": "سمعة قوية جدًا وعنده زباين ثابتين والمنطقة حيوية",
        },
        "guarantor": {"en": "Brother", "ar": "أخوه"},
        "literacy": {"en": "Literate", "ar": "يعرف يقرا ويكتب"},
        "repay_probability": 0.55,
    },
]

# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------

TRANSLATIONS = {
    "en": {
        "title": "Loan Default Game",
        "case_label": "Case {n} of {total}",
        "loan_amount": "Loan Amount",
        "egp": "EGP",
        "credit_limit": "Credit Limit Utilization",
        "risk_grade": "Risk Grade",
        "experience": "Years of Experience",
        "years_suffix": "years",
        "first_business": "First-time business (0 years experience)",
        "monthly_income": "Monthly Income",
        "beneficiary": "Third-party Beneficiary",
        "field_investigation": "Field Investigation",
        "guarantor": "Guarantor",
        "literacy": "Literacy",
        "business_type": "Business Type",
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
    },
    "ar": {
        "title": "لعبة تعثر السداد",
        "case_label": "الحالة {n} من {total}",
        "loan_amount": "مبلغ القرض",
        "egp": "جنيه",
        "credit_limit": "نسبة استخدام السقف الائتماني",
        "risk_grade": "تصنيف المخاطر",
        "experience": "سنوات الخبرة",
        "years_suffix": "سنين",
        "first_business": "نشاط جديد (٠ سنين خبرة)",
        "monthly_income": "الدخل الشهري",
        "beneficiary": "مستفيد من الغير",
        "field_investigation": "تقرير المعاينة الميدانية",
        "guarantor": "الضامن",
        "literacy": "محو الأمية",
        "business_type": "نوع النشاط",
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
    },
}

CASES_BY_ID = {c["id"]: c for c in CASES}

SCORE_MATRIX = {
    ("approve", "repay"): 100,
    ("approve", "default"): -100,
    ("reject", "repay"): -50,
    ("reject", "default"): 50,
}


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
  .muted { color: var(--muted); }
</style>
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
    Review 8 loan applications and decide whether to approve or reject each one.<br>
    راجع ٨ طلبات قروض وقرر توافق ولا ترفض كل واحد فيهم.
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
  <div class="score-badge">{{ t('score') }}: {{ score }}</div>
</div>
<div class="progress"><div class="progress-fill" style="width: {{ (index / total * 100) | round(1) }}%;"></div></div>
<div class="card">
  <h2 class="muted">{{ t('case_label').format(n=index + 1, total=total) }}</h2>
  <h1>{{ case.business_type[lang] }}</h1>
  <div class="grid">
    <div>
      <div class="field-label">{{ t('loan_amount') }}</div>
      <div class="field-value">{{ '{:,}'.format(case.loan_amount) }} {{ t('egp') }}</div>
    </div>
    <div>
      <div class="field-label">{{ t('credit_limit') }}</div>
      <div class="field-value">{{ case.credit_limit_pct }}% &mdash; {{ case.credit_limit_note[lang] }}</div>
    </div>
    <div>
      <div class="field-label">{{ t('risk_grade') }}</div>
      <div class="field-value">{{ case.risk_grade[lang] }}</div>
    </div>
    <div>
      <div class="field-label">{{ t('experience') }}</div>
      <div class="field-value">{{ t('first_business') if case.experience_years == 0 else (case.experience_years|string + ' ' + t('years_suffix')) }}</div>
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

OUTCOME_HTML = """
{% extends 'base.html' %}
{% block body %}
<div class="topbar">
  <div class="title">{{ t('title') }}</div>
  <div class="score-badge">{{ t('score') }}: {{ score }}</div>
</div>
<div class="card">
  <h2 class="muted">{{ t('case_label').format(n=result.index + 1, total=total) }} &mdash; {{ business_type }}</h2>
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
  <div class="final-score">{{ score }}</div>
  <h2>{{ t('summary') }}</h2>
  <table>
    <tr>
      <th>#</th>
      <th>{{ t('business_type') }}</th>
      <th>{{ t('approve') }}/{{ t('reject') }}</th>
      <th>{{ t('outcome') }}</th>
      <th>{{ t('points') }}</th>
    </tr>
    {% for d in decisions %}
    <tr>
      <td>{{ loop.index }}</td>
      <td>{{ d.business_type }}</td>
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

app.jinja_env.loader = DictLoader({
    "base.html": BASE_HTML,
    "language.html": LANGUAGE_HTML,
    "case.html": CASE_HTML,
    "outcome.html": OUTCOME_HTML,
    "final.html": FINAL_HTML,
})

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def resolve_decisions(decisions, lang):
    return [
        {
            "business_type": CASES_BY_ID[d["case_id"]]["business_type"][lang],
            "decision": d["decision"],
            "outcome": d["outcome"],
            "delta": d["delta"],
        }
        for d in decisions
    ]


# ---------------------------------------------------------------------------
# CSV logging
# ---------------------------------------------------------------------------


def save_session_to_csv():
    lang = session.get("lang", "en")
    resolved = resolve_decisions(session.get("decisions", []), lang)
    fieldnames = ["timestamp", "session_id", "language", "total_score"]
    for i in range(1, len(CASES) + 1):
        fieldnames += [
            f"case{i}_business_type",
            f"case{i}_decision",
            f"case{i}_outcome",
            f"case{i}_points",
        ]

    file_exists = os.path.isfile(CSV_PATH)
    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "session_id": session.get("session_id", ""),
        "language": lang,
        "total_score": session.get("score", 0),
    }
    for i, d in enumerate(resolved, start=1):
        row[f"case{i}_business_type"] = d["business_type"]
        row[f"case{i}_decision"] = d["decision"]
        row[f"case{i}_outcome"] = d["outcome"]
        row[f"case{i}_points"] = d["delta"]

    with open(CSV_PATH, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


# ---------------------------------------------------------------------------
# Email notification
# ---------------------------------------------------------------------------


def send_session_email(lang, score, session_id, resolved_decisions):
    if not EMAIL_APP_PASSWORD:
        app.logger.warning("EMAIL_APP_PASSWORD not set; skipping session result email.")
        return

    lines = [
        f"Language: {lang}",
        f"Session ID: {session_id}",
        f"Total score: {score}",
        "",
        "Decisions:",
    ]
    for i, d in enumerate(resolved_decisions, start=1):
        lines.append(
            f"{i}. {d['business_type']} - {d['decision']} - {d['outcome']} - {d['delta']:+d}"
        )

    msg = EmailMessage()
    msg["Subject"] = f"Loan Default Game session result - score {score}"
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECIPIENT
    msg.set_content("\n".join(lines))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_APP_PASSWORD)
            server.send_message(msg)
    except Exception:
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
    return redirect(url_for("show_case"))


@app.route("/case")
def show_case():
    lang = session.get("lang")
    if not lang:
        return redirect(url_for("index"))
    index = session.get("index", 0)
    if index >= len(CASES):
        return redirect(url_for("final"))
    return render_template(
        "case.html",
        lang=lang,
        case=CASES[index],
        index=index,
        total=len(CASES),
        score=session.get("score", 0),
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

    case = CASES[index]
    outcome = session["outcomes"][index]
    delta = SCORE_MATRIX[(decision, outcome)]

    session["score"] = session.get("score", 0) + delta

    decisions = session.get("decisions", [])
    entry = {
        "case_id": case["id"],
        "decision": decision,
        "outcome": outcome,
        "delta": delta,
    }
    decisions.append(entry)
    session["decisions"] = decisions

    result = dict(entry)
    result["index"] = index
    session["last_result"] = result

    return redirect(url_for("show_outcome"))


@app.route("/outcome")
def show_outcome():
    lang = session.get("lang")
    result = session.get("last_result")
    if not lang or not result:
        return redirect(url_for("index"))
    business_type = CASES_BY_ID[result["case_id"]]["business_type"][lang]
    return render_template(
        "outcome.html",
        lang=lang,
        result=result,
        business_type=business_type,
        total=len(CASES),
        score=session.get("score", 0),
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
    )


@app.route("/restart", methods=["POST"])
def restart():
    session.clear()
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
