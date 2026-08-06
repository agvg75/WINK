"""Every parameter the literature says changes an orientation result.

Andres asked whether we are leaving parameters out. This is the answer, drawn
first from the lab's own methods papers, which are unusually explicit about
what perturbs magnetotaxis.

THE PRIMARY SOURCE IS BAINBRIDGE ET AL. 2019, J Comp Physiol A - "Factors that
influence magnetic orientation in C. elegans" - which is an inventory of
exactly this question. Its discussion states plainly that "crowding, ambient
humidity, temperature, starvation, and contamination history can all sway the
preference of a population from positive to negative magnetotaxis (or indeed
abolish the behavior altogether)."

THAT SENTENCE SETS THE STANDARD FOR THIS FILE. These are not covariates that
add noise; several of them REVERSE THE SIGN of the result. A parameter that
can flip an effect from positive to negative is not metadata, and recording it
after the fact from memory is not good enough.

`captured` says whether WINK asks for it today. Where it does not, `matters`
says what goes wrong, because a list of missing fields is only useful if
someone can tell which ones to add first.
"""
from __future__ import annotations

SOURCES = {
    "bainbridge2019": {
        "cite": ("Bainbridge C, Clites BL, Caldart CS, Palacios B, Rollins K, "
                 "Golombek DA, Pierce JT, Vidal-Gadea AG (2019). Factors that "
                 "influence magnetic orientation in Caenorhabditis elegans. "
                 "J Comp Physiol A."),
        "doi": "10.1007/s00359-019-01364-y",
        "status": "retrieved",
    },
    "vidalgadea2015": {
        "cite": ("Vidal-Gadea AG et al. (2015). Magnetosensitive neurons "
                 "mediate geomagnetic orientation in Caenorhabditis elegans. "
                 "eLife 4:e07493."),
        "doi": "10.7554/eLife.07493",
        "status": "cited_by_primary",
    },
    "landler2018": {
        "cite": ("Landler L et al. (2018). Comment on 'Magnetosensitive "
                 "neurons mediate geomagnetic orientation in Caenorhabditis "
                 "elegans'. eLife."),
        "doi": "10.7554/eLife.30187",
        "status": "cited_by_primary",
        "why_here": ("The source of the assay-as-unit statistical convention "
                     "adopted in Bainbridge 2019."),
    },
    "kirschvink1992": {
        "cite": ("Kirschvink JL (1992). Uniform magnetic fields and "
                 "double-wrapped coil systems. Bioelectromagnetics 13:401-411."),
        "status": "cited_by_primary",
        "why_here": "The double-wrapped design that makes the sham possible.",
    },
    "goodman2014": {
        "cite": ("Goodman MB et al. (2014), cited in Bainbridge 2019 as the "
                 "thermotaxis convention of avoiding assays above 50% RH."),
        "status": "cited_by_primary",
    },
}

# ---------------------------------------------------------------------------
# capture status is relative to what WINK's orientation assays ask for as of
# 2026-08-06. "partial" means the field exists but is not used the way the
# literature requires.
# ---------------------------------------------------------------------------
PARAMETERS = [
    # --- the ones that reverse the sign -----------------------------------
    {
        "name": "time_within_assay",
        "group": "temporal",
        "captured": "no",
        "severity": "reverses_result",
        "source": "bainbridge2019",
        "finding": ("The preferred angle rotates by about 180 degrees over a "
                    "90-minute assay, passing through an interval with no "
                    "detectable preference. Reported means: 0-30 min 183 deg "
                    "(r=0.65, p<0.001); 30-60 min not significant (r=0.13, "
                    "p=0.7); 60-90 min r=0.35, p=0.12."),
        "matters": ("A single mean heading pooled over a whole assay averages "
                    "a reversal against itself and lands near zero. The result "
                    "is not a weak preference - it is two opposite strong "
                    "preferences cancelling, and nothing in the summary shows "
                    "the difference. Headings must be binned in time."),
        "implement": ("Bin headings into 10-minute windows, group into 30-min "
                      "intervals, and report per interval - never one number "
                      "for the assay."),
    },
    {
        "name": "time_off_food_before_assay",
        "group": "animal_state",
        "captured": "yes",
        "severity": "reverses_result",
        "source": "bainbridge2019",
        "finding": ("Worms tested immediately versus after ~30 min off food "
                    "in liquid migrate in OPPOSITE directions - 300 deg vs "
                    "120 deg in a uniform field, and up vs down in burrowing. "
                    "Held across three assays and three wild isolates."),
        "matters": ("Two plates run 30 minutes apart are not replicates; they "
                    "may be opposite conditions."),
        "note": ("WINK captures this. The 30-minute figure in plate_assay's "
                 "ENHANCED_SLOWING_S matches the interval reported here, "
                 "though the underlying phenomena differ."),
    },
    {
        "name": "assay_start_latency",
        "group": "temporal",
        "captured": "no",
        "severity": "reverses_result",
        "source": "bainbridge2019",
        "finding": ("'All assays began within 5 min of worms being collected "
                    "from their cultivation plate.' Given the 30-minute "
                    "reversal above, this is a tight and deliberate window."),
        "matters": ("Latency from collection to assay start places the animal "
                    "on the reversal curve. Unrecorded, it is the most likely "
                    "explanation for a plate that behaves backwards."),
    },
    {
        "name": "cultivation_apparatus",
        "group": "animal_state",
        "captured": "no",
        "severity": "abolishes_result",
        "source": "bainbridge2019",
        "finding": ("Cultivating worms in an INCUBATOR interferes with the "
                    "robustness of magnetotaxis, attributed to strong magnetic "
                    "fields cast by the incubator during development, and/or "
                    "shock on transfer to different conditions for testing."),
        "matters": ("The confound is in the animal's developmental history, "
                    "not the assay, so nothing measured on the day will reveal "
                    "it. Named as a possible source of a failed replication."),
    },
    {
        "name": "life_stage",
        "group": "animal_state",
        "captured": "partial",
        "severity": "abolishes_result",
        "source": "bainbridge2019",
        "finding": ("Larval-stage and OLD ADULT worms cannot perform magnetic "
                    "orientation, though they orient to chemical, thermal and "
                    "humidity gradients from L1 onward. Efficient magnetic "
                    "orientation correlates with AFD microvilli."),
        "matters": ("Age is a GATE for magnetotaxis, not a covariate - outside "
                    "day-1 adult the behaviour is absent, so a null result "
                    "means nothing. WINK asks for worm_age as free text; it "
                    "does not enforce or warn."),
    },
    {
        "name": "starvation_and_contamination_history",
        "group": "animal_state",
        "captured": "no",
        "severity": "reverses_result",
        "source": "bainbridge2019",
        "finding": ("Starvation and contamination history 'can sway the "
                    "preference of a population from positive to negative "
                    "magnetotaxis (or indeed abolish the behavior "
                    "altogether)'. Animals used were 'never starved, "
                    "overpopulated, or infected'."),
        "matters": ("A history, not a state - unrecoverable after the fact, "
                    "and it flips the sign."),
    },
    {
        "name": "crowding",
        "group": "animal_state",
        "captured": "partial",
        "severity": "reverses_result",
        "source": "bainbridge2019",
        "finding": "Crowding is listed among the factors that sway preference.",
        "matters": ("WINK now records n_placed and density, which is the "
                    "assay-plate side of this. Culture-plate crowding during "
                    "development is separate and is not captured."),
    },
    # --- environment --------------------------------------------------------
    {
        "name": "relative_humidity",
        "group": "environment",
        "captured": "partial",
        "severity": "degrades_result",
        "source": "bainbridge2019",
        "finding": ("Orientation is more robust below 50% RH. Dry days "
                    "averaged 35.4% RH (n=7) and gave more robust orientation "
                    "than humid days averaging 60.8% RH (n=12). The "
                    "thermotaxis field adopts the same 50% RH convention."),
        "matters": ("WINK asks for humidity and defaults to 37%, which sits in "
                    "the dry band - but it does not know 50% is a threshold, "
                    "so a 60% assay is recorded without comment."),
        "implement": "Flag assays above 50% RH as expected-to-be-less-robust.",
    },
    {
        "name": "thermal_gradient_across_plate",
        "group": "environment",
        "captured": "no",
        "severity": "confound",
        "source": "bainbridge2019",
        "finding": ("Temperature difference between plate centre and edge "
                    "(5 cm) was measured throughout every assay, a fan "
                    "circulated air inside the coil system to prevent "
                    "gradients, and in the six-point assay the magnet was "
                    "covered with a 0.5 cm plastic barrier specifically to "
                    "minimise a thermal gradient."),
        "matters": ("A magnet warms one side of a plate and a thermotaxing "
                    "animal will migrate for thermal reasons. Without the "
                    "gradient measurement, a magnetotaxis result and a "
                    "thermotaxis result are indistinguishable - and this lab "
                    "treats it as a per-assay measurement, not a one-off "
                    "characterisation."),
    },
    {
        "name": "illumination_gradient",
        "group": "environment",
        "captured": "no",
        "severity": "confound",
        "source": "bainbridge2019",
        "finding": ("Test images were quantified in ImageJ 'to ensure no "
                    "brightness gradients were present across the entire "
                    "filming arena'."),
        "matters": ("A brightness gradient is a directional cue and a heat "
                    "gradient at once. Checked per setup in the source, and "
                    "not asked for anywhere in WINK."),
    },
    {
        "name": "electric_field_shielding",
        "group": "environment",
        "captured": "no",
        "severity": "confound",
        "source": "bainbridge2019",
        "finding": ("Camera and LED lights were wrapped in grounded copper "
                    "Faraday fabric, and the same material completely "
                    "enclosed the assay 'to prevent any electric fields from "
                    "intruding'."),
        "matters": ("Powering a coil to make a magnetic field also makes an "
                    "electric one. Unshielded, the stimulus is not what the "
                    "title says it is."),
    },
    {
        "name": "circadian_phase",
        "group": "temporal",
        "captured": "no",
        "severity": "unquantified",
        "source": "bainbridge2019",
        "finding": ("The replicating lab maintained LD 12:12 at 400:0 lux and "
                    "constant 17.5 C, and a circadian laboratory (Golombek) "
                    "co-authored. Time of day is controlled but its effect is "
                    "not isolated in this paper."),
        "matters": ("Controlled by the source lab and absent from WINK, so a "
                    "student running mornings and afternoons cannot later ask "
                    "whether it mattered."),
    },
    # --- apparatus ----------------------------------------------------------
    {
        "name": "field_verification_before_and_after",
        "group": "apparatus",
        "captured": "no",
        "severity": "confound",
        "source": "bainbridge2019",
        "finding": ("'Temperature and magnetic measurements were performed "
                    "before and after each experiment to confirm our "
                    "experimental conditions,' using a DC milligauss meter."),
        "matters": ("WINK models the field from magnet geometry and can "
                    "validate against a closed form, but nothing records that "
                    "the field was MEASURED on the day. A drifting supply or a "
                    "moved magnet is invisible to a model."),
    },
    {
        "name": "coil_orientation_randomised",
        "group": "apparatus",
        "captured": "no",
        "severity": "confound",
        "source": "bainbridge2019",
        "finding": ("'Before each assay, we rotated the magnetic coil system "
                    "to a random starting position.'"),
        "matters": ("Without it, any room-fixed cue - a window, a bench, a "
                    "draught - is perfectly confounded with field direction. "
                    "This is a randomisation, and whether it was done is not "
                    "recoverable from the data."),
    },
    {
        "name": "field_geometry_layout",
        "group": "apparatus",
        "captured": "yes",
        "severity": "changes_result",
        "source": "bainbridge2019",
        "finding": ("'The geometric layout for how the magnetic field "
                    "enveloped the assay' is named as critical. Uniform linear "
                    "(0.65 G) and radial magnet fields produce different "
                    "accumulation patterns; a 700 G magnet was used elsewhere "
                    "in the same paper."),
        "note": ("Now captured: UniformFieldProvider, MagnetProvider and "
                 "RingMagnetProvider with declared geometry."),
    },
    {
        "name": "sham_and_zero_field_controls",
        "group": "apparatus",
        "captured": "yes",
        "severity": "required_control",
        "source": ["bainbridge2019", "kirschvink1992"],
        "finding": ("Three conditions run: 1x earth uniform field (N=7), "
                    "magnetic control cancelling earth (N=10), and current "
                    "control with the double-wrapped coils antiparallel, same "
                    "power output, no field (N=6)."),
        "note": "Now captured as COIL_CONDITIONS.",
    },
    # --- analysis conventions ------------------------------------------------
    {
        "name": "assay_as_statistical_unit",
        "group": "analysis",
        "captured": "no",
        "severity": "invalidates_statistics",
        "source": ["bainbridge2019", "landler2018"],
        "finding": ("'Following Landler et al. (2018), animals were not pooled "
                    "but each assay mean heading was rather treated as a "
                    "unit.' Each 10-min window contributes ONE heading per "
                    "assay."),
        "matters": ("Pooling worms treats animals on one plate as independent "
                    "when they share a plate, a batch and an experimenter. It "
                    "inflates n by the number of worms and shrinks p "
                    "accordingly. WINK's regime_comparison currently pools "
                    "worms within a plate."),
    },
    {
        "name": "track_segment_normalisation",
        "group": "analysis",
        "captured": "no",
        "severity": "biases_result",
        "source": "bainbridge2019",
        "finding": ("Trajectories were binned into 5% intervals so that "
                    "animals crossing the field of view quickly and animals "
                    "lingering contribute equally."),
        "matters": ("Weighting by raw samples lets the slowest animals "
                    "dominate the population heading - and speed is not "
                    "independent of orientation, so the bias has a direction."),
    },
    {
        "name": "participation_radius",
        "group": "analysis",
        "captured": "partial",
        "severity": "changes_result",
        "source": "bainbridge2019",
        "finding": ("'Animals had to move greater than 5 mm from the center "
                    "starting position to be considered participants.'"),
        "matters": ("The donut assay has this concept as its inner edge; the "
                    "linear assay in WINK does not apply a participation "
                    "radius at all."),
    },
    {
        "name": "field_of_view_censoring",
        "group": "analysis",
        "captured": "no",
        "severity": "biases_result",
        "source": "bainbridge2019",
        "finding": ("Animals were tracked from 5 mm out until they left a "
                    "36 x 27 mm field of view, which they did at very "
                    "different times."),
        "matters": ("Leaving the field of view is censoring, and fast animals "
                    "leave first - so late time windows are built from the "
                    "slow ones. The same survival logic as the donut crossing, "
                    "in an assay where it is not currently applied."),
    },
    {
        "name": "heading_sample_interval",
        "group": "analysis",
        "captured": "partial",
        "severity": "changes_result",
        "source": "bainbridge2019",
        "finding": ("Filmed at 1 fps for 100 min but SAMPLED at 0.2 Hz - every "
                    "fifth frame - for heading analysis."),
        "matters": ("The interval over which a heading is computed sets which "
                    "turns are visible; it is a separate parameter from frame "
                    "rate and WINK records only the frame rate."),
    },
    # --- preparation ---------------------------------------------------------
    {
        "name": "plate_age_and_preparation",
        "group": "preparation",
        "captured": "no",
        "severity": "unquantified",
        "source": "bainbridge2019",
        "finding": ("A 1-day-old 10 cm chemotaxis plate; animals transferred "
                    "in a 0.5 ul droplet of liquid NGM at pH 7; excess wicked "
                    "away with Kimwipe to release them."),
        "matters": ("Plate age changes surface moisture, which changes both "
                    "locomotion and the humidity term above."),
    },
    {
        "name": "immobilisation_agent",
        "group": "preparation",
        "captured": "no",
        "severity": "changes_result",
        "source": "bainbridge2019",
        "finding": ("Sodium azide, 0.1 M painted around the circumference in "
                    "one assay and 1 M in 1 ul droplets at six radial spots in "
                    "another - it defines where an endpoint is scored."),
        "matters": ("The trap geometry IS the endpoint measurement; six spots "
                    "and a painted rim give different indices."),
    },
    {
        "name": "food_present_during_assay",
        "group": "preparation",
        "captured": "no",
        "severity": "changes_result",
        "source": "bainbridge2019",
        "finding": ("The replicating lab ran assays ON A BACTERIAL LAWN "
                    "specifically to avoid on-assay starvation, and used "
                    "E. coli HB101 rather than OP50."),
        "matters": ("Whether the assay surface has food interacts directly "
                    "with the time-off-food reversal, and bacterial strain "
                    "differs between labs running 'the same' assay."),
    },
]


def by_capture(status):
    return [p for p in PARAMETERS if p["captured"] == status]


def gaps(min_severity=None):
    order = ["reverses_result", "abolishes_result", "invalidates_statistics",
             "changes_result", "biases_result", "confound", "degrades_result",
             "unquantified", "required_control"]
    out = [p for p in PARAMETERS if p["captured"] in {"no", "partial"}]
    return sorted(out, key=lambda p: order.index(p["severity"])
                  if p["severity"] in order else 99)


def report():
    L = [f"{len(PARAMETERS)} parameters from the literature; "
         f"{len(by_capture('yes'))} captured, "
         f"{len(by_capture('partial'))} partial, "
         f"{len(by_capture('no'))} missing", ""]
    for p in gaps():
        L.append(f"[{p['captured'].upper():7s}] {p['severity']:22s} "
                 f"{p['name']}")
        L.append(f"          {p['matters'][:150]}")
    return "\n".join(L)


UNCHECKED = (
    "Only the lab's own methods papers have been read so far - principally "
    "Bainbridge 2019, which is an inventory of this exact question. The wider "
    "chemotaxis, thermotaxis and animal-navigation literature has NOT been "
    "swept, so absence from this list is not evidence a parameter does not "
    "matter. Chemotaxis and thermotaxis are represented here only where the "
    "magnetic paper happened to mention them.")
