# Loan Officer Experiment

An English-language Flask experiment for a four-person pilot on how loan
officers weigh a numeric credit score against the applicant's stated purpose.

## Experimental design

- Four participants: `01`–`04`
- Eight different loan applications per participant
- 2 × 2 within-participant design:
  - high or low numeric credit score
  - productive or personal stated loan purpose
- Two observations per design cell for each participant
- Story/score combinations are counterbalanced across participant IDs
- One untimed practice application
- Sixty seconds per real application, followed by a 30-second grace period
- One randomly selected decision determines the performance bonus
- Maximum bonus: 5,000 KRW

Each real application collects:

1. Approve or reject
2. Estimated repayment probability (0–100%)
3. Estimated business-success probability (0–100%)
4. The participant's main deciding factor
5. Time spent on the application

## Run from PowerShell

```powershell
git clone https://github.com/hanasayed23-pixel/loan-default-game.git
cd loan-default-game
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
$env:SECRET_KEY = "replace-with-a-long-random-value"
$env:ADMIN_KEY = "replace-with-a-private-admin-password"
py app.py
```

Participant page: <http://127.0.0.1:5000>

Administrator page:

```text
http://127.0.0.1:5000/admin?key=YOUR_ADMIN_KEY
```

## Render configuration

The existing `Procfile` starts one Gunicorn worker with eight threads, which is
appropriate for four participants playing simultaneously.

In the Render service, set:

- `SECRET_KEY`: a long random value
- `ADMIN_KEY`: a private password known only to the researcher
- `RESEND_API_KEY`: optional; enables an emailed CSV backup after each participant
- `NOTIFY_EMAIL`: optional destination for that backup

Render's free filesystem is temporary. Download the raw CSV from the
administrator page immediately after the last participant finishes. The
administrator report can also be printed or saved as a PDF.

## Create the professor-ready results

Install the analysis packages:

```powershell
py -m pip install -r requirements-analysis.txt
```

After downloading the raw CSV:

```powershell
py analyze_session.py .\decisions.csv
```

The `results` folder will contain:

- `Results_LoanOfficer_Experiment.xlsx`
- `Results_Summary.pdf`
- four PNG charts

With only four participants, this is a pilot. Interpret effect direction and
individual consistency; do not claim population-level proof from conventional
significance tests.
