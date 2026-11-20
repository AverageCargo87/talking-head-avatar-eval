"""Cost model: a fully live cloud avatar vs "prerender once + live answers only". ESTIMATES.

    python scripts/cost_model.py [--students 1 10 100] [--rub-per-usd 90]

Inputs are the vendor's public tariff page as read on 2026-08-19 and one measured lesson
script (40 minutes, 15.1 minutes of pure speech in 73 lines). The vendor bills per second
for the WHOLE session, silence included, so a live avatar costs the full 40 minutes for
every student, while a prerender costs the 15.1 minutes of speech once.

These are estimates for a design decision. The prerender tool was built
(prerender/anam_render.py), the per-student savings were never realised in production.
"""
import argparse

LESSON_MIN = 40.0
SPEECH_MIN = 15.1          # measured on the lesson script: 73 lines
LIVE_ANSWERS_MIN = 2.5     # assumption: 2-3 minutes of live answers per student
GROWTH = {"usd_month": 299, "minutes": 2000, "overage_usd_min": 0.12}   # the tier that allows 2 h sessions
CEILING_RUB_PER_LESSON = 400                                            # the customer's ceiling per 40 min


def per_minute_usd():
    package = GROWTH["usd_month"] / GROWTH["minutes"]
    return GROWTH["overage_usd_min"], package          # (cheapest, from the package)


def model(rub_per_usd=90.0):
    lo, hi = per_minute_usd()
    return {
        "live_lesson_rub": (LESSON_MIN * lo * rub_per_usd, LESSON_MIN * hi * rub_per_usd),
        "prerender_once_rub": (SPEECH_MIN * lo * rub_per_usd, SPEECH_MIN * hi * rub_per_usd),
        "live_answers_rub": (LIVE_ANSWERS_MIN * lo * rub_per_usd, LIVE_ANSWERS_MIN * hi * rub_per_usd),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--students", type=int, nargs="+", default=[1, 10, 100, 1000])
    ap.add_argument("--rub-per-usd", type=float, default=90.0)
    a = ap.parse_args()
    m = model(a.rub_per_usd)
    f = lambda r: f"{r[0]:.0f}-{r[1]:.0f}"  # noqa: E731
    print(f"ESTIMATES at {a.rub_per_usd:.0f} RUB/USD, Growth tier, per-second billing incl. silence")
    print(f"  fully live 40-min lesson     : {f(m['live_lesson_rub'])} RUB per student "
          f"(customer ceiling {CEILING_RUB_PER_LESSON})")
    print(f"  prerender {SPEECH_MIN} min of speech : {f(m['prerender_once_rub'])} RUB once, for all students")
    print(f"  live answers {LIVE_ANSWERS_MIN} min         : {f(m['live_answers_rub'])} RUB per student")
    print(f"\n{'students':>9} {'fully live, RUB':>18} {'prerender + answers, RUB':>26}")
    for n in a.students:
        live = (n * m["live_lesson_rub"][0], n * m["live_lesson_rub"][1])
        pre = (m["prerender_once_rub"][0] + n * m["live_answers_rub"][0],
               m["prerender_once_rub"][1] + n * m["live_answers_rub"][1])
        print(f"{n:>9} {f(live):>18} {f(pre):>26}")


if __name__ == "__main__":
    main()
