"""The controls that were or were not run, recorded per assay.

The parameter sweep in assay_parameters.py said what the literature reports as
mattering. This asks, for one assay, whether it was done - and it exists
because several of those parameters cannot be recovered afterwards. Whether
the coil was rotated to a random orientation, whether the field was measured
with a magnetometer, how long the animals sat between the culture plate and
the assay: none of these leave a trace in the tracks.

EVERY CHECK NAMES ITS SOURCE, and every one is drawn from the lab's own
methods rather than invented here. A checklist a student does not believe is a
checklist a student clicks through.

UNRECORDED IS NOT THE SAME AS NOT DONE, and the difference is kept. A control
that was run but never written down is a lost record; a control that was not
run is a confound. Both need fixing and they need different fixing, so `None`
means unrecorded and `False` means it did not happen.

NOTHING HERE BLOCKS AN ANALYSIS. These are conditions under which a result is
more or less interpretable, not gates - except the life-stage one, which is
different in kind: outside day-1 adult the magnetic behaviour is reported
absent, so a null result carries no information at all.
"""
from __future__ import annotations

# Bainbridge et al. 2019, J Comp Physiol A. doi:10.1007/s00359-019-01364-y
SRC = "Bainbridge et al. 2019 (J Comp Physiol A)"

HUMIDITY_THRESHOLD_RH = 50.0
START_LATENCY_S = 300.0          # "within 5 min of worms being collected"
FOOD_REVERSAL_S = 1800.0         # the 30-minute preference reversal
THERMAL_GRADIENT_C = 0.5         # centre-to-edge, over 5 cm


class ProtocolError(Exception):
    """Refusals that name the consequence."""


def _flag(name, state, severity, message, source=SRC, applies=True):
    return {"check": name, "state": state, "severity": severity,
            "message": message, "source": source, "applies": applies}


def check(protocol, *, assay="magnetotaxis"):
    """Score one assay's protocol record. Returns findings, worst first."""
    p = dict(protocol or {})
    magnetic = assay == "magnetotaxis"
    out = []

    # --- life stage: a gate, not a covariate ------------------------------
    stage = p.get("life_stage")
    if magnetic:
        if stage is None:
            out.append(_flag(
                "life_stage", "unrecorded", "gate",
                "Life stage was not recorded. Larval and old adult worms "
                "CANNOT magnetically orient, though they chemotax and "
                "thermotax normally - so outside day-1 adult a null result "
                "carries no information at all, and cannot be told from a "
                "real absence of the behaviour."))
        elif "day 1 adult" not in str(stage).lower() and \
                "day-1 adult" not in str(stage).lower():
            out.append(_flag(
                "life_stage", "outside_window", "gate",
                f"Life stage recorded as {stage!r}. Magnetic orientation is "
                f"reported only in day-1 adults; larvae and old adults do not "
                f"perform it. A negative result here is uninformative rather "
                f"than evidence of no effect."))

    # --- things that reverse the sign --------------------------------------
    lat = p.get("assay_start_latency_s")
    if lat is None:
        out.append(_flag(
            "assay_start_latency", "unrecorded", "reverses_result",
            f"Time from collecting the animals to starting the assay was not "
            f"recorded. Preference reverses by about 180 degrees around "
            f"{FOOD_REVERSAL_S / 60:.0f} min off food, and the source protocol "
            f"begins every assay within "
            f"{START_LATENCY_S / 60:.0f} min for that reason. Unrecorded, "
            f"this is the likeliest explanation for a plate that behaves "
            f"backwards."))
    elif float(lat) > START_LATENCY_S:
        frac = float(lat) / FOOD_REVERSAL_S
        out.append(_flag(
            "assay_start_latency", "long", "reverses_result",
            f"Animals waited {float(lat) / 60:.0f} min before the assay "
            f"started, against the {START_LATENCY_S / 60:.0f} min the source "
            f"protocol allows - {frac:.0%} of the way to the reversal. Plates "
            f"that waited different amounts are not replicates of each other."))

    cult = p.get("cultivation_apparatus")
    if cult is None:
        out.append(_flag(
            "cultivation_apparatus", "unrecorded", "abolishes_result",
            "Where the animals were reared was not recorded. Cultivating in "
            "an INCUBATOR is reported to interfere with magnetotaxis, "
            "attributed to the incubator's own magnetic field during "
            "development. The confound is in the animal's history, so nothing "
            "measured on the day will reveal it."))
    elif "incubator" in str(cult).lower():
        out.append(_flag(
            "cultivation_apparatus", "incubator", "abolishes_result",
            "Animals were reared in an incubator, which is reported to "
            "interfere with the robustness of magnetotaxis - the incubator "
            "casts a strong magnetic field throughout development, and there "
            "may also be a shock on transfer to test conditions. Named in the "
            "source as a possible cause of a failed replication."))

    for key, label in (("starved", "starvation"),
                       ("contaminated", "contamination"),
                       ("overpopulated", "overpopulation")):
        v = p.get(f"culture_{key}")
        if v is None:
            out.append(_flag(
                f"culture_{key}", "unrecorded", "reverses_result",
                f"Culture {label} history was not recorded. The source states "
                f"these can sway a population from positive to negative "
                f"magnetotaxis or abolish it, and used animals that were "
                f"'never starved, overpopulated, or infected'. It is a "
                f"history, so it cannot be recovered later."))
        elif v:
            out.append(_flag(
                f"culture_{key}", "present", "reverses_result",
                f"Culture {label} is recorded as present. The source reports "
                f"this can reverse the sign of the result."))

    # --- confounds specific to a powered coil --------------------------------
    if magnetic:
        if p.get("coil_orientation_randomised") is None:
            out.append(_flag(
                "coil_orientation_randomised", "unrecorded", "confound",
                "Whether the coil system was rotated to a random starting "
                "position was not recorded. The source does this before every "
                "assay; without it any room-fixed cue - a window, a bench, a "
                "draught - is perfectly confounded with field direction, and "
                "no analysis of the tracks can separate them."))
        elif not p.get("coil_orientation_randomised"):
            out.append(_flag(
                "coil_orientation_randomised", "not_done", "confound",
                "The coil orientation was not randomised between assays, so "
                "field direction is fixed in room coordinates and any "
                "directional cue in the room predicts it exactly."))

        before = p.get("field_measured_before_mT")
        after = p.get("field_measured_after_mT")
        if before is None or after is None:
            out.append(_flag(
                "field_verification", "unrecorded", "confound",
                "The field was not recorded as measured before AND after the "
                "assay. WINK models the field from magnet geometry and can "
                "check it against a closed form, but a model cannot see a "
                "drifting supply, a moved magnet or a coil that was never "
                "switched on."))
        else:
            drift = abs(float(after) - float(before))
            ref = max(abs(float(before)), 1e-9)
            if drift / ref > 0.05:
                out.append(_flag(
                    "field_verification", "drifted", "confound",
                    f"The field changed by {drift / ref:.0%} between the "
                    f"before and after measurements ({before} to {after} mT). "
                    f"The animals were not in one condition."))

        # Unrecorded and absent are kept apart here as everywhere else. Using
        # `not p.get(...)` collapsed them, which contradicted the module's own
        # rule - a lost record and a missing control need different fixes.
        shield = p.get("faraday_shielded")
        if shield is None:
            out.append(_flag(
                "electric_field_shielding", "unrecorded", "confound",
                "Electric-field shielding was not recorded. Powering a coil to "
                "make a magnetic field also makes an electric one; the source "
                "wraps camera and lights in grounded copper fabric and "
                "encloses the assay in it."))
        elif not shield:
            out.append(_flag(
                "electric_field_shielding", "absent", "confound",
                "The assay was not electrically shielded. A powered coil makes "
                "an electric field alongside the magnetic one, so the stimulus "
                "is not only what the title says it is."))

    # --- environment ---------------------------------------------------------
    rh = p.get("humidity_percent")
    if rh is None:
        out.append(_flag(
            "relative_humidity", "unrecorded", "degrades_result",
            f"Humidity was not recorded. Orientation is more robust below "
            f"{HUMIDITY_THRESHOLD_RH:.0f}% RH - the source's dry days averaged "
            f"35.4% and gave more robust orientation than humid days at "
            f"60.8%."))
    elif float(rh) > HUMIDITY_THRESHOLD_RH:
        out.append(_flag(
            "relative_humidity", "humid", "degrades_result",
            f"Humidity was {float(rh):.0f}% RH, above the "
            f"{HUMIDITY_THRESHOLD_RH:.0f}% threshold. Expect a weaker result: "
            f"the source's humid days (60.8% average) oriented less robustly "
            f"than its dry days (35.4%), and the thermotaxis field avoids "
            f"assays above this line for the same reason. A weak result here "
            f"is not evidence of no effect."))

    grad = p.get("thermal_gradient_c")
    if grad is None:
        out.append(_flag(
            "thermal_gradient", "unrecorded", "confound",
            "The temperature difference between plate centre and edge was not "
            "measured. The source measures it throughout EVERY assay, runs a "
            "fan inside the coil system to prevent gradients, and in the "
            "six-point assay puts a 0.5 cm plastic barrier over the magnet "
            "specifically to stop one forming. A magnet warms one side of a "
            "plate, and a thermotaxing animal migrates for thermal reasons - "
            "without this number a magnetic result and a thermal one are "
            "indistinguishable."))
    elif abs(float(grad)) > THERMAL_GRADIENT_C:
        out.append(_flag(
            "thermal_gradient", "present", "confound",
            f"A {abs(float(grad)):.2f} C centre-to-edge gradient was measured. "
            f"C. elegans thermotaxes to gradients far shallower than it "
            f"magnetotaxes, so this is a competing directional stimulus, not "
            f"a nuisance."))

    lit = p.get("illumination_gradient_checked")
    if lit is None:
        out.append(_flag(
            "illumination_gradient", "unrecorded", "confound",
            "No record of checking that illumination is even across the arena. "
            "The source quantifies test images in ImageJ 'to ensure no "
            "brightness gradients were present across the entire filming "
            "arena'. A brightness gradient is a directional cue and a heat "
            "gradient at once."))
    elif not lit:
        out.append(_flag(
            "illumination_gradient", "not_done", "confound",
            "Illumination evenness was not checked. An uneven arena provides a "
            "directional cue and a thermal one at the same time, either of "
            "which the animals can follow instead of the stimulus."))

    # --- preparation ----------------------------------------------------------
    if p.get("food_on_assay_surface") is None:
        out.append(_flag(
            "food_on_assay_surface", "unrecorded", "changes_result",
            "Whether the assay surface carried a bacterial lawn was not "
            "recorded. The replicating lab in the source ran assays ON a lawn "
            "specifically to avoid on-assay starvation, which interacts "
            "directly with the time-off-food reversal.",))
    if p.get("bacterial_strain") is None:
        out.append(_flag(
            "bacterial_strain", "unrecorded", "unquantified",
            "Bacterial strain was not recorded. The two labs in the source "
            "used OP50 and HB101 respectively while running 'the same' "
            "assay."))
    # The trap geometry IS the endpoint measurement. Bainbridge 2019 used
    # 0.1 M azide painted around the whole circumference in one assay and 1 M
    # in six radial droplets in another - those are different measurements of
    # different things, and an index from one cannot be compared with an index
    # from the other.
    agent = p.get("immobilisation_agent")
    geom = p.get("immobilisation_geometry")
    if agent is None and geom is None:
        out.append(_flag(
            "immobilisation", "unrecorded", "changes_result",
            "Neither the immobilisation agent nor where it was placed was "
            "recorded. The trap geometry IS the endpoint measurement - a "
            "painted rim scores 'reached the edge' while six radial spots "
            "score 'chose this direction', and the same animals give "
            "different indices. The source used 0.1 M azide on the "
            "circumference in one assay and 1 M in six droplets in another."))
    elif geom is None:
        out.append(_flag(
            "immobilisation", "geometry_unrecorded", "changes_result",
            f"Agent recorded as {agent!r} but not where it was placed. The "
            f"concentration matters far less than the geometry: a rim and a "
            f"set of spots ask different questions of the animal."))
    elif agent is None:
        out.append(_flag(
            "immobilisation", "agent_unrecorded", "unquantified",
            f"Placement recorded as {geom!r} but not what was used. Azide "
            f"concentration affects how quickly an arriving animal stops, "
            f"which sets how far past the line it travels first."))

    # Crowding on the CULTURE plate during development, which is separate from
    # density on the assay plate - plate_assay records the latter.
    if p.get("culture_density") is None:
        out.append(_flag(
            "culture_density", "unrecorded", "reverses_result",
            "Crowding during development was not recorded. The source lists "
            "crowding among the factors that can sway a population from "
            "positive to negative magnetotaxis. This is the CULTURE plate, "
            "not the assay plate - n_placed and density on the assay are "
            "recorded separately, and a well-spaced assay run with animals "
            "reared crowded is still a crowded-animal experiment."))

    if p.get("plate_age_days") is None:
        out.append(_flag(
            "plate_age_days", "unrecorded", "unquantified",
            "Plate age was not recorded; the source uses 1-day-old plates. "
            "Plate age changes surface moisture, which changes both "
            "locomotion and the humidity term above."))
    if p.get("time_of_day") is None:
        out.append(_flag(
            "time_of_day", "unrecorded", "unquantified",
            "Time of day was not recorded. The replicating lab held LD 12:12 "
            "at constant temperature and a circadian laboratory co-authored, "
            "so it is controlled in the source - but its effect is not "
            "isolated, which is precisely why it should be recorded rather "
            "than assumed irrelevant."))

    order = {"gate": 0, "abolishes_result": 1, "reverses_result": 2,
             "confound": 3, "changes_result": 4, "degrades_result": 5,
             "unquantified": 6}
    out.sort(key=lambda f: order.get(f["severity"], 9))
    return out


def summarise(protocol, *, assay="magnetotaxis"):
    findings = check(protocol, assay=assay)
    unrecorded = [f for f in findings if f["state"] == "unrecorded"]
    actual = [f for f in findings if f["state"] != "unrecorded"]
    worst = findings[0]["severity"] if findings else None
    return {
        "n_findings": len(findings),
        "n_unrecorded": len(unrecorded),
        "n_conditions_present": len(actual),
        "worst_severity": worst,
        "findings": findings,
        "interpretable": not any(
            f["severity"] in {"gate", "abolishes_result"} and
            f["state"] != "unrecorded" for f in findings),
        "unrecorded_is_not_not_done": (
            "A control that ran but was never written down is a lost record; "
            "one that did not run is a confound. Both need fixing and they "
            "need different fixing, so these are counted apart."),
    }
