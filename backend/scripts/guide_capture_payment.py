import json
from playwright.sync_api import sync_playwright

BASE = "https://bipoccreativeinnovationstudio.com"
RESERVE = (BASE + "/reserve?id=3da10bf7-29f9-4bd0-9ba0-4d164fd0b35b"
           "&date=2026-06-13&start=2026-06-13T12%3A00%3A00-06%3A00")
OUT = "/tmp/shots"
DSR = 2


def log(*a): print(*a, flush=True)


def bb(loc):
    b = loc.bounding_box()
    return [round(b["x"]*DSR), round(b["y"]*DSR), round(b["width"]*DSR), round(b["height"]*DSR)] if b else None


with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True)
    ctx = br.new_context(viewport={"width": 1400, "height": 1000}, device_scale_factor=DSR)
    pg = ctx.new_page()
    pg.goto(RESERVE, wait_until="networkidle", timeout=45000)
    pg.wait_for_timeout(2500)
    pg.fill("#reserve-guest-name", "Jordan Lee")
    pg.fill("#reserve-guest-phone", "403-555-0142")
    cb = pg.locator("#reserve-policy-checkbox")
    if cb.count():
        cb.check(force=True)
    pg.wait_for_timeout(400)
    pg.locator("button:has-text('Continue to checkout')").first.click(timeout=15000)
    pg.wait_for_timeout(4000)
    try:
        pg.locator("button:has-text('Save contact information')").first.click()
    except Exception as e:
        log("save", e)
    pg.wait_for_timeout(2500)
    try:
        pg.wait_for_selector("#booking-payment-element iframe, iframe[src*='paypal.com']", timeout=20000, state="attached")
    except Exception as e:
        log("paypal", e)
    pg.wait_for_timeout(7000)

    # Position so the PayPal buttons and sidebar deposit summary are both in frame
    payment_buttons = pg.locator("#booking-payment-element").first
    payment_buttons.scroll_into_view_if_needed()
    pg.wait_for_timeout(800)
    # nudge up a little so the payment details above are also visible
    pg.mouse.wheel(0, -260)
    pg.wait_for_timeout(800)

    pg.screenshot(path=f"{OUT}/an_05_payment.png")

    anns = []
    try:
        b = bb(payment_buttons)
        if b: anns.append({"n": 5, "label": "Pay your deposit with PayPal", "bbox": b, "side": "left"})
    except Exception as e:
        log("payment buttons bbox", e)
    try:
        dep = pg.locator("text=Deposit due now").first
        b = bb(dep)
        if b: anns.append({"n": None, "label": "Only the deposit is due now", "bbox": b, "side": "left"})
    except Exception as e:
        log("dep bbox", e)
    # PayPal checkout buttons, including eligible wallets such as Apple Pay.
    try:
        paypal_frame = pg.locator("#booking-payment-element iframe, iframe[src*='paypal.com']").first
        b = bb(paypal_frame)
        if b: anns.append({"n": None, "label": "Use PayPal or eligible wallets like Apple Pay", "bbox": b, "side": "top"})
    except Exception as e:
        log("paypal bbox", e)

    meta = json.load(open(f"{OUT}/meta.json"))
    meta["an_05_payment"] = {"size": [2800, 2000], "anns": anns}
    json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=2)
    log("payment anns:", anns)
    ctx.close(); br.close()
log("DONE")
