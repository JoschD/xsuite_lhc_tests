from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import xtrack as xt

from utils.logging import disable_logging

if TYPE_CHECKING:
    from lhc_beam import LHCBeam


LOGGER = logging.getLogger(__name__)


def match(beam: LHCBeam, line: xt.Line, step: float = 1e-8,  tolerance: float = 1e-10, chroma: bool = False):
    """ Match the line to the natural tunes and chroma stored in the beam-object.

    Args:
        beam (LHCBeam): beam object storing machine configuration data
        line (xt.Line): line to be matched
        step (float, optional): step size for the optimization. Defaults to 1e-8.
        tolerance (float, optional): tolerance for the optimization. Defaults to 1e-10.
        chroma (bool, optional): whether to match chroma. Defaults to False.
    """
    LOGGER.info("Matching line to natural tunes" + "" if not chroma else " and chroma")
    tune_knob = "dq{plane}.b{beam}_op"
    chroma_knob = "dqp{plane}.b{beam}_op"

    vary=[xt.Vary(name=tune_knob.format(beam=beam.beam, plane=plane), step=step) for plane in "xy"]
    targets=[xt.TargetSet(qx=beam.nat_tunes[0], qy=beam.nat_tunes[1], tol=tolerance)]
    if chroma:
        vary.append(xt.Vary(name=chroma_knob.format(beam=beam.beam, plane=plane), step=step) for plane in "xy")
        targets.append(xt.TargetSet(dqx=beam.chroma, dqy=beam.chroma, tol=tolerance))

    with disable_logging():
        opt = line.match(vary=vary, targets=targets)
        # opt.assert_within_tol=False
        opt.solve()


def insert_monitors_at_pattern(line: xt.Line, pattern: str = "BPM", n_turns: int = 10_000, n_particles: int = 1) -> xt.Line:
    """
    Add particle monitors to the given line at all elements whose names match the given regex pattern.
    Each monitor will record for the specified number of turns and particles.
    """
    # Find all element names matching the pattern (e.g., all BPMs)
    selected_list = [name for name in line.element_names if re.match(pattern, name, flags=re.IGNORECASE)]

    if not selected_list:
        raise ValueError(f"No elements match the pattern '{pattern}'")

    # Get the s-positions of these elements
    s_positions = line.get_s_position(selected_list)

    # Prepare a base monitor object to copy for each BPM
    monitor_base = xt.ParticlesMonitor(
        start_at_turn=0,
        stop_at_turn=n_turns,
        num_particles=n_particles
    )

    # Register a monitor element for each BPM, and collect placement instructions
    inserts: list[xt.Place] = []
    for name, s in zip(selected_list, s_positions):
        monitor_name = f"{name}_monitor"

        monitor = monitor_base.copy()

        line.env.elements[monitor_name] = monitor
        inserts.append(line.env.place(monitor_name, at=s))

    # Insert all monitors at once for efficiency
    line.insert(inserts)
