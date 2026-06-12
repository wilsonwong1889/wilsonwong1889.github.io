import os, json
from playwright.sync_api import sync_playwright

BASE = "https://bipoccreativeinnovationstudio.com"
RESERVE = (BASE + "/reserve?id=3da10bf7-29f9-4bd0-9ba0-4d164fd0b35b"
           "&date=2026-06-13&start=2026-06-13T12%3A00%3A00-06%3A00")
OUT = "/tmp/shots"
os.makedirs(OUT, exist_ok=True)
DSR = 2
VP = {"width": 1400, "height": 1000}
meta = {}


def log(*a): print(*a, flush=True)


def bbox(pg, selector, has_text=None):
    """Return [x,y,w,h] in image px for the first matching visible element, else None."""
    try:
        loc = pg.locator(selector, has_text=has_text) if has_text else pg.locator(selector)
        loc = loc.first
        bb = loc.bounding_box()
        if not bb:
            return None
        return [round(bb["x"] * DSR), round(bb["y"] * DSR),
                round(bb["width"] * DSR), round(bb["height"] * DSR)]
    except Exception as e:
        log("   bbox fail", selector, e)
        return None


def shot(pg, name, targets):
    path = f"{OUT}/{name}.png"
    pg.screenshot(path=path)
    anns = []
    for t in targets:
        bb = bbox(pg, t["sel"], t.get("has_text"))
        if bb:
            anns.append({"n": t.get("n"), "label": t["label"], "bbox": bb,
                         "side": t.get("side", "left")})
    meta[name] = {"size": [VP["width"] * DSR, VP["height"] * DSR], "anns": anns}
    log(name, "->", len(anns), "anns")


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport=VP, device_scale_factor=DSR)
    pg = ctx.new_page()

    # 1 — Rooms calendar
    pg.goto(BASE + "/rooms", wait_until="networkidle", timeout=45000)
    pg.wait_for_timeout(2200)
    shot(pg, "an_01_rooms", [
        {"n": 1, "sel": "button.avail-cal-day.is-available", "has_text": "13",
         "label": "Click any green (open) day", "side": "left"},
    ])

    # 2 — Studios with time buttons
    pg.locator("button.avail-cal-day.is-available", has_text="13").first.click()
    pg.wait_for_timeout(1500)
    pg.evaluate("document.querySelector('a.availability-time-button')?.scrollIntoView({block:'center'})")
    pg.wait_for_timeout(1200)
    shot(pg, "an_02_studios", [
        {"n": 2, "sel": "a.availability-time-button", "label": "Pick a start time on a room", "side": "top"},
    ])

    # 3 — Reserve top (stepper)
    pg.goto(RESERVE, wait_until="networkidle", timeout=45000)
    pg.wait_for_timeout(2500)
    shot(pg, "an_03_reserve", [
        {"n": 3, "sel": ".reserve-step-list", "label": "Date -> Time -> Details -> Checkout", "side": "bottom"},
    ])

    # 4 — Details (time, duration, guest)
    pg.evaluate("document.querySelector('#reserve-guest-name')?.scrollIntoView({block:'center'})")
    pg.wait_for_timeout(700)
    pg.fill("#reserve-guest-name", "Jordan Lee")
    pg.fill("#reserve-guest-phone", "403-555-0142")
    pg.wait_for_timeout(500)
    shot(pg, "an_04_details", [
        {"n": 4, "sel": "#reserve-guest-name", "label": "Enter name & phone (guest is fine)", "side": "left"},
    ])

    # 5 — Payment
    try:
        try:
            cb = pg.locator("#reserve-policy-checkbox")
            if cb.count():
                cb.check(force=True)
                pg.wait_for_timeout(400)
        except Exception as e:
            log("policy", e)
        pg.locator("button:has-text('Continue to checkout')").first.click(timeout=15000)
        pg.wait_for_timeout(4000)
        try:
            pg.locator("button:has-text('Save contact information')").first.click()
            log("saved contact")
        except Exception as e:
            log("save", e)
        pg.wait_for_timeout(2000)
        try:
            pg.wait_for_selector("iframe[src*='js.stripe.com']", timeout=20000)
        except Exception as e:
            log("stripe wait", e)
        pg.wait_for_timeout(6000)
        pg.evaluate("[...document.querySelectorAll('*')].find(e=>/Payment details/.test(e.textContent)&&e.children.length<3)?.scrollIntoView({block:'start'})")
        pg.wait_for_timeout(1500)
        shot(pg, "an_05_payment", [
            {"n": 5, "sel": "button", "has_text": "Pay now", "label": "Pay the deposit to confirm", "side": "left"},
        ])
    except Exception as e:
        log("STEP5 FAIL", e)

    # 6 — Staff catalog
    try:
        pg.goto(BASE + "/staff", wait_until="networkidle", timeout=45000)
        pg.wait_for_timeout(2500)
        shot(pg, "an_06_staff", [
            {"n": 6, "sel": "#staff-search-text", "label": "Search the team by name, skill, or role", "side": "bottom"},
        ])
    except Exception as e:
        log("STEP6 FAIL", e)

    # 7 — Staff booking sidebar
    try:
        pg.locator("#staff-team-grid a, #staff-team-grid button").first.click()
        pg.wait_for_timeout(2000)
        pg.evaluate("document.querySelector('.reserve-step-list')?.scrollIntoView({block:'center'})")
        pg.wait_for_timeout(1200)
        shot(pg, "an_07_staff_booking", [
            {"n": 7, "sel": ".reserve-step-list", "label": "Staff -> Time -> Details -> Checkout", "side": "bottom"},
        ])
    except Exception as e:
        log("STEP7 FAIL", e)

    # 8 — Engineer application
    try:
        pg.goto(BASE + "/staff", wait_until="networkidle", timeout=45000)
        pg.wait_for_timeout(1500)
        pg.evaluate("document.querySelector('#engineer-application-form')?.scrollIntoView({block:'start'})")
        pg.wait_for_timeout(1000)
        shot(pg, "an_08_apply", [
            {"n": 8, "sel": "textarea[name='skillset']", "label": "List what you do, in detail", "side": "left"},
            {"n": 9, "sel": "#engineer-application-submit", "label": "Submit your application", "side": "left"},
        ])
    except Exception as e:
        log("STEP8 FAIL", e)

    ctx.close(); b.close()

json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=2)
log("DONE; steps:", list(meta.keys()))
