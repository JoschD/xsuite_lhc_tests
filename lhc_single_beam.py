"""
Setting up the nominal LHC in xsuite using cpymad.
"""
from __future__ import annotations

from enum import StrEnum, auto
import logging
from pathlib import Path

import tfs
import xpart as xp
import xtrack as xt
from cpymad.madx import Madx

from lhc_beam import LHCBeam
from utils.logging import disable_logging, init_cpymad_logging, init_logging
from utils.tfs import twiss_to_omc3
from utils.xsuite import match


MADX_LOGGING: bool = False

LOGGER = logging.getLogger(__name__)


class Step(StrEnum):
    """ Enum for the different steps of the simulation """
    raw = auto()
    nominal = auto()



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
    line.to_json(beam.output_path("line", Step.raw, suffix=".json"))
    madx.exit()
    return line


def nominal(beam: LHCBeam, line: xt.Line | None):
    """ Continue the LHC setup to the nominal machine, i.e.
    match the tunes and write out the twiss table.

    Args:
        beam (LHCBeam): beam object storing machine configuration data
        line (xt.Line): line of the loaded machine, if not given loads from json.
    """
    LOGGER.info("Creating nominal twiss table")

    if line is None:
        LOGGER.debug("Loading from file.")
        line = xt.Line.from_json(beam.output_path("line", Step.raw, suffix=".json"))

    match(beam, line)

    tw: xt.TwissTable = line.twiss(continue_on_closed_orbit_error=False, strengths=True)
    df = twiss_to_omc3(tw)
    tfs.write(beam.output_path("twiss", Step.nominal), df, save_index="NAME")

    line.to_json(beam.output_path("line", Step.nominal, suffix=".json"))


def main():
    beam = LHCBeam(
        beam=1,
        year="2025",
        modifiers=["R2025aRP_A18cmC18cmA10mL200cm_Flat.madx"],
        model_dir=Path("./test_nolog"),
    )

    line = create_line(beam)
    nominal(beam, line)
    # nominal(beam)



if __name__ == "__main__":
    init_logging()
    main()
