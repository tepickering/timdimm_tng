"""
FastAPI web interface for OxWagon enclosure status and timDIMM start/stop control.
"""

import csv
import io
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

from timdimm_tng.timdimm_startstop import timdimm_start, timdimm_stop

app = FastAPI(title="timDIMM Web Interface")

STATUS_FILE = Path.home() / "ox_wagon_status.json"
STOP_FILE = Path.home() / "STOP"
SEEING_FILE = Path.home() / "seeing.csv"

HTML_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>timDIMM Status</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace;
    background: #1a1a2e; color: #e0e0e0;
    display: flex; flex-direction: column; align-items: center;
    min-height: 100vh; padding: 1.5rem;
  }
  h1 { margin-bottom: 1rem; color: #c8d6e5; font-size: 1.6rem; }
  .card {
    background: #16213e; border-radius: 8px; padding: 1.2rem;
    width: 100%; max-width: 820px; margin-bottom: 1rem;
    box-shadow: 0 2px 8px rgba(0,0,0,0.4);
  }
  .card h2 { font-size: 1rem; color: #8395a7; margin-bottom: 0.8rem; }
  table { width: 100%; border-collapse: collapse; }
  td { padding: 0.35rem 0.5rem; border-bottom: 1px solid #1a1a2e; font-size: 0.9rem; }
  td.label { color: #c8d6e5; }
  td.val { text-align: right; font-weight: 600; }
  td.spacer { width: 1.5rem; }
  .on  { color: #2ecc71; }
  .off { color: #e74c3c; }
  .toggle-btn {
    display: block; width: 100%; padding: 0.9rem;
    font-size: 1.1rem; font-weight: 700; border: none; border-radius: 6px;
    cursor: pointer; transition: background 0.2s;
  }
  .running  { background: #e74c3c; color: #fff; }
  .running:hover { background: #c0392b; }
  .stopped  { background: #2ecc71; color: #fff; }
  .stopped:hover { background: #27ae60; }
  canvas { width: 100% !important; }
  .meta { font-size: 0.75rem; color: #636e72; text-align: center; margin-top: 0.6rem; }
  #error { color: #e74c3c; text-align: center; margin-bottom: 0.5rem; display: none; }
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
</head>
<body>
<h1>timDIMM Status</h1>
<div id="error"></div>

<div class="card">
  <h2>System Control</h2>
  <button id="toggle" class="toggle-btn stopped" onclick="toggle()">Loading...</button>
</div>

<div class="card">
  <h2>Latest Seeing Measurement</h2>
  <table id="seeing-table"><tbody></tbody></table>
</div>

<div class="card">
  <h2>Seeing — Last 12 Hours</h2>
  <canvas id="seeing-chart" height="260"></canvas>
</div>

<div class="card">
  <h2>OxWagon Enclosure</h2>
  <table id="status-table"><tbody></tbody></table>
</div>

<div class="meta">Auto-refresh every 5 s</div>

<script>
let seeingChart = null;

function initChart() {
  const ctx = document.getElementById("seeing-chart").getContext("2d");
  seeingChart = new Chart(ctx, {
    type: "scatter",
    data: { datasets: [{
      label: "Seeing (arcsec)",
      data: [],
      backgroundColor: "rgba(52,152,219,0.6)",
      pointRadius: 2,
    }]},
    options: {
      animation: false,
      scales: {
        x: {
          type: "time",
          time: { unit: "hour", displayFormats: { hour: "HH:mm" }, tooltipFormat: "yyyy-MM-dd HH:mm" },
          title: { display: true, text: "UTC Time", color: "#8395a7" },
          ticks: { color: "#8395a7" },
          grid: { color: "rgba(255,255,255,0.06)" },
        },
        y: {
          min: 0, max: 5,
          title: { display: true, text: 'Seeing (")', color: "#8395a7" },
          ticks: { color: "#8395a7" },
          grid: { color: "rgba(255,255,255,0.06)" },
        }
      },
      plugins: { legend: { display: false } }
    }
  });
}

async function fetchStatus() {
  try {
    const resp = await fetch("/api/status");
    if (!resp.ok) throw new Error(resp.statusText);
    const data = await resp.json();

    // toggle button
    const btn = document.getElementById("toggle");
    if (data.running) {
      btn.textContent = "Stop timDIMM";
      btn.className = "toggle-btn running";
    } else {
      btn.textContent = "Start timDIMM";
      btn.className = "toggle-btn stopped";
    }

    // ox wagon status table — 2 columns of key/value pairs
    const tbody = document.querySelector("#status-table tbody");
    tbody.innerHTML = "";
    const ox = data.ox_wagon || {};
    const entries = Object.entries(ox);
    const half = Math.ceil(entries.length / 2);
    for (let i = 0; i < half; i++) {
      const tr = document.createElement("tr");
      function cell(key, val) {
        const cls = (val === true) ? "on" : (val === false) ? "off" : "";
        const display = (val === true) ? "YES" : (val === false) ? "NO" : String(val);
        return `<td class="label">${key}</td><td class="val ${cls}">${display}</td>`;
      }
      let html = cell(entries[i][0], entries[i][1]);
      html += '<td class="spacer"></td>';
      if (i + half < entries.length) {
        html += cell(entries[i + half][0], entries[i + half][1]);
      } else {
        html += "<td></td><td></td>";
      }
      tr.innerHTML = html;
      tbody.appendChild(tr);
    }

    document.getElementById("error").style.display = "none";
  } catch (e) {
    const el = document.getElementById("error");
    el.textContent = "Failed to fetch status: " + e.message;
    el.style.display = "block";
  }
}

async function fetchSeeing() {
  try {
    const resp = await fetch("/api/seeing");
    if (!resp.ok) throw new Error(resp.statusText);
    const data = await resp.json();

    // latest seeing table
    const tbody = document.querySelector("#seeing-table tbody");
    tbody.innerHTML = "";
    const latest = data.latest;
    if (latest) {
      const keys = Object.keys(latest);
      const half = Math.ceil(keys.length / 2);
      for (let i = 0; i < half; i++) {
        const tr = document.createElement("tr");
        let html = `<td class="label">${keys[i]}</td><td class="val">${latest[keys[i]]}</td>`;
        html += '<td class="spacer"></td>';
        if (i + half < keys.length) {
          html += `<td class="label">${keys[i + half]}</td><td class="val">${latest[keys[i + half]]}</td>`;
        } else {
          html += "<td></td><td></td>";
        }
        tr.innerHTML = html;
        tbody.appendChild(tr);
      }
    }

    // seeing chart
    if (seeingChart && data.history) {
      seeingChart.data.datasets[0].data = data.history.map(
        r => ({ x: r.time, y: r.seeing })
      );
      seeingChart.update();
    }
  } catch (e) { /* seeing data unavailable — leave stale */ }
}

async function toggle() {
  const btn = document.getElementById("toggle");
  btn.disabled = true;
  try {
    const resp = await fetch("/api/toggle", { method: "POST" });
    const data = await resp.json();
    if (data.running) {
      btn.textContent = "Stop timDIMM";
      btn.className = "toggle-btn running";
    } else {
      btn.textContent = "Start timDIMM";
      btn.className = "toggle-btn stopped";
    }
  } catch (e) {
    alert("Toggle failed: " + e.message);
  } finally {
    btn.disabled = false;
  }
}

initChart();
fetchStatus();
fetchSeeing();
setInterval(fetchStatus, 5000);
setInterval(fetchSeeing, 5000);
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


@app.get("/api/status")
async def status():
    ox_wagon = {}
    if STATUS_FILE.exists():
        try:
            ox_wagon = json.loads(STATUS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    running = not STOP_FILE.exists()
    return JSONResponse({"running": running, "ox_wagon": ox_wagon})


def _read_seeing_csv():
    """Read the last 12 hours of seeing data from ~/seeing.csv.

    Uses ``tail`` to grab a generous number of recent lines rather than
    reading the entire (potentially huge) file.
    """
    if not SEEING_FILE.exists():
        return None, []

    # grab header + last ~5000 lines (enough for 12 h at ~1 line / 10 s)
    try:
        header = SEEING_FILE.open().readline().strip()
        result = subprocess.run(
            ["tail", "-5000", str(SEEING_FILE)],
            capture_output=True, text=True, timeout=5,
        )
        lines = header + "\n" + result.stdout
    except Exception:
        return None, []

    reader = csv.DictReader(io.StringIO(lines))
    rows = []
    for row in reader:
        try:
            t = datetime.fromisoformat(row["time"])
            seeing = float(row["seeing"])
        except (KeyError, ValueError):
            continue
        rows.append((t, seeing, row))

    if not rows:
        return None, []

    latest = dict(rows[-1][2])
    try:
        latest["seeing"] = f'{float(latest["seeing"]):.3f}"'
    except (KeyError, ValueError):
        pass
    try:
        latest["azimuth"] = f'{float(latest["azimuth"]):.1f}\u00b0'
    except (KeyError, ValueError):
        pass
    try:
        latest["exptime"] = f'{float(latest["exptime"]) * 1000:.0f} ms'
    except (KeyError, ValueError):
        pass
    cutoff = rows[-1][0] - timedelta(hours=12)
    history = [
        {"time": r[2]["time"], "seeing": r[1]}
        for r in rows if r[0] >= cutoff
    ]

    return latest, history


@app.get("/api/seeing")
async def seeing():
    latest, history = _read_seeing_csv()
    return JSONResponse({"latest": latest, "history": history})


@app.post("/api/toggle")
async def toggle():
    if STOP_FILE.exists():
        timdimm_start()
        running = True
    else:
        timdimm_stop()
        running = False
    return JSONResponse({"running": running})


def main():
    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
