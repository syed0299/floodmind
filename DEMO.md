# FloodMind demo guide

A 5-minute pitch with a live demo, the checks to run before it, backup paths if anything fails, and short answers to the questions judges are likely to ask.

## The day before

- [ ] A native Tamil speaker has checked every line in [TAMIL_REVIEW.md](TAMIL_REVIEW.md).
- [ ] Deck placeholders filled: `[Team name]`, `[Hackathon name]`, `[Contact]` (cover and closing slides).
- [ ] Test the phone report page **on the venue's Wi-Fi**. Some venue networks stop phones from reaching a laptop. If yours does, bring a phone hotspot and connect the laptop to it.
- [ ] Rehearse the full run twice, once with no internet.
- [ ] Laptop charger, and a second phone to scan the QR code yourself if no judge volunteers.

## 30 minutes before

```bash
cd ~/Downloads/FloodMind
.venv/bin/python -m floodmind.preflight                # every line should say ok
.venv/bin/python -m floodmind.server --host 0.0.0.0     # leave this running
```

1. If macOS asks whether Python may accept incoming connections, click **Allow**.
2. Open http://127.0.0.1:8791. The status pill should say **Live**. Press **Refresh** once.
3. Scan the QR code on the Today view with your own phone and open the report page. Don't send anything.
4. If there are any reports from rehearsal, click **Clear demo reports** twice.
5. Open the pitch deck in another tab. Set the browser zoom so the whole Today view fits the projector.

## The 5 minutes

| Time | Show | Say (short version) |
|---|---|---|
| 0:00 | Deck: cover, then "The same wards flood every year" | Chennai floods where it flooded before: ward flood rates in even and odd years correlate at 0.84. |
| 0:40 | Deck: "Two serious systems already forecast Chennai" | Google forecasts at 20 km. Tamil Nadu spent ₹107 crore on 390 sensors. Nobody offers a ward-level layer that any city can run from open data, that learns during the storm and explains why places flood. |
| 1:10 | Deck: "One system, three loops" | Forecast tomorrow, correct during the storm, diagnose between monsoons. |
| 1:30 | **Dashboard, Today view** | This is today's real forecast for all 200 wards, refreshed every 3 hours from IMD and ECMWF. Today is dry, so it's calm, and that's the honest answer. |
| 1:50 | **A judge scans the QR code and reports their ward as flooded** | Watch the map: their ward and its neighbours rise within seconds, and FloodMind shows which ward it wants to hear from next. |
| 2:40 | **Replay a flood → Cyclone Ditwah, 2 Dec 2025** (forecast from the day before) | The forecast said 22 mm; 153 mm fell. FloodMind honestly said 15%. Drag the slider: after 8 citizen reports the remaining wards average 33%, and the error falls by a third. |
| 3:20 | **Drain check** | Every flood shows where drainage is failing. Egmore floods on 7 more wet days in every 100 than its ground explains. The list overlaps the government's own vulnerable areas. |
| 3:50 | **Scorecard** | Every number is from years the model never saw. Using the forecast from the day before, when it says high risk it's right 3 times in 4. We gave up 4% of overall score so a cloudburst can't be ignored. |
| 4:30 | Deck: limits and next, then the closing slide | Ward-level, not street depth; labels come from news. Next: a shadow run through this monsoon. Every flood makes the next forecast better. |

After the demo, click **Clear demo reports** twice.

## If something fails

| Problem | What to do |
|---|---|
| Phones can't open the report page | Select a ward on the dashboard and use **Report flooded here** / **Report dry here**. It's the same correction. |
| No internet at the venue | Carry on. The server serves the last saved forecast, and the status pill shows its age. Replays, Drain check and Scorecard need no internet. |
| The server won't start | Open `dashboard/index.html` directly, or the shared dashboard link. Everything except live reports works from the built-in snapshot. |
| Everything fails | Use the deck. The demo and "Running now" slides show the same screens. |

## Likely questions

**How accurate is it?** Every number is from years the model never saw. Using only the rain forecast from the day before (2024–25): when FloodMind says a ward is at high risk, flooding was reported there 76% of the time. It flagged every major storm at the advisory level. It misses many smaller floods, and it struggles on the first day of a storm when the rain forecast is wrong. False alarms on dry days: 1–3.5%.

**How is this different from Google Flood Hub or Tamil Nadu's system?** Google forecasts in 20 km cells. Tamil Nadu reaches street level for selected areas with ₹107 crore of sensors. FloodMind covers all 200 wards from open data, learns from citizens during the storm, ranks failing drains, and publishes its own scorecard. It's built to complement them.

**What's new here?** The models are standard. What's new: ward-level forecasting from news-derived flood records for an Indian city; one loop of forecast, citizen correction and drain diagnosis, tested on storms it never saw; and the finding that terrain doesn't explain where Chennai floods (ROC 0.50) while flood history does.

**Why not deep learning?** We tried a stronger tree model; it barely beat logistic regression, and their average beats both. A deep model needs hourly street-level flood records that don't exist for Chennai yet. Street-level depth is on the roadmap, with flood simulations as training data.

**Your labels come from news. Isn't that biased?** Yes. A flood nobody reported counts as dry. We checked that media-attention proxies don't explain the drain ranking (R² 0.04), and the next step, a shadow monsoon, scores forecasts against fresh reports.

**What if the rain forecast is wrong?** It will be sometimes. Ditwah's forecast missed by 130 mm. That's why the correction loop exists: from the day-before forecast, 10 citizen reports raise PR-AUC on the other wards from 0.41 to 0.60.

**How do you stop fake reports?** Today: one report per ward per hour per browser. A false "dry" can't raise risk and a false "flooded" can't lower it. For a real deployment we'd add photo checks and trust scores.

**Is it ready to use?** It's a validated prototype, ready for a supervised shadow run, not for public warnings. Public warnings must come from IMD and the state.

**What would it cost to run?** It runs on a laptop and open data. A hosted pilot is one small cloud server, plus a commercial weather-data licence.

**Can it work in other cities?** The data sources are national or global, so it should transfer. We haven't tested that yet, and it's the next experiment.
