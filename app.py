r"""
app.py - Loan Default Game (English only)
2x2 within-subject factorial | 8 rounds | 60 s + 30 s grace | RIS payment

Design targets
  * ONE page load for all 8 rounds. Round advance is client-side, so a slow
    free-tier server cannot add latency between decisions.
  * Every round is one screen: applicant card, decision, two probability
    judgments, and the participant's main deciding factor.
  * Keyboard shortcuts for motor speed:
        A / R           approve / reject
        Z X C V B N     deciding factor
        Enter           next application
    (Reason keys deliberately avoid A and R, which are taken by the decision.)

Scientific constraints deliberately enforced in the markup
  * Credit score High and Low are rendered with IDENTICAL styling. Colour-coding
    them would add a valence cue on top of the manipulated text.
  * Eight different stories are used. Credit-score assignment is counterbalanced
    across participant IDs so a story is not permanently tied to one score level.
  * Approve and Reject are visually symmetric; only label and position differ.
  * Outcomes are drawn before decisions and revealed only after all eight rounds,
    preventing feedback in an early round from changing later decisions.

Run locally:  py app.py     ->  http://127.0.0.1:5000
Admin:        http://127.0.0.1:5000/admin?key=<ADMIN_KEY>
"""

import csv
import io
import json
import os
import random
import secrets
import time
from datetime import datetime

from flask import (Flask, Response, jsonify, redirect, render_template_string,
                   request, session, url_for)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(16))

ADMIN_KEY = os.environ.get("ADMIN_KEY", "kdi2026")
PARTICIPANT_IDS = ["01", "02", "03", "04"]

# ---------------------------------------------------------------------------
# Design: 2x2 within-subject factorial, two observations per cell
# ---------------------------------------------------------------------------

DEFAULT_PROB = {"High": 0.20, "Low": 0.45}
MAX_BONUS_KRW = 5000

STORIES = [
    {
        "code": "P1", "use": "Productive",
        "label": "Increase shop stock to raise sales",
        "text": "He wants to increase the shop's stock to raise sales.",
        "name": "Mahmoud", "loc": "Kom Ombo",
    },
    {
        "code": "P2", "use": "Productive",
        "label": "Open a second grocery branch",
        "text": "He wants to open a second grocery branch in a nearby village.",
        "name": "Atef", "loc": "Daraw",
    },
    {
        "code": "P3", "use": "Productive",
        "label": "Buy a refrigerator and display shelves",
        "text": "He wants to buy a refrigerator and display shelves for the shop.",
        "name": "Ragab", "loc": "Edfu",
    },
    {
        "code": "P4", "use": "Productive",
        "label": "Add a home-delivery service",
        "text": "He wants to buy a delivery motorcycle and add home delivery.",
        "name": "Sayed", "loc": "Nasr El-Nuba",
    },
    {
        "code": "N1", "use": "Non-productive",
        "label": "Daughter's wedding trousseau",
        "text": "He needs the loan to cover his daughter's wedding trousseau next month.",
        "name": "Ashraf", "loc": "El-Sebaeya",
    },
    {
        "code": "N2", "use": "Non-productive",
        "label": "Pay for urgent medical treatment",
        "text": "He needs the loan to pay for urgent medical treatment for his wife.",
        "name": "Yasser", "loc": "Abu El-Rish",
    },
    {
        "code": "N3", "use": "Non-productive",
        "label": "Repay an overdue loan from another lender",
        "text": "He has an overdue loan from another lender and must repay it "
                "soon before they take action against him.",
        "name": "Hassan", "loc": "El-Shallal",
    },
    {
        "code": "N4", "use": "Non-productive",
        "label": "Pay a son's university fees",
        "text": "He needs the loan to pay his son's university fees this semester.",
        "name": "Mostafa", "loc": "Sehel Island",
    },
]

HIGH_SCORES = [780, 785, 795, 800]
LOW_SCORES = [520, 540, 560, 580]

# Identical in every vignette. Announced once on the instructions page.
STANDING = [
    ("Loan requested", "100,000 EGP"),
    ("Business", "Grocery shop"),
    ("Years in business", "5 years"),
    ("Monthly income", "4,000 EGP"),
    ("Guarantor", "Brother"),
    ("Literacy", "Reads and writes"),
    ("Field investigation", "Normal reputation, no negative remarks"),
    ("Third-party beneficiary", "No"),
]

PRACTICE = {
    "case_id": "PRACTICE", "credit_score": 700, "credit_score_level": "Practice",
    "use_of_funds": "Practice", "purpose_label": "Practice case",
    "name": "Kareem", "loc": "Aswan",
    "purpose": "He wants to buy a second refrigerator for the shop.",
    "outcome": "Repay",
}

REASONS = [
    {"key": "Z", "text": "Credit score"},
    {"key": "X", "text": "The stated purpose of the loan"},
    {"key": "C", "text": "Whether the use generates income to repay"},
    {"key": "V", "text": "The applicant's personal circumstances"},
    {"key": "B", "text": "The financial data (income vs instalment)"},
    {"key": "N", "text": "Something else"},
]

CSV_COLUMNS = [
    "session_id", "participant_id", "timestamp", "consent_given", "round_index",
    "case_id", "credit_score", "credit_score_level", "use_of_funds", "purpose_label",
    "applicant_name", "decision", "repayment_probability",
    "business_success_probability", "reason_choice",
    "true_default_prob", "outcome", "points", "seconds_on_round",
]

# ---------------------------------------------------------------------------
# In-process store (Render free tier runs a single worker)
# ---------------------------------------------------------------------------

SESSIONS = {}
DISK_CSV = os.environ.get("DATA_FILE", "decisions.csv")


def build_cases(seed, participant_id):
    rng = random.Random(seed)
    cases = []
    # IDs 01/03 receive pattern A; IDs 02/04 receive its complement. Within
    # productive and non-productive stories, every participant gets two high
    # and two low scores. Across the four-person pilot every story appears
    # twice with a high score and twice with a low score.
    pattern_a = ["High", "High", "Low", "Low", "High", "High", "Low", "Low"]
    levels = pattern_a if int(participant_id) % 2 else [
        "Low" if level == "High" else "High" for level in pattern_a
    ]
    high_i = low_i = 0
    for story, level in zip(STORIES, levels):
        if level == "High":
            score = HIGH_SCORES[high_i]
            high_i += 1
        else:
            score = LOW_SCORES[low_i]
            low_i += 1
        cases.append({
            "case_id": f"{story['code']}-{level[0]}",
            "credit_score": score,
            "credit_score_level": level,
            "use_of_funds": story["use"],
            "purpose_label": story["label"],
            "purpose": story["text"],
            "name": story["name"], "loc": story["loc"],
            "true_default_prob": DEFAULT_PROB[level],
            "outcome": "Default" if rng.random() < DEFAULT_PROB[level] else "Repay",
        })
    rng.shuffle(cases)
    for i, c in enumerate(cases, start=1):
        c["round_index"] = i
    return cases


def points_for(decision, outcome):
    if decision == "Approve":
        return -100 if outcome == "Default" else 100
    return 50 if outcome == "Default" else -50


def bonus_krw(points):
    return int(MAX_BONUS_KRW * (points + 100) / 200)


def append_disk(row):
    try:
        new = not os.path.exists(DISK_CSV)
        with open(DISK_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            if new:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in CSV_COLUMNS})
    except Exception:
        pass    # memory + the emailed copy remain authoritative


# ---------------------------------------------------------------------------
# Shared CSS
# ---------------------------------------------------------------------------

CSS = """
:root{
  --paper:#EDEFEA; --card:#FBFBF8; --ink:#1C2B4A; --rule:#C9CDC4;
  --muted:#6E7581; --bronze:#8A6A2F; --band:#E3E6DE;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:var(--paper); color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",Arial,sans-serif;
  font-size:15px; line-height:1.5; -webkit-font-smoothing:antialiased;
}
.mono{font-family:ui-monospace,"Cascadia Mono","Segoe UI Mono","DejaVu Sans Mono",monospace}
.wrap{max-width:1080px;margin:0 auto;padding:22px 20px 44px}
.rule{height:1px;background:var(--rule);border:0;margin:16px 0}
h1{font-size:24px;letter-spacing:-.015em;margin:0 0 6px}
h2{font-size:15px;margin:0 0 8px}
.eyebrow{
  font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--muted);font-weight:600;margin:0 0 3px
}
.card{background:var(--card);border:1px solid var(--rule);border-radius:2px}
.btn{
  font:inherit;font-weight:600;cursor:pointer;background:var(--card);
  color:var(--ink);border:1.5px solid var(--ink);border-radius:2px;
  padding:11px 18px;transition:background .12s,color .12s
}
.btn:hover{background:var(--ink);color:var(--card)}
.btn[disabled]{opacity:.4;cursor:not-allowed}
.btn.sel{background:var(--ink);color:var(--card)}
.btn.ghost{border-color:var(--rule);font-weight:500}
.btn.ghost.sel{border-color:var(--ink)}
.btn.wide{width:100%;text-align:center}
.kbd{
  display:inline-block;min-width:17px;padding:0 4px;margin-right:7px;
  border:1px solid currentColor;border-radius:2px;
  font-size:10.5px;font-weight:700;opacity:.75;
  font-family:ui-monospace,monospace
}
:focus-visible{outline:2.5px solid var(--bronze);outline-offset:2px}
.muted{color:var(--muted);font-size:13px}
label{display:block;font-size:13px;font-weight:600;margin-bottom:6px}
select{
  font:inherit;padding:10px;border:1.5px
 solid var(--rule);
  border-radius:2px;background:var(--card);color:var(--ink);width:100%
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""

# ---------------------------------------------------------------------------
# Screen 1 - participant number only
# ---------------------------------------------------------------------------

START_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Loan Default Game</title><style>{{css|safe}}</style></head><body>
<div class="wrap" style="max-width:460px;padding-top:64px">
  <p class="eyebrow">KDI School &middot; Experimental Economics</p>
  <h1>Loan Default Game</h1>
  <p class="muted">Aswan microfinance pilot</p>
  <hr class="rule">
  {% if error %}<p style="color:#9B2C2C;font-weight:600">{{error}}</p>{% endif %}
  <form method="post" style="display:grid;gap:18px">
    <div>
      <label for="pid">Your participant number</label>
      <select id="pid" name="participant_id" required autofocus>
        <option value="">&mdash; select &mdash;</option>
        {% for p in available %}<option value="{{p}}">{{p}}</option>{% endfor %}
      </select>
      <p class="muted" style="margin:7px 0 0">It is on the card at your seat.</p>
      {% if not available %}<p class="muted">All four numbers are in use. Tell the researcher.</p>{% endif %}
    </div>
    <div class="card" style="padding:14px">
      <label style="display:flex;gap:10px;align-items:flex-start;margin:0;font-weight:500">
        <input type="checkbox" name="consent" value="yes" required
               style="width:18px;height:18px;margin-top:2px;flex:0 0 auto">
        <span>I am at least 18 years old. I have read the consent information
        provided by the researcher, I understand that participation is voluntary,
        and I agree to take part in this study.</span>
      </label>
    </div>
    <button class="btn wide" type="submit">Start</button>
  </form>
</div></body></html>"""

# ---------------------------------------------------------------------------
# Screen 2 - instructions, comprehension check, practice, 8 rounds, result
# ---------------------------------------------------------------------------

GAME_HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Loan Default Game</title><style>{{css|safe}}
.step{display:none}.step.on{display:block}
.grid{display:grid;grid-template-columns:1.15fr .85fr;gap:20px;align-items:start}
@media(max-width:820px){.grid{grid-template-columns:1fr}}
.standing{
  background:var(--band);border:1px solid var(--rule);border-radius:2px;
  padding:11px 14px;display:grid;grid-template-columns:1fr 1fr;gap:5px 22px
}
.standing div{display:flex;justify-content:space-between;gap:12px;font-size:12.5px}
.standing span:first-child{color:var(--muted)}
.standing span:last-child{font-weight:600;text-align:right}
.payrow{display:grid;grid-template-columns:1fr auto auto;gap:4px 16px;font-size:13.5px}
.payrow div{padding:3px 0;border-bottom:1px solid var(--rule)}
.payrow div:nth-child(3n+2),.payrow div:nth-child(3n){text-align:right;font-weight:600}
.steps{counter-reset:s;list-style:none;padding:0;margin:0;display:grid;gap:7px}
.steps li{counter-increment:s;display:flex;gap:11px;font-size:14px}
.steps li::before{
  content:counter(s);flex:0 0 20px;height:20px;margin-top:1px;
  border:1.5px solid var(--ink);border-radius:50%;
  font-size:11px;font-weight:700;display:grid;place-items:center
}
.varybox{padding:18px;border-bottom:1px solid var(--rule)}
.scorerow{display:flex;align-items:baseline;gap:10px;margin-bottom:14px}
.scorelab{font-size:11px;letter-spacing:.13em;text-transform:uppercase;color:var(--muted);font-weight:600}
.scoreval{font-size:26px;font-weight:700;letter-spacing:-.02em}
.purpose{font-size:17px;line-height:1.45;margin:0}
.banner{
  border:1px solid var(--rule);border-left:3px solid var(--ink);
  background:var(--card);padding:9px 13px;font-size:13px;margin-bottom:14px
}
.prog{display:flex;gap:5px;margin-bottom:16px}
.pip{height:4px;flex:1;background:var(--band);border-radius:2px}
.pip.done{background:var(--ink)}.pip.now{background:var(--bronze)}
.timer{display:flex;justify-content:space-between;align-items:center;border:1.5px solid var(--rule);border-radius:2px;background:var(--card);padding:8px 14px;margin-bottom:14px;font-variant-numeric:tabular-nums}
.timer .tlabel{font-size:11px;letter-spacing:.13em;text-transform:uppercase;color:var(--muted);font-weight:600}
.timer .tval{font-size:20px;color:var(--ink);font-weight:700}
.timer.low{border-color:var(--bronze)}.timer.low .tval{color:var(--bronze)}
.timer.zero{border-color:#B23A2E}.timer.zero .tval{color:#B23A2E}
.twarn{border:1px solid var(--bronze);background:#F3ECDD;color:#8A6A2F;border-radius:2px;padding:9px 14px;margin-bottom:14px;font-size:13px;font-weight:600}
.chips{display:flex;flex-wrap:wrap;gap:7px}
.chips .btn{padding:8px 12px;font-size:13.5px}
.reasons{display:grid;gap:6px}
.reasons .btn{text-align:left;padding:9px 12px;font-size:13.5px;font-weight:500}
.big{display:grid;grid-template-columns:1fr 1fr;gap:11px}
.big .btn{padding:17px 10px;font-size:16px}
.fade{animation:f .13s ease-out}@keyframes f{from{opacity:0}to{opacity:1}}
.pay{font-size:40px;font-weight:700;letter-spacing:-.02em;margin:6px 0}
.two{display:grid;grid-template-columns:1fr 1fr;gap:26px}
@media(max-width:820px){.two{grid-template-columns:1fr;gap:0}}
</style></head><body><div class="wrap">

<!-- ============ INSTRUCTIONS ============ -->
<section class="step on" id="s-intro">
  <p class="eyebrow">Instructions &middot; participant {{ pid }}</p>
  <h1>You are a loan officer</h1>
  <p style="margin:0 0 18px">You will review <strong>8 loan applications</strong>, one at a
  time, and decide whether to <strong>approve</strong> or <strong>reject</strong> each one.</p>

  <div class="two">
    <div>
      <p class="eyebrow">Identical in all 8 applications</p>
      <div class="standing" style="grid-template-columns:1fr">
        {% for k,v in standing %}<div><span>{{k}}</span><span class="mono">{{v}}</span></div>{% endfor %}
      </div>
      <p class="muted" style="margin:8px 0 0">Read these once now. They never change,
      so you will not need to read them again.</p>

      <p class="eyebrow" style="margin-top:20px">Only two things differ</p>
      <div class="card" style="padding:13px 15px">
        <p style="margin:0 0 7px"><strong>1. The credit score</strong> &mdash; a number
        between 300 and 850; a higher number indicates a stronger credit history.</p>
        <p style="margin:0"><strong>2. The reason the applicant gives</strong> for wanting
        the loan.</p>
      </div>
      <p class="muted" style="margin:8px 0 0">That is everything you have to work with.</p>
    </div>

    <div>
      <p class="eyebrow">Each application is one screen</p>
      <ol class="steps">
        <li>Read the credit score and the stated reason.</li>
        <li>Press <span class="kbd">A</span>to approve or <span class="kbd">R</span>to reject.</li>
        <li>Estimate the chance of repayment and business success (0&ndash;100%).</li>
        <li>Choose the one factor that mattered most &mdash; keys <span class="kbd">Z</span>to<span class="kbd">N</span>.</li>
        <li>Press <span class="kbd">&crarr;</span>for the next application.</li>
      </ol>
      <p class="muted" style="margin:9px 0 0">You can click instead of using the keys.
      The repayment outcome is revealed only after all eight decisions.</p>

      <p class="eyebrow" style="margin-top:20px">Points you earn</p>
      <div class="payrow">
        <div>Approve, and they repay</div><div>+100</div><div>5,000 KRW</div>
        <div>Reject, and they would have defaulted</div><div>+50</div><div>3,750 KRW</div>
        <div>Reject, and they would have repaid</div><div>&minus;50</div><div>1,250 KRW</div>
        <div>Approve, and they default</div><div>&minus;100</div><div>0 KRW</div>
      </div>
    </div>
  </div>

  <hr class="rule">
  <p class="eyebrow">How you get paid</p>
  <p style="margin:0 0 6px"><strong>At the end, one of your eight decisions is drawn at
  random, and only that one is paid</strong> &mdash; at the rate in the table above, up to
  5,000 KRW.</p>
  <p style="margin:0 0 6px">So treat every single application as if it is the one that
  counts, because any of them might be.</p>
  <p class="muted" style="margin:0">There is no trick and no answer we are looking for.
  Take the time you need and decide the way you actually would.</p>

  <hr class="rule">
  <p class="muted" style="margin:0 0 12px">Next: one practice application that does
  not count, followed by the eight real applications.</p>
  <button class="btn" onclick="go('s-round');render()" autofocus>Start practice</button>
</section>

<!-- ============ COMPREHENSION CHECK ============ -->
<section class="step" id="s-check">
  <p class="eyebrow">Two questions</p>
  <h1>Both answers must be correct to continue</h1>
  <div style="margin:20px 0">
    <p style="font-weight:600;margin:0 0 8px">1. If you approve an applicant who then
    defaults, what happens to your points?</p>
    <div class="chips" id="c1">
      <button class="btn ghost" data-v="a">+100</button>
      <button class="btn ghost" data-v="b">&minus;100</button>
      <button class="btn ghost" data-v="c">&minus;50</button>
      <button class="btn ghost" data-v="d">+50</button>
    </div>
  </div>
  <div style="margin:0 0 20px">
    <p style="font-weight:600;margin:0 0 8px">2. How many of your eight decisions
    determine your payment?</p>
    <div class="chips" id="c2">
      <button class="btn ghost" data-v="a">All eight, averaged</button>
      <button class="btn ghost" data-v="b">One, drawn at random</button>
      <button
 class="btn ghost" data-v="c">The best one</button>
    </div>
  </div>
  <p id="cmsg" class="muted" style="min-height:20px;margin:0 0 12px"></p>
  <button class="btn" id="cbtn" onclick="checkAnswers()">Check my answers</button>
  <button class="btn ghost" onclick="go('s-intro')">Back to instructions</button>
</section>

<!-- ============ PRACTICE + 8 ROUNDS ============ -->
<section class="step" id="s-round">
  <div class="prog" id="prog"></div>
  <p class="eyebrow" id="r-eyebrow"></p>
  <div class="timer" id="rtimer" style="display:none">
    <span class="tlabel">Time left</span>
    <span class="tval" id="tval">1:00</span>
  </div>
  <div class="twarn" id="twarn" style="display:none">Time is almost up &mdash; you have 30 extra seconds. Please make your decision.</div>
  <div class="grid">
    <div>
      <div id="r-banner"></div>
      <div class="card" id="r-card">
        <div class="varybox">
          <p class="muted mono" id="r-who" style="margin:0 0 12px;font-size:12.5px"></p>
          <div class="scorerow">
            <span class="scorelab">Credit score</span>
            <span class="scoreval" id="r-score"></span>
          </div>
          <p class="scorelab" style="margin:0 0 5px">Stated reason for the loan</p>
          <p class="purpose" id="r-purpose"></p>
        </div>
        <div style="padding:12px 14px">
          <div class="standing" style="border:0;background:transparent;padding:0">
            {% for k,v in standing %}<div><span>{{k}}</span><span class="mono">{{v}}</span></div>{% endfor %}
          </div>
        </div>
      </div>
    </div>
    <div>
      <p class="eyebrow">Your decision</p>
      <div class="big" style="margin-bottom:18px">
        <button class="btn" id="b-app" onclick="pickDec('Approve')"><span class="kbd">A</span>Approve</button>
        <button class="btn" id="b-rej" onclick="pickDec('Reject')"><span class="kbd">R</span>Reject</button>
      </div>
      <div id="prob-wrap" style="display:none;margin-bottom:18px">
        <label for="repay-prob">Estimated chance this applicant repays the loan</label>
        <div style="display:grid;grid-template-columns:1fr 88px;gap:10px;align-items:center;margin-bottom:12px">
          <input id="repay-prob" type="range" min="0" max="100" step="5" value="50"
                 oninput="syncProb('repay')">
          <input id="repay-num" type="number" min="0" max="100" step="5" value="50"
                 oninput="syncProb('repay','number')" aria-label="Repayment probability percent">
        </div>
        <label for="success-prob">Estimated chance the applicant's business succeeds</label>
        <div style="display:grid;grid-template-columns:1fr 88px;gap:10px;align-items:center">
          <input id="success-prob" type="range" min="0" max="100" step="5" value="50"
                 oninput="syncProb('success')">
          <input id="success-num" type="number" min="0" max="100" step="5" value="50"
                 oninput="syncProb('success','number')" aria-label="Business success probability percent">
        </div>
      </div>
      <div id="rsn-wrap" style="display:none">
        <p class="eyebrow">Single most important factor</p>
        <div class="reasons" id="rsn"></div>
      </div>
      <hr class="rule">
      <button class="btn wide" id="nextbtn" disabled onclick="submitRound()">
        <span class="kbd">&crarr;</span><span id="nextlbl">Next application</span>
      </button>
      <p class="muted" id="running" style="margin-top:10px"></p>
    </div>
  </div>
</section>

<!-- ============ RESULT ============ -->
<section class="step" id="s-done">
  <p class="eyebrow">Session complete</p>
  <h1>The decision drawn at random</h1>
  <div class="card" style="padding:20px;max-width:520px">
    <p class="muted mono" id="d-line" style="margin:0 0 6px"></p>
    <p style="margin:0 0 14px" id="d-detail"></p>
    <hr class="rule" style="margin:12px 0">
    <p class="eyebrow">Your bonus</p>
    <p class="pay" id="d-krw"></p>
    <p class="muted" id="d-total"></p>
  </div>
  <p class="muted" style="margin-top:18px">Thank you. Please show this screen to the researcher.</p>
</section>

<script>
const CASES    = {{ cases_json|safe }};
const PRACTICE = {{ practice_json|safe }};
const REASONS  = {{ reasons_json|safe }};
const SID      = "{{ sid }}";

let idx=-1, dec=null, repayProb=50, successProb=50, rsn=null, total=0, tRound=0;
const queue=[];

function go(id){
  document.querySelectorAll('.step').forEach(s=>s.classList.remove('on'));
  document.getElementById(id).classList.add('on');
  window.scrollTo(0,0);
}

/* ---- comprehension check ---- */
let a1=null,a2=null;
document.querySelectorAll('#c1 .btn').forEach(b=>b.onclick=()=>{a1=b.dataset.v;
  document.querySelectorAll('#c1 .btn').forEach(x=>x.classList.remove('sel'));b.classList.add('sel');});
document.querySelectorAll('#c2 .btn').forEach(b=>b.onclick=()=>{a2=b.dataset.v;
  document.querySelectorAll('#c2 .btn').forEach(x=>x.classList.remove('sel'));b.classList.add('sel');});
function checkAnswers(){
  const m=document.getElementById('cmsg');
  if(a1===null||a2===null){m.textContent='Answer both questions first.';return;}
  if(a1==='b'&&a2==='b'){
    m.textContent='Correct. We begin with one practice application.';
    document.getElementById('cbtn').disabled=true;
    setTimeout(()=>{go('s-round');render();},600);
  } else {
    m.textContent='Not quite. Go back to the instructions and check the points table '
      + 'and the payment rule, then try again.';
  }
}

/* ---- build the fixed deciding-factor controls once ---- */
const rsnBox=document.getElementById('rsn');
REASONS.forEach(r=>{
  const b=document.createElement('button');b.className='btn ghost';
  b.innerHTML='<span class="kbd">'+r.key+'</span>'+r.text;
  b.onclick=()=>{rsn=r.text;[...rsnBox.children].forEach(c=>c.classList.remove('sel'));
    b.classList.add('sel');gate();};
  rsnBox.appendChild(b);
});

function cur(){return idx<0?PRACTICE:CASES[idx];}
function isPractice(){return idx<0;}

function syncProb(which,source){
  const slider=document.getElementById(which+'-prob');
  const number=document.getElementById(which+'-num');
  let value=source==='number'?Number(number.value):Number(slider.value);
  value=Math.max(0,Math.min(100,Number.isFinite(value)?value:50));
  slider.value=value;number.value=value;
  if(which==='repay')repayProb=value;else successProb=value;
  gate();
}

/* ---- per-application countdown: 60s, then a warning + 30s, soft (never auto-submits) ---- */
let timerIv=null;
function stopTimer(){ if(timerIv){clearInterval(timerIv);timerIv=null;} }
function fmtT(s){var m=Math.floor(s/60),x=s%60;return m+':'+(x<10?'0':'')+x;}
function startTimer(){
  stopTimer();
  const box=document.getElementById('rtimer');
  const val=document.getElementById('tval');
  const warn=document.getElementById('twarn');
  box.classList.remove('low','zero');
  warn.style.display='none';
  if(isPractice()){box.style.display='none';return;}   // practice is untimed
  box.style.display='flex';
  let remaining=60, extra=30, extended=false;
  val.textContent=fmtT(remaining);
  timerIv=setInterval(()=>{
    remaining--;
    if(remaining<=0){
      if(!extended){
        extended=true;remaining=extra;
        box.classList.add('low');warn.style.display='block';
        val.textContent=fmtT(remaining);
      } else {
        remaining=0;val.textContent=fmtT(0);
        box.classList.remove('low');box.classList.add('zero');
        stopTimer();
      }
    } else {
      val.textContent=fmtT(remaining);
    }
  },1000);
}

function render(){
  const c=cur();
  document.getElementById('r-eyebrow').textContent =
    isPractice() ? 'Practice application â€” not counted' : 'Application '+(idx+1)+' of 8';
  document.getElementById('prog').innerHTML =
    CASES.map((_,i)=>'<div class="pip '+(idx>i?'done':(idx===i?'now':''))+'"></div>').join('');
  document.getElementById('r-who').textContent = c.name+' Â· '+c.loc;
  document.getElementById('r-score').textContent = c.credit_score;
  document.getElementById('r-purpose').textContent = c.purpose;

  document.getElementById('r-banner').innerHTML = '';
  document.getElementById('running').textContent =
    isPractice() ? '' : 'Running points: '+total;

  dec=null;repayProb=50;successProb=50;rsn=null;
  document.getElementById('b-app').classList.remove('sel');
  document.getElementById('b-rej').classList.remove('sel');
  document.getElementById('prob-wrap').style.display='none';
  document.getElementById('rsn-wrap').style.display='none';
  document.getElementById('repay-prob').value=50;
  document.getElementById('repay-num').value=50;
  document.getElementById('success-prob').value=50;
  document.getElementById('success-num').value=50;
  [...rsnBox.children].forEach(c=>c.classList.remove('sel'));
  document.getElementById('nextlbl').textContent =
    isPractice() ? 'Start the eight applications'
                 : (idx===CASES.length-1 ? 'Show my result' : 'Next application');
  const card=document.getElementById('r-card');
  card.classList.add('fade');setTimeout(()=>card.classList.remove('fade'),160);
  gate();tRound=Date.now();startTimer();
}

function pickDec(d){
  dec=d;
  document.getElementById('b-app').classList.toggle('sel',d==='Approve');
  document.getElementById('b-rej').classList.toggle('sel',d==='Reject');
  document.getElementById('prob-wrap').style.display='block';
  document.getElementById('rsn-wrap').style.display='block';
  gate();
}
function gate(){
  const ok = dec && rsn!==null
    && repayProb>=0 && repayProb<=100 && successProb>=0 && successProb<=100;
  document.getElementById('nextbtn').disabled = !ok;
}

function submitRound(){
  if(document.getElementById('nextbtn').disabled)return;
  const c=cur();
  if(isPractice()){idx=0;render();return;}
  const pts = dec==='Approve' ? (c.outcome==='Default'?-100:100)
                              : (c.outcome==='Default'?50:-50);

  total+=pts;
  save({session_id:SID,round_index:c.round_index,case_id:c.case_id,
    credit_score:c.credit_score,credit_score_level:c.credit_score_level,
    use_of_funds:c.use_of_funds,
    purpose_label:c.purpose_label,applicant_name:c.name,decision:dec,
    repayment_probability:repayProb,business_success_probability:successProb,
    reason_choice:rsn,
    true_default_prob:c.true_default_prob,outcome:c.outcome,points:pts,
    seconds_on_round:Math.round((Date.now()-tRound)/1000)});
  if(idx===CASES.length-1){finish();return;}
  idx++;render();
}

/* background save that never blocks the interface */
function save(row){
  queue.push(row);
  fetch('/api/round',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(row),keepalive:true})
    .then(r=>{if(r.ok){const i=queue.indexOf(row);if(i>=0)queue.splice(i,1);}})
    .catch(()=>{});
}
setInterval(()=>{[...queue].forEach(r=>save(r));},6000);

function finish(){
  stopTimer();
  fetch('/api/finish',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({session_id:SID,total_points:total,pending:queue})})
    .then(r=>r.json()).then(d=>{
      document.getElementById('d-line').textContent =
        'Application '+d.selected_round_index+' â€” '+d.applicant_name;
      document.getElementById('d-detail').textContent =
        d.decision+' Â· '+d.outcome+' Â· '
        +(d.selected_round_points>0?'+':'')+d.selected_round_points+' points';
      document.getElementById('d-krw').textContent = d.bonus_krw.toLocaleString()+' KRW';
      document.getElementById('d-total').textContent = 'Total points across all 8: '+d.total_points;
      go('s-done');
    }).catch(()=>{
      go('s-done');
      document.getElementById('d-krw').textContent='â€”';
      document.getElementById('d-detail').textContent='Show this screen to the researcher.';
    });
}

/* keyboard: the main speed lever. A and R are the decision, so reason keys are Z X C V B N. */
document.addEventListener('keydown',e=>{
  if(!document.getElementById('s-round').classList.contains('on'))return;
  if(e.metaKey||e.ctrlKey||e.altKey)return;
  const k=e.key.toUpperCase();
  if(k==='A'){pickDec('Approve');e.preventDefault();return;}
  if(k==='R'){pickDec('Reject');e.preventDefault();return;}
  if(dec){const i=REASONS.findIndex(r=>r.key===k);
    if(i>=0){rsnBox.children[i].click();e.preventDefault();return;}}
  if(e.key==='Enter'){submitRound();e.preventDefault();}
});
</script></div></body></html>"""

ADMIN_HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="8"><title>Admin</title><style>{{css|safe}}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{border:1px solid var(--rule);padding:7px 9px;text-align:left}
th{background:var(--ink);color:#fff;font-size:11px;letter-spacing:.09em;text-transform:uppercase}
.slow{background:#F6E7CF}
</style></head><body><div class="wrap">
<p class="eyebrow">Live monitor &middot; refreshes every 8 s</p>
<h1>Session dashboard</h1>
<p class="muted">{{ rows|length }} session(s) &middot; {{ total_rows }} decisions saved</p>
<p><a class="btn" href="/admin/report?key={{key}}">View hypothesis results</a>
&nbsp; <a class="btn ghost" href="/admin/csv?key={{key}}">Download CSV</a></p>
<hr class="rule">
<table><tr>
<th>ID</th><th>Round</th><th>Elapsed</th><th>Avg / round</th>
<th>Approved</th><th>Points</th><th>Bonus</th><th>Status</th></tr>
{% for r in rows %}<tr{% if r.avg and r.avg>75 %} class="slow"{% endif %}>
<td class="mono">{{r.pid}}</td><td class="mono">{{r.n}} / 8</td>
<td class="mono">{{r.elapsed}}</td>
<td class="mono">{{ (r.avg|round(0)|int ~ ' s') if r.avg else 'â€”' }}</td>
<td class="mono">{{r.approved}}</td><td class="mono">{{r.points}}</td>
<td class="mono">{{ (r.bonus ~ ' KRW') if r.bonus is not none else 'â€”' }}</td>
<td>{{r.status}}</td></tr>{% endfor %}
</table>
<hr class="rule">
<p class="muted">Rows shaded amber are averaging over 75 seconds per application.
Download the CSV the moment the last participant finishes &mdash; Render's free tier has
an ephemeral filesystem, so this download is the primary copy.</p>
</div></body></html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET", "POST"])
def start():
    taken = {s["participant_id"] for s in SESSIONS.values()}
    available = [p for p in PARTICIPANT_IDS if p not in taken]
    error = None
    if request.method == "POST":
        pid = request.form.get("participant_id", "")
        consent = request.form.get("consent") == "yes"
        if not consent:
            error = "Please provide consent before starting."
        elif pid not in available:
            error = "That number is already in use. Please pick another."
        else:
            sid = f"S{pid}-{secrets.token_hex(3)}"
            SESSIONS[sid] = {
                "session_id": sid, "participant_id": pid, "consent_given": True,
                "cases": build_cases(seed=f"{pid}{sid}", participant_id=pid), "rows": [],
                "started_at": time.time(), "finished_at": None,
                "total_points": None, "bonus_krw": None,
                "selected_round_index": None,
            }
            session["sid"] = sid
            return redirect(url_for("game"))
    return render_template_string(START_HTML, css=CSS, available=available, error=error)


@app.route("/game")
def game():
    sid = session.get("sid")
    if not sid or sid not in SESSIONS:
        return redirect(url_for("start"))
    s = SESSIONS[sid]
    return render_template_string(
        GAME_HTML, css=CSS, sid=sid, pid=s["participant_id"], standing=STANDING,
        cases_json=json.dumps(s["cases"]),
        practice_json=json.dumps(PRACTICE),
        reasons_json=json.dumps(REASONS),
    )


@app.route("/api/round", methods=["POST"])
def api_round():
    d = request.get_json(silent=True) or {}
    s = SESSIONS.get(d.get("session_id"))
    if not s:
        return jsonify({"ok": False}), 404
    if any(r["round_index"] == d.get("round_index") for r in s["rows"]):
        return jsonify({"ok": True, "duplicate": True})
    row = {
        "session_id": s["session_id"], "participant_id": s["participant_id"],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "consent_given": s["consent_given"],
    }
    for k in ("round_index", "case_id", "credit_score", "credit_score_level",
              "use_of_funds", "purpose_label", "applicant_name", "decision",
              "repayment_probability", "business_success_probability",
              "reason_choice", "true_default_prob", "outcome", "points",
              "seconds_on_round"):
        row[k] = d.get(k)
    s["rows"].append(row)
    append_disk(row)
    return jsonify({"ok": True})


@app.route("/api/finish", methods=["POST"])
def api_finish():
    d = request.get_json(silent=True) or {}
    s = SESSIONS.get(d.get("session_id"))
    if not s:
        return jsonify({"ok": False}), 404
    for row in (d.get("pending") or []):
        if not any(r["round_index"] == row.get("round_index") for r in s["rows"]):
            row.update({"session_id": s["session_id"], "participant_id": s["participant_id"],
                        "consent_given": s["consent_given"],
                        "timestamp": datetime.now().isoformat(timespec="seconds")})
            s["rows"].append(row)
            append_disk(row)

    rows = sorted(s["rows"], key=lambda r: r["round_index"])
    if not rows:
        return jsonify({"ok": False}), 400

    pick = random.choice(rows)          # Random Incentivized Selection, server-side
    s["selected_round_index"] = pick["round_index"]
    s["total_points"] = sum(r["points"] for r in rows)
    s["bonus_krw"] = bonus_krw(pick["points"])
    s["finished_at"] = time.time()
    notify_researcher(s)
    return jsonify({
        "ok": True,
        "selected_round_index": pick["round_index"],
        "applicant_name": pick["applicant_name"],
        "decision": pick["decision"],
        "outcome": pick["outcome"],
        "selected_round_points": pick["points"],
        "bonus_krw": s["bonus_krw"],
        "total_points": s["total_points"],
    })


def notify_researcher(s):
    """Email the session CSV via Resend, if configured. Never blocks the result."""
    key = os.environ.get("RESEND_API_KEY")
    to = os.environ.get("NOTIFY_EMAIL", "hannahmohamed.sayed23@gmail.com")
    if not (key and to):
        return
    try:
        import urllib.request
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in sorted(s["rows"], key=lambda x: x["round_index"]):
            w.writerow({k: r.get(k, "") for k in CSV_COLUMNS})
        body = json.dumps({
            "from": os.environ.get("NOTIFY_FROM", "onboarding@resend.dev"),
            "to": [to],
            "subject": f"Loan Default Game - participant {s['participant_id']} finished",
            "text": (f"Participant {s['participant_id']}\n"
                     f"Total points: {s['total_points']}\n"
                     f"Paid round: {s['selected_round_index']}\n"
                     f"Bonus: {s['bonus_krw']} KRW\n\n{buf.getvalue()}"),
        }).encode()
        req = urllib.request.Request(
            "https://api.resend.com/emails", data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=6).read()
    except Exception:
        pass


def _fmt(sec):
    return f"{int(sec)//60}:{int(sec) % 60:02d}"


REPORT_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>Results &middot; hypotheses</title><style>{{css|safe}}
table{border-collapse:collapse;width:100%;font-size:13.5px;margin:6px 0 4px}
th,td{border:1px
 solid var(--rule);padding:7px 9px;text-align:left}
th{background:var(--ink);color:#fff;font-size:11px;letter-spacing:.09em;text-transform:uppercase}
.hblock{border:1px solid var(--rule);border-left:3px solid var(--ink);border-radius:2px;padding:16px 18px;margin:16px 0;background:var(--card)}
.hblock h2{margin:0 0 2px;font-size:17px}
.pred{font-size:12.5px;color:var(--muted);margin:0 0 14px}
.barlab{font-size:12px;color:var(--ink);margin:10px 0 4px;display:flex;justify-content:space-between}
.barlab .n{color:var(--muted)}
.bar{background:var(--band);border-radius:2px;height:22px;overflow:hidden}
.bar>span{display:block;height:100%;background:var(--ink)}
.bar.alt>span{background:var(--bronze)}
.effect{margin-top:12px;font-size:13.5px}
.effect .big{font-weight:700;font-size:15px}
.tag{display:inline-block;font-size:11px;font-weight:700;padding:2px 8px;border-radius:2px;margin-left:6px}
.tag.yes{background:#DDE7D8;color:#3B5D34}.tag.no{background:#F3D9D4;color:#8A2F22}
</style></head><body><div class="wrap">
<p class="eyebrow">Results &middot; matched to the three hypotheses</p>
<h1>Hypothesis results</h1>
<p class="muted">{{ n_participants }} participant(s) &middot; {{ n }} decisions
{% if n_unfinished %}&middot; {{ n_unfinished }} still in progress{% endif %}</p>
<p>
  <a class="btn" href="/admin/report.csv?key={{key}}">Download results table (CSV)</a>
  &nbsp; <button class="btn ghost" onclick="window.print()">Print / Save charts as PDF</button>
  &nbsp; <a class="btn ghost" href="/admin?key={{key}}">Back to live monitor</a>
</p>
<hr class="rule">

<h2 style="margin-bottom:4px">Payoff per participant</h2>
<table><tr><th>Participant</th><th>Decisions</th><th>Approved</th><th>Total points</th><th>Bonus</th><th>Status</th></tr>
{% for p in payoffs %}<tr>
<td class="mono">{{p.pid}}</td><td class="mono">{{p.n}} / 8</td><td class="mono">{{p.approved}}</td>
<td class="mono">{{p.points}}</td><td class="mono">{{ (p.bonus ~ ' KRW') if p.bonus is not none else 'â€”' }}</td>
<td>{{p.status}}</td></tr>{% endfor %}
</table>

{% macro hb(h) %}
<div class="hblock">
  <h2>{{h.title}}</h2>
  <p class="pred">Prediction: {{h.pred}}</p>
  <div class="barlab"><span>{{h.g1}}</span><span class="n">{{h.r1pct}}% approved &middot; {{h.a1}}/{{h.n1}}</span></div>
  <div class="bar"><span style="width:{{h.r1pct}}%"></span></div>
  <div class="barlab"><span>{{h.g2}}</span><span class="n">{{h.r2pct}}% approved &middot; {{h.a2}}/{{h.n2}}</span></div>
  <div class="bar alt"><span style="width:{{h.r2pct}}%"></span></div>
  <p class="effect"><span class="big">{{h.effect_pp}} pp</span> {{h.effect_desc}}
  <span class="tag {{'yes' if h.supports else 'no'}}">{{ 'matches prediction' if h.supports else 'against prediction' }}</span></p>
</div>
{% endmacro %}

<h2 style="margin-top:22px">The three hypotheses</h2>
{% if n == 0 %}<p class="muted">No decisions saved yet.</p>{% else %}
{{ hb(h1) }}{{ hb(h2) }}{{ hb(h3) }}
{% endif %}

<h2 style="margin-top:22px">What drove the decisions</h2>
<p class="muted" style="margin-top:0">Single most important factor participants chose (all decisions).</p>
<table><tr><th>Stated factor</th><th>Times chosen</th></tr>
{% for r in reasons %}<tr><td>{{r.label}}</td><td class="mono">{{r.count}}</td></tr>{% endfor %}
</table>

<hr class="rule">
<p class="muted">These are descriptive approval rates and differences (percentage points).
For formal permutation-test p-values, run <span class="mono">analyze_session.py</span> on the downloaded decisions CSV.</p>
</div></body></html>"""


def _hypothesis_summary():
    """Pool every saved decision row and compute H1/H2/H3 descriptively.
    Definitions match hypothesis_engine.py exactly."""
    rows = []
    for s in SESSIONS.values():
        rows.extend(s.get("rows", []))

    def is_high(r): return str(r.get("credit_score_level", "")).strip().lower() == "high"
    def is_prod(r): return str(r.get("use_of_funds", "")).strip().lower().startswith("prod")
    def is_appr(r): return str(r.get("decision", "")).strip().lower() == "approve"

    def rate(sub):
        n = len(sub)
        a = sum(1 for r in sub if is_appr(r))
        pct = round(100 * a / n, 1) if n else 0
        return {"n": n, "a": a, "pct": pct}

    high = rate([r for r in rows if is_high(r)])
    low = rate([r for r in rows if not is_high(r)])
    prod = rate([r for r in rows if is_prod(r)])
    nonp = rate([r for r in rows if not is_prod(r)])
    cellA = rate([r for r in rows if is_high(r) and not is_prod(r)])
    cellB = rate([r for r in rows if (not is_high(r)) and is_prod(r)])

    def eff(x, y):
        return round(x["pct"] - y["pct"], 1)

    h1 = {"title": "H1 â€” Credit score", "pred": "High credit score is approved more than Low.",
          "g1": "High credit score", "g2": "Low credit score",
          "r1pct": high["pct"], "a1": high["a"], "n1": high["n"],
          "r2pct": low["pct"], "a2": low["a"], "n2": low["n"],
          "effect_pp": eff(high, low), "effect_desc": "higher approval for High score.",
          "supports": eff(high, low) > 0}
    h2 = {"title": "H2 â€” Stated loan purpose", "pred": "Productive (income-generating) purposes are approved more than personal purposes.",
          "g1": "Productive use", "g2": "Non-productive use",
          "r1pct": prod["pct"], "a1": prod["a"], "n1": prod["n"],
          "r2pct": nonp["pct"], "a2": nonp["a"], "n2": nonp["n"],
          "effect_pp": eff(prod, nonp), "effect_desc": "higher approval for productive use.",
          "supports": eff(prod, nonp) > 0}
    h3 = {"title": "H3 â€” Credit-score dominance in conflict", "pred": "When the signals conflict, credit score dominates: High+personal is approved more than Low+productive.",
          "g1": "High score + personal purpose", "g2": "Low score + productive purpose",
          "r1pct": cellA["pct"], "a1": cellA["a"], "n1": cellA["n"],
          "r2pct": cellB["pct"], "a2": cellB["a"], "n2": cellB["n"],
          "effect_pp": eff(cellA, cellB), "effect_desc": "gap between the two conflict cases.",
          "supports": eff(cellA, cellB) > 0}

    reason_labels = {r["text"]: 0 for r in REASONS}
    for r in rows:
        rc = str(r.get("reason_choice", "")).strip()
        if rc in reason_labels:
            reason_labels[rc] += 1
        elif rc:
            reason_labels[rc] = reason_labels.get(rc, 0) + 1
    reasons = [{"label": k, "count": v} for k, v in reason_labels.items()]

    payoffs = []
    n_unfinished = 0
    for s in sorted(SESSIONS.values(), key=lambda x: x["participant_id"]):
        srows = s.get("rows", [])
        if not s.get("finished_at"):
            n_unfinished += 1
        payoffs.append({
            "pid": s["participant_id"], "n": len(srows),
            "approved": sum(1 for r in srows if is_appr(r)),
            "points": sum(r.get("points") or 0 for r in srows),
            "bonus": s.get("bonus_krw"),
            "status": "finished" if s.get("finished_at") else ("in progress" if srows else "instructions"),
        })

    return {
        "n": len(rows), "n_participants": len(SESSIONS), "n_unfinished": n_unfinished,
        "h1": h1, "h2": h2, "h3": h3, "reasons": reasons, "payoffs": payoffs,
    }


@app.route("/admin/report")
def admin_report():
    if request.args.get("key") != ADMIN_KEY:
        return "Unauthorised", 401
    data = _hypothesis_summary()
    return render_template_string(REPORT_HTML, css=CSS, key=ADMIN_KEY, **data)


@app.route("/admin/report.csv")
def admin_report_csv():
    if request.args.get("key") != ADMIN_KEY:
        return "Unauthorised", 401
    d = _hypothesis_summary()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "label", "group", "approval_rate_pct", "n_approved", "n_decisions"])
    for pf in d["payoffs"]:
        w.writerow(["payoff", "participant " + pf["pid"], pf["bonus"], "", pf["approved"], pf["n"]])
    for h in (d["h1"], d["h2"], d["h3"]):
        w.writerow([h["title"], "group 1", h["g1"], h["r1pct"], h["a1"], h["n1"]])
        w.writerow([h["title"], "group 2", h["g2"], h["r2pct"], h["a2"], h["n2"]])
        w.writerow([h["title"], "effect (g1 - g2) pp", "", h["effect_pp"], "", ""])
        w.writerow([h["title"], "matches prediction", "", "yes" if h["supports"] else "no", "", ""])
    for r in d["reasons"]:
        w.writerow(["reason chosen", r["label"], "", "", r["count"], ""])
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=hypothesis-results-{stamp}.csv"})


@app.route("/admin")
def admin():
    if request.args.get("key") != ADMIN_KEY:
        return "Unauthorised", 401
    rows = []
    for s in sorted(SESSIONS.values(), key=lambda x: x["participant_id"]):
        n = len(s["rows"])
        end = s["finished_at"] or time.time()
        secs = [r.get("seconds_on_round") or 0 for r in s["rows"]]
        rows.append({
            "pid": s["participant_id"], "n": n,
            "elapsed": _fmt(end - s["started_at"]),
            "avg": (sum(secs) / len(secs)) if secs else None,
            "approved": sum(1 for r in s["rows"] if r.get("decision") == "Approve"),
            "points": sum(r.get("points") or 0 for r in s["rows"]),
            "bonus": s["bonus_krw"],
            "status": "finished" if s["finished_at"] else ("in progress" if n else "instructions"),
        })
    return render_template_string(ADMIN_HTML, css=CSS, rows=rows, key=ADMIN_KEY,
                                  total_rows=sum(r["n"] for r in rows))


@app.route("/admin/csv")
def admin_csv():
    if request.args.get("key") != ADMIN_KEY:
        return "Unauthorised", 401
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    w.writeheader()
    for s in sorted(SESSIONS.values(), key=lambda x: x["participant_id"]):
        for r in sorted(s["rows"], key=lambda x:
 x["round_index"]):
            w.writerow({k: r.get(k, "") for k in CSV_COLUMNS})
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return Response(
        buf.getvalue().encode("utf-8-sig"), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=decisions-{stamp}.csv"})


if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", 5000)))
