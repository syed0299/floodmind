# Tamil review sheet

Every Tamil string FloodMind shows, with its English meaning and where it appears. Please check that each line is natural, correct and easy to understand for Chennai residents, and write any correction in the last column. Words in `{braces}` are filled in automatically (ward number, place name, hours, percentage).

## Ward advisories (`floodmind/alerts.py`)

Shown on the dashboard and in the CAP alerts.

| # | English meaning | Tamil now | Correction |
|---|---|---|---|
| A1 | High chance | அதிக வாய்ப்பு | |
| A2 | Elevated chance | கணிசமான வாய்ப்பு | |
| A3 | Low chance | குறைந்த வாய்ப்பு | |
| A4 | Ward {n} | வார்டு {n} | |
| A5 | near {place} | {place} அருகே | |
| A6 | Ward {n} ({place}): {level} of rainwater stagnating on the streets in the next {24} hours (about {p}%). | வார்டு {n} ({place}): அடுத்த {24} மணி நேரத்தில் தெருக்களில் மழைநீர் தேங்க {level} (சுமார் {p}%). | |
| A7 | (high) Move vehicles to higher ground, avoid subways and low-lying roads, keep your phone charged. | வாகனங்களை மேடான இடத்துக்கு மாற்றவும், சுரங்கப்பாதைகளையும் தாழ்வான சாலைகளையும் தவிர்க்கவும், கைபேசியை சார்ஜ் செய்து வைக்கவும். | |
| A8 | (elevated) Avoid subways; watch whether water is entering ground floors. | சுரங்கப்பாதைகளைத் தவிர்க்கவும்; தரைத்தளத்தில் நீர் புகுகிறதா எனக் கவனிக்கவும். | |
| A9 | Urban flooding (CAP event name) | நகர்ப்புற வெள்ளம் | |

Place names inside advisories currently come from OpenStreetMap in English letters, for example "வார்டு 177 (Velachery)". Should they be written in Tamil script (வேளச்சேரி)? If yes, a list of the 200 ward names in Tamil would be needed.

## Phone report page (`dashboard/report.html`)

| # | English meaning | Tamil now | Correction |
|---|---|---|---|
| R1 | Report flooding in your ward | உங்கள் வார்டில் வெள்ளத்தைப் பதிவு செய்யுங்கள் | |
| R2 | Step 1 / Step 2 | படி 1 / படி 2 | |
| R3 | Where are you? | நீங்கள் எங்கே இருக்கிறீர்கள்? | |
| R4 | Or tap your ward on the map | அல்லது வரைபடத்தில் உங்கள் வார்டைத் தொடுங்கள் | |
| R5 | Search your area or ward number | உங்கள் பகுதி அல்லது வார்டு எண்ணைத் தேடுங்கள் | |
| R6 | Change | மாற்று | |
| R7 | Is there water on the street right now? | இப்போது தெருவில் தண்ணீர் தேங்கியுள்ளதா? | |
| R8 | Yes, flooded / water on the street | ஆம், வெள்ளம் / தெருவில் தண்ணீர் | |
| R9 | No / no standing water | இல்லை / தண்ணீர் தேங்கவில்லை | |
| R10 | Step 3 · optional | படி 3 · விருப்பம் | |
| R11 | How deep is it? | எவ்வளவு ஆழம்? | |
| R12 | Ankle / Knee / Waist / Above waist | கணுக்கால் / முழங்கால் / இடுப்பு / இடுப்புக்கு மேல் | |
| R13 | Send report | அனுப்பு | |
| R14 | Thank you | நன்றி | |
| R15 | Report another ward | இன்னொரு வார்டைப் பதிவு செய் | |
| R16 | Wards FloodMind would most like to hear from: | FloodMind கேட்க விரும்பும் வார்டுகள்: | |
| R17 | Flood chance here: {before}% → {after}% | இங்கு வெள்ள வாய்ப்பு: {before}% → {after}% | |
| R18 | The map on the big screen and the nearby wards have been updated. | பெரிய திரையில் உள்ள வரைபடமும் அருகிலுள்ள வார்டுகளும் புதுப்பிக்கப்பட்டன. | |
| R19 | Only the ward, your answer, the depth and the time are stored. No name, phone number or location is stored. This is a demonstration system; in an emergency call 1913 (GCC) or 112. | வார்டு, உங்கள் பதில், ஆழம், நேரம் மட்டுமே சேமிக்கப்படும். பெயர், தொலைபேசி எண், இருப்பிடம் சேமிக்கப்படாது. இது ஒரு செயல்விளக்க அமைப்பு; அவசரத்துக்கு 1913 (GCC) அல்லது 112 அழைக்கவும். | |
| R20 | Can't reach FloodMind. Check you're on the same Wi-Fi as the laptop and try again. | FloodMind-ஐ அணுக முடியவில்லை. மடிக்கணினியின் அதே Wi-Fi-இல் இருக்கிறீர்களா எனப் பார்த்து மீண்டும் முயலுங்கள். | |
| R21 | Choose your ward first. | முதலில் உங்கள் வார்டைத் தேர்ந்தெடுங்கள். | |
| R22 | GCC ward {n} | GCC வார்டு {n} | |

## Pitch deck (slide "From forecast to action")

| # | English meaning | Tamil now | Correction |
|---|---|---|---|
| D1 | Tamil · high | தமிழ் · அதிகம் | |
| D2 | Ward 177 (Velachery): high chance of rainwater stagnating on the streets in the next 24 hours (about 88%). Move vehicles to higher ground, avoid subways and low-lying roads. | வார்டு 177 (வேளச்சேரி): அடுத்த 24 மணி நேரத்தில் தெருக்களில் மழைநீர் தேங்க அதிக வாய்ப்பு (சுமார் 88%). வாகனங்களை மேடான இடத்துக்கு மாற்றவும், சுரங்கப்பாதைகளையும் தாழ்வான சாலைகளையும் தவிர்க்கவும். | |

## Questions for the reviewer

1. Is "மழைநீர் தேங்க" (rainwater stagnating) the right everyday phrase for street flooding in Chennai, or would "வெள்ளம்" (flood) or "நீர் தேக்கம்" (waterlogging) read better?
2. For R9, is a plain "இல்லை" (No) enough on the button, or should it say "இல்லை, தண்ணீர் இல்லை" (No, no water)?
3. Is "கைபேசி" or "செல்போன்" more natural for "phone"?
