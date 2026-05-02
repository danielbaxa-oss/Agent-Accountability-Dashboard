import os
import requests
import json
from datetime import datetime, timedelta
import pytz

# ── Config ────────────────────────────────────────────────────────────────────
FILLOUT_API_KEY = os.environ["FILLOUT_API_KEY"]
FORM_ID         = "8NYjecw9G1us"
OUTPUT_FILE     = "docs/index.html"
PACIFIC         = pytz.timezone("America/Los_Angeles")
AGENTS          = ["Sue", "Chase", "Bob", "Marie", "Laura"]

# Column aliases
COL_NAME        = "Select Your Name"
COL_CONTACTS    = "How Many Contacts Did You Make Today?"
COL_APPT_SET    = "How Many Appointments Did You Set Today?"
COL_APPT_COMP   = "How Many Appointments Did You Complete Today?"
COL_CONTRACTS   = "What is the number of Listing or Buyer Contracts Signed?"
COL_ESC_OPEN    = "What is the number of Escrows Opened?"
COL_ESC_CLOSE   = "What is the number of Escrows Closed?"

# ── Fetch all submissions from Fillout API ────────────────────────────────────
def fetch_submissions():
    url = f"https://api.fillout.com/v1/api/forms/{FORM_ID}/submissions"
    headers = {"Authorization": f"Bearer {FILLOUT_API_KEY}"}
    all_responses = []
    offset = 0
    limit  = 150

    while True:
        r = requests.get(url, headers=headers, params={"limit": limit, "offset": offset})
        r.raise_for_status()
        data = r.json()
        responses = data.get("responses", [])
        all_responses.extend(responses)
        if len(responses) < limit:
            break
        offset += limit

    return all_responses

# ── Parse into flat rows ──────────────────────────────────────────────────────
def parse_submissions(responses):
    rows = []
    def safe_int(val):
        try:
            return int(float(str(val).strip()))
        except (ValueError, TypeError):
            return 0

    for resp in responses:
        # Parse submission date
        submitted_str = resp.get("submittedAt") or resp.get("lastUpdatedAt", "")
        try:
            dt = datetime.fromisoformat(submitted_str.replace("Z", "+00:00"))
            dt = dt.astimezone(PACIFIC)
        except Exception:
            continue

        # Extract question answers by label
        answers = {q["name"]: q.get("value", 0) for q in resp.get("questions", [])}

        name = answers.get(COL_NAME, "")
        if not name or "TEST" in str(name).upper():
            continue
        if name not in AGENTS:
            continue

        rows.append({
            "date": dt.date(),
            "week_start": (dt.date() - timedelta(days=dt.weekday())),  # Monday
            "name": name,
            "contacts":   safe_int(answers.get(COL_CONTACTS,  0)),
            "appt_set":   safe_int(answers.get(COL_APPT_SET,  0)),
            "appt_comp":  safe_int(answers.get(COL_APPT_COMP, 0)),
            "contracts":  safe_int(answers.get(COL_CONTRACTS, 0)),
            "esc_open":   safe_int(answers.get(COL_ESC_OPEN,  0)),
            "esc_close":  safe_int(answers.get(COL_ESC_CLOSE, 0)),
        })

    return rows

# ── Aggregate by agent + week ─────────────────────────────────────────────────
def aggregate(rows):
    from collections import defaultdict
    # weekly[agent][week_start] = {metrics}
    weekly = defaultdict(lambda: defaultdict(lambda: {
        "contacts": 0, "appt_set": 0, "appt_comp": 0,
        "contracts": 0, "esc_open": 0, "esc_close": 0, "days": set()
    }))
    daily = defaultdict(lambda: defaultdict(lambda: {
        "contacts": 0, "appt_set": 0, "appt_comp": 0,
        "contracts": 0, "esc_open": 0, "esc_close": 0
    }))

    for r in rows:
        w = weekly[r["name"]][r["week_start"]]
        w["contacts"]  += r["contacts"]
        w["appt_set"]  += r["appt_set"]
        w["appt_comp"] += r["appt_comp"]
        w["contracts"] += r["contracts"]
        w["esc_open"]  += r["esc_open"]
        w["esc_close"] += r["esc_close"]
        w["days"].add(r["date"])

        d = daily[r["name"]][r["date"]]
        d["contacts"]  += r["contacts"]
        d["appt_set"]  += r["appt_set"]
        d["appt_comp"] += r["appt_comp"]
        d["contracts"] += r["contracts"]
        d["esc_open"]  += r["esc_open"]
        d["esc_close"] += r["esc_close"]

    return weekly, daily

# ── Determine last complete week ──────────────────────────────────────────────
def last_complete_week():
    today = datetime.now(PACIFIC).date()
    # Monday of current week
    this_monday = today - timedelta(days=today.weekday())
    # Last complete week = previous Monday
    last_monday = this_monday - timedelta(weeks=1)
    last_sunday = last_monday + timedelta(days=6)
    return last_monday, last_sunday

# ── Build HTML ────────────────────────────────────────────────────────────────
def build_html(weekly, daily):
    last_monday, last_sunday = last_complete_week()
    generated = datetime.now(PACIFIC).strftime("%B %d, %Y at %I:%M %p PT")

    # Build per-agent sections
    agent_sections = ""
    for agent in AGENTS:
        agent_weekly = weekly.get(agent, {})

        # Only complete weeks (week_start <= last_monday)
        complete_weeks = {
            ws: v for ws, v in agent_weekly.items()
            if ws <= last_monday
        }

        if not complete_weeks:
            continue

        sorted_weeks = sorted(complete_weeks.keys())

        # Trendline data
        labels_js  = json.dumps([w.strftime("%-m/%-d") for w in sorted_weeks])
        contacts_js = json.dumps([complete_weeks[w]["contacts"] for w in sorted_weeks])

        # Last complete week detail
        lcw = complete_weeks.get(last_monday, {})
        lcw_contacts  = lcw.get("contacts",  0)
        lcw_appt_set  = lcw.get("appt_set",  0)
        lcw_appt_comp = lcw.get("appt_comp", 0)
        lcw_contracts = lcw.get("contracts", 0)
        lcw_esc_open  = lcw.get("esc_open",  0)
        lcw_esc_close = lcw.get("esc_close", 0)
        lcw_days      = sorted(lcw.get("days", set()))

        week_label = f"{last_monday.strftime('%b %-d')} – {last_sunday.strftime('%b %-d, %Y')}"

        # Daily breakdown rows for last complete week
        day_rows = ""
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for d in lcw_days:
            dd = daily[agent].get(d, {})
            day_rows += f"""
            <tr>
              <td>{d.strftime('%a %-m/%-d')}</td>
              <td>{dd.get('contacts',0)}</td>
              <td>{dd.get('appt_set',0)}</td>
              <td>{dd.get('appt_comp',0)}</td>
              <td>{dd.get('contracts',0)}</td>
              <td>{dd.get('esc_open',0)}</td>
              <td>{dd.get('esc_close',0)}</td>
            </tr>"""

        chart_id = f"chart_{agent.lower()}"

        agent_sections += f"""
        <div class="agent-card">
          <div class="agent-header">
            <span class="agent-name">{agent}</span>
            <span class="agent-meta">Weekly Contacts Trendline</span>
          </div>

          <div class="chart-wrap">
            <canvas id="{chart_id}"></canvas>
          </div>

          <div class="week-label">Last Complete Week: {week_label}</div>

          <div class="kpi-row">
            <div class="kpi"><div class="kpi-val">{lcw_contacts}</div><div class="kpi-lbl">Contacts</div></div>
            <div class="kpi"><div class="kpi-val">{lcw_appt_set}</div><div class="kpi-lbl">Appts Set</div></div>
            <div class="kpi"><div class="kpi-val">{lcw_appt_comp}</div><div class="kpi-lbl">Appts Completed</div></div>
            <div class="kpi"><div class="kpi-val">{lcw_contracts}</div><div class="kpi-lbl">Contracts</div></div>
            <div class="kpi"><div class="kpi-val">{lcw_esc_open}</div><div class="kpi-lbl">Escrows Opened</div></div>
            <div class="kpi"><div class="kpi-val">{lcw_esc_close}</div><div class="kpi-lbl">Escrows Closed</div></div>
          </div>

          <details class="daily-detail">
            <summary>Daily Breakdown</summary>
            <table class="daily-table">
              <thead>
                <tr>
                  <th>Day</th><th>Contacts</th><th>Appts Set</th>
                  <th>Appts Comp</th><th>Contracts</th><th>Esc Open</th><th>Esc Close</th>
                </tr>
              </thead>
              <tbody>{day_rows}</tbody>
            </table>
          </details>

          <script>
            (function() {{
              const ctx = document.getElementById('{chart_id}').getContext('2d');
              new Chart(ctx, {{
                type: 'line',
                data: {{
                  labels: {labels_js},
                  datasets: [{{
                    label: 'Contacts',
                    data: {contacts_js},
                    borderColor: '#2563eb',
                    backgroundColor: 'rgba(37,99,235,0.08)',
                    borderWidth: 2.5,
                    pointRadius: 4,
                    pointBackgroundColor: '#2563eb',
                    tension: 0.3,
                    fill: true
                  }}]
                }},
                options: {{
                  responsive: true,
                  plugins: {{
                    legend: {{ display: false }},
                    tooltip: {{ mode: 'index', intersect: false }}
                  }},
                  scales: {{
                    y: {{ beginAtZero: true, grid: {{ color: 'rgba(0,0,0,0.06)' }} }},
                    x: {{ grid: {{ display: false }} }}
                  }}
                }}
              }});
            }})();
          </script>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agent Accountability Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #f4f6f9;
    color: #1a1a2e;
    padding: 24px 16px;
  }}
  .dashboard-header {{
    text-align: center;
    margin-bottom: 32px;
  }}
  .dashboard-header h1 {{
    font-size: 1.6rem;
    font-weight: 700;
    color: #1a1a2e;
  }}
  .dashboard-header .updated {{
    font-size: 0.8rem;
    color: #64748b;
    margin-top: 4px;
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(520px, 1fr));
    gap: 24px;
    max-width: 1200px;
    margin: 0 auto;
  }}
  .agent-card {{
    background: #fff;
    border-radius: 12px;
    padding: 24px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
  }}
  .agent-header {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 16px;
  }}
  .agent-name {{
    font-size: 1.25rem;
    font-weight: 700;
    color: #1a1a2e;
  }}
  .agent-meta {{
    font-size: 0.75rem;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }}
  .chart-wrap {{
    height: 180px;
    margin-bottom: 20px;
  }}
  .week-label {{
    font-size: 0.78rem;
    color: #64748b;
    margin-bottom: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }}
  .kpi-row {{
    display: grid;
    grid-template-columns: repeat(6, 1fr);
    gap: 8px;
    margin-bottom: 16px;
  }}
  .kpi {{
    text-align: center;
    background: #f8fafc;
    border-radius: 8px;
    padding: 10px 4px;
  }}
  .kpi-val {{
    font-size: 1.4rem;
    font-weight: 700;
    color: #2563eb;
  }}
  .kpi-lbl {{
    font-size: 0.65rem;
    color: #64748b;
    margin-top: 2px;
    line-height: 1.2;
  }}
  .daily-detail summary {{
    cursor: pointer;
    font-size: 0.8rem;
    color: #64748b;
    padding: 4px 0;
    user-select: none;
  }}
  .daily-detail summary:hover {{ color: #2563eb; }}
  .daily-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.8rem;
    margin-top: 10px;
  }}
  .daily-table th {{
    background: #f1f5f9;
    padding: 6px 8px;
    text-align: center;
    font-weight: 600;
    color: #475569;
  }}
  .daily-table td {{
    padding: 6px 8px;
    text-align: center;
    border-bottom: 1px solid #f1f5f9;
  }}
  @media (max-width: 560px) {{
    .grid {{ grid-template-columns: 1fr; }}
    .kpi-row {{ grid-template-columns: repeat(3, 1fr); }}
  }}
</style>
</head>
<body>
<div class="dashboard-header">
  <h1>Agent Accountability Dashboard</h1>
  <div class="updated">Updated {generated} &nbsp;·&nbsp; Showing completed weeks only</div>
</div>
<div class="grid">
{agent_sections}
</div>
</body>
</html>"""

    return html

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Fetching submissions from Fillout...")
    responses = fetch_submissions()
    print(f"  {len(responses)} responses retrieved")

    rows = parse_submissions(responses)
    print(f"  {len(rows)} valid rows parsed")

    weekly, daily = aggregate(rows)

    os.makedirs("docs", exist_ok=True)
    html = build_html(weekly, daily)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard written to {OUTPUT_FILE}")
