"""
Setting up the nominal LHC in xsuite using cpymad.
"""
from __future__ import annotations

from enum import StrEnum, auto
import logging
from pathlib import Path

import numpy as np
import tfs
import xpart as xp
import xtrack as xt
from cpymad.madx import Madx

from lhc_beam import LHCBeam
from utils.logging import disable_logging, init_cpymad_logging, init_logging
from utils.tfs import twiss_to_omc3
from utils.xsuite import match, insert_monitors_at_pattern
import turn_by_turn as tbt

from omc3.model.constants import TWISS_DAT, TWISS_ELEMENTS_DAT

MADX_LOGGING: bool = False
SDDS_NAME: str = "Beam{beam}@BunchTurn@{name}.sdds"  # confirms to GUI loading filter


LOGGER = logging.getLogger(__name__)


class Step(StrEnum):
    """ Enum for the different steps of the simulation """
    raw = auto()
    nominal = auto()
    with_errors = auto()


def load_sequence_and_optics(beam: LHCBeam) -> Madx:
    """ Load the sequence and optics modifiers into a MAD-X instance. """
    LOGGER.info("Loading sequence and optics modifiers")

    madx = Madx(
            cwd=beam.model_dir,
            **init_cpymad_logging(
                console=MADX_LOGGING,
                command_log=beam.model_dir / "madx_commands.madx",
                output_log=beam.model_dir / "madx_output.log",
            )
    )

    # Load Sequence
    madx.call(str(beam.acc_models_link / beam.sequence_file))

    # Cycling
    madx.seqedit(sequence=beam.sequence)
    madx.flatten()
    madx.cycle(start=beam.cycling_element)
    madx.endedit()

    # Beam Setup  (needs to be done before calling optics, as these call `use, sequece`)
    for _seq, _bv in ((beam.sequence, beam.bv), (beam.get_sequence_for_beam(beam.other_beam), -beam.bv)):
        madx.beam(
            sequence=_seq,
            bv=_bv,
            energy=beam.energy,
            particle="proton",
            npart=beam.n_particles,
            kbunch=1,
        )

    # Define optics/modifiers
    for modifier in beam.modifiers:
        madx.call(str(modifier))

    # Remove IR symmetry definitions
    madx.call(str(beam.acc_models_link / "toolkit" / "remove-triplet-symmetry-knob.madx"))
    return madx


def create_line(beam: LHCBeam):
    """ Create the line from the sequence and optics modifiers.
    Saves it into a JSON file. """
    LOGGER.info("Creating line")
    madx = load_sequence_and_optics(beam)

    with disable_logging():
        line: xt.Line = xt.Line.from_madx_sequence(madx.sequence[beam.sequence], deferred_expressions=True)

    line.twiss_default["method"] = "4d"
    line.particle_ref = xt.Particles(p0c=beam.energy*1e9, q0=1, mass0=xp.PROTON_MASS_EV)
    line.to_json(beam.get_line_path(Step.raw))
    madx.exit()
    return line


def nominal(beam: LHCBeam, line: xt.Line | None = None):
    """ Continue the LHC setup to the nominal machine, i.e.
    match the tunes and write out the twiss table.

    Args:
        beam (LHCBeam): beam object storing machine configuration data
        line (xt.Line): line of the loaded machine, if not given loads from json.
    """
    LOGGER.info("Creating nominal twiss table")

    if line is None:
        LOGGER.debug("Loading from file.")
        line = xt.Line.from_json(beam.get_line_path(Step.raw))

    match(beam, line)

    # Write twiss to compare with old madx simlulations (if needed):
    # tw: xt.TwissTable = line.twiss(continue_on_closed_orbit_error=False, strengths=True)
    # df = twiss_to_omc3(tw)
    # tfs.write(beam.get_twiss_path(Step.nominal), df, save_index="NAME")

    line.to_json(beam.get_line_path(Step.nominal))


def install_errors(beam: LHCBeam, line: xt.Line | None = None):
    """ Continue the LHC setup to the nominal machine, i.e.
    match the tunes and write out the twiss table.

    Args:
        beam (LHCBeam): beam object storing machine configuration data
        line (xt.Line): line of the loaded machine, if not given loads from json.
    """
    LOGGER.info("Creating nominal twiss table")

    if line is None:
        LOGGER.debug("Loading from file.")
        line = xt.Line.from_json(beam.get_line_path(Step.nominal))

    # Introduce some global coupling (modifies MQS) to increase 3Qy resonance
    line.vv["cmrs.b1"] = 2e-4
    line.vv["cmis.b1"] = 2e-4

    ############# TODO: More Control? ################

    # If you want to change values of a knob that is also already part of another knob,
    # you need to ask someone with more xsuite experience, as the modification
    # of values might override the expression, here: coupling knob

    # knob_name = "kqs.r1b1"  # might not exist for beam2, check sequence file in acc-models-lhc/lhc.seq

    # see expression with
    # line.vars[knob_name]._expr()

    # modify the value
    # line.vv[knob_name] += 0.5e-4  # modification should show up in logging output!

    # see expression with
    # line.vars[knob_name]._expr()

    # inspect the targets with:
    # line.vars[knob_name]._find_dependant_targets()

    ####################################

    match(beam, line)

    line.to_json(beam.get_line_path(Step.with_errors))


def create_turn_by_turn_data(
        beam: LHCBeam,
        line: xt.Line | None = None,
        n_turns: int = 10,
        action: float = 3e-9,
        output_name: str = "tracked"
    ) -> tbt.TbtData:
    """ Perform the tracking of a particle with the given action 2J in m (in both planes).

    First ParticleMonitors are inserted into the line at the posision of the BPM-elements.
    We ignore BPMs ending in `_something` to exclude "_DOROS"-BPMS to avoid having two monitors
    at exactly the same position, which causes some NaN-problems in the 3-BPM method.

    Then a single particle at the given action is tracked and the data is converted
    to a tbt.TbtData object and saved to an sdds file in "lhc" format.

    Args:
        beam (LHCBeam): beam object storing machine configuration data
        line (xt.Line): line of the loaded machine, if not given loads from json (stage: nominal).
        n_turns (int): number of turns to track
        action (float): 2J in m
        output_name (str): Identifyer of the output file
    """
    if line is None:
        LOGGER.debug("Loading from file.")
        line = xt.Line.from_json(beam.get_line_path(Step.with_errors))

    insert_monitors_at_pattern(line, n_turns=n_turns, pattern="BPM.*B[12]$")  # ignore BPMs ending in _something

    # calculate initial position from action: z = sqrt(action_z * beta_z)
    tw: xt.TwissTable = line.twiss(continue_on_closed_orbit_error=False, strengths=True)
    x = np.sqrt(action * tw["betx"][0])
    y = np.sqrt(action * tw["bety"][0])

    particles = line.build_particles(particle_ref=line.particle_ref, num_particles=1, x=[x], y=[y], px=[0], py=[0])
    line.track(particles, num_turns=n_turns, with_progress=True)

    tbt_data = tbt.convert_to_tbt(line, datatype="xtrack")  # turn_by_turn version > 0.9.1 needed!
    tbt.write(beam.model_dir / SDDS_NAME.format(beam=beam.beam, name=output_name), tbt_data, datatype="lhc")

    return tbt_data


def create_omc3_model_dir(beam: LHCBeam, line: xt.Line | None = None):
    """ Create an omc3 model directory from the given line.

    Will be created in a subfolder and can then be loaded from the GUI.

    Needs to contain:
        - twiss.dat
        - twiss_elements.dat
        - modifiers.madx (or a job.nominal.madx with `!@modifier` tags)

    Optional:
        - acc-models symlink
    """
    if line is None:
        LOGGER.debug("Loading from file.")
        line = xt.Line.from_json(beam.get_line_path(Step.nominal))

    omc3_dir = beam.model_dir / f"omc3_{beam.model_dir.name}"
    omc3_dir.mkdir(exist_ok=True, parents=True)

    tw: xt.TwissTable = line.twiss(continue_on_closed_orbit_error=False, strengths=True)
    df = twiss_to_omc3(tw)
    df.headers["ENERGY"] = beam.energy
    tfs.write(omc3_dir / TWISS_ELEMENTS_DAT, df, save_index="NAME")
    tfs.write(omc3_dir / TWISS_DAT, df.loc[df.index.str.match("BPM"), :], save_index="NAME")

    # omc3 will try to find modifiers, either in the job or as modifier.madx file:
    with open(omc3_dir / "modifiers.madx", "w") as f:
        for modifier in beam.modifiers:
            f.write(f"call, file = \"{modifier}\";\n")

    # create a copy of the acc-models symlink
    old_link = beam.model_dir / beam.acc_models_link
    new_link = omc3_dir / beam.acc_models_link
    if new_link.is_symlink():
        new_link.unlink()
    new_link.symlink_to(old_link.readlink())


# Nonlinear BPM behaviour ------------------------------------------------------

def nonlinear_scaling(x: np.ndarray, alpha: float) -> np.ndarray:
    """ Function to apply to all coordinates. """
    return x + alpha * x**2


def modify_turn_by_turn_data(beam: LHCBeam, tbt_data: tbt.TbtData | None, alpha: float = 0):
    """ Modify the turn-by-turn data with the given alpha value. """
    if tbt_data is None:
        tbt_data = tbt.read(beam.model_dir / SDDS_NAME.format(beam=beam.beam, name="tracked"), datatype="lhc")

    # TODO: modify the tbt_data: apply nonlinear scaling

    tbt.write(
        beam.model_dir / SDDS_NAME.format(beam=beam.beam, name=f"tracked_modified{alpha:.2f}"),
        tbt_data,
        datatype="lhc"
    )


# Run Main ---------------------------------------------------------------------

def main():
    beam = LHCBeam(
        beam=1,
        nat_tunes=(62.28, 60.31), # TODO: Ask Ewen about the tunes, mybe better go closer to 3Qy resonance
        year="2025",
        modifiers=["R2025aRP_A18cmC18cmA10mL200cm_Flat.madx"],
        model_dir=Path("./test_out"),
    )

    # From scratch: pass line/tbt object
    # ##################################

    # line = create_line(beam)
    # nominal(beam, line)
    # create_turn_by_turn_data(beam, line.copy(), n_turns=6600, output_name="nominal")
    # create_omc3_model_dir(beam, line)
    # install_errors(beam, line)
    # tbt_data = create_turn_by_turn_data(beam, line, n_turns=6600)
    # modify_turn_by_turn_data(beam, tbt_data, alpha=0.1)  # maybe even in a loop

    # -------------------------------

    # Re-do: loads line/tbt object
    # ############################

    # nominal(beam)
    # create_omc3_model_dir(beam)
    install_errors(beam)
    create_turn_by_turn_data(beam, n_turns=6600)
    # modify_turn_by_turn_data(beam, alpha=0.1)

if __name__ == "__main__":
    init_logging()
    main()
