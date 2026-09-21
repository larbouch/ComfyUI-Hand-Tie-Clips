r"""The media slots: dense numbering, and the JS half exists.

    D:\ComfyUI\venv\Scripts\python.exe tools\check_media_slots.py

H3 takes 9 reference images, 3 reference videos and 3 standalone reference
audios. The pack matched the 9 and passed exactly one of the others until the
slots were added, so two whole channels sat at a third of capacity.

Two things about that are easy to get wrong and impossible to see afterwards.

**Numbering is dense.** Core numbers reference blocks by the order it iterates
them and the prompt cites those ordinals, so a gap must not survive: filling
slots 1 and 3 has to produce <Video 1> and <Video 2>, not 1 and 3. If it ever
produced a gap, a beat naming "the second clip" would cite something else and
nothing would report it.

**A file widget with no slot in the strip falls through to a native dial.**
That is the 0.4.0 failure recorded at run_panel.js:53 and it has recurred since.
Nothing checked it, so this does: every `*_file` widget the node declares must
be claimed by `media_strip.js`, and every widget the strip expects must exist.
"""
from __future__ import annotations

import importlib.util
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMFY = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, COMFY)

FAIL = []


def ck(name, cond, detail=""):
    print("  %-4s %-52s %s" % ("ok" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def load_pack():
    spec = importlib.util.spec_from_file_location(
        "htcpack", os.path.join(HERE, "__init__.py"),
        submodule_search_locations=[HERE])
    m = importlib.util.module_from_spec(spec)
    sys.modules["htcpack"] = m
    spec.loader.exec_module(m)
    return m


def main():
    load_pack()
    H3 = sys.modules["htcpack.h3_ref_chain"]
    dense = H3._dense_media

    print("dense numbering")
    ck("all three present number 1..3",
       list(dense("ref_audio_", ["a", "b", "c"])) == ["ref_audio_1", "ref_audio_2", "ref_audio_3"])
    ck("a gap in the middle does NOT survive",
       list(dense("ref_video_", ["a", None, "c"])) == ["ref_video_1", "ref_video_2"],
       "slot 3 becomes <Video 2>")
    ck("only the last slot filled still starts at 1",
       list(dense("ref_audio_", [None, None, "c"])) == ["ref_audio_1"])
    ck("order is preserved, not sorted",
       list(dense("x", ["z", "a"]).values()) == ["z", "a"])
    ck("nothing filled is None, not an empty dict",
       dense("ref_audio_", [None, None, None]) is None,
       "core takes None to mean the channel is unused")

    print("the node declares what core accepts")
    it = H3.HandTieClips.INPUT_TYPES()
    allw = dict(it.get("required", {}))
    allw.update(it.get("optional", {}))
    vids = [w for w in allw if re.fullmatch(r"reference_video(_[23])?_file", w)]
    auds = [w for w in allw if re.fullmatch(r"voice(_[23])?_file", w)]
    ck("three reference video slots", len(vids) == 3, str(sorted(vids)))
    ck("three voice slots", len(auds) == 3, str(sorted(auds)))
    for w in vids + auds:
        trim = w[:-len("_file")]
        ck(f"{w} has both trim widgets",
           f"{trim}_start_s" in allw and f"{trim}_end_s" in allw)

    print("the JS half exists for every file widget")
    js = io.open(os.path.join(HERE, "js/editor/media_strip.js"), encoding="utf-8").read()
    block = js.split("const SLOTS = [", 1)[1].split("\n];", 1)[0]
    slot_files = re.findall(r'\["([a-z0-9_]+_file)"', block)
    # The `*` suffix marks a FIXED-WIDTH window: a `_start_s` and deliberately
    # no `_end_s`, because the width is the chain rather than a user choice.
    # Without the `*` in this class the master-audio slot silently dropped out
    # of `trims` and its widget was never checked to exist at all.
    trims = re.findall(r'"([a-z0-9_]+\*?)",\s*null,\s*null\]', block)

    unclaimed = [w for w in allw
                 if w.endswith("_file") and w not in slot_files]
    ck("no file widget falls through to a native dial",
       not unclaimed, f"unclaimed: {unclaimed}" if unclaimed else f"{len(slot_files)} slots")

    expected = set(slot_files)
    fixed = set()
    for t in trims:
        if t.endswith("*"):
            fixed.add(t[:-1])
            expected.add(f"{t[:-1]}_start_s")
        else:
            expected |= {f"{t}_start_s", f"{t}_end_s"}
    missing = sorted(w for w in expected if w not in allw)
    ck("every widget the strip expects exists in Python",
       not missing, f"missing: {missing}" if missing else f"{len(expected)} checked")

    ck("master audio is the fixed-width slot", fixed == {"master_audio"},
       f"fixed: {sorted(fixed)}")
    # An `_end_s` on a fixed-width slot would be a widget the strip never
    # draws and never hides -- it would sit on the node body as a raw dial
    # that does nothing, which is the failure MEDIA_WIDGETS exists to prevent.
    stray = sorted(f"{b}_end_s" for b in fixed if f"{b}_end_s" in allw)
    ck("a fixed-width slot declares no _end_s in Python", not stray,
       f"stray: {stray}" if stray else f"{len(fixed)} checked")

    # ---- the readout must print the number the node will actually receive.
    #
    # Measured 2026-09-19 against renders chain_00234 / chain_00236: a window
    # dragged to a readout of "opens 4.03 s" opened the take at 4.00 s. The bar
    # writes hundredths, the widget declared `step: 0.1`, the frontend derives
    # its rounding from the step, and the 0.03 s went missing in between --
    # 1440 samples at 48 kHz, confirmed by correlating the render against the
    # source take. Nothing raised, because both halves were individually
    # defensible. Only their disagreement was wrong, and no check looked at
    # two files at once.
    print()
    print("the trim bar and the widgets agree on granularity")

    bar = io.open(os.path.join(HERE, "js/editor/trim_bar.js"),
                  encoding="utf-8").read()
    node = io.open(os.path.join(HERE, "h3_ref_chain.py"),
                   encoding="utf-8").read()

    ck("the bar writes hundredths", "Math.round(a * 100) / 100" in bar,
       "the precision its readout implies")
    # The structural half of the fix, and the half that survives a step being
    # changed again: adopt back what was stored instead of trusting the drag.
    ck("and adopts back what was actually stored",
       "function commit(" in bar and "set?.(start, end)" in bar
       and "get?.() || {}" in bar,
       "else the readout can print a value the node never sees")
    ck("no bare set() is left on the commit path",
       "set(Math.round(a * 100) / 100" not in bar,
       "every store goes through commit()")

    decl = re.search(
        r'"master_audio_start_s":\s*\("FLOAT",\s*\{(.*?)"tooltip"', node, re.S)
    body = decl.group(1) if decl else ""
    got = re.search(r'"step":\s*([0-9.]+)', body)
    val = float(got.group(1)) if got else None
    ck("master_audio_start_s can store hundredths",
       val is not None and val <= 0.01,
       f"step={val}" + ("" if val is None
                        else f" -> worst case {val / 2 * 1000:.0f} ms"))
    rnd = re.search(r'"round":\s*([0-9.]+)', body)
    ck("and pins its rounding rather than deriving it",
       rnd is not None and float(rnd.group(1)) <= 0.01,
       "step-to-round derivation is frontend behaviour, not a contract")

    print()
    if FAIL:
        print("%d FAILURE(S): %s" % (len(FAIL), ", ".join(FAIL)))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
