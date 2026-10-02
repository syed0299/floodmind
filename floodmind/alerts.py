"""Tamil/English ward advisories from structured model output, plus CAP 1.2 XML.

Templates (not an LLM) so the wording is predictable and can be reviewed once by a native
speaker. These are demo advisories, not official warnings; in India public warnings come
from IMD and the state disaster authority (TN-Alert / SACHET).
"""
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

IST = timezone(timedelta(hours=5, minutes=30))

LEVELS = [  # (min probability, key, English, Tamil)
    (0.60, "high", "High chance", "அதிக வாய்ப்பு"),
    (0.30, "elevated", "Elevated chance", "கணிசமான வாய்ப்பு"),
    (0.00, "low", "Low chance", "குறைந்த வாய்ப்பு"),
]


def level(p):
    for lo, key, en, ta in LEVELS:
        if p >= lo:
            return key, en, ta


def advisory(ward_id, locality, p, horizon_h=24):
    key, en_lvl, ta_lvl = level(p)
    place = f"Ward {ward_id}" + (f" ({locality})" if locality else "")
    loc_ta = f"{locality[5:]} அருகே" if locality.startswith("near ") else locality
    place_ta = f"வார்டு {ward_id}" + (f" ({loc_ta})" if loc_ta else "")
    pct = round(100 * p)
    en = (f"{place}: {en_lvl} of street flooding in the next {horizon_h} hours (about {pct}%).")
    ta = (f"{place_ta}: அடுத்த {horizon_h} மணி நேரத்தில் தெருக்களில் மழைநீர் தேங்க "
          f"{ta_lvl} (சுமார் {pct}%).")
    if key == "high":
        en += " Move vehicles to higher ground, avoid subways and low roads, keep phones charged."
        ta += (" வாகனங்களை மேடான இடத்துக்கு மாற்றவும், சுரங்கப்பாதைகளையும் தாழ்வான "
               "சாலைகளையும் தவிர்க்கவும், கைபேசியை சார்ஜ் செய்து வைக்கவும்.")
    elif key == "elevated":
        en += " Avoid subways and watch for water entering ground floors."
        ta += " சுரங்கப்பாதைகளைத் தவிர்க்கவும்; தரைத்தளத்தில் நீர் புகுகிறதா எனக் கவனிக்கவும்."
    return {"level": key, "en": en, "ta": ta}


def cap_xml(ward_id, locality, p, area_polygon_latlon, issued=None, horizon_h=24):
    """Common Alerting Protocol 1.2 message (the format SACHET ingests)."""
    issued = issued or datetime.now(IST)
    key, en_lvl, _ = level(p)
    severity = {"high": "Severe", "elevated": "Moderate", "low": "Minor"}[key]
    poly = " ".join(f"{lat:.5f},{lon:.5f}" for lat, lon in area_polygon_latlon)
    a = advisory(ward_id, locality, p, horizon_h)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>floodmind-w{ward_id}-{issued:%Y%m%d%H%M}</identifier>
  <sender>floodmind-demo</sender>
  <sent>{issued.isoformat(timespec="seconds")}</sent>
  <status>Exercise</status>
  <msgType>Alert</msgType>
  <scope>Public</scope>
  <info>
    <language>en-IN</language>
    <category>Met</category>
    <event>Urban flooding</event>
    <urgency>Expected</urgency>
    <severity>{severity}</severity>
    <certainty>{"Likely" if p >= 0.5 else "Possible"}</certainty>
    <expires>{(issued + timedelta(hours=horizon_h)).isoformat(timespec="seconds")}</expires>
    <headline>{escape(en_lvl)} of street flooding, Ward {ward_id}</headline>
    <description>{escape(a["en"])}</description>
    <area><areaDesc>{escape(f"GCC Ward {ward_id} {locality}".strip())}</areaDesc><polygon>{poly}</polygon></area>
  </info>
  <info>
    <language>ta-IN</language>
    <category>Met</category>
    <event>நகர்ப்புற வெள்ளம்</event>
    <urgency>Expected</urgency>
    <severity>{severity}</severity>
    <certainty>{"Likely" if p >= 0.5 else "Possible"}</certainty>
    <description>{escape(a["ta"])}</description>
    <area><areaDesc>வார்டு {ward_id}</areaDesc><polygon>{poly}</polygon></area>
  </info>
</alert>"""
